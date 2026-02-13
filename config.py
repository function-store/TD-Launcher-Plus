"""Configuration management for TD Launcher Plus."""

import json
import logging
import os
import platform
import re
import time
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    'version': 1,
    'recent_files': [],
    'templates': [],
    'max_recent_files': 33,
    'confirm_remove_from_list': True,
    'show_icons': False,
    'show_readme': False,
    'show_full_history': True,
    'has_prompted_file_assoc': False,
}


class Config:
    """Manages TD Launcher Plus configuration."""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._config_dir = self._get_config_dir()
        self._config_file = os.path.join(self._config_dir, 'config.json')
        self.load()

    def _get_config_dir(self) -> str:
        """Get cross-platform config directory path."""
        system = platform.system()
        if system == 'Darwin':  # macOS
            return os.path.expanduser('~/.config/td-launcher')
        elif system == 'Windows':
            appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
            return os.path.join(appdata, 'TD Launcher Plus')
        else:  # Linux and others
            return os.path.expanduser('~/.config/td-launcher')

    def _ensure_config_dir(self) -> bool:
        """Ensure config directory exists."""
        try:
            os.makedirs(self._config_dir, exist_ok=True)
            return True
        except OSError:
            return False

    def load(self) -> Dict[str, Any]:
        """Load config from file."""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    
                    # Migration: "recent_files" -> "launcher_recents"
                    if 'recent_files' in loaded and 'launcher_recents' not in loaded:
                        loaded['launcher_recents'] = loaded.pop('recent_files')
                    
                    # Merge with defaults to ensure all keys exist
                    self._config = {**DEFAULT_CONFIG, **loaded}
            else:
                self._config = DEFAULT_CONFIG.copy()
        except (json.JSONDecodeError, IOError):
            self._config = DEFAULT_CONFIG.copy()
        return self._config

    def save(self) -> bool:
        """Save config to file."""
        try:
            self._ensure_config_dir()
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2)
            return True
        except (IOError, TypeError):
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a config value and save."""
        self._config[key] = value
        self.save()

    def __getitem__(self, key: str) -> Any:
        return self._config[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._config[key] = value

    # Recent files management

    def _get_path_from_entry(self, entry) -> str:
        """Get path from a recent file/template entry (handles both str and dict)."""
        return entry if isinstance(entry, str) else entry.get('path', '')

    def _read_windows_td_recents(self) -> list:
        """Read TD's native recent files from Windows registry.

        Registry location: HKCU\\Software\\Derivative\\recent files
        Values are file0..fileN with absolute paths as REG_SZ strings.
        Returns list of dicts with 'path' and 'source' keys.
        """
        try:
            import winreg
        except ImportError:
            return []

        raw = []
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Derivative\recent files"
            )
            num_values = winreg.QueryInfoKey(key)[1]
            for i in range(num_values):
                name, value, vtype = winreg.EnumValue(key, i)
                if name.startswith('file') and value and value.strip():
                    # Extract numeric index for sorting (file0 -> 0, file1 -> 1, …)
                    try:
                        idx = int(name[4:])
                    except ValueError:
                        idx = 9999
                    raw.append((idx, value))
            winreg.CloseKey(key)
        except (OSError, FileNotFoundError):
            logger.debug("Could not read TD recent files from registry")

        # Sort by index (lower index = more recent)
        raw.sort(key=lambda x: x[0])
        return [{'path': path, 'source': 'td'} for _, path in raw]

    def _read_mac_td_recents(self) -> list:
        """Read TD's native recent files from macOS Shared File List (.sfl4).

        Location: ~/Library/Application Support/com.apple.sharedfilelist/
                  com.apple.LSSharedFileList.ApplicationRecentDocuments/
                  ca.derivative.touchdesigner.sfl4

        Parses bookmark data embedded in the NSKeyedArchiver plist to
        extract file paths. Returns list of dicts with 'path' and 'source'.
        """
        import plistlib

        sfl_path = os.path.expanduser(
            "~/Library/Application Support/com.apple.sharedfilelist/"
            "com.apple.LSSharedFileList.ApplicationRecentDocuments/"
            "ca.derivative.touchdesigner.sfl4"
        )
        if not os.path.exists(sfl_path):
            logger.debug("TD .sfl4 file not found: %s", sfl_path)
            return []

        try:
            with open(sfl_path, 'rb') as f:
                plist_data = plistlib.load(f)
        except Exception as e:
            logger.debug("Could not parse TD .sfl4 file: %s", e)
            return []

        entries = []
        for obj in plist_data.get('$objects', []):
            if isinstance(obj, bytes) and obj.startswith(b'book'):
                path = self._extract_path_from_bookmark(obj)
                if path and path not in [e['path'] for e in entries]:
                    entries.append({'path': path, 'source': 'td'})

        return entries

    @staticmethod
    def _extract_path_from_bookmark(bookmark_data: bytes) -> Optional[str]:
        """Extract a file path from macOS bookmark binary data.

        Splits on non-printable byte runs to isolate string fragments,
        uses 'file:///' as end boundary, and anchors on known macOS
        root directories to skip binary header noise.
        """
        try:
            decoded = bookmark_data.decode('latin-1')
            parts = re.split(r'[^\x20-\x7e]+', decoded)
            components = [p for p in parts if p and 'book' not in p.lower()[:4]]

            # Path components precede 'file:///' in bookmark data
            if 'file:///' in components:
                candidates = components[:components.index('file:///')]
            else:
                candidates = components

            # Find filename (last component with a file extension)
            filename_idx = None
            for i in range(len(candidates) - 1, -1, -1):
                comp = candidates[i]
                if '.' in comp:
                    ext = comp.split('.')[-1]
                    if len(ext) <= 5 and ext.isalnum():
                        filename_idx = i
                        break

            if filename_idx is None:
                return None

            # Anchor on a known macOS root directory to skip header noise
            root_dirs = {
                'Users', 'Volumes', 'Applications', 'Library', 'System',
                'private', 'tmp', 'var', 'opt', 'usr', 'etc', 'Network',
                'bin', 'sbin', 'cores', 'dev',
            }
            start_idx = None
            for i in range(filename_idx):
                if candidates[i] in root_dirs:
                    start_idx = i
                    break

            if start_idx is None:
                return None

            path_parts = candidates[start_idx:filename_idx + 1]
            if len(path_parts) >= 2:
                return '/' + '/'.join(path_parts)

        except Exception:
            pass

        return None

    def _blank_windows_td_recent(self, file_path: str) -> bool:
        """Blank a matching entry in the Windows registry recent files.

        Sets the registry value to empty string for the entry matching file_path.
        Returns True if an entry was blanked.
        """
        try:
            import winreg
        except ImportError:
            return False

        norm_path = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Derivative\recent files",
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE
            )
            num_values = winreg.QueryInfoKey(key)[1]
            for i in range(num_values):
                name, value, vtype = winreg.EnumValue(key, i)
                if name.startswith('file') and value:
                    entry_norm = os.path.normcase(os.path.normpath(os.path.abspath(value)))
                    if entry_norm == norm_path:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, '')
                        winreg.CloseKey(key)
                        logger.debug(f"Blanked registry entry {name} for {file_path}")
                        return True
            winreg.CloseKey(key)
        except (OSError, FileNotFoundError):
            logger.debug("Could not blank TD recent file in registry")

        return False

    def add_recent_file(self, file_path: str) -> None:
        """Add a file to launcher recent files list."""
        abs_path = os.path.abspath(file_path)
        # Use launcher_recents instead of generic recent_files
        recent_files = self._config.get('launcher_recents', [])

        # Remove if already exists (handle both string and dict entries)
        recent_files = [rf for rf in recent_files if self._get_path_from_entry(rf) != abs_path]

        # Add to top with source info
        entry = {
            'path': abs_path,
            'source': 'launcher',
            'last_opened': time.time()
        }
        recent_files.insert(0, entry)

        # Limit size
        max_recent = self._config.get('max_recent_files', 33)
        self._config['launcher_recents'] = recent_files[:max_recent]
        self.save()

    def remove_recent_file(self, file_path: str) -> None:
        """Remove a file from recent files list (removes from both lists)."""
        # Normalize for comparison (handles case and slash differences)
        norm_path = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))

        def paths_match(entry_path):
            """Check if entry path matches the target path (normalized)."""
            entry_norm = os.path.normcase(os.path.normpath(os.path.abspath(entry_path)))
            return entry_norm == norm_path

        # Remove from Launcher list
        launcher_recents = self._config.get('launcher_recents', [])
        self._config['launcher_recents'] = [
            rf for rf in launcher_recents
            if not paths_match(self._get_path_from_entry(rf))
        ]

        # Remove from TD list (config-based, for macOS/legacy)
        td_recents = self._config.get('td_recents', [])
        self._config['td_recents'] = [
            rf for rf in td_recents
            if not paths_match(self._get_path_from_entry(rf))
        ]

        # On Windows, also blank the matching registry entry
        if platform.system() == 'Windows':
            self._blank_windows_td_recent(file_path)

        self.save()
    def clear_recents(self) -> None:
        """Clear all recent files (launcher and TD)."""
        self._config['launcher_recents'] = []
        self._config['td_recents'] = []
        self.save()

    def clear_missing_files(self) -> int:
        """Remove entries whose files no longer exist on disk.

        Cleans launcher_recents, td_recents (config-based), templates,
        and blanks matching Windows registry entries.
        Does NOT touch macOS .sfl4 td-recents (read-only).
        Returns the number of entries removed.
        """
        removed = 0

        # Launcher recents
        launcher = self._config.get('launcher_recents', [])
        cleaned = [rf for rf in launcher if os.path.exists(self._get_path_from_entry(rf))]
        removed += len(launcher) - len(cleaned)
        self._config['launcher_recents'] = cleaned

        # Config-based td_recents (legacy / non-native)
        td = self._config.get('td_recents', [])
        cleaned_td = [rf for rf in td if os.path.exists(self._get_path_from_entry(rf))]
        removed += len(td) - len(cleaned_td)
        self._config['td_recents'] = cleaned_td

        # On Windows, blank missing registry entries too
        if platform.system() == 'Windows':
            for entry in self._read_windows_td_recents():
                path = entry.get('path', '')
                if path and not os.path.exists(path):
                    self._blank_windows_td_recent(path)
                    removed += 1

        # Templates
        templates = self._config.get('templates', [])
        cleaned_t = [t for t in templates if os.path.exists(self._get_path_from_entry(t))]
        removed += len(templates) - len(cleaned_t)
        self._config['templates'] = cleaned_t

        self.save()
        return removed

    def get_recent_files(self, merged: bool = True) -> list:
        """Get processed recent files list.
        
        Args:
            merged: If True, returns merged list of Launcher + TD recents (sorted by date).
                    If False, returns only Launcher recents.
        """
        launcher_recents = self._config.get('launcher_recents', [])
        
        if not merged:
            return launcher_recents

        # Read TD recents from native source (registry on Windows, .sfl4 on macOS)
        # On macOS, also merge config-based td_recents (written by the utility TOX)
        # since .sfl4 access requires Full Disk Access which packaged apps lack.
        if platform.system() == 'Windows':
            td_recents = self._read_windows_td_recents()
        elif platform.system() == 'Darwin':
            td_recents = self._read_mac_td_recents()
            # Merge config-based td_recents from the utility TOX
            config_td = self._config.get('td_recents', [])
            sfl_paths = {self._get_path_from_entry(e) for e in td_recents}
            for path in config_td:
                p = path if isinstance(path, str) else self._get_path_from_entry(path)
                if p and p not in sfl_paths:
                    td_recents.append({'path': p, 'source': 'td'})
        else:
            td_recents = self._config.get('td_recents', [])
        
        # Combine and deduplicate (normalize case, slashes, and absolute paths)
        seen_paths = set()
        merged_list = []

        def normalize_path(p):
            """Normalize path for comparison: absolute, normalized slashes, lowercase on Windows."""
            return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ''

        def _append_unique(items, source_tag=None):
            """Add entries to merged_list, skipping duplicates."""
            for item in items:
                path = self._get_path_from_entry(item)
                norm_path = normalize_path(path)
                if path and norm_path not in seen_paths:
                    entry = item if isinstance(item, dict) else {'path': path, 'last_opened': 0}
                    if source_tag:
                        entry['source'] = source_tag
                    merged_list.append(entry)
                    seen_paths.add(norm_path)

        if platform.system() == 'Darwin':
            # On macOS, td_recents comes from the utility TOX (snapshot at sync time)
            # and optionally from .sfl4 (if Full Disk Access is granted).
            # Launcher entries opened after the last TOX sync should appear first,
            # then native .sfl4 / TOX entries, then older launcher entries.
            td_recents_ts = self._config.get('td_recents_timestamp', 0)

            recent_launcher = []
            older_launcher = []
            for item in launcher_recents:
                entry = item if isinstance(item, dict) else {'path': item, 'last_opened': 0}
                if entry.get('last_opened', 0) > td_recents_ts:
                    recent_launcher.append(entry)
                else:
                    older_launcher.append(entry)
            recent_launcher.sort(key=lambda e: e.get('last_opened', 0), reverse=True)

            _append_unique(recent_launcher)
            _append_unique(td_recents, source_tag='td')
            _append_unique(older_launcher)
        else:
            # On Windows, registry is always fresh — TD recents go first.
            _append_unique(td_recents, source_tag='td')
            _append_unique(launcher_recents)

        return merged_list

    # Preferences

    @property
    def show_full_history(self) -> bool:
        return self._config.get('show_full_history', True)

    @show_full_history.setter
    def show_full_history(self, value: bool) -> None:
        self._config['show_full_history'] = value
        self.save()

    # Templates management

    def add_template(self, file_path: str, name: Optional[str] = None) -> None:
        """Add a file to templates list."""
        abs_path = os.path.abspath(file_path)
        templates = self._config.get('templates', [])

        # Check if already exists (handle both string and dict entries)
        for t in templates:
            if self._get_path_from_entry(t) == abs_path:
                return

        # Add to the top of the list
        templates.insert(0, abs_path)

        self._config['templates'] = templates
        self.save()

    def remove_template(self, file_path: str) -> None:
        """Remove a file from templates list."""
        abs_path = os.path.abspath(file_path)
        templates = self._config.get('templates', [])
        self._config['templates'] = [
            t for t in templates if self._get_path_from_entry(t) != abs_path
        ]
        self.save()

    def get_templates(self) -> list:
        """Get list of templates."""
        return self._config.get('templates', [])

    def move_template_up(self, file_path: str) -> bool:
        """Move a template up in the list (wraps to bottom). Returns True if moved."""
        abs_path = os.path.abspath(file_path)
        templates = self._config.get('templates', [])

        # Find the index of the template
        idx = None
        for i, t in enumerate(templates):
            if self._get_path_from_entry(t) == abs_path:
                idx = i
                break

        if idx is None:
            return False

        if idx == 0:
            # Wrap to bottom: move first item to end
            item = templates.pop(0)
            templates.append(item)
        else:
            # Swap with previous
            templates[idx], templates[idx - 1] = templates[idx - 1], templates[idx]
            
        self._config['templates'] = templates
        self.save()
        return True

    def move_template_down(self, file_path: str) -> bool:
        """Move a template down in the list (wraps to top). Returns True if moved."""
        abs_path = os.path.abspath(file_path)
        templates = self._config.get('templates', [])

        # Find the index of the template
        idx = None
        for i, t in enumerate(templates):
            if self._get_path_from_entry(t) == abs_path:
                idx = i
                break

        if idx is None:
            return False

        if idx >= len(templates) - 1:
            # Wrap to top: move last item to start
            item = templates.pop(idx)
            templates.insert(0, item)
        else:
            # Swap with next
            templates[idx], templates[idx + 1] = templates[idx + 1], templates[idx]
            
        self._config['templates'] = templates
        self.save()
        return True

    # Preferences

    @property
    def show_icons(self) -> bool:
        return self._config.get('show_icons', False)

    @show_icons.setter
    def show_icons(self, value: bool) -> None:
        self._config['show_icons'] = value
        self.save()

    @property
    def show_readme(self) -> bool:
        return self._config.get('show_readme', False)

    @show_readme.setter
    def show_readme(self, value: bool) -> None:
        self._config['show_readme'] = value
        self.save()

    @property
    def confirm_remove(self) -> bool:
        return self._config.get('confirm_remove_from_list', True)

    @confirm_remove.setter
    def confirm_remove(self, value: bool) -> None:
        self._config['confirm_remove_from_list'] = value
        self.save()

    @property
    def has_prompted_file_assoc(self) -> bool:
        return self._config.get('has_prompted_file_assoc', False)

    @has_prompted_file_assoc.setter
    def has_prompted_file_assoc(self, value: bool) -> None:
        self._config['has_prompted_file_assoc'] = value
        self.save()


def show_remove_confirmation(filename: str) -> tuple:
    """Show native confirmation dialog for removing a file from list.

    Returns (confirmed: bool, never_ask_again: bool)
    """
    if platform.system() == 'Darwin':
        script = f'''
        set dialogResult to display dialog "Remove \\"{filename}\\" from this list?\\n\\nThis only removes it from TD Launcher Plus's list, not from your file system." buttons {{"Cancel", "Remove", "Remove & Don't Ask Again"}} default button "Remove" with title "Remove from List"
        return button returned of dialogResult
        '''
        try:
            result = subprocess.run(['osascript', '-e', script],
                                    capture_output=True, text=True, timeout=30)
            button = result.stdout.strip()
            if button == "Remove":
                return (True, False)
            elif button == "Remove & Don't Ask Again":
                return (True, True)
            else:
                return (False, False)
        except Exception:
            return (False, False)
    else:
        # Windows/Linux - just return True for now
        return (True, False)
