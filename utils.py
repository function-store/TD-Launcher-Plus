"""Utility functions for TD Launcher Plus."""

import os
import sys
import platform
import subprocess
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Conditional imports
try:
    import dearpygui.dearpygui as dpg
    HAS_DPG = True
except ImportError:
    HAS_DPG = False

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


def format_file_modified_time(file_path: str) -> str:
    """Get formatted modification time for a file."""
    try:
        mtime = os.path.getmtime(file_path)
        dt = datetime.fromtimestamp(mtime)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""


def show_native_file_picker(prompt: str = "Select TouchDesigner File") -> Optional[str]:
    """Show native file picker dialog.

    Returns the selected file path or None if cancelled.
    """
    if platform.system() == 'Darwin':
        # macOS - use AppleScript
        script = f'''
        set theFile to choose file with prompt "{prompt}" of type {{"toe"}}
        return POSIX path of theFile
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                if path and os.path.exists(path):
                    return path
        except Exception as e:
            logger.error(f"File picker error: {e}")
        return None

    elif platform.system() == 'Windows':
        # Windows - use tkinter
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilename(
                title=prompt,
                filetypes=[("TouchDesigner files", "*.toe"), ("All files", "*.*")]
            )
            root.destroy()
            if file_path:
                return file_path
        except Exception as e:
            logger.error(f"File picker error: {e}")
        return None

    return None


def show_native_file_picker_multiple(prompt: str = "Select TouchDesigner Files") -> list:
    """Show native file picker dialog allowing multiple selection.

    Returns a list of selected file paths, or empty list if cancelled.
    """
    if platform.system() == 'Darwin':
        # macOS - use AppleScript with multiple selections
        script = f'''
        set theFiles to choose file with prompt "{prompt}" of type {{"toe"}} with multiple selections allowed
        set posixPaths to ""
        repeat with aFile in theFiles
            set posixPaths to posixPaths & POSIX path of aFile & linefeed
        end repeat
        return posixPaths
        '''
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                paths = []
                for line in result.stdout.strip().split('\n'):
                    path = line.strip()
                    if path and os.path.exists(path):
                        paths.append(path)
                return paths
        except Exception as e:
            logger.error(f"File picker error: {e}")
        return []

    elif platform.system() == 'Windows':
        # Windows - use tkinter with multiple selection
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            file_paths = filedialog.askopenfilenames(
                title=prompt,
                filetypes=[("TouchDesigner files", "*.toe"), ("All files", "*.*")]
            )
            root.destroy()
            if file_paths:
                return list(file_paths)
        except Exception as e:
            logger.error(f"File picker error: {e}")
        return []

    return []


def find_project_icon(project_path: str) -> Optional[str]:
    """Find an icon for a project file based on a specific priority order.

    Priority:
    1. icon_{name}.png/jpg/jpeg (Manual override)
    2. icon_temp_{name}.png/jpg/jpeg (Auto-generated specific)
    3. icon.png/jpg/jpeg (Generic project icon)
    4. Any image in the directory NOT starting with "icon_" (e.g., screenshots)
    5. Returns None (caller should use default app icon)

    Returns the path to the icon file, or None if not found.
    """
    if not os.path.exists(project_path):
        return None

    project_dir = os.path.dirname(project_path)
    if not project_dir:
        project_dir = '.'

    # Get project base name (remove .toe extension)
    project_filename = os.path.basename(project_path)
    if project_filename.lower().endswith('.toe'):
        project_base = project_filename[:-4]
    else:
        project_base = os.path.splitext(project_filename)[0]

    # Also get base name without version number (e.g., "project.7" -> "project")
    project_base_no_version = project_base
    if '.' in project_base:
        parts = project_base.rsplit('.', 1)
        if parts[1].isdigit():
            project_base_no_version = parts[0]

    # Prep names to check for specific overrides
    names_to_check = []
    if project_base_no_version != project_base:
        names_to_check.append(project_base_no_version)
    names_to_check.append(project_base)

    # 1. icon_{name}
    for name in names_to_check:
        for ext in ['.png', '.jpg', '.jpeg']:
            icon_path = os.path.join(project_dir, f'icon_{name}{ext}')
            if os.path.exists(icon_path):
                return icon_path

    # 2. icon_temp_{name}
    for name in names_to_check:
        for ext in ['.png', '.jpg', '.jpeg']:
            icon_path = os.path.join(project_dir, f'icon_temp_{name}{ext}')
            if os.path.exists(icon_path):
                return icon_path

    # 3. icon
    for ext in ['.png', '.jpg', '.jpeg']:
        icon_path = os.path.join(project_dir, f'icon{ext}')
        if os.path.exists(icon_path):
            return icon_path

    # 4. Any image not starting with icon_ (Fallback to screenshots etc.)
    try:
        candidates = []
        for f in os.listdir(project_dir):
            f_lower = f.lower()
            if f_lower.endswith(('.png', '.jpg', '.jpeg')) and not f_lower.startswith('icon_'):
                full_path = os.path.join(project_dir, f)
                if os.path.isfile(full_path):
                    candidates.append(full_path)
        
        if candidates:
            # Pick the most recently modified one
            candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return candidates[0]
    except Exception:
        pass

    # 5. Not found - caller will use default
    return None


def find_readme(project_path: str) -> Optional[str]:
    """Find a README file for a project."""
    if not os.path.exists(project_path):
        return None

    project_dir = os.path.dirname(project_path)

    # Look for readme files (case insensitive)
    try:
        for f in os.listdir(project_dir):
            if f.lower().startswith("readme") and f.lower().endswith(".md"):
                return os.path.join(project_dir, f)
    except OSError:
        pass

    return None


def read_readme_content(readme_path: str, max_length: int = 5000) -> str:
    """Read content of a readme file."""
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... (content truncated)"
            return content
    except Exception as e:
        return f"Error reading README: {e}"


def get_project_summary(project_path: str) -> str:
    """Get a brief summary of a project from its README.
    
    Returns the first non-title, non-empty line of the README.
    """
    readme_path = find_readme(project_path)
    if not readme_path:
        return ""
        
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip headers, lists, quotes, horizontal rules, links etc.
                if not line or line.startswith(('#', '*', '-', '>', '=', '[', '```', '!')):
                    continue
                # Found the first non-empty, non-markdown-symbol line
                # Truncate if it's exceptionally long
                if len(line) > 250:
                    line = line[:247] + "..."
                return line
    except Exception:
        pass
        
    return ""


def load_icon_texture(icon_path: str, size: int = 50) -> Optional[str]:
    """Load an image and create a DearPyGui texture for it.

    Returns the texture tag, or None if loading failed.
    """
    if not HAS_DPG or not HAS_PIL:
        return None

    try:
        # Generate unique tag based on path and size
        texture_tag = f"icon_{hash(icon_path)}_{size}"

        # Check if already loaded
        if dpg.does_item_exist(texture_tag):
            return texture_tag

        # Load, crop to square, and resize in one efficient step
        img = Image.open(icon_path)
        img = img.convert('RGBA')
        img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)

        # Convert to flat list of floats (0-1 range)
        pixels = list(img.getdata())
        flat_pixels = []
        for pixel in pixels:
            flat_pixels.extend([c / 255.0 for c in pixel])

        # Create texture
        with dpg.texture_registry():
            dpg.add_static_texture(
                width=size,
                height=size,
                default_value=flat_pixels,
                tag=texture_tag
            )

        return texture_tag

    except Exception as e:
        logger.debug(f"Failed to load icon texture: {e}")
        return None


def load_default_icon(size: int = 50) -> Optional[str]:
    """Load the app icon as default placeholder texture.

    Returns the texture tag, or None if creation failed.
    """
    if not HAS_DPG:
        return None

    texture_tag = f"default_icon_{size}"

    if dpg.does_item_exist(texture_tag):
        return texture_tag

    try:
        # Try to load app icon
        icon_candidates = [
            get_resource_path("td_launcher_plus.icns"),
            get_resource_path("td_launcher_plus.ico"),
        ]

        icon_loaded = False
        if HAS_PIL:
            for icon_path in icon_candidates:
                if os.path.exists(icon_path):
                    try:
                        img = Image.open(icon_path)
                        img = img.convert('RGBA')
                        img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)

                        pixels = list(img.getdata())
                        flat_pixels = []
                        for pixel in pixels:
                            flat_pixels.extend([c / 255.0 for c in pixel])

                        with dpg.texture_registry():
                            dpg.add_static_texture(
                                width=size,
                                height=size,
                                default_value=flat_pixels,
                                tag=texture_tag
                            )
                        icon_loaded = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to load app icon {icon_path}: {e}")

        # Fallback to gray square if app icon not loaded
        if not icon_loaded:
            pixels = []
            for y in range(size):
                for x in range(size):
                    if x == 0 or x == size - 1 or y == 0 or y == size - 1:
                        pixels.extend([0.4, 0.4, 0.4, 1.0])
                    else:
                        pixels.extend([0.2, 0.2, 0.2, 1.0])

            with dpg.texture_registry():
                dpg.add_static_texture(
                    width=size,
                    height=size,
                    default_value=pixels,
                    tag=texture_tag
                )

        return texture_tag

    except Exception as e:
        logger.debug(f"Failed to create default icon: {e}")
        return None
def show_clear_confirmation() -> bool:
    """Show native confirmation dialog for clearing recent files.

    Returns True if confirmed.
    """
    if platform.system() == 'Darwin':
        script = '''
        set dialogResult to display dialog "Clear all Recent Files history?\\n\\nThis will remove both manually opened files and synced TouchDesigner history from the list." buttons {"Cancel", "Clear History"} default button "Clear History" with title "Clear Recent Files" with icon caution
        return button returned of dialogResult
        '''
        try:
            result = subprocess.run(['osascript', '-e', script],
                                    capture_output=True, text=True, timeout=30)
            button = result.stdout.strip()
            return button == "Clear History"
        except Exception:
            return False
    else:
        # Windows/Linux fallback
        return True
