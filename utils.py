"""Utility functions for TD Launcher."""

import os
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
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


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
                text=True,
                timeout=60
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


def find_project_icon(project_path: str) -> Optional[str]:
    """Find an icon for a project file.

    Looks for:
    1. icon.jpg or icon.png in the same directory
    2. If not found, the most recently modified .jpg or .png file

    Returns the path to the icon file, or None if not found.
    """
    if not os.path.exists(project_path):
        return None

    project_dir = os.path.dirname(project_path)

    # First, look for icon.jpg or icon.png
    for icon_name in ['icon.png', 'icon.jpg', 'icon.jpeg']:
        icon_path = os.path.join(project_dir, icon_name)
        if os.path.exists(icon_path):
            return icon_path

    # If no icon found, look for the most recent image file
    image_files = []
    try:
        for f in os.listdir(project_dir):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                full_path = os.path.join(project_dir, f)
                mtime = os.path.getmtime(full_path)
                image_files.append((mtime, full_path))
    except OSError:
        return None

    if not image_files:
        return None

    # Sort by modification time, most recent first
    image_files.sort(reverse=True)
    return image_files[0][1]


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

        # Load and resize image
        img = Image.open(icon_path)
        img = img.convert('RGBA')
        img = img.resize((size, size), Image.Resampling.LANCZOS)

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
        app_dir = os.path.dirname(os.path.abspath(__file__))
        icon_candidates = [
            os.path.join(app_dir, "td_launcher.icns"),
            os.path.join(app_dir, "td_launcher.ico"),
            os.path.join(app_dir, "td_launcher.png"),
        ]

        icon_loaded = False
        if HAS_PIL:
            for icon_path in icon_candidates:
                if os.path.exists(icon_path):
                    try:
                        img = Image.open(icon_path)
                        img = img.convert('RGBA')
                        img = img.resize((size, size), Image.Resampling.LANCZOS)

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
