#!/usr/bin/env python3
"""TD Launcher Plus - TouchDesigner project launcher with version management."""

import os
import sys
import time
import platform
import subprocess
import logging
import threading
import webbrowser
import ctypes
from typing import Optional
from urllib.request import urlretrieve

import dearpygui.dearpygui as dpg

from config import Config, show_remove_confirmation
from td_manager import TDManager
from utils import (
    format_file_modified_time,
    show_native_file_picker,
    show_native_file_picker_multiple,
    find_project_icon,
    find_readme,
    read_readme_content,
    get_project_summary,
    load_icon_texture,
    load_default_icon,
    show_clear_confirmation,
    get_resource_path,
)

# Version
APP_VERSION = "2.0.0"

# Setup logging
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class LauncherApp:
    """Main TD Launcher Plus application."""

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
        self.countdown_start_time = 0
        self.countdown_duration = 3.0
        self.countdown_enabled = False
        
        # Track the most recently manually added file in this session
        self.active_manual_file = None

        # Session-only recent files (shown in UI but not persisted until launched)
        self.session_recent_files: list = []

        # Visible file lists (populated by _build_recent_files_list and _build_templates_list)
        self.visible_recent_files: list = []
        self.visible_templates: list = []

        self.mono_font = None
        self.active_highlight_tags = set()
        self.last_clicked_path: Optional[str] = None
        self.tab_selection_indices = {'recent': -1, 'templates': -1}
        self.selection_focus = 'versions' if toe_file else 'picker'
        self.deferred_analysis_time = 0.0
        self.analysis_thread = None
        self.current_analysis_id = 0
        self.analysis_status = "idle" # "idle", "loading", "ready_for_ui"
        self.active_highlight_tags = set()

        # Icon cache
        self.icon_textures = {}
        self.default_icon_texture = None

        # Download state
        self.td_url: Optional[str] = None
        self.td_uri: Optional[str] = None
        self.td_filename: Optional[str] = None

        # Install monitoring state
        self.install_pending_version: Optional[str] = None
        self.install_check_time: float = 0

        # Readme state
        self.current_readme_path: Optional[str] = None
        self.readme_modified: bool = False
        self.mono_font = None
        self.readme_wrapped: bool = True
        self.readme_editing_active: bool = False
        self.readme_edit_buffer: str = ""
        self.last_readme_click_time: float = 0

        # Version analysis cache (path -> build_info)
        self.version_cache: dict = {}

        # Modifier key tracking (more reliable than is_key_down in packaged builds)
        self._modifier_held = False
        self._modifier_keys = set()  # Track which modifier keys are held

    def _is_ctrl_pressed(self) -> bool:
        """Check if Ctrl (Windows) or Cmd (macOS) is currently pressed using OS-native APIs.
        
        This bypasses DearPyGui's keyboard handlers which may not work in packaged builds.
        Uses Windows GetAsyncKeyState or macOS Quartz/AppKit.
        """
        if platform.system() == 'Windows':
            # VK_CONTROL = 0x11, VK_LCONTROL = 0xA2, VK_RCONTROL = 0xA3
            try:
                user32 = ctypes.windll.user32
                # Check if high-order bit is set (key is pressed)
                return bool(user32.GetAsyncKeyState(0x11) & 0x8000)
            except Exception:
                return False
        elif platform.system() == 'Darwin':
            # macOS - check Command key (Cmd) using multiple methods
            # Method 1: Try Quartz CGEventSource
            try:
                from Quartz import CGEventSourceKeyState, kCGEventSourceStateHIDSystemState
                # kVK_Command = 0x37
                if CGEventSourceKeyState(kCGEventSourceStateHIDSystemState, 0x37):
                    return True
            except Exception:
                pass
            
            # Method 2: Try AppKit NSEvent modifierFlags
            try:
                from AppKit import NSEvent
                # NSEventModifierFlagCommand = 1 << 20 = 0x100000
                flags = NSEvent.modifierFlags()
                if flags & 0x100000:  # Command key
                    return True
            except Exception:
                pass
            
            # Method 3: Fall back to DPG (if it works on macOS)
            try:
                if hasattr(dpg, 'mvKey_ModSuper'):
                    return dpg.is_key_down(dpg.mvKey_ModSuper)
            except Exception:
                pass
            
            return False
        return False

    def run(self):
        """Run the application."""
        logger.info(f"TD Launcher Plus v{APP_VERSION}")
        logger.info(f"Platform: {platform.system()}")
        logger.info(f"Found {len(self.td_manager.versions)} TD installations")

        # Initialize file info if provided
        if self.toe_file:
            self._analyze_toe_file(self.toe_file)
            self.selected_file = self.toe_file
            self.active_manual_file = self.toe_file  # Set as session active
            # Note: Don't add to recents here - only when actually launched
        else:
            # Select first recent file by default
            recent = self.config.get_recent_files()
            if recent:
                entry = recent[0]
                self.selected_file = entry if isinstance(entry, str) else entry.get('path')

        # Create GUI
        dpg.create_context()

        # Load fonts
        with dpg.font_registry():
            try:
                # 1. Monospaced font for README
                mono_paths = [
                    "C:/Windows/Fonts/consola.ttf", # Windows
                    "/System/Library/Fonts/Supplemental/Courier New.ttf", # Mac
                    "/System/Library/Fonts/Monaco.ttf",
                    "/Library/Fonts/Andale Mono.ttf"
                ]
                for path in mono_paths:
                    if os.path.exists(path):
                        self.mono_font = dpg.add_font(path, 18)
                        # Create a smaller version for the caption
                        self.caption_font = dpg.add_font(path, 10)
                        break

            except Exception as e:
                logger.debug(f"Failed to load fonts: {e}")

        with dpg.handler_registry():
            dpg.add_mouse_click_handler(callback=self._on_mouse_click)
            dpg.add_key_press_handler(callback=self._on_key_press)
            dpg.add_key_release_handler(callback=self._on_key_release)

        self._build_ui()
        
        # Clean up window margins and scrollbars
        with dpg.theme() as global_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 8, 8)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 4)
        dpg.bind_theme(global_theme)

        # Create viewport
        info_width = 1190 if self.config.show_readme else 630
        # Windows title bar eats into viewport height
        menu_bar_offset = 40 if platform.system() == 'Windows' else 0
        viewport_kwargs = dict(
            title=f'TD Launcher Plus',
            width=info_width,
            height=675 + menu_bar_offset,
            resizable=True,
        )
        # Set window icon on Windows (macOS uses app bundle icon)
        if platform.system() == 'Windows':
            ico_path = get_resource_path("td_launcher_plus.ico")
            if os.path.exists(ico_path):
                viewport_kwargs['small_icon'] = ico_path
                viewport_kwargs['large_icon'] = ico_path
        dpg.create_viewport(**viewport_kwargs)
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
            self._check_install_complete()
            dpg.render_dearpygui_frame()

        dpg.destroy_context()

    def _analyze_toe_file(self, file_path: str):
        """Analyze a .toe file, using cache if available."""
        abs_path = os.path.abspath(file_path)

        # Check cache first
        if abs_path in self.version_cache:
            cached = self.version_cache[abs_path]
            self.build_info = cached.get('build_info')
            self.build_year = cached.get('build_year')
            self.td_url = cached.get('td_url')
            self.td_uri = cached.get('td_uri')
            self.td_filename = cached.get('td_filename')
            self.analysis_status = "ready_for_ui"
            return

        # Not in cache - analyze in background
        self.current_analysis_id += 1
        analysis_id = self.current_analysis_id
        self.analysis_status = "loading"

        def _worker(path, aid):
            try:
                build_info = self.td_manager.inspect_toe_file(path)

                # Only apply if this is still the active analysis
                if aid == self.current_analysis_id:
                    self.build_info = build_info
                    build_year = None
                    td_url = None
                    td_uri = None
                    td_filename = None

                    if self.build_info:
                        parts = self.build_info.split('.')
                        if len(parts) > 1:
                            try:
                                build_year = int(parts[1])
                            except ValueError:
                                pass
                        td_url = self.td_manager.generate_download_url(self.build_info)
                        if td_url:
                            td_filename = td_url.split("/")[-1]
                            toe_dir = os.path.dirname(os.path.abspath(path))
                            td_uri = os.path.join(toe_dir, td_filename)

                    self.build_year = build_year
                    self.td_url = td_url
                    self.td_uri = td_uri
                    self.td_filename = td_filename

                    # Store in cache
                    self.version_cache[abs_path] = {
                        'build_info': self.build_info,
                        'build_year': build_year,
                        'td_url': td_url,
                        'td_uri': td_uri,
                        'td_filename': td_filename
                    }

                    self.analysis_status = "ready_for_ui"
            except Exception as e:
                logger.error(f"Background analysis failed: {e}")
                if aid == self.current_analysis_id:
                    self.analysis_status = "ready_for_ui"

        thread = threading.Thread(target=_worker, args=(file_path, analysis_id), daemon=True)
        thread.start()
        self.analysis_thread = thread

    # =========================================================================
    # UI Building
    # =========================================================================

    def _set_row_highlight(self, tag: str, state: bool):
        """Helper to set highlight state and track active tags."""
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, state)
            
            # Update active set
            if state:
                self.active_highlight_tags.add(tag)
            elif tag in self.active_highlight_tags:
                self.active_highlight_tags.remove(tag)

            # Update theme based on state
            user_data = dpg.get_item_user_data(tag)
            if user_data and isinstance(user_data, dict):
                source = user_data.get('source', 'default')
                
                # Determine theme
                theme_tag = None
                if state:
                    # Selected Themes
                    # Check for Global Version Focus first - Use Green Theme
                    if hasattr(self, 'selection_focus') and self.selection_focus == 'versions':
                        theme_tag = "selected_focused_theme"
                    elif source == 'active':
                        theme_tag = "active_item_theme"
                    elif source == 'launcher':
                        theme_tag = "selected_launcher_theme"
                    elif source == 'td':
                        theme_tag = "selected_td_theme"
                    else:
                        theme_tag = "selected_default_theme"
                else:
                    # Normal Themes
                    if source == 'active':
                        theme_tag = "active_item_theme"
                    elif source == 'launcher':
                        theme_tag = "launcher_item_theme"
                    elif source == 'td':
                        theme_tag = "td_item_theme"
                    else:
                        theme_tag = "default_item_theme"
                
                if theme_tag and dpg.does_item_exist(theme_tag):
                    dpg.bind_item_theme(tag, theme_tag)

    def _build_ui(self):
        """Build the main UI."""
        show_icons = self.config.show_icons
        show_readme = self.config.show_readme

        # Create global click handler registry
        if dpg.does_item_exist("global_handler_registry"):
            dpg.delete_item("global_handler_registry")
        with dpg.handler_registry(tag="global_handler_registry"):
            dpg.add_mouse_click_handler(callback=self._on_global_mouse_click)

        # Create click handler registry
        if dpg.does_item_exist("row_click_handler"):
            dpg.delete_item("row_click_handler")
        with dpg.item_handler_registry(tag="row_click_handler"):
            dpg.add_item_clicked_handler(callback=self._on_row_clicked)

        with dpg.window(tag="Primary Window", no_scrollbar=True, no_move=True):
            # Header Row with Top-Right Info button
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, width=-1):
                dpg.add_table_column(width_stretch=True) # Title
                dpg.add_table_column(width_fixed=True)   # Info Button
                
                with dpg.table_row():
                    with dpg.group(horizontal=True):
                        dpg.add_text(f'TD Launcher Plus v{APP_VERSION}', color=[50, 255, 0, 255], tag="header_title")
                        with dpg.group():
                            dpg.add_spacer(height=0)
                            dpg.add_text('by Function Store', color=[100, 100, 100, 255], tag="header_caption")
                    
                    # Bind smaller mono font to caption only
                    if hasattr(self, 'caption_font') and self.caption_font:
                        dpg.bind_item_font("header_caption", self.caption_font)
                        
                    dpg.add_button(label="Info", callback=self._show_about_modal, small=True)
            
            dpg.add_separator()
            
            # Create global theme for launcher-sourced recent items (Green)
            if not dpg.does_item_exist("launcher_item_theme"):
                with dpg.theme(tag="launcher_item_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [200, 255, 200, 255], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, [80, 80, 80, 100], category=dpg.mvThemeCat_Core)
                        
            # Vibrant Green for the absolute active session file
            # When selected/active, hover should match selection color (or simulate it) to not turn gray
            if not dpg.does_item_exist("active_item_theme"):
                with dpg.theme(tag="active_item_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [50, 255, 50, 255], category=dpg.mvThemeCat_Core)
                        # Override hover to match ACTIVE header color (default blue-ish or custom?)
                        # Actually 'Header' default is roughly [66, 150, 250, 103]
                        dpg.add_theme_color(dpg.mvThemeCol_Header, [66, 150, 250, 103], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, [66, 150, 250, 103], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, [66, 150, 250, 160], category=dpg.mvThemeCat_Core)

            # Create global theme for TD-synced recent items (Yellow)
            if not dpg.does_item_exist("td_item_theme"):
                with dpg.theme(tag="td_item_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        # Pleasant soft yellow
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 200, 255], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, [80, 80, 80, 100], category=dpg.mvThemeCat_Core)

            # Default theme for standard items (White)
            if not dpg.does_item_exist("default_item_theme"):
                with dpg.theme(tag="default_item_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, [80, 80, 80, 100], category=dpg.mvThemeCat_Core)

            # Selected Themes (Prevent Gray Hover)
            # ------------------------------------
            # When selected, use default Header blue for active, hover, AND selection background
            header_blue = [66, 150, 250, 103]  # Default approximate blue
            header_active = [66, 150, 250, 160]  # Slightly brighter for active state
            
            if not dpg.does_item_exist("selected_launcher_theme"):
                with dpg.theme(tag="selected_launcher_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [200, 255, 200, 255], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_Header, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, header_active, category=dpg.mvThemeCat_Core)

            if not dpg.does_item_exist("selected_td_theme"):
                with dpg.theme(tag="selected_td_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 200, 255], category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_Header, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, header_active, category=dpg.mvThemeCat_Core)

            if not dpg.does_item_exist("selected_default_theme"):
                with dpg.theme(tag="selected_default_theme"):
                    with dpg.theme_component(dpg.mvAll):
                        # Text color handled by default/parent or override if needed?
                        # Default white
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255, 255], category=dpg.mvThemeCat_Core) 
                        dpg.add_theme_color(dpg.mvThemeCol_Header, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, header_blue, category=dpg.mvThemeCat_Core)
                        dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, header_active, category=dpg.mvThemeCat_Core)

            # Green theme for when Version List is Focused
            if not dpg.does_item_exist("selected_focused_theme"):
                header_green = [46, 180, 46, 120]
                header_green_active = [46, 180, 46, 180]
                with dpg.theme(tag="selected_focused_theme"):
                    with dpg.theme_component(dpg.mvAll):
                         dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255, 255], category=dpg.mvThemeCat_Core)
                         dpg.add_theme_color(dpg.mvThemeCol_Header, header_green, category=dpg.mvThemeCat_Core)
                         dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, header_green, category=dpg.mvThemeCat_Core)
                         dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, header_green_active, category=dpg.mvThemeCat_Core)

            with dpg.group(tag="main_ui_group"):
                # Tab bar
                with dpg.tab_bar(tag="file_picker_tabs", callback=self._on_tab_changed):
                    dpg.add_tab(label="Recent Files", tag="recent_files_tab")
                    dpg.add_tab(label="Templates", tag="templates_tab")

                # Controls row: Using table to push Clear to the right
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, width=-1):
                    dpg.add_table_column(width_stretch=True) # Controls
                    dpg.add_table_column(width_fixed=True)   # Clear button
                    
                    with dpg.table_row():
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Browse...", tag="browse_btn_recent", callback=self._on_browse)
                            
                            dpg.add_checkbox(
                                label="Full History", 
                                tag="show_full_history_checkbox", 
                                default_value=self.config.show_full_history, 
                                callback=self._on_toggle_full_history
                            )
                            with dpg.tooltip("show_full_history_checkbox"):
                                dpg.add_text("Show merged history including TD app recent files extracted by TDLauncherPlusUtility.tox when included in a project (Yellow).\nUncheck to see only manually opened files (Green).")
                            
                            dpg.add_checkbox(label="Show Icons", tag="show_icons_checkbox", default_value=show_icons, callback=self._on_toggle_icons)
                            dpg.add_checkbox(label="Show Info", tag="show_readme_checkbox", default_value=show_readme, callback=self._on_toggle_readme)
                        
                        dpg.add_button(
                            label="Clear...", 
                            tag="clear_recents_btn", 
                            callback=self._on_clear_recents,
                            small=True
                        )

                # Main content area - horizontal layout when readme shown
                with dpg.group(horizontal=show_readme, tag="content_layout"):
                    # Left side - file picker and version panel
                    with dpg.group(tag="left_panel"):
                        # File lists
                        with dpg.child_window(height=240, width=585 if show_readme else -1, tag="recent_files_list", horizontal_scrollbar=True):
                            self._build_recent_files_list()
                        with dpg.child_window(height=240, width=585 if show_readme else -1, tag="templates_list", horizontal_scrollbar=True, show=False):
                            self._build_templates_list()
                        self._apply_template_theme()
                        dpg.add_separator()
                        # Version panel
                        with dpg.child_window(height=260, width=585 if show_readme else -1, tag="version_panel"):
                            pass  # Content will be added by _update_version_panel calls

                    # Right side - README panel (only when show_readme)
                    if show_readme:
                        with dpg.child_window(tag="readme_container", width=575, height=507, border=False):
                            dpg.add_group(tag="readme_header_group")
                            dpg.add_separator()
                            dpg.add_text("Select a file...", tag="readme_status_text", color=[150, 150, 150, 255])
                            dpg.add_separator()
                            with dpg.child_window(tag="readme_scroll_parent", width=-1, height=390, horizontal_scrollbar=True):
                                with dpg.group(horizontal=True, tag="readme_content_group"):
                                    pass # Filled by _rebuild_readme_ui_internal
                            
                            dpg.add_separator()
                            with dpg.group(horizontal=True):
                                dpg.add_button(label="Save", tag="readme_save_button", callback=self._on_save_readme, show=False)
                                dpg.add_button(label="View", tag="readme_view_button", callback=self._on_view_readme, show=False)
                                dpg.add_button(label="Wrap: ON", tag="readme_wrap_toggle", callback=self._on_toggle_readme_wrap, show=False)
                            
                            # Initial population
                            self._rebuild_readme_ui_internal()

                dpg.add_separator()
                self._build_launch_button()

            # Theme for readme panel
            if show_readme:
                with dpg.theme() as info_theme:
                    with dpg.theme_component(dpg.mvChildWindow):
                        dpg.add_theme_color(dpg.mvThemeCol_ChildBg, [28, 28, 28, 255])
                        dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 4)
                    with dpg.theme_component(dpg.mvInputText):
                        dpg.add_theme_color(dpg.mvThemeCol_FrameBg, [20, 20, 20, 255])
                        dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
                        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 2)

                if dpg.does_item_exist("readme_container"):
                    dpg.bind_item_theme("readme_container", info_theme)
                if dpg.does_item_exist("readme_content_text"):
                    dpg.bind_item_theme("readme_content_text", info_theme)
                if dpg.does_item_exist("readme_content_display"):
                    # Use the same theme for consistency or define a specific one
                    dpg.bind_item_theme("readme_content_display", info_theme)

        dpg.set_primary_window("Primary Window", True)

        # If file was provided or we have recent files, select the first one visually
        # This also populates the version panel and README
        if self.visible_recent_files:
            # Force instant update at startup so UI is ready before first keypress
            self._move_picker_selection(1, instant=True)
        elif self.selected_file and self.toe_file:
            # Backup for when file provided but config empty (rare)
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
                with dpg.child_window(height=240, width=-1, tag="recent_files_list", horizontal_scrollbar=True):
                    self._build_recent_files_list()

            # Templates Tab
            with dpg.tab(label="Templates", tag="templates_tab"):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Add Templates...",
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
                with dpg.child_window(height=240, width=-1, tag="templates_list", horizontal_scrollbar=True):
                    self._build_templates_list()
                self._apply_template_theme()

    def _apply_template_theme(self):
        """Apply distinct theme to templates list."""
        if not dpg.does_item_exist("templates_list"):
            return

        # Check if theme already exists
        if dpg.does_item_exist("template_list_theme"):
            dpg.bind_item_theme("templates_list", "template_list_theme")
            return

        with dpg.theme(tag="template_list_theme"):
            dark_green = [26, 40, 28, 166]
            with dpg.theme_component(dpg.mvChildWindow):
                # Subtle dark pine green [26, 40, 28, 255]
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, dark_green)
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, dark_green)
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, dark_green)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, dark_green)

        dpg.bind_item_theme("templates_list", "template_list_theme")

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


        self.visible_recent_files = []
        # Pass the merge flag based on config
        recent_files = self.config.get_recent_files(merged=self.config.show_full_history)
        
        # Ensure active_manual_file is at the very top if it exists
        if self.active_manual_file:
            abs_active = os.path.abspath(self.active_manual_file)
            active_index = -1
            for idx, rf in enumerate(recent_files):
                if os.path.abspath(self.config._get_path_from_entry(rf)) == abs_active:
                    active_index = idx
                    break
            
            if active_index > 0:
                # Move to top
                active_item = recent_files.pop(active_index)
                recent_files.insert(0, active_item)
            elif active_index == -1:
                # If not in list (e.g. filtered out), add it
                recent_files.insert(0, {'path': abs_active, 'source': 'launcher', 'last_opened': time.time()})

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

        # 1. First pass: Calculate max display name width
        max_chars = 20 # Minimum base
        for rf in recent_files:
            file_path = rf if isinstance(rf, str) else rf.get('path', '')
            file_path = file_path.strip() if file_path else ''
            filename = os.path.basename(file_path)
            parent_folder = os.path.basename(os.path.dirname(file_path))
            
            d_name = filename
            if self._is_versioned_toe(filename):
                if parent_folder.lower() == 'backup':
                    d_name = f"Backup/{filename}"
                else:
                    base = filename[:-4]
                    base_no_version = base.rsplit('.', 1)[0]
                    d_name = f"{base_no_version}.toe"
            max_chars = max(max_chars, len(d_name))
        
        # Pixels approx: width = chars * multiplier
        # Using 9 as a safe bet for the default font
        calculated_width = max(200, (max_chars * 8) + 0)
        #calculated_width = 10

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

            # Skip if we've already shown this path (normalize for case/slash differences)
            norm_path = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))
            if norm_path in shown_paths:
                continue
            shown_paths.add(norm_path)
            self.visible_recent_files.append(file_path)

            exists = os.path.exists(file_path)
            modified = format_file_modified_time(file_path) if exists else ""
            i = display_index
            display_index += 1

            # Determine source for styling
            source = rf.get('source', 'legacy') if isinstance(rf, dict) else 'legacy'
            
            with dpg.group(horizontal=True, parent="recent_files_list", tag=f"recent_row_{i}"):
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

                # Content group for vertical centering
                with dpg.group():
                    if show_icons:
                        dpg.add_spacer(height=15)
                    with dpg.group(horizontal=True):
                        # Filename (selectable)
                        
                        # Apply custom text color based on source
                        # Normalize paths for comparison
                        abs_file_path = os.path.abspath(file_path) if file_path else ""
                        abs_active_path = os.path.abspath(self.active_manual_file) if self.active_manual_file else ""
                        
                        # Check if this is the currently selected file (for DPG visual state)
                        is_currently_selected = False
                        if self.selected_file:
                            is_currently_selected = (abs_file_path == os.path.abspath(self.selected_file))
                        
                        # Check if this is the active manual file (for Source coloring - Green)
                        is_active_session_source = (abs_file_path == abs_active_path)

                        if is_active_session_source:
                            user_source_type = 'active'
                        elif source == 'launcher':
                            user_source_type = 'launcher'
                        elif source == 'td':
                            user_source_type = 'td'
                        else:
                            user_source_type = 'default'

                        dpg.add_selectable(
                            label=display_name,
                            tag=f"recent_file_{i}",
                            callback=self._on_file_selected,
                            user_data={'path': file_path, 'type': 'recent', 'source': user_source_type},
                            width=calculated_width,
                            default_value=is_currently_selected
                        )
                        
                        if is_currently_selected:
                            self.active_highlight_tags.add(f"recent_file_{i}")
                            # Bind selected theme (Blue hover)
                            # Check for Global Version Focus first - Use Green Theme
                            if hasattr(self, 'selection_focus') and self.selection_focus == 'versions':
                                dpg.bind_item_theme(f"recent_file_{i}", "selected_focused_theme")
                            # Then Active Item Theme
                            elif user_source_type == 'active':
                                 # Keep Active Green text but override hover
                                 dpg.bind_item_theme(f"recent_file_{i}", "active_item_theme") # Active theme already has custom hover to match
                            elif user_source_type == 'launcher':
                                 dpg.bind_item_theme(f"recent_file_{i}", "selected_launcher_theme")
                            elif user_source_type == 'td':
                                 dpg.bind_item_theme(f"recent_file_{i}", "selected_td_theme")
                            else:
                                 dpg.bind_item_theme(f"recent_file_{i}", "selected_default_theme")
                        else:
                            # Bind normal theme (Gray hover)
                            if user_source_type == 'active':
                                if dpg.does_item_exist("active_item_theme"):
                                    dpg.bind_item_theme(f"recent_file_{i}", "active_item_theme")
                            elif user_source_type == 'launcher':
                                if dpg.does_item_exist("launcher_item_theme"):
                                    dpg.bind_item_theme(f"recent_file_{i}", "launcher_item_theme")
                            elif user_source_type == 'td':
                                if dpg.does_item_exist("td_item_theme"):
                                    dpg.bind_item_theme(f"recent_file_{i}", "td_item_theme")
                            else:
                                # Default theme (gray hover)
                                if dpg.does_item_exist("default_item_theme"):
                                    dpg.bind_item_theme(f"recent_file_{i}", "default_item_theme")
                            
                        summary = get_project_summary(file_path)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(summary if summary else file_path, wrap=400)

                        # Remove button (moved next to name)
                        dpg.add_button(
                            label="X",
                            tag=f"remove_recent_{i}",
                            callback=self._on_remove_recent,
                            user_data=file_path,
                            small=True
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
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(file_path, wrap=400)

                        # Missing indicator
                        if not exists:
                            dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"recent_missing_{i}")
                            dpg.bind_item_handler_registry(f"recent_missing_{i}", "row_click_handler")

    def _build_templates_list(self):
        """Build the templates list."""
        if dpg.does_item_exist("templates_list"):
            dpg.delete_item("templates_list", children_only=True)

        self.visible_templates = []
        templates = self.config.get_templates()
        show_icons = self.config.show_icons

        if not templates:
            dpg.add_text(
                "No templates added yet.\nClick 'Add Templates...' or drag a .toe file onto the app icon.",
                parent="templates_list",
                color=[150, 150, 150, 255]
            )
            return

        # 1. First pass: Calculate max name width
        max_chars = 22 # Minimum base
        for t in templates:
            name = os.path.basename(t) if isinstance(t, str) else t.get('name', os.path.basename(t.get('path', '')))
            max_chars = max(max_chars, len(name))
        
        # Consistent multiplier
        calculated_width = max(200, (max_chars * 9) + 20)

        for i, t in enumerate(templates):
            # Handle both string paths and dict entries
            file_path = t if isinstance(t, str) else t.get('path', '')
            self.visible_templates.append(file_path)
            name = os.path.basename(file_path) if isinstance(t, str) else t.get('name', os.path.basename(file_path))
            exists = os.path.exists(file_path)
            modified = format_file_modified_time(file_path) if exists else ""

            with dpg.group(horizontal=True, parent="templates_list", tag=f"template_row_{i}"):
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

                # Content group for vertical centering
                with dpg.group():
                    if show_icons:
                        dpg.add_spacer(height=15)
                    with dpg.group(horizontal=True):
                        # Name (selectable)
                        dpg.add_selectable(
                            label=name,
                            tag=f"template_{i}",
                            callback=self._on_file_selected,
                            user_data={'path': file_path, 'type': 'template'},
                            width=calculated_width
                        )
                        summary = get_project_summary(file_path)
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(summary if summary else file_path, wrap=400)

                        # Up Button
                        dpg.add_button(
                            label="^",
                            tag=f"template_up_{i}",
                            callback=self._on_move_template_up,
                            user_data=file_path,
                            small=True
                        )

                        # Down Button
                        dpg.add_button(
                            label="v",
                            tag=f"template_down_{i}",
                            callback=self._on_move_template_down,
                            user_data=file_path,
                            small=True
                        )

                        # Remove button
                        dpg.add_button(
                            label="X",
                            tag=f"remove_template_{i}",
                            callback=self._on_remove_template,
                            user_data=file_path,
                            small=True
                        )

                        # Modified date
                        dpg.add_text(f"  {modified}", color=[100, 150, 100, 255], tag=f"template_mod_{i}")
                        dpg.bind_item_handler_registry(f"template_mod_{i}", "row_click_handler")

                        # Path
                        dpg.add_text(f"  {file_path}", color=[150, 150, 150, 255], tag=f"template_path_{i}")
                        dpg.bind_item_handler_registry(f"template_path_{i}", "row_click_handler")
                        with dpg.tooltip(dpg.last_item()):
                            dpg.add_text(file_path, wrap=400)

                        # Missing indicator
                        if not exists:
                            dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"template_missing_{i}")
                            dpg.bind_item_handler_registry(f"template_missing_{i}", "row_click_handler")

    def _build_version_panel(self):
        """Build the version panel section."""
        with dpg.child_window(height=260, width=-1, tag="version_panel"):
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
            height=60,
            callback=self._on_launch,
            enabled=False
        )

            


    def _rebuild_readme_ui_internal(self):
        """Surgically rebuild only the readme panel internal widgets."""
        if not dpg.does_item_exist("readme_container"):
            return

        # 1. Rebuild Header
        if dpg.does_item_exist("readme_header_group"):
            if dpg.does_item_exist("readme_edit_header_btn"):
                dpg.delete_item("readme_edit_header_btn")
            dpg.delete_item("readme_header_group", children_only=True)
            with dpg.group(horizontal=True, parent="readme_header_group"):
                dpg.add_text("Project Info", color=[200, 200, 200, 255])
                if not self.readme_editing_active:
                    dpg.add_button(
                        label="Edit", small=True, 
                        callback=self._on_readme_text_clicked,
                        tag="readme_edit_header_btn"
                    )
                else:
                    dpg.add_text("(Editing Mode)", color=[100, 200, 100, 255])

        # 2. Rebuild Content
        if dpg.does_item_exist("readme_content_group"):
            # Explicitly delete tagged grandchildren first (DPG alias cleanup bug)
            for tag in ("readme_gutter_text", "readme_content_display", "readme_content_text"):
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            dpg.delete_item("readme_content_group", children_only=True)
            
            gutter = ""
            display_content = "No README content loaded."
            
            if self.current_readme_path and os.path.exists(self.current_readme_path):
                try:
                    # For display, we read from disk
                    with open(self.current_readme_path, 'r', encoding='utf-8') as f:
                        disk_content = f.read()
                    
                    # Use buffer if editing, otherwise disk content
                    active_text = self.readme_edit_buffer if self.readme_editing_active else disk_content
                    
                    if not self.readme_editing_active and self.readme_wrapped:
                        vp_width = dpg.get_viewport_width()
                        dynamic_width = max(30, int((vp_width - 630) / 9))
                        gutter, display_content = self._wrap_content_with_gutter(active_text, width=dynamic_width)
                    else:
                        line_count = active_text.count('\n') + 1
                        gutter = '\n'.join([f"{i+1:>3} " for i in range(line_count)])
                        display_content = active_text
                except Exception as e:
                    display_content = f"Error reading README: {e}"

            with dpg.group(horizontal=True, parent="readme_content_group"):
                # Always show gutter (line numbers)
                dpg.add_text(gutter, tag="readme_gutter_text", color=[100, 100, 100, 255])
                
                if not self.readme_editing_active:
                    # Content display
                    dpg.add_text(
                        display_content,
                        tag="readme_content_display",
                        wrap=540 if self.readme_wrapped else 0
                    )
                else:
                    # Raw input for editing - use the buffer!
                    dpg.add_input_text(
                        default_value=self.readme_edit_buffer,
                        tag="readme_content_text",
                        multiline=True,
                        width=2000 if not self.readme_wrapped else -1,
                        height=400,
                        callback=self._on_readme_changed,
                        on_enter=False
                    )

        # 3. Handler Registries
        # 3.1 Edit Mode (Focus loss)
        if dpg.does_item_exist("readme_edit_handler_registry"):
            dpg.delete_item("readme_edit_handler_registry")
        
        if self.readme_editing_active and dpg.does_item_exist("readme_content_text"):
            with dpg.item_handler_registry(tag="readme_edit_handler_registry"):
                dpg.add_item_deactivated_handler(callback=self._on_readme_deactivated)
            dpg.bind_item_handler_registry("readme_content_text", "readme_edit_handler_registry")

    def _get_readme_display_text(self) -> str:
        """Get the current readme content for display-only mode."""
        if not self.current_readme_path or not os.path.exists(self.current_readme_path):
            return "No README.md found in project root."
        try:
            with open(self.current_readme_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading README: {e}"

    def _on_global_mouse_click(self, sender, app_data):
        """Global click detector for double-clicks in the README area."""
        if app_data != dpg.mvMouseButton_Left:
            return
            
        # 1. Broadly check if we are in view mode
        if self.readme_editing_active:
            return

        # 2. Check if the README container is actually being clicked
        # Note: 'readme_scroll_parent' covers the whole info region
        if dpg.does_item_exist("readme_scroll_parent") and dpg.is_item_hovered("readme_scroll_parent"):
            current_time = time.time()
            time_diff = current_time - self.last_readme_click_time
            self.last_readme_click_time = current_time

            # Use slightly generous threshold for best feel
            if 0.01 < time_diff < 0.6:
                logger.debug(f"README double-click (dt={time_diff:.3f}s)")
                # Trigger the real edit activation
                self._on_readme_text_clicked(None, None, None)
            else:
                logger.debug(f"README single-click (dt={time_diff:.3f}s)")

    def _on_readme_text_clicked(self, sender, app_data, user_data=None):
        """Switch to edit mode surgically."""
        if not self.readme_editing_active:
            self.readme_editing_active = True
            
            # Load current file content into buffer for editing
            self.readme_edit_buffer = ""
            if self.current_readme_path and os.path.exists(self.current_readme_path):
                try:
                    with open(self.current_readme_path, 'r', encoding='utf-8') as f:
                        self.readme_edit_buffer = f.read()
                except Exception as e:
                    logger.error(f"Failed to load README for editing: {e}")

            logger.debug("Switching to README edit mode")
            self._rebuild_readme_ui_internal() # Surgical rebuild
            if dpg.does_item_exist("readme_content_text"):
                dpg.focus_item("readme_content_text")

    def _on_readme_deactivated(self, sender, app_data, user_data=None):
        """Switch back to display mode surgically."""
        if self.readme_editing_active:
            self.readme_editing_active = False
            logger.debug("Switching to README display mode")
            self._rebuild_readme_ui_internal() # Surgical rebuild


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
            if dpg.does_item_exist("launch_button"):
                dpg.configure_item("launch_button", enabled=False)
                dpg.configure_item("launch_button", label="Select a file to launch")
            self.countdown_enabled = False
            return

        # Analyze the file (unless skipped or already loading)
        if not skip_analysis:
            self.build_info = None # Reset while loading
            self._analyze_toe_file(self.selected_file)

        if self.analysis_status == "loading":
            dpg.add_text(
                "Loading build info...",
                parent="version_panel",
                color=[150, 150, 0, 255]
            )
            if dpg.does_item_exist("launch_button"):
                dpg.configure_item("launch_button", enabled=False)
                dpg.configure_item("launch_button", label="Analyzing file...")
            return

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
                # Default taller height (180) when no missing version warning is present
                with dpg.child_window(height=240, width=-1, parent="version_panel", tag="td_version_container"):
                    dpg.add_radio_button(
                        version_keys,
                        default_value=version_keys[-1],  # Most recent version
                        tag="td_version",
                        horizontal=False,
                        callback=self._on_version_selected
                    )
                if dpg.does_item_exist("launch_button"):
                    filename = os.path.basename(self.selected_file)
                    dpg.configure_item("launch_button", enabled=True)
                    dpg.configure_item("launch_button", label=f"Launch {filename}")
            else:
                dpg.add_text(
                    "No TouchDesigner versions found!",
                    parent="version_panel",
                    color=[255, 50, 0, 255]
                )
                if dpg.does_item_exist("launch_button"):
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
            # Maintain current countdown state instead of forcing True

        dpg.add_separator(parent="version_panel")

        # Version selection
        version_keys = self.td_manager.get_sorted_version_keys()
        
        default_version = None
        if version_keys:
            if self.build_info in version_keys:
                default_version = self.build_info
            else:
                # Match missing - find closest older version
                target_v = self.td_manager.parse_version_string(self.build_info)
                # version_keys is sorted ascending (earliest to latest)
                # Fallback to oldest installed if all are newer
                default_version = version_keys[0] 
                
                for v_key in version_keys:
                    current_v = self.td_manager.parse_version_string(v_key)
                    if current_v <= target_v:
                        default_version = v_key
                    else:
                        # version_keys is sorted, so we can stop once we exceed target
                        break


        # Dynamic height based on download button presence (Installed: 180, Missing: 100)
        container_height = 190 if version_installed else 163
        with dpg.child_window(height=container_height, width=-1, parent="version_panel", tag="td_version_container"):
            dpg.add_radio_button(
                version_keys,
                default_value=default_version,
                tag="td_version",
                horizontal=False,
                callback=self._on_version_selected
            )

        # Update launch button
        if dpg.does_item_exist("launch_button"):
            dpg.configure_item("launch_button", enabled=True)
            dpg.configure_item("launch_button", label=f"Launch {filename}")

        # Update readme panel
        self._update_readme_panel()

    def _on_version_selected(self, sender, app_data):
        """Handle version radio button selection."""
        self.selection_focus = 'versions'
        
        # Visual feedback: Refresh highlight to show Green (focused)
        current_tab = self._get_current_tab()
        idx = self.tab_selection_indices.get(current_tab, -1)
        if idx >= 0:
             prefix = "recent_file_" if current_tab == 'recent' else "template_"
             tag = f"{prefix}{idx}"
             self._set_row_highlight(tag, True)
             
        self.readme_editing_active = False # Reclaim focus
        if dpg.does_item_exist("readme_content_text"):
            dpg.configure_item("readme_content_text", readonly=True)
        if dpg.does_item_exist("file_picker_tabs"):
            dpg.focus_item("file_picker_tabs") # Steal DPG focus back
        # Can add logic here if we want to preview version changes

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

    def _on_toggle_readme_wrap(self, sender, app_data):
        """Toggle between wrapped view and raw edit."""
        self.readme_wrapped = not self.readme_wrapped
        label = "Wrap: ON" if self.readme_wrapped else "Wrap: OFF"
        dpg.configure_item("readme_wrap_toggle", label=label)
        
        # Re-process current content
        content = dpg.get_value("readme_content_text")
        if self.readme_wrapped:
            # Wrap it
            gutter, wrapped = self._wrap_content_with_gutter(self._unwrap_content(content))
            dpg.set_value("readme_content_text", wrapped)
            dpg.set_value("readme_gutter_text", gutter)
            dpg.configure_item("readme_content_text", width=-1)
        else:
            # Unwrap it
            unwrapped = self._unwrap_content(content)
            dpg.set_value("readme_content_text", unwrapped)
            # Simple gutter for unwrapped
            num_lines = unwrapped.count('\n') + 1
            gutter = '\n'.join([f"{i+1:>3} " for i in range(num_lines)])
            dpg.set_value("readme_gutter_text", gutter)
            dpg.configure_item("readme_content_text", width=2048)
        
        self._sync_readme_height()

    def _sync_readme_height(self):
        """Sync editor height to content to avoid internal scrollbars."""
        if not dpg.does_item_exist("readme_content_text"):
            return
        content = dpg.get_value("readme_content_text")
        num_lines = content.count('\n') + 1
        # 18pt font is roughly 24px tall with padding
        new_h = max(390, num_lines * 26 + 20)
        dpg.configure_item("readme_content_text", height=new_h)

    def _wrap_content_with_gutter(self, text: str, width: int = 65):
        """Wrap text into content and gutter strings using indentation."""
        if not text:
            return "", ""
        
        lines = text.split('\n')
        wrapped_content = []
        gutter_lines = []
        
        for i, line in enumerate(lines):
            line_num = str(i + 1)
            line_num_display = f"{line_num:>3} "
            
            if not line:
                wrapped_content.append("")
                gutter_lines.append(line_num_display)
                continue
                
            first = True
            remaining = line
            while remaining:
                if first:
                    chunk = remaining[:width]
                    wrapped_content.append(chunk)
                    gutter_lines.append(line_num_display)
                    first = False
                    remaining = remaining[width:]
                else:
                    # Wrapped part: just indent slightly, no arrows
                    chunk = remaining[:width-1]
                    wrapped_content.append(f" {chunk}")
                    gutter_lines.append("    ") 
                    remaining = remaining[width-1:]
                
        return '\n'.join(gutter_lines), '\n'.join(wrapped_content)

    def _unwrap_content(self, text: str) -> str:
        """Remove visual line indentation from wrapped lines."""
        if not text:
            return ""
        # We look for newlines followed by our single-space indent
        return text.replace('\n ', '')

    def _update_readme_panel(self):
        """Update the readme panel metadata and trigger surgical rebuild."""
        if not self.config.show_readme:
            return

        if self.selected_file and os.path.exists(self.selected_file):
            readme_path = find_readme(self.selected_file)
            project_dir = os.path.dirname(self.selected_file)
            
            if readme_path:
                self.current_readme_path = readme_path
                status_text = os.path.basename(readme_path)
                status_color = [100, 255, 100, 255]
            else:
                self.current_readme_path = os.path.join(project_dir, "README.md")
                status_text = "README.md (new)"
                status_color = [200, 200, 100, 255]
            
            if dpg.does_item_exist("readme_status_text"):
                dpg.set_value("readme_status_text", status_text)
                dpg.configure_item("readme_status_text", color=status_color)
            
            if dpg.does_item_exist("readme_save_button"):
                dpg.configure_item("readme_save_button", show=True)
            if dpg.does_item_exist("readme_view_button"):
                dpg.configure_item("readme_view_button", show=True)
            if dpg.does_item_exist("readme_wrap_toggle"):
                dpg.configure_item("readme_wrap_toggle", show=True)
            
            self.readme_modified = False
            # Trigger surgical rebuild to show the content of the new file
            self._rebuild_readme_ui_internal()
        else:
            self.current_readme_path = None
            if dpg.does_item_exist("readme_status_text"):
                dpg.set_value("readme_status_text", "Select a file...")
                dpg.configure_item("readme_status_text", color=[150, 150, 150, 255])
            self._rebuild_readme_ui_internal()

    def _on_readme_changed(self, sender, app_data):
        """Handle readme content changes and sync to buffer."""
        self.readme_modified = True
        self.readme_edit_buffer = app_data # DPG passes current string as app_data
        if dpg.does_item_exist("readme_save_button"):
            dpg.configure_item("readme_save_button", label="Save*")
        
        # Live refresh line numbers in the gutter
        if dpg.does_item_exist("readme_gutter_text"):
            line_count = app_data.count('\n') + 1
            gutter_lines = [f"{i+1:>3} " for i in range(line_count)]
            dpg.set_value("readme_gutter_text", '\n'.join(gutter_lines))

        self._sync_readme_height()

    def _on_save_readme(self, sender, app_data):
        """Save readme content to file using the robust buffer."""
        if not self.current_readme_path:
            return

        # Use the buffer directly instead of reading from a potentially-deleted widget
        try:
            with open(self.current_readme_path, 'w', encoding='utf-8') as f:
                f.write(self.readme_edit_buffer)
            
            self.readme_modified = False
            self.readme_editing_active = False # Back to viewing after save
            
            dpg.configure_item("readme_save_button", label="Save")
            
            # Rebuild from the newly written disk file
            self._rebuild_readme_ui_internal()
            
            logger.info(f"Saved README to {self.current_readme_path}")
        except Exception as e:
            logger.error(f"Failed to save README: {e}")

    def _on_view_readme(self, sender, app_data):
        """View readme rendered as HTML in browser."""
        import webbrowser
        import tempfile

        content = dpg.get_value("readme_content_text")
        # Unwrap for the HTML viewer
        content = self._unwrap_content(content)
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

    def _on_tab_changed(self, sender, app_data):
        """Handle tab bar selection change."""
        self.readme_editing_active = False # Reclaim focus
        # app_data is usually the ID of the tab in Dear PyGui tab_bar callbacks
        tab_id = app_data
        tab_tag = dpg.get_item_alias(tab_id) if isinstance(tab_id, int) else tab_id
        
        # In grid mode, we need to toggle list visibility and button labels
        # In grid mode, we need to toggle list visibility and button labels
        if tab_tag == "recent_files_tab":
            if dpg.does_item_exist("recent_files_list"):
                dpg.configure_item("recent_files_list", show=True)
            if dpg.does_item_exist("templates_list"):
                dpg.configure_item("templates_list", show=False)
            if dpg.does_item_exist("browse_btn_recent"):
                dpg.configure_item("browse_btn_recent", label="Browse...", callback=self._on_browse)
            if dpg.does_item_exist("show_full_history_checkbox"):
                dpg.configure_item("show_full_history_checkbox", show=True)
                
        elif tab_tag == "templates_tab":
            if dpg.does_item_exist("recent_files_list"):
                dpg.configure_item("recent_files_list", show=False)
            if dpg.does_item_exist("templates_list"):
                dpg.configure_item("templates_list", show=True)
            if dpg.does_item_exist("browse_btn_recent"):
                dpg.configure_item("browse_btn_recent", label="Add Templates...", callback=self._on_add_template)
            if dpg.does_item_exist("show_full_history_checkbox"):
                dpg.configure_item("show_full_history_checkbox", show=False)

        # Restore selection for the newly active tab
        self.selection_focus = 'picker'
        current_tab = 'recent' if tab_tag == "recent_files_tab" else 'templates'
        items = self.visible_recent_files if current_tab == 'recent' else self.visible_templates
        if items:
            # If nothing selected yet in this tab, select first row
            if self.tab_selection_indices[current_tab] == -1:
                self.tab_selection_indices[current_tab] = 0
            
            # Refresh visual state and loading
            self._move_picker_selection(0)

    def _on_toggle_full_history(self, sender, app_data, user_data):
        """Handle toggle of full history checkbox."""
        self.config.show_full_history = app_data
        self._build_recent_files_list()
        self._restore_selection_highlight()

    def _on_clear_recents(self, sender, app_data):
        """Handle clear history button click."""
        if show_clear_confirmation():
            logger.info("Clearing recent files history")
            self.config.clear_recents()
            
            # Clear internal state
            self.visible_recent_files = []
            self.selected_file = None
            self.active_highlight_tags.clear()
            
            # Rebuild UI
            self._build_recent_files_list()
            self._update_version_panel()
            
            if dpg.does_item_exist("readme_content_text"):
                dpg.set_value("readme_content_text", "")

    def _on_key_release(self, sender, app_data):
        """Track modifier key releases."""
        key_code = app_data
        # Use the same modifier codes as _on_key_press for consistent detection
        _modifier_codes = {
            getattr(dpg, 'mvKey_ModCtrl', 0),  # DPG 2.0+ (either Ctrl)
            getattr(dpg, 'mvKey_LControl', 341), getattr(dpg, 'mvKey_RControl', 345),
            341, 345,  # Ctrl (GLFW fallback codes)
            343, 347,  # Command (macOS)
        }
        if key_code in _modifier_codes:
            self._modifier_keys.discard(key_code)
            self._modifier_held = len(self._modifier_keys) > 0

    def _on_key_press(self, sender, app_data):
        """Handle key presses."""
        self._cancel_countdown()
        key_code = app_data

        # Track modifier keys manually (more reliable than is_key_down in packaged builds)
        _modifier_codes = {
            getattr(dpg, 'mvKey_ModCtrl', 0),  # DPG 2.0+ (either Ctrl)
            getattr(dpg, 'mvKey_LControl', 341), getattr(dpg, 'mvKey_RControl', 345),
            341, 345,  # Ctrl (GLFW fallback codes)
            343, 347,  # Command (macOS)
        }
        if key_code in _modifier_codes:
            self._modifier_keys.add(key_code)
            self._modifier_held = True
            return  # Don't process modifier-only presses as shortcuts

        # HYBRID APPROACH: Check both event tracking AND is_key_down() as fallback
        # In packaged builds, one or the other may work depending on DPG version
        modifier_held = self._modifier_held
        
        # PRIMARY FIX: Use Windows API / macOS Carbon to check Ctrl directly
        # This bypasses DPG's event handlers which may not receive Ctrl in packaged builds
        if not modifier_held:
            modifier_held = self._is_ctrl_pressed()
        
        # Fallback: If that didn't work, try DPG's is_key_down()
        if not modifier_held:
            try:
                # Try DPG 2.0+ style first
                if hasattr(dpg, 'mvKey_ModCtrl'):
                    modifier_held = dpg.is_key_down(dpg.mvKey_ModCtrl)
                # Fallback to specific Ctrl keys
                if not modifier_held and hasattr(dpg, 'mvKey_LControl'):
                    modifier_held = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
            except Exception as e:
                logger.debug(f"is_key_down fallback failed: {e}")
        


        # 1. Ctrl+S / Cmd+S - Save README (Bypasses edit block)
        if modifier_held and key_code == getattr(dpg, 'mvKey_S', -1):
            if self.readme_editing_active:
                logger.debug("Shortcut: Saving README via Ctrl+S")
                self._on_save_readme(None, None)
                return

        # Skip navigation shortcuts if README is focused AND in editing mode
        is_readme_focused = dpg.is_item_focused("readme_content_text") if dpg.does_item_exist("readme_content_text") else False
        
        # Tab Focus Steering: If we land in README via Tab but NOT in editing mode, bounce out
        if key_code == getattr(dpg, 'mvKey_Tab', -1) and is_readme_focused and not self.readme_editing_active:
            if dpg.does_item_exist("file_picker_tabs"):
                dpg.focus_item("file_picker_tabs")
            return

        if key_code != getattr(dpg, 'mvKey_Tab', -1):
            # Only block if we are EXPLICITLY in editing mode
            if is_readme_focused and self.readme_editing_active:
                return

        # 2. E Key - Toggle/Edit README
        if key_code == getattr(dpg, 'mvKey_E', -1) and modifier_held:
            # Ctrl+E / Cmd+E: Start Edit (Show first if hidden)
            logger.debug("Shortcut: Starting Edit via Ctrl+E")
            was_hidden = not self.config.show_readme
            if was_hidden:
                self._on_toggle_readme(None, True)
                if dpg.does_item_exist("show_readme_checkbox"):
                    dpg.set_value("show_readme_checkbox", True)
                # After toggle, need to update readme panel to set current_readme_path
                self._update_readme_panel()
            
            # Enter edit mode (toggle resets this, so call it after)
            self.readme_editing_active = True
            
            # Load content for editing - use the path that _update_readme_panel found
            self.readme_edit_buffer = ""
            if self.current_readme_path and os.path.exists(self.current_readme_path):
                try:
                    with open(self.current_readme_path, 'r', encoding='utf-8') as f:
                        self.readme_edit_buffer = f.read()
                except Exception:
                    pass
            
            self._rebuild_readme_ui_internal()
            
            # Focus the editor - use split_frame to let UI render first
            # Mac needs this even when not hidden; Windows too for consistency
            dpg.split_frame()
            if dpg.does_item_exist("readme_content_text"):
                dpg.focus_item("readme_content_text")
            return

        if key_code == getattr(dpg, 'mvKey_E', -1) and not modifier_held:
            # E (No modifier): Toggle On/Off
            new_state = not self.config.show_readme
            logger.debug(f"Shortcut: Toggling README to {new_state} via E")
            self._on_toggle_readme(None, new_state)
            if dpg.does_item_exist("show_readme_checkbox"):
                dpg.set_value("show_readme_checkbox", new_state)
            return

        # 3. C Key - Toggle Icons
        if key_code == getattr(dpg, 'mvKey_C', -1) and not modifier_held:
            new_state = not self.config.show_icons
            logger.debug(f"Shortcut: Toggling Icons to {new_state} via C")
            self._on_toggle_icons(None, new_state)
            return

        # 4. H Key - Toggle Full History
        if key_code == getattr(dpg, 'mvKey_H', -1) and not modifier_held:
            new_state = not self.config.show_full_history
            logger.debug(f"Shortcut: Toggling Full History to {new_state} via H")
            if dpg.does_item_exist("show_full_history_checkbox"):
                dpg.set_value("show_full_history_checkbox", new_state)
            self._on_toggle_full_history(None, new_state, None)
            return
            
        # 5. Ctrl+D / Cmd+D - Quick Launch Top Template (D for Default)
        if modifier_held and key_code == getattr(dpg, 'mvKey_D', -1):
            templates = self.config.get_templates()
            if templates:
                top_template = templates[0]
                file_path = top_template if isinstance(top_template, str) else top_template.get('path', '')
                
                # Get newest version
                version_keys = self.td_manager.get_sorted_version_keys()
                if version_keys:
                    newest_version = version_keys[-1]
                    logger.debug(f"Shortcut: Quick-launching top template {file_path} with {newest_version}")
                    self._launch_project(file_path, newest_version, promote=False)
                else:
                    logger.warning("Quick Launch failed: No TouchDesigner versions discovered.")
            else:
                logger.warning("Quick Launch failed: No templates found.")
            return

        # 6. Ctrl+1-9 / Cmd+1-9 - Launch template by position with newest TD version
        number_keys = {
            getattr(dpg, 'mvKey_1', 49): 0,
            getattr(dpg, 'mvKey_2', 50): 1,
            getattr(dpg, 'mvKey_3', 51): 2,
            getattr(dpg, 'mvKey_4', 52): 3,
            getattr(dpg, 'mvKey_5', 53): 4,
            getattr(dpg, 'mvKey_6', 54): 5,
            getattr(dpg, 'mvKey_7', 55): 6,
            getattr(dpg, 'mvKey_8', 56): 7,
            getattr(dpg, 'mvKey_9', 57): 8,
        }
        if modifier_held and key_code in number_keys:
            template_index = number_keys[key_code]
            templates = self.config.get_templates()
            if template_index < len(templates):
                template = templates[template_index]
                file_path = template if isinstance(template, str) else template.get('path', '')
                
                # Get newest version
                version_keys = self.td_manager.get_sorted_version_keys()
                if version_keys:
                    newest_version = version_keys[-1]
                    logger.debug(f"Shortcut: Launching template #{template_index + 1} ({file_path}) with {newest_version}")
                    self._launch_project(file_path, newest_version, promote=False)
                else:
                    logger.warning(f"Quick Launch #{template_index + 1} failed: No TouchDesigner versions discovered.")
            else:
                logger.debug(f"Template #{template_index + 1} does not exist (only {len(templates)} templates)")
            return

        # Space - toggle focus between picker and versions
        # Standard ascii space is 32. DPG on Windows sometimes uses 524.
        if (key_code == 32 or key_code == 524 or key_code == getattr(dpg, 'mvKey_Space', -1)) and not modifier_held:
            if self.selection_focus == 'picker':
                if dpg.does_item_exist("td_version"):
                    self.selection_focus = 'versions'
                    # Visual feedback: Picker turns Green, highlight versions
                    
                    # Refresh picker highlight to pick up Green theme (don't clear selection)
                    current_tab = self._get_current_tab()
                    idx = self.tab_selection_indices.get(current_tab, -1)
                    if idx >= 0:
                         prefix = "recent_file_" if current_tab == 'recent' else "template_"
                         tag = f"{prefix}{idx}"
                         self._set_row_highlight(tag, True)
                    
                    # Highlight version selection
                    self._move_version_selection(0)
            else:
                self.selection_focus = 'picker'
                self.readme_editing_active = False # Reclaim focus on space toggle
                # Visual feedback: Picker turns Blue
                
                # Refresh picker highlight to pick up Blue theme
                current_tab = self._get_current_tab()
                idx = self.tab_selection_indices.get(current_tab, -1)
                if idx >= 0:
                     prefix = "recent_file_" if current_tab == 'recent' else "template_"
                     tag = f"{prefix}{idx}"
                     self._set_row_highlight(tag, True)
                     
                self._move_picker_selection(0)
            return
            
        # Determing if we should move versions or file picker
        move_versions = (self.selection_focus == 'versions')

        # Tab - switch tabs
        if key_code == getattr(dpg, 'mvKey_Tab', None):
            self._switch_picker_tab()
            # Force focus back to tab bar so it never lands in textbox
            if dpg.does_item_exist("file_picker_tabs"):
                dpg.focus_item("file_picker_tabs")
            return

        # Up/W - move selection up (or reorder template with modifier)
        if key_code in (getattr(dpg, 'mvKey_Up', None), getattr(dpg, 'mvKey_W', None)):
            if modifier_held and self._get_current_tab() == 'templates' and self.selected_file:
                self._reorder_template(-1)
            elif move_versions:
                self._move_version_selection(-1)
            else:
                self._move_picker_selection(-1)
            return

        # Down/S - move selection down (or reorder template with modifier)
        if key_code in (getattr(dpg, 'mvKey_Down', None), getattr(dpg, 'mvKey_S', None)):
            if modifier_held and self._get_current_tab() == 'templates' and self.selected_file:
                self._reorder_template(1)
            elif move_versions:
                self._move_version_selection(1)
            else:
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

            file_path = items[idx] if isinstance(items[idx], str) else items[idx].get('path', '')
            if not file_path:
                return

            self.readme_editing_active = False # Reclaim focus
            if dpg.does_item_exist("readme_content_text"):
                dpg.configure_item("readme_content_text", readonly=True)
            if dpg.does_item_exist("file_picker_tabs"):
                dpg.focus_item("file_picker_tabs") # Steal DPG focus back

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

        # Sync logical focus to picker
        self.selection_focus = 'picker'
        
        # Clear all selections
        self._clear_all_selections()
        if sender:
            self._set_row_highlight(sender, True)
            
            # Sync index if sender is a numbered list item
            try:
                parts = sender.split('_')
                if parts[-1].isdigit():
                    current_tab = self._get_current_tab()
                    self.tab_selection_indices[current_tab] = int(parts[-1])
            except (AttributeError, ValueError):
                pass

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
            # Double-click - launch with current version selection IF it's installed
            if os.path.exists(file_path):
                version = dpg.get_value("td_version") if dpg.does_item_exist("td_version") else self.build_info
                if version and self.td_manager.is_version_installed(version):
                    self.countdown_enabled = False
                    # Double-click should NOT promote to top
                    self._on_launch(sender, app_data, promote=False)
                    self.last_click_time = 0
                    self.last_clicked_path = None
                else:
                    logger.warning(f"Double-click launch skipped: Version {version} not installed.")
            return

        # If it's the same file but NOT a double-click, update the time but don't re-load
        self.last_click_time = current_time

    def _on_browse(self, sender, app_data):
        """Handle browse button click."""
        file_path = show_native_file_picker("Open TouchDesigner File")
        if file_path:
            self.selected_file = file_path
            self.last_clicked_path = file_path

            # Set as active manual file (White)
            self.active_manual_file = file_path

            # Add to session recents (shown in UI but not persisted until launched)
            abs_path = os.path.abspath(file_path)
            if abs_path not in self.session_recent_files:
                self.session_recent_files.insert(0, abs_path)

            # Rebuild list and select the file
            self._build_recent_files_list()
            if self.visible_recent_files:
                self.tab_selection_indices['recent'] = 0
            self._move_picker_selection(0)

            self._update_version_panel()

    def _on_add_template(self, sender, app_data):
        """Handle add template button click."""
        file_paths = show_native_file_picker_multiple("Select TouchDesigner Project Templates")
        if file_paths:
            for file_path in file_paths:
                self.config.add_template(file_path)
            
            # Select the last added template
            last_added = file_paths[-1]
            self._rebuild_templates_with_selection(last_added)
            self._update_version_panel()

    def _on_remove_recent(self, sender, app_data, user_data):
        """Handle remove recent file button click."""
        self._confirm_and_remove(user_data, 'recent')

    def _on_remove_template(self, sender, app_data, user_data):
        """Handle remove template button click."""
        self._confirm_and_remove(user_data, 'template')

    def _on_move_template_up(self, sender, app_data, user_data):
        """Handle move template up button click."""
        file_path = user_data
        if self.config.move_template_up(file_path):
            self._rebuild_templates_with_selection(file_path)

    def _on_move_template_down(self, sender, app_data, user_data):
        """Handle move template down button click."""
        file_path = user_data
        if self.config.move_template_down(file_path):
            self._rebuild_templates_with_selection(file_path)

    def _rebuild_templates_with_selection(self, file_path: str):
        """Rebuild templates list and restore selection to the given file."""
        # Find the new index
        templates = self.config.get_templates()
        abs_path = os.path.abspath(file_path)
        new_idx = 0
        for i, t in enumerate(templates):
            path = t if isinstance(t, str) else t.get('path', '')
            if os.path.abspath(path) == abs_path:
                new_idx = i
                break

        # Update selection index and rebuild
        self.tab_selection_indices['templates'] = new_idx
        self.selected_file = file_path
        self._build_templates_list()
        self._restore_selection_highlight()

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
        self._cancel_countdown()

        # Save current state
        saved_file = self.selected_file
        saved_build_info = self.build_info
        saved_tab = self._get_current_tab()
        saved_indices = self.tab_selection_indices.copy()

        # Clear selected file before rebuild so _build_ui doesn't analyze
        self.selected_file = None

        # Rebuild UI with new layout
        if dpg.does_item_exist("Primary Window"):
            dpg.delete_item("Primary Window")

        # Resize viewport before rebuild
        if app_data:
            dpg.set_viewport_width(1190)
        else:
            dpg.set_viewport_width(630)

        self._build_ui()
        self.readme_editing_active = False # Reset focus state on rebuild
        if dpg.does_item_exist("file_picker_tabs"):
            dpg.focus_item("file_picker_tabs") # Force DPG focus away from text fields

        # Restore state without re-analyzing
        self.selected_file = saved_file
        self.build_info = saved_build_info
        self.tab_selection_indices = saved_indices

        if saved_file:
            # Just rebuild version panel UI, don't re-analyze
            self._rebuild_version_panel_ui()

        # Switch to correct tab and restore visual selection
        if saved_tab == 'templates' and dpg.does_item_exist("templates_tab"):
            templates_id = dpg.get_alias_id("templates_tab")
            dpg.set_value("file_picker_tabs", templates_id)
            # Show templates list, hide recent files list
            if dpg.does_item_exist("templates_list"):
                dpg.configure_item("templates_list", show=True)
            if dpg.does_item_exist("recent_files_list"):
                dpg.configure_item("recent_files_list", show=False)

        # Restore visual selection highlight (instant=True skips deferred analysis)
        self._restore_selection_highlight()

    def _launch_project(self, file_path, version, promote=True):
        """Core logic to launch a TD project with a specific version."""
        if promote:
            self.config.add_recent_file(file_path)
            self.active_manual_file = file_path  # Set as session active
            self._build_recent_files_list()

        executable = self.td_manager.get_executable(version)
        if not executable:
            logger.error(f"Could not find executable for version {version}")
            return

        logger.info(f"Launching {file_path} with {version}")

        try:
            if platform.system() == 'Darwin':
                app_path = self.td_manager.get_app_path(version)
                if app_path:
                    subprocess.Popen(['open', '-a', app_path, file_path])
                else:
                    subprocess.Popen([executable, file_path])
            else:
                subprocess.Popen([executable, file_path])
            
            # Close launcher after successful launch command
            dpg.stop_dearpygui()
        except Exception as e:
            logger.error(f"Failed to launch: {e}")

    def _on_launch(self, sender, app_data, promote=True):
        """Handle launch button click."""
        if not self.selected_file:
            return

        # Get selected version
        version = dpg.get_value("td_version") if dpg.does_item_exist("td_version") else self.build_info
        self._launch_project(self.selected_file, version, promote=promote)

    def _on_download(self, sender, app_data):
        """Handle download button click."""
        if not self.td_url or not self.td_uri:
            return

        # Skip download if installer already exists next to the project file
        if os.path.exists(self.td_uri):
            logger.info(f"Installer already exists: {self.td_uri}")
            dpg.set_value("download_filter", 'z')
            dpg.set_value("install_filter", 'a')
            self._show_install_prompt_modal()
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
            self._show_install_prompt_modal()

        except Exception as e:
            logger.error(f"Download failed: {e}")
            dpg.set_value("download_filter", 'd')

    def _show_install_prompt_modal(self):
        """Show modal prompting user to install the downloaded TD version."""
        modal_tag = "install_prompt_modal"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        filename = os.path.basename(self.td_uri) if self.td_uri else ""
        viewport_width = dpg.get_viewport_width()
        viewport_height = dpg.get_viewport_height()
        modal_width = 380
        modal_height = 130

        with dpg.window(
            label="Download Complete",
            modal=True,
            tag=modal_tag,
            no_resize=True,
            no_move=False,
            width=modal_width,
            height=modal_height,
            pos=[(viewport_width - modal_width) // 2, (viewport_height - modal_height) // 2]
        ):
            dpg.add_text(f"Ready to install {self.build_info}")
            dpg.add_text(filename, color=[150, 150, 150, 255])
            dpg.add_spacer(height=5)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Install",
                    callback=lambda: (self._on_install(None, None), dpg.delete_item(modal_tag))
                )
                dpg.add_button(
                    label="Later",
                    callback=lambda: dpg.delete_item(modal_tag)
                )

    def _on_install(self, sender, app_data):
        """Handle install button click."""
        if not self.td_uri or not os.path.exists(self.td_uri):
            return

        logger.info(f"Installing {self.td_uri}")

        try:
            if platform.system() == 'Darwin':
                subprocess.Popen(['open', self.td_uri])
            else:
                os.startfile(self.td_uri)
            # Start monitoring for installation completion
            if self.build_info:
                self.install_pending_version = self.build_info
                self.install_check_time = time.time()
                logger.info(f"Monitoring registry for {self.build_info} installation...")
        except Exception as e:
            logger.error(f"Install failed: {e}")

    def _check_install_complete(self):
        """Poll registry to check if pending installation has completed."""
        if not self.install_pending_version:
            return

        # Check every 3 seconds
        now = time.time()
        if now - self.install_check_time < 3.0:
            return
        self.install_check_time = now

        # Re-scan registry for new versions
        self.td_manager.discover_versions()
        if self.td_manager.is_version_installed(self.install_pending_version):
            logger.info(f"{self.install_pending_version} installed successfully")
            installed_uri = self.td_uri
            self.install_pending_version = None
            # Refresh the version panel to reflect the new installation
            self._update_version_panel(skip_analysis=True)
            # Offer to delete the installer file
            if installed_uri and os.path.exists(installed_uri):
                self._show_delete_installer_modal(installed_uri)

    def _show_delete_installer_modal(self, installer_path):
        """Show modal offering to delete the installer file after successful install."""
        modal_tag = "delete_installer_modal"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        filename = os.path.basename(installer_path)
        viewport_width = dpg.get_viewport_width()
        viewport_height = dpg.get_viewport_height()
        modal_width = 380
        modal_height = 130

        with dpg.window(
            label="Installation Complete",
            modal=True,
            tag=modal_tag,
            no_resize=True,
            no_move=False,
            width=modal_width,
            height=modal_height,
            pos=[(viewport_width - modal_width) // 2, (viewport_height - modal_height) // 2]
        ):
            dpg.add_text(f"Installation complete. Delete installer?")
            dpg.add_text(filename, color=[150, 150, 150, 255])
            dpg.add_spacer(height=5)
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Delete",
                    callback=lambda: self._delete_installer(installer_path, modal_tag)
                )
                dpg.add_button(
                    label="Keep",
                    callback=lambda: dpg.delete_item(modal_tag)
                )

    def _delete_installer(self, installer_path, modal_tag):
        """Delete the installer file and close the modal."""
        try:
            os.remove(installer_path)
            logger.info(f"Deleted installer: {installer_path}")
        except Exception as e:
            logger.error(f"Failed to delete installer: {e}")
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

    def _show_about_modal(self, sender, app_data):
        """Show the About / Info modal."""
        modal_tag = "about_modal"
        if dpg.does_item_exist(modal_tag):
            dpg.delete_item(modal_tag)

        # Center approx
        viewport_width = dpg.get_viewport_width()
        viewport_height = dpg.get_viewport_height()
        modal_width = 350
        modal_height = 240

        with dpg.window(
            label="About TD Launcher Plus",
            tag=modal_tag,
            modal=True,
            show=True,
            no_resize=True,
            no_move=True,
            width=modal_width,
            height=modal_height,
            pos=[(viewport_width - modal_width) // 2, (viewport_height - modal_height) // 2]
        ):
            dpg.add_text(f"TD Launcher Plus v{APP_VERSION}", color=[50, 255, 0, 255])
            dpg.add_spacer(height=5)
            dpg.add_text("A project launcher for TouchDesigner\nwith recent files list, version selection\nand more.")
            dpg.add_spacer(height=10)
            
            with dpg.group(horizontal=True):
                dpg.add_text("Author:")
                dpg.add_text("Dan Molnar", color=[200, 255, 200, 255])
                dpg.add_text("(Function Store)", color=[150, 150, 150, 255])

            with dpg.group(horizontal=True):
                dpg.add_text("Original Author:")
                dpg.add_text("Lucas Morgan", color=[200, 255, 200, 255])
                dpg.add_text("(EnviralDesign)", color=[150, 150, 150, 255])

            dpg.add_spacer(height=10)
            with dpg.table(header_row=False, width=-1):
                dpg.add_table_column(width_stretch=True)
                dpg.add_table_column(width_fixed=True)
                dpg.add_table_column(width_stretch=True)
                with dpg.table_row():
                    dpg.add_text("") # Left stretch
                    with dpg.group(horizontal=True):
                        dpg.add_button(label="GitHub Repo", callback=self._on_visit_github)
                        dpg.add_button(label="Update", callback=self._on_check_updates)
                        dpg.add_button(label="Close", callback=lambda: dpg.delete_item(modal_tag))
                    dpg.add_text("") # Right stretch

    def _on_visit_github(self):
        """Open the GitHub repository in the browser."""
        webbrowser.open("https://github.com/function-store/TD-Launcher-Plus")

    def _on_check_updates(self):
        """Open the latest releases page on GitHub."""
        webbrowser.open("https://github.com/function-store/TD-Launcher-Plus/releases/latest")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _clear_all_selections(self):
        """Clear all active selections efficiently."""
        # Use set to clear only what is active instead of scanning all rows
        # We must use list() copy because _set_row_highlight removes from the set
        for tag in list(self.active_highlight_tags):
            self._set_row_highlight(tag, False)
        
        # Set should be empty now, but clear just in case
        self.active_highlight_tags.clear()

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
            if dpg.does_item_exist("launch_button"):
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
        """Update the countdown timer and handle debounced analysis."""
        # Handle background analysis completion
        if self.analysis_status == "ready_for_ui":
            self.analysis_status = "idle"
            self._update_version_panel(skip_analysis=True)

        # Handle debounced analysis
        if self.deferred_analysis_time > 0 and time.time() > self.deferred_analysis_time:
            self.deferred_analysis_time = 0
            self._update_version_panel()

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
            self._move_picker_selection(0) # Trigger selection restoration
        elif recent_id and templates_id:
            dpg.set_value("file_picker_tabs", templates_id)
            self._move_picker_selection(0)

    def _move_picker_selection(self, step: int, instant: bool = False):
        """Move selection up or down in the current list."""
        current_tab = self._get_current_tab()

        if current_tab == 'recent':
            items = self.visible_recent_files
            prefix = "recent_file_"
        else:
            items = self.visible_templates
            prefix = "template_"

        if not items:
            return

        # Initialize to 0 if starting from -1
        if self.tab_selection_indices[current_tab] == -1:
            self.tab_selection_indices[current_tab] = 0
        else:
            self.tab_selection_indices[current_tab] = (self.tab_selection_indices[current_tab] + step) % len(items)

        # Update visual selection
        self._clear_all_selections()
        tag = f"{prefix}{self.tab_selection_indices[current_tab]}"
        if dpg.does_item_exist(tag):
            self._set_row_highlight(tag, True)
            
            # Scroll to selection
            container = "recent_files_list" if current_tab == 'recent' else "templates_list"
            if dpg.does_item_exist(container):
                # Precise row heights based on DPG metrics:
                # With icons: Image(50) + vertical spacing(4) + potential header overhead + container padding
                # Standard DPG row in this layout with 50px icon ends up ~68-72px including spacing.
                row_h = 68 if self.config.show_icons else 32
                target_y = self.tab_selection_indices[current_tab] * row_h
                
                curr_scroll = dpg.get_y_scroll(container)
                page_h = 280  # Consistent height for both modes
                
                # If we're moving Up and selection is above the fold
                if target_y < curr_scroll:
                    dpg.set_y_scroll(container, max(0, target_y - 4)) 
                # If we're moving Down and selection is below the fold
                elif target_y + row_h > curr_scroll + page_h:
                    dpg.set_y_scroll(container, target_y + row_h - page_h + 4)

        # Update selected file
        item = items[self.tab_selection_indices[current_tab]]
        file_path = item if isinstance(item, str) else item.get('path', '')
        if os.path.exists(file_path):
            self.selected_file = file_path
            self.last_clicked_path = file_path
            
            if instant:
                self.deferred_analysis_time = 0
                self._update_version_panel()
            else:
                # Defer analysis to keep navigation snappy
                self.deferred_analysis_time = time.time() + 0.150

    def _reorder_template(self, direction: int):
        """Reorder the selected template up (-1) or down (1)."""
        if not self.selected_file:
            return

        # Move the template in the config
        if direction < 0:
            moved = self.config.move_template_up(self.selected_file)
        else:
            moved = self.config.move_template_down(self.selected_file)

        if moved:
            # Find new index after move
            templates = self.config.get_templates()
            abs_path = os.path.abspath(self.selected_file)
            new_idx = 0
            for i, t in enumerate(templates):
                path = t if isinstance(t, str) else t.get('path', '')
                if os.path.abspath(path) == abs_path:
                    new_idx = i
                    break

            # Update selection index before rebuilding
            self.tab_selection_indices['templates'] = new_idx

            # Rebuild the list
            self._build_templates_list()

            # Restore selection highlight
            self._restore_selection_highlight()

    def _restore_selection_highlight(self):
        """Restore visual selection highlight without triggering analysis."""
        current_tab = self._get_current_tab()

        if current_tab == 'recent':
            items = self.visible_recent_files
            prefix = "recent_file_"
        else:
            items = self.visible_templates
            prefix = "template_"

        if not items:
            return

        idx = self.tab_selection_indices.get(current_tab, -1)
        if idx < 0 or idx >= len(items):
            return

        # Update visual selection only
        self._clear_all_selections()
        tag = f"{prefix}{idx}"
        if dpg.does_item_exist(tag):
            self._set_row_highlight(tag, True)

    def _move_version_selection(self, step: int):
        """Move version selection up or down."""
        if not dpg.does_item_exist("td_version"):
            return
            
        version_keys = self.td_manager.get_sorted_version_keys()
        if not version_keys:
            return
            
        current_version = dpg.get_value("td_version")
        try:
            # Keys are sorted, so we can find index
            current_idx = version_keys.index(current_version)
        except ValueError:
            current_idx = 0
            
        new_idx = max(0, min(current_idx + step, len(version_keys) - 1))
        dpg.set_value("td_version", version_keys[new_idx])
        
        # Scroll to selection
        if dpg.does_item_exist("td_version_container"):
            row_h = 22 # Standard radio row height
            target_y = new_idx * row_h
            curr_scroll = dpg.get_y_scroll("td_version_container")
            page_h = 150 # Height as defined in _update_version_panel (synced)
            
            if target_y < curr_scroll:
                dpg.set_y_scroll("td_version_container", target_y)
            elif target_y + row_h > curr_scroll + page_h:
                dpg.set_y_scroll("td_version_container", target_y + row_h - page_h)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_current_tab(self) -> str:
        """Get the current picker tab."""
        try:
            if dpg.does_item_exist("file_picker_tabs"):
                current = dpg.get_value("file_picker_tabs")
                # DPG can return alias string OR int ID depending on version/context
                # Safer to check if it matches the "Templates" tab ID/Alias
                templates_alias = "templates_tab"
                templates_id = dpg.get_alias_id(templates_alias)
                
                if current == templates_alias or current == templates_id:
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
