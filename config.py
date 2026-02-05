"""Configuration management for TD Launcher Plus."""

import json
import os
import platform
import time
import subprocess
from typing import Any, Dict, Optional

DEFAULT_CONFIG = {
    'version': 1,
    'recent_files': [],
    'templates': [],
    'max_recent_files': 20,
    'confirm_remove_from_list': True,
    'show_icons': False,
    'show_readme': False,
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

    def add_recent_file(self, file_path: str) -> None:
        """Add a file to recent files list."""
        abs_path = os.path.abspath(file_path)
        recent_files = self._config.get('recent_files', [])

        # Remove if already exists (handle both string and dict entries)
        recent_files = [rf for rf in recent_files if self._get_path_from_entry(rf) != abs_path]

        # Add to front (as string path for simplicity)
        recent_files.insert(0, abs_path)

        # Trim to max
        max_files = self._config.get('max_recent_files', 20)
        self._config['recent_files'] = recent_files[:max_files]
        self.save()

    def remove_recent_file(self, file_path: str) -> None:
        """Remove a file from recent files list."""
        abs_path = os.path.abspath(file_path)
        recent_files = self._config.get('recent_files', [])
        self._config['recent_files'] = [
            rf for rf in recent_files if self._get_path_from_entry(rf) != abs_path
        ]
        self.save()

    def get_recent_files(self) -> list:
        """Get list of recent files."""
        return self._config.get('recent_files', [])

    # Templates management

    def add_template(self, file_path: str, name: Optional[str] = None) -> None:
        """Add a file to templates list."""
        abs_path = os.path.abspath(file_path)
        templates = self._config.get('templates', [])

        # Check if already exists (handle both string and dict entries)
        for t in templates:
            if self._get_path_from_entry(t) == abs_path:
                return

        # Add as string path for simplicity
        templates.append(abs_path)

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
