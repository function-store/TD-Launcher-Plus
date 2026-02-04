#!/usr/bin/env python3
"""TD Launcher - TouchDesigner project launcher with version management."""

import os
import sys
import time
import platform
import subprocess
import logging
from typing import Optional
from urllib.request import urlretrieve

import dearpygui.dearpygui as dpg

from config import Config, show_remove_confirmation
from td_manager import TDManager
from utils import (
    format_file_modified_time,
    show_native_file_picker,
    find_project_icon,
    find_readme,
    read_readme_content,
    load_icon_texture,
    load_default_icon,
)

# Version
APP_VERSION = "1.1.0"

# Setup logging
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class LauncherApp:
    """Main TD Launcher application."""

    def __init__(self, toe_file: Optional[str] = None):
        # Core components
        self.config = Config()
        self.td_manager = TDManager()

        # File state
        self.toe_file = toe_file
        self.selected_file: Optional[str] = None
        self.build_info: Optional[str] = None
        self.build_year: Optional[int] = None

        # UI state
        self.picker_mode = toe_file is None
        self.countdown_enabled = False
        self.seconds_started = 0.0
        self.download_progress = 0.0

        # Selection tracking
        self.last_click_time = 0.0
        self.last_clicked_path: Optional[str] = None
        self.picker_selection_index = 0

        # Icon cache
        self.icon_textures = {}
        self.default_icon_texture = None

        # Download state
        self.td_url: Optional[str] = None
        self.td_uri: Optional[str] = None
        self.td_filename: Optional[str] = None

        # Readme state
        self.current_readme_path: Optional[str] = None
        self.readme_modified: bool = False

    def run(self):
        """Run the application."""
        logger.info(f"TD Launcher {APP_VERSION}")
        logger.info(f"Platform: {platform.system()}")
        logger.info(f"Found {len(self.td_manager.versions)} TD installations")

        # Initialize file info if provided
        if self.toe_file:
            self._analyze_toe_file(self.toe_file)
            self.selected_file = self.toe_file
            self.config.add_recent_file(self.toe_file)

        # Create GUI
        dpg.create_context()

        with dpg.handler_registry():
            dpg.add_mouse_click_handler(callback=self._on_mouse_click)
            dpg.add_key_press_handler(callback=self._on_key_press)

        self._build_ui()

        # Create viewport (always wide to avoid resize flicker)
        dpg.create_viewport(
            title=f'TD Launcher {APP_VERSION}',
            width=960,
            height=550,
            resizable=True
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window("Primary Window", True)

        self.seconds_started = time.time()

        # Set countdown state
        if self.picker_mode:
            self.countdown_enabled = False
        elif self.build_info and not self.td_manager.is_version_installed(self.build_info):
            self.countdown_enabled = False
        else:
            self.countdown_enabled = True

        # Main loop
        while dpg.is_dearpygui_running():
            self._update_countdown()
            dpg.render_dearpygui_frame()

        dpg.destroy_context()

    def _analyze_toe_file(self, file_path: str):
        """Analyze a .toe file to get version info."""
        try:
            self.build_info = self.td_manager.inspect_toe_file(file_path)
            if self.build_info:
                parts = self.build_info.split('.')
                if len(parts) > 1:
                    self.build_year = int(parts[1])
                self.td_url = self.td_manager.generate_download_url(self.build_info)
                if self.td_url:
                    self.td_filename = self.td_url.split("/")[-1]
                    if platform.system() == 'Darwin':
                        toe_dir = os.path.dirname(os.path.abspath(file_path))
                        self.td_uri = os.path.join(toe_dir, self.td_filename)
                    else:
                        self.td_uri = os.path.join(os.getcwd(), self.td_filename)
        except Exception as e:
            logger.error(f"Failed to analyze TOE file: {e}")

    # =========================================================================
    # UI Building
    # =========================================================================

    def _build_ui(self):
        """Build the main UI."""
        show_icons = self.config.show_icons
        show_readme = self.config.show_readme

        # Create click handler registry
        if dpg.does_item_exist("row_click_handler"):
            dpg.delete_item("row_click_handler")
        with dpg.item_handler_registry(tag="row_click_handler"):
            dpg.add_item_clicked_handler(callback=self._on_row_clicked)

        with dpg.window(tag="Primary Window"):
            dpg.add_text(f'TD Launcher {APP_VERSION}', color=[50, 255, 0, 255])
            dpg.add_separator()

            # Main layout - use table only if readme shown, otherwise simple group
            if show_readme:
                with dpg.table(
                    tag="main_layout_table",
                    header_row=False,
                    borders_innerV=False,
                    borders_outerV=False,
                    borders_innerH=False,
                    borders_outerH=False,
                    no_pad_outerX=True,
                    no_pad_innerX=True,
                    policy=dpg.mvTable_SizingStretchProp
                ):
                    dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
                    dpg.add_table_column(tag="readme_column", width_fixed=True, init_width_or_weight=310)

                    with dpg.table_row():
                        with dpg.group(tag="main_ui_group"):
                            self._build_file_picker_section(show_icons, show_readme)
                            dpg.add_separator()
                            self._build_version_panel()
                            dpg.add_separator()
                            self._build_launch_button()

                        with dpg.group(tag="readme_panel_group"):
                            self._build_readme_panel()
            else:
                with dpg.group(tag="main_ui_group"):
                    self._build_file_picker_section(show_icons, show_readme)
                    dpg.add_separator()
                    self._build_version_panel()
                    dpg.add_separator()
                    self._build_launch_button()

        dpg.set_primary_window("Primary Window", True)
        self.seconds_started = time.time()

        # If file was provided, update version panel
        if self.selected_file:
            self._update_version_panel()

    def _build_file_picker_section(self, show_icons: bool, show_readme: bool):
        """Build the file picker tabs section."""
        with dpg.tab_bar(tag="file_picker_tabs"):
            # Recent Files Tab
            with dpg.tab(label="Recent Files", tag="recent_files_tab"):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Browse...",
                        tag="browse_btn_recent",
                        callback=self._on_browse
                    )
                    dpg.add_checkbox(
                        label="Show Icons",
                        tag="show_icons_checkbox",
                        default_value=show_icons,
                        callback=self._on_toggle_icons
                    )
                    dpg.add_checkbox(
                        label="Show Info",
                        tag="show_readme_checkbox",
                        default_value=show_readme,
                        callback=self._on_toggle_readme
                    )
                with dpg.child_window(height=150, width=-1, tag="recent_files_list"):
                    self._build_recent_files_list()

            # Templates Tab
            with dpg.tab(label="Templates", tag="templates_tab"):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Add Template...",
                        callback=self._on_add_template,
                        tag="add_template_btn"
                    )
                    dpg.add_checkbox(
                        label="Show Icons",
                        tag="show_icons_checkbox_templates",
                        default_value=show_icons,
                        callback=self._on_toggle_icons
                    )
                    dpg.add_checkbox(
                        label="Show Info",
                        tag="show_readme_checkbox_templates",
                        default_value=show_readme,
                        callback=self._on_toggle_readme
                    )
                with dpg.child_window(height=150, width=-1, tag="templates_list"):
                    self._build_templates_list()

    def _is_versioned_toe(self, filename: str) -> bool:
        """Check if filename has .number.toe format (e.g., project.7.toe)."""
        if not filename.lower().endswith('.toe'):
            return False
        base = filename[:-4]  # Remove .toe
        if '.' in base:
            parts = base.rsplit('.', 1)
            return parts[1].isdigit()
        return False

    def _build_recent_files_list(self):
        """Build the recent files list."""
        if dpg.does_item_exist("recent_files_list"):
            dpg.delete_item("recent_files_list", children_only=True)

        recent_files = self.config.get_recent_files()
        show_icons = self.config.show_icons

        if not recent_files:
            dpg.add_text(
                "No recent files.\nOpen a .toe file or drag one onto the app icon.",
                parent="recent_files_list",
                color=[150, 150, 150, 255]
            )
            return

        display_index = 0
        shown_paths = set()  # Track paths we've already displayed

        for rf in recent_files:
            # Handle both string paths and dict entries
            file_path = rf if isinstance(rf, str) else rf.get('path', '')
            file_path = file_path.strip() if file_path else ''
            filename = os.path.basename(file_path)
            parent_folder = os.path.basename(os.path.dirname(file_path))

            # Handle versioned files (e.g., project.7.toe)
            if self._is_versioned_toe(filename):
                if parent_folder.lower() == 'backup':
                    # Show Backup files with prefix
                    display_name = f"Backup/{filename}"
                else:
                    # Convert to non-versioned path (project.7.toe -> project.toe)
                    base = filename[:-4]  # Remove .toe
                    base_no_version = base.rsplit('.', 1)[0]
                    non_versioned_filename = f"{base_no_version}.toe"
                    file_path = os.path.join(os.path.dirname(file_path), non_versioned_filename)
                    filename = non_versioned_filename
                    display_name = filename
            else:
                display_name = filename

            # Skip if we've already shown this path
            if file_path in shown_paths:
                continue
            shown_paths.add(file_path)

            exists = os.path.exists(file_path)
            modified = format_file_modified_time(file_path) if exists else ""
            i = display_index
            display_index += 1

            with dpg.group(horizontal=True, parent="recent_files_list"):
                # Icon
                if show_icons:
                    icon_path = find_project_icon(file_path) if exists else None
                    texture_tag = None
                    if icon_path:
                        texture_tag = load_icon_texture(icon_path)
                    if not texture_tag:
                        texture_tag = load_default_icon()
                    if texture_tag:
                        dpg.add_image(texture_tag, width=50, height=50, tag=f"recent_icon_{i}")
                        dpg.bind_item_handler_registry(f"recent_icon_{i}", "row_click_handler")

                # Filename (selectable)
                dpg.add_selectable(
                    label=display_name,
                    tag=f"recent_file_{i}",
                    callback=self._on_file_selected,
                    user_data={'path': file_path, 'type': 'recent'},
                    width=200
                )

                # Modified date
                dpg.add_text(
                    f"  {modified}",
                    color=[100, 150, 100, 255] if exists else [100, 50, 50, 255],
                    tag=f"recent_mod_{i}"
                )
                dpg.bind_item_handler_registry(f"recent_mod_{i}", "row_click_handler")

                # Path
                dpg.add_text(
                    f"  {file_path}",
                    color=[150, 150, 150, 255] if exists else [100, 50, 50, 255],
                    tag=f"recent_path_{i}"
                )
                dpg.bind_item_handler_registry(f"recent_path_{i}", "row_click_handler")

                # Missing indicator
                if not exists:
                    dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"recent_missing_{i}")
                    dpg.bind_item_handler_registry(f"recent_missing_{i}", "row_click_handler")

                # Remove button
                dpg.add_button(
                    label="X",
                    tag=f"remove_recent_{i}",
                    callback=self._on_remove_recent,
                    user_data=file_path,
                    small=True
                )

    def _build_templates_list(self):
        """Build the templates list."""
        if dpg.does_item_exist("templates_list"):
            dpg.delete_item("templates_list", children_only=True)

        templates = self.config.get_templates()
        show_icons = self.config.show_icons

        if not templates:
            dpg.add_text(
                "No templates added yet.\nClick 'Add Template...' or drag a .toe file onto the app icon.",
                parent="templates_list",
                color=[150, 150, 150, 255]
            )
            return

        for i, t in enumerate(templates):
            # Handle both string paths and dict entries
            file_path = t if isinstance(t, str) else t.get('path', '')
            name = os.path.basename(file_path) if isinstance(t, str) else t.get('name', os.path.basename(file_path))
            exists = os.path.exists(file_path)
            modified = format_file_modified_time(file_path) if exists else ""

            with dpg.group(horizontal=True, parent="templates_list"):
                # Icon
                if show_icons:
                    icon_path = find_project_icon(file_path) if exists else None
                    texture_tag = None
                    if icon_path:
                        texture_tag = load_icon_texture(icon_path)
                    if not texture_tag:
                        texture_tag = load_default_icon()
                    if texture_tag:
                        dpg.add_image(texture_tag, width=50, height=50, tag=f"template_icon_{i}")
                        dpg.bind_item_handler_registry(f"template_icon_{i}", "row_click_handler")

                # Name (selectable)
                dpg.add_selectable(
                    label=name,
                    tag=f"template_{i}",
                    callback=self._on_file_selected,
                    user_data={'path': file_path, 'type': 'template'},
                    width=220
                )

                # Modified date
                dpg.add_text(f"  {modified}", color=[100, 150, 100, 255], tag=f"template_mod_{i}")
                dpg.bind_item_handler_registry(f"template_mod_{i}", "row_click_handler")

                # Path
                dpg.add_text(f"  {file_path}", color=[150, 150, 150, 255], tag=f"template_path_{i}")
                dpg.bind_item_handler_registry(f"template_path_{i}", "row_click_handler")

                # Missing indicator
                if not exists:
                    dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"template_missing_{i}")
                    dpg.bind_item_handler_registry(f"template_missing_{i}", "row_click_handler")

                # Remove button
                dpg.add_button(
                    label="X",
                    tag=f"remove_template_{i}",
                    callback=self._on_remove_template,
                    user_data=file_path,
                    small=True
                )

    def _build_version_panel(self):
        """Build the version panel section."""
        with dpg.child_window(height=250, width=-1, tag="version_panel"):
            dpg.add_text(
                "Select a file above to see version info",
                color=[150, 150, 150, 255]
            )

    def _build_launch_button(self):
        """Build the launch button."""
        dpg.add_button(
            label="Select a file to launch",
            tag="launch_button",
            width=-1,
            height=40,
            callback=self._on_launch,
            enabled=False
        )

    def _build_readme_panel(self):
        """Build the readme panel."""
        dpg.add_text("Project Info", color=[200, 200, 200, 255])
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text(
                "Select a file...",
                tag="readme_status_text",
                color=[150, 150, 150, 255],
            )
            dpg.add_button(
                label="Save",
                tag="readme_save_button",
                callback=self._on_save_readme,
                small=True,
                show=False
            )
            dpg.add_button(
                label="View",
                tag="readme_view_button",
                callback=self._on_view_readme,
                small=True,
                show=False
            )
        dpg.add_separator()
        dpg.add_input_text(
            tag="readme_content_text",
            multiline=True,
            width=290,
            height=390,
            default_value="",
            callback=self._on_readme_changed,
            on_enter=False
        )

    def _update_version_panel(self, skip_analysis: bool = False):
        """Update the version panel with selected file info."""
        if dpg.does_item_exist("version_panel"):
            dpg.delete_item("version_panel", children_only=True)

        if not self.selected_file or not os.path.exists(self.selected_file):
            dpg.add_text(
                "Select a file above to see version info",
                parent="version_panel",
                color=[150, 150, 150, 255]
            )
            dpg.configure_item("launch_button", enabled=False)
            dpg.configure_item("launch_button", label="Select a file to launch")
            self.countdown_enabled = False
            return

        # Analyze the file (unless skipped)
        if not skip_analysis:
            self._analyze_toe_file(self.selected_file)

        if not self.build_info:
            dpg.add_text(
                "Could not detect required TD version",
                parent="version_panel",
                color=[255, 150, 0, 255]
            )
            dpg.add_text(
                "Select a version manually below:",
                parent="version_panel",
                color=[150, 150, 150, 255]
            )
            dpg.add_separator(parent="version_panel")

            # Still show version selection
            version_keys = self.td_manager.get_sorted_version_keys()
            if version_keys:
                with dpg.child_window(height=100, width=-1, parent="version_panel"):
                    dpg.add_radio_button(
                        version_keys,
                        default_value=version_keys[-1],  # Most recent version
                        tag="td_version",
                        horizontal=False
                    )
                filename = os.path.basename(self.selected_file)
                dpg.configure_item("launch_button", enabled=True)
                dpg.configure_item("launch_button", label=f"Launch {filename}")
            else:
                dpg.add_text(
                    "No TouchDesigner versions found!",
                    parent="version_panel",
                    color=[255, 50, 0, 255]
                )
                dpg.configure_item("launch_button", enabled=False)

            # Still update readme panel
            self._update_readme_panel()
            return

        filename = os.path.basename(self.selected_file)
        dpg.add_text(f'File: {filename}', parent="version_panel", color=[50, 255, 0, 255])

        version_installed = self.td_manager.is_version_installed(self.build_info)

        if not version_installed:
            dpg.add_text(
                f'Required: {self.build_info} (NOT INSTALLED)',
                parent="version_panel",
                color=[255, 50, 0, 255]
            )
            self._build_download_controls()
            self.countdown_enabled = False
        else:
            dpg.add_text(
                f'Required: {self.build_info} (installed)',
                parent="version_panel",
                color=[50, 255, 0, 255]
            )
            self.countdown_enabled = True

        dpg.add_separator(parent="version_panel")
        dpg.add_text("Override version:", parent="version_panel", color=[150, 150, 150, 255])

        # Version selection
        version_keys = self.td_manager.get_sorted_version_keys()
        default_version = self.build_info if self.build_info in version_keys else (
            version_keys[0] if version_keys else None
        )

        with dpg.child_window(height=100, width=-1, parent="version_panel"):
            dpg.add_radio_button(
                version_keys,
                default_value=default_version,
                tag="td_version",
                horizontal=False
            )

        # Update launch button
        dpg.configure_item("launch_button", enabled=True)
        dpg.configure_item("launch_button", label=f"Launch {filename}")

        # Update readme panel
        self._update_readme_panel()

    def _rebuild_version_panel_ui(self):
        """Rebuild version panel UI without re-analyzing the file."""
        self._update_version_panel(skip_analysis=True)

    def _build_download_controls(self):
        """Build download/install controls for missing version."""
        with dpg.group(parent="version_panel"):
            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingFixedFit,
                row_background=True,
                resizable=False,
                borders_innerV=False,
                borders_outerV=False,
                borders_innerH=False,
                borders_outerH=False,
                width=-1
            ):
                dpg.add_table_column(width_stretch=True)
                with dpg.table_row():
                    with dpg.filter_set(id="download_filter"):
                        if self.build_year and self.build_year > 2019:
                            dpg.set_value("download_filter", 'a')
                        else:
                            dpg.set_value("download_filter", 'c')
                        dpg.add_button(
                            label=f'Download: {self.build_info}',
                            width=-1,
                            callback=self._on_download,
                            filter_key="a"
                        )
                        dpg.add_progress_bar(
                            overlay='downloading 0.0%',
                            tag='download_progress_bar',
                            width=-1,
                            default_value=0.0,
                            filter_key="b"
                        )
                        dpg.add_text(
                            'TD versions from 2019 and earlier are not compatible.',
                            color=[255, 50, 0, 255],
                            filter_key="c"
                        )
                        dpg.add_text(
                            'Error downloading - go to derivative.ca to download manually',
                            color=[255, 50, 0, 255],
                            filter_key="d"
                        )

            with dpg.filter_set(id="install_filter"):
                dpg.set_value("install_filter", 'z')
                dpg.add_button(
                    label=f'Install: {self.build_info}',
                    width=-1,
                    enabled=True,
                    filter_key="a",
                    callback=self._on_install
                )

    def _update_readme_panel(self):
        """Update the readme panel with file info."""
        if not self.config.show_readme:
            return

        if not dpg.does_item_exist("readme_status_text"):
            return

        if self.selected_file and os.path.exists(self.selected_file):
            readme_path = find_readme(self.selected_file)
            project_dir = os.path.dirname(self.selected_file)
            if readme_path:
                content = read_readme_content(readme_path, max_length=50000)  # Allow more for editing
                dpg.set_value("readme_status_text", os.path.basename(readme_path))
                dpg.configure_item("readme_status_text", color=[100, 255, 100, 255])
                dpg.set_value("readme_content_text", content)
                self.current_readme_path = readme_path
            else:
                # No readme - allow creating one
                dpg.set_value("readme_status_text", "README.md (new)")
                dpg.configure_item("readme_status_text", color=[200, 200, 100, 255])
                dpg.set_value("readme_content_text", "")
                self.current_readme_path = os.path.join(project_dir, "README.md")
            dpg.configure_item("readme_save_button", show=True)
            dpg.configure_item("readme_view_button", show=True)
            self.readme_modified = False
        else:
            dpg.set_value("readme_status_text", "Select a file...")
            dpg.configure_item("readme_status_text", color=[150, 150, 150, 255])
            dpg.set_value("readme_content_text", "")
            dpg.configure_item("readme_save_button", show=False)
            dpg.configure_item("readme_view_button", show=False)
            self.current_readme_path = None
            self.readme_modified = False

    def _on_readme_changed(self, sender, app_data):
        """Handle readme content changes."""
        self.readme_modified = True
        if dpg.does_item_exist("readme_save_button"):
            dpg.configure_item("readme_save_button", label="Save *")

    def _on_save_readme(self, sender, app_data):
        """Save readme content to file."""
        if not self.current_readme_path:
            return

        content = dpg.get_value("readme_content_text")
        try:
            with open(self.current_readme_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.readme_modified = False
            dpg.configure_item("readme_save_button", label="Save")
            # Update status to show it exists now
            dpg.set_value("readme_status_text", os.path.basename(self.current_readme_path))
            dpg.configure_item("readme_status_text", color=[100, 255, 100, 255])
            logger.info(f"Saved README to {self.current_readme_path}")
        except Exception as e:
            logger.error(f"Failed to save README: {e}")

    def _on_view_readme(self, sender, app_data):
        """View readme rendered as HTML in browser."""
        import webbrowser
        import tempfile

        content = dpg.get_value("readme_content_text")
        if not content.strip():
            return

        # Get project name for title
        project_name = "README"
        if self.selected_file:
            project_name = os.path.basename(os.path.dirname(self.selected_file))

        # Basic markdown to HTML conversion
        html_content = self._markdown_to_html(content, project_name)

        # Write to temp file and open
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                temp_path = f.name
            webbrowser.open(f'file://{temp_path}')
            logger.info(f"Opened README preview: {temp_path}")
        except Exception as e:
            logger.error(f"Failed to open README preview: {e}")

    def _markdown_to_html(self, markdown: str, title: str = "README") -> str:
        """Convert markdown to HTML with styling."""
        import html
        import re

        text = markdown

        # Extract and protect code blocks first (before HTML escaping)
        code_blocks = []
        def save_code_block(match):
            lang = match.group(1) or ''
            code = match.group(2)
            code_blocks.append((lang, html.escape(code)))
            return f'___CODE_BLOCK_{len(code_blocks) - 1}___'

        text = re.sub(r'```(\w*)\n(.*?)```', save_code_block, text, flags=re.DOTALL)

        # Extract inline code
        inline_codes = []
        def save_inline_code(match):
            inline_codes.append(html.escape(match.group(1)))
            return f'___INLINE_CODE_{len(inline_codes) - 1}___'

        text = re.sub(r'`([^`]+)`', save_inline_code, text)

        # Escape HTML in remaining text
        text = html.escape(text)

        # Convert markdown syntax to HTML
        # Headers (order matters - longest first)
        text = re.sub(r'^##### (.+)$', r'<h5>\1</h5>', text, flags=re.MULTILINE)
        text = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
        text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
        text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)

        # Bold and italic
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

        # Images (must come before links)
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width: 100%;">', text)

        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

        # Lists
        text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'(<li>.*</li>\n?)+', r'<ul>\g<0></ul>', text)

        # Horizontal rules
        text = re.sub(r'^---+$', r'<hr>', text, flags=re.MULTILINE)

        # Paragraphs (convert double newlines)
        text = re.sub(r'\n\n+', r'</p><p>', text)
        text = f'<p>{text}</p>'

        # Clean up empty paragraphs
        text = re.sub(r'<p>\s*</p>', '', text)
        text = re.sub(r'<p>(<h[1-5]>)', r'\1', text)
        text = re.sub(r'(</h[1-5]>)</p>', r'\1', text)
        text = re.sub(r'<p>(<ul>)', r'\1', text)
        text = re.sub(r'(</ul>)</p>', r'\1', text)
        text = re.sub(r'<p>(___CODE_BLOCK_)', r'\1', text)
        text = re.sub(r'(___CODE_BLOCK_\d+___)</p>', r'\1', text)
        text = re.sub(r'<p>(<hr>)', r'\1', text)
        text = re.sub(r'(<hr>)</p>', r'\1', text)

        # Restore code blocks
        for i, (lang, code) in enumerate(code_blocks):
            lang_class = f' class="language-{lang}"' if lang else ''
            text = text.replace(f'___CODE_BLOCK_{i}___', f'<pre><code{lang_class}>{code}</code></pre>')

        # Restore inline code
        for i, code in enumerate(inline_codes):
            text = text.replace(f'___INLINE_CODE_{i}___', f'<code>{code}</code>')

        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(title)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 40px auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }}
        h1, h2, h3, h4, h5 {{ color: #4CAF50; margin-top: 24px; }}
        h1 {{ border-bottom: 1px solid #333; padding-bottom: 10px; }}
        h4, h5 {{ color: #81C784; }}
        a {{ color: #64B5F6; }}
        code {{
            background: #2d2d2d;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, monospace;
        }}
        pre {{
            background: #2d2d2d;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        pre code {{ padding: 0; }}
        ul {{ padding-left: 24px; }}
        li {{ margin: 4px 0; }}
        hr {{ border: none; border-top: 1px solid #333; margin: 24px 0; }}
        strong {{ color: #fff; }}
    </style>
</head>
<body>
{text}
</body>
</html>'''

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _on_mouse_click(self, sender, app_data):
        """Handle mouse clicks (cancels countdown)."""
        self._cancel_countdown()

    def _on_key_press(self, sender, app_data):
        """Handle key presses."""
        self._cancel_countdown()
        key_code = app_data

        # Skip navigation shortcuts if typing in readme field
        if dpg.does_item_exist("readme_content_text") and dpg.is_item_focused("readme_content_text"):
            return

        # Tab - switch tabs
        if key_code == getattr(dpg, 'mvKey_Tab', None):
            self._switch_picker_tab()
            return

        # Up/W - move selection up
        if key_code in (getattr(dpg, 'mvKey_Up', None), getattr(dpg, 'mvKey_W', None)):
            self._move_picker_selection(-1)
            return

        # Down/S - move selection down
        if key_code in (getattr(dpg, 'mvKey_Down', None), getattr(dpg, 'mvKey_S', None)):
            self._move_picker_selection(1)
            return

        # Enter - launch
        if key_code in (
            getattr(dpg, 'mvKey_Enter', None),
            getattr(dpg, 'mvKey_Return', None),
            getattr(dpg, 'mvKey_KeyPadEnter', None),
        ):
            if self.selected_file:
                self._on_launch(sender, app_data)
            return

        # Escape - exit
        if key_code == getattr(dpg, 'mvKey_Escape', None):
            dpg.stop_dearpygui()
            return

        # Backspace/Delete - remove from list
        if key_code in (
            getattr(dpg, 'mvKey_Back', None),
            getattr(dpg, 'mvKey_Backspace', None),
            getattr(dpg, 'mvKey_Delete', None),
        ):
            if self.selected_file and self.last_clicked_path:
                self._confirm_and_remove(self.last_clicked_path)
            return

    def _on_row_clicked(self, sender, app_data, user_data):
        """Handle clicks on row items (icons, dates, paths)."""
        try:
            if not isinstance(app_data, tuple) or len(app_data) < 2:
                return

            item_id = app_data[1]
            clicked_tag = dpg.get_item_alias(item_id)

            if not clicked_tag:
                return

            # Determine list type and index
            if clicked_tag.startswith("recent_"):
                items = self.config.get_recent_files()
                selectable_prefix = "recent_file_"
            elif clicked_tag.startswith("template_"):
                items = self.config.get_templates()
                selectable_prefix = "template_"
            else:
                return

            # Extract index
            parts = clicked_tag.split("_")
            if len(parts) < 2:
                return

            try:
                idx = int(parts[-1])
            except ValueError:
                return

            if idx < 0 or idx >= len(items):
                return

            file_path = items[idx].get('path', '')
            if not file_path:
                return

            selectable_tag = f"{selectable_prefix}{idx}"
            self._on_file_selected(
                selectable_tag,
                app_data,
                {'path': file_path, 'type': 'recent' if 'recent' in clicked_tag else 'template'}
            )

        except Exception as e:
            logger.debug(f"Row click error: {e}")

    def _on_file_selected(self, sender, app_data, user_data):
        """Handle file selection."""
        file_path = user_data.get('path', '')
        current_time = time.time()

        # Clear all selections
        self._clear_all_selections()
        if sender and dpg.does_item_exist(sender):
            dpg.set_value(sender, True)

        # Double-click detection
        if file_path != self.last_clicked_path:
            self.last_click_time = current_time
            self.last_clicked_path = file_path

            if os.path.exists(file_path):
                self.selected_file = file_path
                self._update_version_panel()
                self.countdown_enabled = False
            return

        time_since_last = current_time - self.last_click_time

        if time_since_last < 0.05:
            return

        if 0.05 <= time_since_last < 0.5:
            # Double-click - launch without re-analyzing (already analyzed on first click)
            if os.path.exists(file_path):
                self.countdown_enabled = False
                self._on_launch(sender, app_data)
            self.last_click_time = 0
            self.last_clicked_path = None
            return

        self.last_click_time = current_time

        if os.path.exists(file_path):
            self.selected_file = file_path
            self._update_version_panel()
            self.countdown_enabled = False

    def _on_browse(self, sender, app_data):
        """Handle browse button click."""
        file_path = show_native_file_picker("Open TouchDesigner File")
        if file_path:
            self.selected_file = file_path
            self.last_clicked_path = file_path
            self._update_version_panel()

    def _on_add_template(self, sender, app_data):
        """Handle add template button click."""
        file_path = show_native_file_picker("Select TouchDesigner Project Template")
        if file_path:
            self.config.add_template(file_path)
            self._build_templates_list()

    def _on_remove_recent(self, sender, app_data, user_data):
        """Handle remove recent file button click."""
        self._confirm_and_remove(user_data, 'recent')

    def _on_remove_template(self, sender, app_data, user_data):
        """Handle remove template button click."""
        self._confirm_and_remove(user_data, 'template')

    def _on_toggle_icons(self, sender, app_data):
        """Handle show icons toggle."""
        self.config.show_icons = app_data

        # Sync checkboxes
        if dpg.does_item_exist("show_icons_checkbox"):
            dpg.set_value("show_icons_checkbox", app_data)
        if dpg.does_item_exist("show_icons_checkbox_templates"):
            dpg.set_value("show_icons_checkbox_templates", app_data)

        # Rebuild lists
        self._build_recent_files_list()
        self._build_templates_list()

    def _on_toggle_readme(self, sender, app_data):
        """Handle show readme toggle."""
        self.config.show_readme = app_data

        # Save current state
        saved_file = self.selected_file
        saved_build_info = self.build_info
        saved_tab = self._get_current_tab()

        # Clear selected file before rebuild so _build_ui doesn't analyze
        self.selected_file = None

        # Rebuild UI with new layout
        if dpg.does_item_exist("Primary Window"):
            dpg.delete_item("Primary Window")
        self._build_ui()

        # Restore state without re-analyzing
        self.selected_file = saved_file
        self.build_info = saved_build_info
        if saved_file:
            # Just rebuild version panel UI, don't re-analyze
            self._rebuild_version_panel_ui()

        # Switch to correct tab
        if saved_tab == 'templates' and dpg.does_item_exist("templates_tab"):
            templates_id = dpg.get_alias_id("templates_tab")
            dpg.set_value("file_picker_tabs", templates_id)

    def _on_launch(self, sender, app_data):
        """Handle launch button click."""
        if not self.selected_file:
            return

        self.config.add_recent_file(self.selected_file)
        self._build_recent_files_list()

        # Get selected version
        version = dpg.get_value("td_version") if dpg.does_item_exist("td_version") else self.build_info
        executable = self.td_manager.get_executable(version)

        if not executable:
            logger.error(f"Could not find executable for version {version}")
            return

        logger.info(f"Launching {self.selected_file} with {version}")

        try:
            if platform.system() == 'Darwin':
                subprocess.Popen(['open', '-a', os.path.dirname(executable), self.selected_file])
            else:
                subprocess.Popen([executable, self.selected_file])
            dpg.stop_dearpygui()
        except Exception as e:
            logger.error(f"Failed to launch: {e}")

    def _on_download(self, sender, app_data):
        """Handle download button click."""
        if not self.td_url or not self.td_uri:
            return

        logger.info(f"Downloading {self.td_url}")
        dpg.set_value("download_filter", 'b')

        try:
            def progress_hook(count, block_size, total_size):
                if total_size > 0:
                    progress = count * block_size / total_size
                    self.download_progress = min(progress, 1.0)
                    if dpg.does_item_exist('download_progress_bar'):
                        dpg.set_value('download_progress_bar', self.download_progress)
                        dpg.configure_item(
                            'download_progress_bar',
                            overlay=f'downloading {self.download_progress * 100:.1f}%'
                        )

            urlretrieve(self.td_url, filename=self.td_uri, reporthook=progress_hook)

            dpg.configure_item('download_progress_bar', overlay='100%')
            dpg.set_value("download_filter", 'z')
            dpg.set_value("install_filter", 'a')

        except Exception as e:
            logger.error(f"Download failed: {e}")
            dpg.set_value("download_filter", 'd')

    def _on_install(self, sender, app_data):
        """Handle install button click."""
        if not self.td_uri or not os.path.exists(self.td_uri):
            return

        logger.info(f"Installing {self.td_uri}")

        try:
            if platform.system() == 'Darwin':
                subprocess.Popen(['open', self.td_uri])
            else:
                subprocess.Popen([self.td_uri])
        except Exception as e:
            logger.error(f"Install failed: {e}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _clear_all_selections(self):
        """Clear all selectable states."""
        i = 0
        while dpg.does_item_exist(f"recent_file_{i}"):
            dpg.set_value(f"recent_file_{i}", False)
            i += 1
        i = 0
        while dpg.does_item_exist(f"template_{i}"):
            dpg.set_value(f"template_{i}", False)
            i += 1

    def _confirm_and_remove(self, file_path: str, list_type: str = None):
        """Confirm and remove a file from a list."""
        if not list_type:
            # Determine list type
            recent_paths = [rf if isinstance(rf, str) else rf.get('path') for rf in self.config.get_recent_files()]
            template_paths = [t if isinstance(t, str) else t.get('path') for t in self.config.get_templates()]
            abs_path = os.path.abspath(file_path)

            if abs_path in recent_paths:
                list_type = 'recent'
            elif abs_path in template_paths:
                list_type = 'template'
            else:
                return

        filename = os.path.basename(file_path)

        if self.config.confirm_remove:
            confirmed, never_ask = show_remove_confirmation(filename)
            if not confirmed:
                return
            if never_ask:
                self.config.confirm_remove = False

        if list_type == 'recent':
            self.config.remove_recent_file(file_path)
            self._build_recent_files_list()
        else:
            self.config.remove_template(file_path)
            self._build_templates_list()

        # Clear selection if removed file was selected
        if self.selected_file and os.path.abspath(self.selected_file) == os.path.abspath(file_path):
            self.selected_file = None
            dpg.configure_item("launch_button", enabled=False)
            dpg.configure_item("launch_button", label="Select a file to launch")

    def _cancel_countdown(self):
        """Cancel the countdown."""
        self.countdown_enabled = False
        if dpg.does_item_exist("launch_button"):
            if self.selected_file:
                filename = os.path.basename(self.selected_file)
                dpg.configure_item("launch_button", label=f"Open with selected version")

    def _update_countdown(self):
        """Update the countdown timer."""
        if not self.countdown_enabled:
            return

        elapsed = time.time() - self.seconds_started
        remaining = max(0, 5 - int(elapsed))

        if dpg.does_item_exist("launch_button"):
            dpg.configure_item(
                "launch_button",
                label=f"Open with selected version in {remaining} seconds"
            )

        if remaining <= 0:
            self.countdown_enabled = False
            self._on_launch(None, None)

    def _switch_picker_tab(self):
        """Switch between Recent Files and Templates tabs."""
        if not dpg.does_item_exist("file_picker_tabs"):
            return

        current = dpg.get_value("file_picker_tabs")
        templates_id = dpg.get_alias_id("templates_tab") if dpg.does_item_exist("templates_tab") else None
        recent_id = dpg.get_alias_id("recent_files_tab") if dpg.does_item_exist("recent_files_tab") else None

        if current == templates_id and recent_id:
            dpg.set_value("file_picker_tabs", recent_id)
        elif recent_id and templates_id:
            dpg.set_value("file_picker_tabs", templates_id)

        self.picker_selection_index = 0

    def _move_picker_selection(self, step: int):
        """Move selection up or down in the current list."""
        current_tab = self._get_current_tab()

        if current_tab == 'recent':
            items = self.config.get_recent_files()
            prefix = "recent_file_"
        else:
            items = self.config.get_templates()
            prefix = "template_"

        if not items:
            return

        self.picker_selection_index = (self.picker_selection_index + step) % len(items)

        # Update visual selection
        self._clear_all_selections()
        tag = f"{prefix}{self.picker_selection_index}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, True)

        # Update selected file
        item = items[self.picker_selection_index]
        file_path = item.get('path', '')
        if os.path.exists(file_path):
            self.selected_file = file_path
            self.last_clicked_path = file_path
            self._update_version_panel()

    def _get_current_tab(self) -> str:
        """Get the current picker tab."""
        try:
            if dpg.does_item_exist("file_picker_tabs"):
                current = dpg.get_value("file_picker_tabs")
                templates_id = dpg.get_alias_id("templates_tab")
                if current == templates_id:
                    return 'templates'
        except Exception:
            pass
        return 'recent'


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point."""
    # Parse command line arguments
    toe_file = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.exists(arg) and arg.lower().endswith('.toe'):
            toe_file = arg

    # Create and run app
    app = LauncherApp(toe_file)
    app.run()


if __name__ == "__main__":
    main()
