import dearpygui.dearpygui as dpg
import subprocess
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import platform
import plistlib
import glob
import logging
import json
from typing import Dict, Any, List, Optional
try:
    from PIL import Image
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Platform-specific file dialog imports
if platform.system() == 'Windows':
    import tkinter as tk
    from tkinter import filedialog

# Platform-specific imports
if platform.system() == 'Windows':
    import winreg

app_version = '1.1.0'

# Setup debug logging
# Check if running as app bundle (different working directory patterns)
is_app_bundle = '/Contents/MacOS' in os.path.abspath(__file__) or os.getcwd() == '/'
DEBUG_MODE = os.environ.get('TD_LAUNCHER_DEBUG', '').lower() in ('1', 'true', 'yes')

if DEBUG_MODE:
    # For app bundles, write log to a location we can access
    log_file = os.path.expanduser('~/Desktop/td_launcher_debug.log') if is_app_bundle else 'td_launcher_debug.log'
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )
    print(f"🐛 DEBUG MODE ENABLED - Logging to console and {log_file}")
    if is_app_bundle:
        print(f"📱 Running as app bundle - debug log: {log_file}")
else:
    logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger(__name__)

# Debug output only when explicitly enabled
if DEBUG_MODE:
    print("=" * 60)
    print("🐛 TD LAUNCHER DEBUG MODE")
    print("=" * 60)
    print(f"Script file: {__file__}")
    print(f"Absolute script path: {os.path.abspath(__file__)}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Command line args: {sys.argv}")
    print(f"App bundle: {is_app_bundle}")
    print(f"Log file location: {log_file}")
    print("=" * 60)

num_sec_until_autostart = 5
current_directory = os.path.dirname(__file__)
countdown_enabled = True
download_progress = 0.0
should_exit = False  # Global flag for graceful shutdown on macOS
picker_mode = False  # True = file picker UI, False = version picker UI
selected_file_path = None  # Currently selected file in picker mode
app_config = None  # Will hold the loaded config
last_click_time = 0  # For double-click detection
last_clicked_path = None  # For double-click detection
last_click_id = None  # Combination of path+time to detect true duplicates
picker_selection_index = 0  # Current selection index in file picker lists
show_icons = False  # Toggle for showing project icons
icon_textures = {}  # Cache for loaded icon textures
default_icon_texture = None  # Default icon texture for files without project icons
show_readme = False  # Toggle for showing README panel

# ============================================================================
# Config Module - Persistent storage for recent files and templates
# ============================================================================

DEFAULT_CONFIG = {
    'version': 1,
    'recent_files': [],  # List of dicts: [{'path': str, 'last_opened': timestamp}, ...]
    'templates': [],  # List of dicts: [{'path': str, 'name': str, 'added': timestamp}, ...]
    'max_recent_files': 20,
    'confirm_remove_from_list': True,  # Show confirmation when removing files from lists
    'show_icons': False,  # Show project icons in file lists
    'show_readme': False,  # Show README.md side panel
}

def get_config_dir() -> str:
    """Get cross-platform config directory path."""
    system = platform.system()

    if system == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        config_dir = os.path.join(base, 'TD Launcher')
    elif system == 'Darwin':  # macOS
        config_dir = os.path.expanduser('~/.config/td-launcher')
    else:  # Linux and others
        xdg_config = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        config_dir = os.path.join(xdg_config, 'td-launcher')

    return config_dir

def get_config_file_path() -> str:
    """Get full path to the config JSON file."""
    return os.path.join(get_config_dir(), 'config.json')

def ensure_config_dir_exists() -> bool:
    """Create config directory if it doesn't exist. Returns True if successful."""
    config_dir = get_config_dir()
    try:
        os.makedirs(config_dir, exist_ok=True)
        return True
    except OSError as e:
        logger.error(f"Failed to create config directory: {e}")
        return False

def load_config() -> Dict[str, Any]:
    """Load config from disk, returning default config if file doesn't exist or is invalid."""
    config_path = get_config_file_path()

    if not os.path.exists(config_path):
        logger.debug(f"Config file not found at {config_path}, using defaults")
        return DEFAULT_CONFIG.copy()

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Validate and merge with defaults (in case new fields were added)
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)

        # Validate recent_files entries exist on disk
        merged['recent_files'] = [
            rf for rf in merged.get('recent_files', [])
            if os.path.exists(rf.get('path', ''))
        ]

        # Validate template entries exist on disk
        merged['templates'] = [
            t for t in merged.get('templates', [])
            if os.path.exists(t.get('path', ''))
        ]

        return merged

    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load config: {e}, using defaults")
        return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> bool:
    """Save config to disk. Returns True if successful."""
    if not ensure_config_dir_exists():
        return False

    config_path = get_config_file_path()

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        logger.debug(f"Config saved to {config_path}")
        return True
    except IOError as e:
        logger.error(f"Failed to save config: {e}")
        return False

def add_recent_file(file_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add a file to the recent files list. Returns updated config."""
    if config is None:
        config = load_config()

    # Normalize path
    file_path = os.path.abspath(file_path)

    # Remove existing entry for this file if present
    config['recent_files'] = [
        rf for rf in config['recent_files']
        if rf.get('path') != file_path
    ]

    # Add new entry at the beginning
    config['recent_files'].insert(0, {
        'path': file_path,
        'last_opened': time.time()
    })

    # Trim to max size
    max_recent = config.get('max_recent_files', 20)
    config['recent_files'] = config['recent_files'][:max_recent]

    save_config(config)
    return config

def add_template(file_path: str, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add a file to templates. Returns updated config."""
    if config is None:
        config = load_config()

    file_path = os.path.abspath(file_path)

    # Check if already exists
    existing = [t for t in config['templates'] if t.get('path') == file_path]
    if existing:
        logger.debug(f"Template already exists: {file_path}")
        return config

    # Use filename as default name
    if name is None:
        name = os.path.basename(file_path)

    config['templates'].append({
        'path': file_path,
        'name': name,
        'added': time.time()
    })

    save_config(config)
    return config

def remove_template(file_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Remove a template from the list. Returns updated config."""
    if config is None:
        config = load_config()

    file_path = os.path.abspath(file_path)
    config['templates'] = [
        t for t in config['templates']
        if t.get('path') != file_path
    ]

    save_config(config)
    return config

def remove_recent_file(file_path: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Remove a file from the recent files list. Returns updated config."""
    if config is None:
        config = load_config()

    file_path = os.path.abspath(file_path)
    config['recent_files'] = [
        rf for rf in config['recent_files']
        if rf.get('path') != file_path
    ]

    save_config(config)
    return config

def show_remove_confirmation(filename: str) -> tuple[bool, bool]:
    """Show confirmation dialog for removing a file from list.
    Returns (confirmed, never_ask_again)."""
    if platform.system() == 'Darwin':  # macOS
        try:
            script = f'''
            set dialogResult to display dialog "Remove \\"{filename}\\" from this list?\\n\\nThis only removes it from TD Launcher's list, not from your file system." buttons {{"Cancel", "Remove", "Remove & Don't Ask Again"}} default button "Remove" with title "Remove from List"
            return button returned of dialogResult
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            button = result.stdout.strip()
            if result.returncode != 0 or button == "Cancel":
                return (False, False)
            elif "Don't Ask Again" in button:
                return (True, True)
            else:
                return (True, False)
        except Exception as e:
            logger.error(f"Failed to show confirmation dialog: {e}")
            return (True, False)  # Default to allowing removal if dialog fails
    else:
        # Windows - just confirm for now
        return (True, False)

def set_confirm_remove_preference(never_ask: bool, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Set the preference for confirmation dialogs."""
    if config is None:
        config = load_config()
    config['confirm_remove_from_list'] = not never_ask
    save_config(config)
    return config

# ============================================================================

# Essential startup logging only
logger.info(f"TD Launcher v{app_version} starting...")
if DEBUG_MODE:
    logger.debug(f"Command line args: {sys.argv}")
    logger.debug(f"Working directory: {os.getcwd()}")
    logger.debug(f"Platform: {platform.system()} {platform.release()}")

if len(sys.argv) >= 2:
    td_file_path = sys.argv[1] # this gets passed in as argument
    picker_mode = False
    if DEBUG_MODE:
        logger.debug(f"File path from command line: {td_file_path}")

    # Convert to absolute path to avoid working directory issues
    if not os.path.isabs(td_file_path):
        td_file_path = os.path.abspath(td_file_path)
        if DEBUG_MODE:
            logger.debug(f"Converted to absolute path: {td_file_path}")
else:
    # No command line argument - show file picker UI
    picker_mode = True
    td_file_path = None
    logger.info("No file specified - will show file picker UI")

# Validate the file path (only if not in picker mode)
if not picker_mode:
    if not os.path.exists(td_file_path):
        logger.error(f"File does not exist: {td_file_path}")
        logger.error(f"Directory contents of parent: {os.listdir(os.path.dirname(td_file_path)) if os.path.exists(os.path.dirname(td_file_path)) else 'Parent directory does not exist'}")
        print(f"❌ Error: File not found: {td_file_path}")
    else:
        if DEBUG_MODE:
            logger.debug(f"Target file exists: {td_file_path} (size: {os.path.getsize(td_file_path)} bytes)")

def query_td_registry_entries():
    # scan the registry and store any keys we find along the way that contain the string "TouchDesigner"
    reg = winreg.ConnectRegistry(None,winreg.HKEY_CLASSES_ROOT)
    td_matching_keys = []
    for i in range(16384): # just iterate on a really big number.. we exit early if we get to the end anyways.
        try:
            key_name = winreg.EnumKey(reg, i)
        except OSError as e:
            if "WinError 259" in str(e):
                print('reached end of registry, finishing registry scan...')
            else:
                print('unknown OSError', e)
            break

        # if touchdesigner exists in key and if there is no suffix like .Asset or .Component, we save the key.
        if "TouchDesigner" in key_name and key_name.split('.')[-1].isdigit():
            td_matching_keys += [ key_name ]
    
    td_matching_keys = sorted(td_matching_keys)

    td_key_id_dict = { k:{} for k in td_matching_keys }
    for k,v in td_key_id_dict.items():
        entry_val = winreg.QueryValue(reg, f'{k}\\shell\\open\\command')
        td_key_id_dict[k]['executable'] = entry_val.split('"')[1]
    
    return td_key_id_dict

def query_td_mac_applications():
    """Mac version: scan /Applications for TouchDesigner apps and extract version info from Info.plist"""
    if DEBUG_MODE:
        logger.debug("Scanning for TouchDesigner applications...")
    td_matching_apps = []
    applications_dir = "/Applications"
    
    # Look for TouchDesigner applications
    td_pattern = os.path.join(applications_dir, "TouchDesigner*")
    logger.debug(f"Searching pattern: {td_pattern}")
    td_apps = glob.glob(td_pattern)
    if DEBUG_MODE:
        logger.debug(f"Found {len(td_apps)} potential TouchDesigner apps")
    
    td_key_id_dict = {}
    
    for app_path in td_apps:
        if not app_path.endswith('.app'):
            continue
            
        app_name = os.path.basename(app_path)
        info_plist_path = os.path.join(app_path, "Contents", "Info.plist")
        logger.debug(f"Processing app: {app_name}")
        logger.debug(f"Info.plist path: {info_plist_path}")
        
        try:
            # Read the Info.plist file
            with open(info_plist_path, 'rb') as f:
                plist_data = plistlib.load(f)
            
            # Extract version information
            bundle_version = plist_data.get('CFBundleVersion', '')
            bundle_name = plist_data.get('CFBundleName', app_name)
            logger.debug(f"Bundle version: {bundle_version}, Bundle name: {bundle_name}")
            
            if bundle_version:
                # Create a key in the format TouchDesigner.VERSION.BUILD
                # Parse the version to match Windows registry format
                version_parts = bundle_version.split('.')
                if len(version_parts) >= 2:
                    year = version_parts[0]
                    build = version_parts[1] if len(version_parts) > 1 else "0"
                    td_key = f"TouchDesigner.{year}.{build}"
                    
                    # Path to the executable inside the app bundle
                    executable_path = os.path.join(app_path, "Contents", "MacOS", "TouchDesigner")
                    
                    td_key_id_dict[td_key] = {
                        'executable': executable_path,
                        'app_path': app_path,
                        'bundle_version': bundle_version
                    }
                    if DEBUG_MODE:
                        logger.debug(f"Found TouchDesigner: {td_key} at {executable_path}")
                else:
                    logger.warning(f"Could not parse version from {bundle_version}")
            else:
                logger.warning(f"No bundle version found for {app_name}")
                    
        except (FileNotFoundError, plistlib.InvalidFileException, KeyError) as e:
            logger.error(f"Could not read Info.plist for {app_path}: {e}")
            print(f"Could not read Info.plist for {app_path}: {e}")
            continue
    
    return td_key_id_dict

'''
def inspect_toe():
    # This function is no longer used, but keeping for reference. Since newer versions of toeexpand do not require dumping the .build directory
    # to disk, we can simply get the build option from the subprocess output as seen in the _v2 function below.

    td_file_path_osstyle = td_file_path.replace('/','\\')
    command = f'"{current_directory}\\toeexpand\\toeexpand.exe" "{td_file_path_osstyle}" .build'

    expand_dir = f'{td_file_path_osstyle}.dir'
    expand_toc = f'{td_file_path_osstyle}.toc'

    expand_dir_obj = Path(expand_dir)
    if expand_dir_obj.exists() == True:
        shutil.rmtree(expand_dir_obj.resolve())

    expand_toc_obj = Path(expand_toc)
    if expand_toc_obj.exists() == True:
        os.remove(expand_toc_obj.resolve())

    res = subprocess.call(command, shell = True)
    build_file = f'{expand_dir}\\.build'
    
    with open(build_file,'r',encoding = 'utf-8') as f:
        build_info = f.read()
    
    expand_dir_obj = Path(expand_dir)
    if expand_dir_obj.exists() == True:
        shutil.rmtree(expand_dir_obj.resolve())

    expand_toc_obj = Path(expand_toc)
    if expand_toc_obj.exists() == True:
        os.remove(expand_toc_obj.resolve())
    
    info_split = build_info.split('\n')
    # print(info_split)
    build_option = f'TouchDesigner.{info_split[1].split(" ")[-1]}'
    
    return build_option
'''

def inspect_toe_v2():
    # this version of inspect_toe does not need to access extracted files on disk, 
    # it simply gets the information directly from the subprocess.Popen() output.
    
    logger.info("Analyzing TOE file version...")
    
    # Cross-platform path handling
    if platform.system() == 'Windows':
        toeexpand_path = os.path.join(current_directory, "toeexpand", "toeexpand.exe")
        logger.debug(f"Using Windows toeexpand: {toeexpand_path}")
    else:  # Mac/Linux
        # For Mac, we'll use toeexpand from the first available TouchDesigner installation
        logger.debug("Looking for toeexpand in TouchDesigner installations...")
        td_apps = query_td_mac_applications()
        if td_apps:
            # Get the first available TouchDesigner app
            first_app = list(td_apps.values())[0]
            app_path = first_app['app_path']
            toeexpand_path = os.path.join(app_path, "Contents", "MacOS", "toeexpand")
            if DEBUG_MODE:
                logger.debug(f"Using toeexpand from: {app_path}")
            logger.debug(f"Toeexpand path: {toeexpand_path}")
        else:
            logger.error("❌ No TouchDesigner installation found for toeexpand")
            raise FileNotFoundError("No TouchDesigner installation found for toeexpand")
    
    # Check if toeexpand exists
    if not os.path.exists(toeexpand_path):
        logger.error(f"❌ toeexpand not found at: {toeexpand_path}")
        raise FileNotFoundError(f"toeexpand not found at: {toeexpand_path}")
    
    # Use cross-platform path
    command = f'"{toeexpand_path}" -b "{td_file_path}"'
    logger.debug(f"Running command: {command}")

    if DEBUG_MODE:
        logger.debug("Running toeexpand to analyze TOE file...")
    
    process = subprocess.Popen(command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    out, err = process.communicate() # this is a blocking call, it will wait until the subprocess is finished.
    
    # Log the raw output for debugging
    raw_output = out.decode('utf-8')
    raw_error = err.decode('utf-8')
    
    logger.debug(f"toeexpand stdout: {repr(raw_output)}")
    if raw_error:
        logger.warning(f"toeexpand stderr: {repr(raw_error)}")
    
    if process.returncode != 0:
        logger.info(f"⚠️  toeexpand returned exit code {process.returncode} (this is often normal)")
        if raw_error:
            logger.debug(f"Error output: {raw_error}")
        # Don't fail immediately - toeexpand often returns 1 even with valid output
    
    build_info = raw_output # convert the output to a string.

    # strip \r from the build_info string.
    build_info = build_info.replace('\r','')
    logger.debug(f"Cleaned build_info: {repr(build_info)}")

    # Check if we have any useful output at all
    if not build_info or len(build_info.strip()) < 5:
        logger.error(f"❌ toeexpand produced no useful output")
        logger.error(f"stdout: {repr(raw_output)}")
        logger.error(f"stderr: {repr(raw_error)}")
        raise RuntimeError(f"toeexpand failed to produce output: {raw_error}")

    info_split = build_info.split('\n') # split the string into a list.
    logger.debug(f"Split info: {info_split}")
    
    # Filter out empty lines
    info_split = [line.strip() for line in info_split if line.strip()]
    logger.debug(f"Filtered info: {info_split}")
    
    if len(info_split) < 2:
        logger.error(f"❌ Unexpected toeexpand output format - need at least 2 lines")
        logger.error(f"Got: {info_split}")
        raise ValueError(f"Unexpected toeexpand output format: {info_split}")

    try:
        version_line = info_split[1]
        logger.debug(f"Version line: {version_line}")
        version_number = version_line.split(" ")[-1]
        build_option = f'TouchDesigner.{version_number}'
        
        logger.info(f"TOE file requires TouchDesigner {build_option}")
        
        return build_option
    except (IndexError, AttributeError) as e:
        logger.error(f"❌ Failed to parse version from toeexpand output: {e}")
        logger.error(f"Raw output was: {repr(build_info)}")
        raise ValueError(f"Failed to parse version from toeexpand output: {e}")


def generate_td_url(build_option):
    # Windows URLs:
    # https://download.derivative.ca/TouchDesigner088.62960.64-Bit.exe
    # https://download.derivative.ca/TouchDesigner099.2017.17040.64-Bit.exe
    # https://download.derivative.ca/TouchDesigner099.2018.28120.64-Bit.exe
    # https://download.derivative.ca/TouchDesigner099.2019.20700.exe
    # https://download.derivative.ca/TouchDesigner.2020.28110.exe
    # https://download.derivative.ca/TouchDesigner.2021.16960.exe
    # https://download.derivative.ca/TouchDesigner.2022.26590.exe
    
    # Mac URLs with architecture-specific suffixes:
    # https://download.derivative.ca/TouchDesigner.2022.26590.intel.dmg
    # https://download.derivative.ca/TouchDesigner.2022.26590.arm64.dmg

    
    split_options = build_option.split('.')
    product = split_options[0]
    year = split_options[1]
    build = split_options[2]
    
    # Platform and architecture-specific file extension
    if platform.system() == 'Windows':
        extension = '.exe'
        arch_suffix = ''
    else:  # Mac
        extension = '.dmg'
        # Detect Mac architecture
        machine = platform.machine().lower()
        if machine in ['arm64', 'aarch64']:
            arch_suffix = '.arm64'
        elif machine in ['x86_64', 'amd64']:
            arch_suffix = '.intel'
        else:
            # Default to intel for unknown architectures
            arch_suffix = '.intel'
            print(f"Warning: Unknown Mac architecture '{machine}', defaulting to Intel")

    # generate the url based on the build option and platform
    if year in [ "2017" , "2018" ] and platform.system() == 'Windows':
        url = f'https://download.derivative.ca/TouchDesigner099.{year}.{build}.64-Bit{extension}'

    elif year in [ "2019" ] and platform.system() == 'Windows':
        url = f'https://download.derivative.ca/TouchDesigner099.{year}.{build}{extension}'

    elif year == [ "2020" , "2021" , "2022"]:
        url = f'https://download.derivative.ca/TouchDesigner.{year}.{build}{arch_suffix}{extension}'

    else: # assume future years will use the same format as we have currently.
        url = f'https://download.derivative.ca/TouchDesigner.{year}.{build}{arch_suffix}{extension}'

    return url


# gather and generate some variables.
# Main execution starts

# Helper function for sorting TD versions
def _parse_td_key_numeric(key: str):
    try:
        parts = key.split('.')
        year = int(parts[1]) if len(parts) > 1 else -1
        build = int(parts[2]) if len(parts) > 2 else -1
        return (year, build)
    except Exception:
        return (-1, -1)

# Platform-specific TouchDesigner discovery (needed for both modes)
logger.info("Checking for installed TouchDesigner versions...")
if platform.system() == 'Windows':
    td_key_id_dict = query_td_registry_entries()
else:  # Mac/Linux
    td_key_id_dict = query_td_mac_applications()

if DEBUG_MODE:
    logger.debug(f"Found {len(td_key_id_dict)} TouchDesigner installations")
    for key, info in td_key_id_dict.items():
        logger.debug(f"  • {key}: {info.get('executable', 'N/A')}")

version_keys = sorted(list(td_key_id_dict.keys()), key=_parse_td_key_numeric)

# Initialize variables that may not be set in picker mode
build_info = None
build_year = None
td_url = None
td_uri = None
td_filename = None

# Only analyze the TOE file if not in picker mode
if not picker_mode:
    # build_info = inspect_toe() # old version
    try:
        build_info = inspect_toe_v2()
        build_year = int(build_info.split('.')[1])
        if DEBUG_MODE:
            logger.debug(f"TOE file requires TouchDesigner year: {build_year}")

        td_url = generate_td_url(build_info)
        if DEBUG_MODE:
            logger.debug(f"Generated download URL: {td_url}")

        # Cross-platform file path
        td_filename = td_url.split("/")[-1]

        if platform.system() == 'Darwin':  # macOS
            # On macOS, save next to the TOE file to avoid permission issues
            toe_directory = os.path.dirname(os.path.abspath(td_file_path))
            td_uri = os.path.join(toe_directory, td_filename)
            logger.debug(f"macOS: Saving download next to TOE file")
            logger.debug(f"TOE file directory: {toe_directory}")
        else:  # Windows and other platforms
            # Keep original behavior for Windows
            td_uri = os.path.join(os.getcwd(), td_filename)
            logger.debug(f"Windows: Using current working directory")

        logger.debug(f"Download filename: {td_filename}")
        logger.debug(f"Local download path: {td_uri}")

        # Log as recent file
        add_recent_file(td_file_path)

    except Exception as e:
        logger.error(f"❌ Failed to analyze TOE file: {e}")
        print(f"❌ Error analyzing TOE file: {e}")
        sys.exit(1)

    # Check if we have the required version
    if build_info in td_key_id_dict:
        logger.info(f"Required version {build_info} is installed")
    else:
        logger.info(f"Required version {build_info} not found - will download")

def cancel_countdown():
    global countdown_enabled
    countdown_enabled = False

def update_download_progress(b=1, bsize=1, tsize=None):
    global download_progress
    frac_progress = b * bsize / tsize
    frac_progress = max( min( frac_progress , 1 ) , 0 )
    download_progress = frac_progress
    dpg.set_value('download_progress_bar', download_progress)
    prog_text = str(download_progress*100)
    left = prog_text.split('.')[0]
    if len(prog_text.split('.')) > 1:
        right = prog_text.split('.')[1][0:1]
    else:
        right = '0'
    prog_text2 = f'{left}.{right}'
    dpg.configure_item('download_progress_bar', overlay=f'downloading {prog_text2}%')
    return

def start_download(sender, app_data):
    logger.info("Starting TouchDesigner download...")
    
    dpg.set_value("download_filter", 'b')

    retriever = urllib.request.urlretrieve

    try:
        # Download progress handled by start_download function
        result = retriever(td_url, filename=td_uri, reporthook=update_download_progress)
        
        # Check file size
        if os.path.exists(td_uri):
            file_size = os.path.getsize(td_uri)
            logger.info("Download completed successfully")
        else:
            logger.error("❌ Download completed but file not found!")

        dpg.configure_item('download_progress_bar', overlay=f'100%')
        dpg.set_value("download_filter", 'z')
        dpg.set_value("install_filter", 'a')
        
        # Download success already logged above
    
    except Exception as e:
        logger.error(f"❌ Download failed: {e}")
        print(f"❌ Download error: {e}")
        dpg.set_value("download_filter", 'd')

    return


def install_touchdesigner_version(sender, app_data):
    logger.info("📦 Starting TouchDesigner installation...")
    logger.info("=" * 50)
    logger.info(f"💿 Installer file: {td_uri}")
    
    # Platform-specific installation handling
    try:
        if platform.system() == 'Windows':
            # Windows: Run the .exe installer silently
            install_command = [ 'start', '', '/WAIT', td_uri, ]
            logger.info(f"💻 Windows install command: {' '.join(install_command)}")
            process = subprocess.Popen(install_command, shell = True)
            logger.info(f"✅ Installer started with PID: {process.pid}")
        else:  # Mac
            # Mac: Open the .dmg file (this will mount it and show in Finder)
            # The user will need to manually drag the app to Applications
            install_command = ['open', td_uri]
            logger.info(f"🍎 macOS install command: {' '.join(install_command)}")
            process = subprocess.Popen(install_command)
            logger.info(f"✅ DMG opened with PID: {process.pid}")
            logger.info("ℹ️  User will need to manually drag TouchDesigner to Applications folder")
            
        logger.info("🎉 Installation process initiated!")
        logger.info("🔚 Closing TD Launcher...")
        
    except Exception as e:
        logger.error(f"❌ Installation failed: {e}")
        print(f"❌ Installation error: {e}")
        return
        
    exit_gui()
    return

def launch_toe_with_version(sender, app_data):
    radio_value = dpg.get_value( "td_version" )
    executable_path = td_key_id_dict[radio_value]['executable']
    
    logger.info("🚀 Launching TouchDesigner...")
    logger.info("=" * 50)
    logger.info(f"🎯 Selected version: {radio_value}")
    logger.info(f"📄 TOE file: {td_file_path}")
    logger.info(f"🔧 Executable: {executable_path}")
    
    try:
        if platform.system() == 'Windows':
            open_command = f'"{executable_path}" "{td_file_path}"'
            logger.info(f"💻 Windows launch command: {open_command}")
            process = subprocess.Popen(open_command, shell = True)
            logger.info(f"✅ Process started with PID: {process.pid}")
        else:  # Mac
            # On Mac, use 'open' command to launch the app with the file
            # open -a "/Applications/TouchDesigner.app" "file.toe"
            app_path = td_key_id_dict[radio_value]['app_path']
            open_command = ['open', '-a', app_path, td_file_path]
            logger.info(f"🍎 macOS launch command: {' '.join(open_command)}")
            process = subprocess.Popen(open_command)
            logger.info(f"✅ Process started with PID: {process.pid}")
            
        logger.info("🎉 TouchDesigner launch initiated successfully!")
        logger.info("🔚 Closing TD Launcher GUI...")
        
    except Exception as e:
        logger.error(f"❌ Failed to launch TouchDesigner: {e}")
        print(f"❌ Error launching TouchDesigner: {e}")
        return
        
    exit_gui()
    return

def exit_gui():
    # if os.path.isfile( td_uri ):
    #     os.remove( td_uri )
    logger.info("🔚 Shutting down GUI gracefully...")
    
    try:
        # On macOS, we need to stop the GUI loop more gently
        if platform.system() == 'Darwin':
            # Set a flag to stop the main loop instead of forcing exit
            global should_exit
            should_exit = True
            logger.info("✅ Exit flag set for graceful shutdown")
        else:
            # Windows can handle direct shutdown
            dpg.stop_dearpygui()
            dpg.destroy_context()
            logger.info("✅ GUI cleanup completed")
            sys.exit(0)
    except Exception as e:
        logger.warning(f"GUI cleanup warning: {e}")
        sys.exit(1)

# Keyboard navigation and actions
def get_current_picker_tab() -> str:
    """Get the currently active tab in picker mode. Returns 'recent' or 'templates'."""
    try:
        if dpg.does_item_exist("file_picker_tabs"):
            active_tab = dpg.get_value("file_picker_tabs")
            if active_tab == dpg.get_item_user_data("templates_tab") or active_tab == dpg.get_alias_id("templates_tab"):
                return 'templates'
    except Exception:
        pass
    return 'recent'


def switch_picker_tab():
    """Switch between Recent Files and Templates tabs."""
    global picker_selection_index
    try:
        if not dpg.does_item_exist("file_picker_tabs"):
            return

        current_tab = get_current_picker_tab()
        if current_tab == 'recent':
            # Switch to templates tab
            if dpg.does_item_exist("templates_tab"):
                dpg.set_value("file_picker_tabs", dpg.get_alias_id("templates_tab"))
        else:
            # Switch to recent files tab
            if dpg.does_item_exist("recent_files_tab"):
                dpg.set_value("file_picker_tabs", dpg.get_alias_id("recent_files_tab"))

        # Reset selection index when switching tabs
        picker_selection_index = 0
        update_picker_selection()
    except Exception as e:
        logger.debug(f"switch_picker_tab error: {e}")


def get_current_list_items() -> list:
    """Get the list of items in the currently active picker tab."""
    if not app_config:
        return []

    current_tab = get_current_picker_tab()
    if current_tab == 'recent':
        return app_config.get('recent_files', [])
    else:
        return app_config.get('templates', [])


def update_picker_selection():
    """Update the visual selection in the picker list based on picker_selection_index."""
    global selected_file_path, last_clicked_path, picker_selection_index

    items = get_current_list_items()
    if not items:
        return

    # Clamp index to valid range
    picker_selection_index = max(0, min(picker_selection_index, len(items) - 1))

    current_tab = get_current_picker_tab()
    item = items[picker_selection_index]
    file_path = item.get('path', '')

    # Update selection state
    if os.path.exists(file_path):
        selected_file_path = file_path
        last_clicked_path = file_path

        # Update button
        if dpg.does_item_exist("open_selected_btn"):
            dpg.configure_item("open_selected_btn", enabled=True)
            filename = os.path.basename(file_path)
            dpg.configure_item("open_selected_btn", label=f"Open: {filename}")
        
        # Update version panel when navigating with keyboard
        # But do NOT enable countdown in picker mode - we don't want auto-launch
        update_version_panel()
        # Ensure countdown is disabled in picker mode
        global countdown_enabled
        countdown_enabled = False

    # Update visual selection (highlight the selected row)
    # Clear all selections first, then set the current one
    for i in range(len(items)):
        if current_tab == 'recent':
            tag = f"recent_file_{i}"
        else:
            tag = f"template_{i}"

        if dpg.does_item_exist(tag):
            dpg.set_value(tag, i == picker_selection_index)


def move_picker_selection(step: int):
    """Move selection up or down in the current picker list."""
    global picker_selection_index

    items = get_current_list_items()
    if not items:
        return

    picker_selection_index = (picker_selection_index + step) % len(items)
    update_picker_selection()


def move_selection(step: int):
    try:
        if not version_keys:
            return
        current_value = dpg.get_value("td_version")
        try:
            current_index = version_keys.index(current_value)
        except ValueError:
            current_index = 0
        new_index = (current_index + step) % len(version_keys)
        dpg.set_value("td_version", version_keys[new_index])
    except Exception as e:
        logger.debug(f"move_selection error: {e}")


def on_key_press(sender, app_data):
    # app_data is the key code
    try:
        # Cancel countdown on any key interaction
        cancel_countdown()

        key_code = app_data

        # Tab key - switch tabs in picker mode
        if key_code == getattr(dpg, 'mvKey_Tab', None):
            if picker_mode:
                switch_picker_tab()
            return

        # Up arrow or W key - move selection up
        if key_code in (
            getattr(dpg, 'mvKey_Up', None),
            getattr(dpg, 'mvKey_W', None),
        ):
            if picker_mode:
                move_picker_selection(-1)
            else:
                move_selection(-1)
            return

        # Down arrow or S key - move selection down
        if key_code in (
            getattr(dpg, 'mvKey_Down', None),
            getattr(dpg, 'mvKey_S', None),
        ):
            if picker_mode:
                move_picker_selection(1)
            else:
                move_selection(1)
            return

        # Enter key - open selected file or launch
        if key_code in (
            getattr(dpg, 'mvKey_Enter', None),
            getattr(dpg, 'mvKey_Return', None),
            getattr(dpg, 'mvKey_KeyPadEnter', None),
            getattr(dpg, 'mvKey_KeypadEnter', None),
        ):
            if selected_file_path:
                launch_from_unified_ui(sender, app_data)
            return

        # Escape key - exit
        if key_code == getattr(dpg, 'mvKey_Escape', None):
            exit_gui()
            return

        # Backspace/Delete - remove selected file from list
        if key_code in (
            getattr(dpg, 'mvKey_Back', None),
            getattr(dpg, 'mvKey_Backspace', None),
            getattr(dpg, 'mvKey_Delete', None),
        ):
            # In picker mode, backspace/delete removes the selected file from list
            if picker_mode and selected_file_path and last_clicked_path:
                # Determine which list the file is in
                if app_config:
                    recent_paths = [rf.get('path') for rf in app_config.get('recent_files', [])]
                    template_paths = [t.get('path') for t in app_config.get('templates', [])]
                    abs_path = os.path.abspath(last_clicked_path)
                    if abs_path in recent_paths:
                        confirm_and_remove_from_list(last_clicked_path, 'recent')
                    elif abs_path in template_paths:
                        confirm_and_remove_from_list(last_clicked_path, 'template')
            return

    except Exception as e:
        logger.debug(f"on_key_press error: {e}")

# ============================================================================
# File Picker UI (when no file is specified)
# ============================================================================

def format_file_modified_time(file_path: str) -> str:
    """Get formatted modification time for a file."""
    try:
        mtime = os.path.getmtime(file_path)
        from datetime import datetime
        dt = datetime.fromtimestamp(mtime)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return ""

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
    for icon_name in ['icon.jpg', 'icon.png', 'Icon.jpg', 'Icon.png', 'ICON.jpg', 'ICON.png']:
        icon_path = os.path.join(project_dir, icon_name)
        if os.path.exists(icon_path):
            return icon_path
    
    # If no icon file, find the latest .jpg or .png file
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
        image_files.extend(glob.glob(os.path.join(project_dir, ext)))
    
    if not image_files:
        return None
    
    # Sort by modification time (newest first)
    image_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return image_files[0]

def find_readme(project_path: str) -> Optional[str]:
    """Find a README file for a project."""
    if not os.path.exists(project_path):
        return None
        
    project_dir = os.path.dirname(project_path)
    print(f"[README DEBUG] Searching for readme in: {project_dir}")
    
    # Case insensitive search for readme*
    for root, dirs, files in os.walk(project_dir, topdown=True):
        # Only check current directory
        # Modify dirs in-place to empty it preventing recursion
        dirs[:] = []
        
        for file in files:
            print(f"[README DEBUG] Checking file: {file}")
            if file.lower().startswith("readme") and file.lower().endswith(".md"):
                found = os.path.join(project_dir, file)
                print(f"[README DEBUG] Found readme: {found}")
                return found
    
    print("[README DEBUG] No readme found")
    return None

def read_readme_content(readme_path: str) -> str:
    """Read content of a readme file."""
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading README: {e}"

def load_icon_texture(icon_path: str, size: int = 50) -> Optional[str]:
    """Load an image and create a DearPyGui texture for it.
    
    Returns the texture tag, or None if loading failed.
    """
    global icon_textures
    
    if not PIL_AVAILABLE:
        return None
    
    # Check if already loaded
    if icon_path in icon_textures:
        return icon_textures[icon_path]
    
    try:
        # Load and process the image
        img = Image.open(icon_path)
        
        # Convert to RGB if necessary (handle RGBA, grayscale, etc.)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Center crop to square
        width, height = img.size
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        right = left + min_dim
        bottom = top + min_dim
        img = img.crop((left, top, right, bottom))
        
        # Resize to target size
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        
        # Convert to numpy array and normalize to 0-1 range
        img_array = np.array(img).astype(np.float32) / 255.0
        
        # Flatten the array for DearPyGui
        img_flat = img_array.flatten().tolist()
        
        # Create unique texture tag
        texture_tag = f"icon_texture_{len(icon_textures)}"
        
        # Create the texture in DearPyGui
        with dpg.texture_registry():
            dpg.add_static_texture(
                width=size,
                height=size,
                default_value=img_flat,
                tag=texture_tag
            )
        
        icon_textures[icon_path] = texture_tag
        return texture_tag
        
    except Exception as e:
        logger.debug(f"Failed to load icon {icon_path}: {e}")
        return None

def load_default_icon(size: int = 50) -> Optional[str]:
    """Load the application icon as the default icon for files without project icons.
    
    Returns the texture tag, or None if loading failed.
    """
    global default_icon_texture
    
    if not PIL_AVAILABLE:
        return None
    
    # Return cached texture if already loaded
    if default_icon_texture is not None:
        return default_icon_texture
    
    # Try to find the app icon
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Look for icon files in priority order
    icon_candidates = [
        os.path.join(script_dir, 'td_launcher.ico'),
        os.path.join(script_dir, 'td_launcher.icns'),
        os.path.join(script_dir, 'td_launcher.png'),
    ]
    
    for icon_path in icon_candidates:
        if os.path.exists(icon_path):
            texture_tag = load_icon_texture(icon_path, size=size)
            if texture_tag:
                default_icon_texture = texture_tag
                return texture_tag
    
    return None

def on_toggle_icons(sender, app_data):
    """Callback when the show icons checkbox is toggled."""
    global show_icons, app_config
    
    show_icons = app_data
    app_config['show_icons'] = show_icons
    save_config(app_config)
    
    # Sync both checkboxes
    if dpg.does_item_exist("show_icons_checkbox"):
        dpg.set_value("show_icons_checkbox", show_icons)
    if dpg.does_item_exist("show_icons_checkbox_templates"):
        dpg.set_value("show_icons_checkbox_templates", show_icons)
    
    # Rebuild the file lists to show/hide icons
    build_recent_files_list()
    build_templates_list()

def on_toggle_readme(sender, app_data):
    """Callback when show readme is toggled."""
    global show_readme, app_config

    show_readme = app_data
    app_config['show_readme'] = show_readme
    save_config(app_config)

    # Sync checkboxes
    if dpg.does_item_exist("show_readme_checkbox"):
        dpg.set_value("show_readme_checkbox", show_readme)
    if dpg.does_item_exist("show_readme_checkbox_templates"):
        dpg.set_value("show_readme_checkbox_templates", show_readme)

    # Toggle panel visibility and column width
    if dpg.does_item_exist("readme_panel_group"):
        dpg.configure_item("readme_panel_group", show=show_readme)
    if dpg.does_item_exist("readme_column"):
        dpg.configure_item("readme_column", init_width_or_weight=310 if show_readme else 0)

    # Resize viewport
    if show_readme:
        dpg.set_viewport_width(960)
        update_readme_panel()
    else:
        dpg.set_viewport_width(650)

def on_row_clicked(sender, app_data, user_data):
    """Handle clicks on non-selectable row items (icons, text)."""
    try:
        # app_data is (mouse_button, item_id)
        if not isinstance(app_data, tuple) or len(app_data) < 2:
            return

        item_id = app_data[1]
        clicked_tag = dpg.get_item_alias(item_id)

        if not clicked_tag:
            return

        # Determine list type and extract index from tag
        # Tags are like: recent_icon_0, recent_mod_0, recent_path_0, recent_missing_0
        #            or: template_icon_0, template_mod_0, template_path_0, template_missing_0

        if clicked_tag.startswith("recent_"):
            list_type = "recent"
            items = app_config.get('recent_files', [])
        elif clicked_tag.startswith("template_"):
            list_type = "template"
            items = app_config.get('templates', [])
        else:
            return

        # Extract index - it's the last part after the final underscore
        parts = clicked_tag.split("_")
        if len(parts) < 2:
            return

        try:
            idx = int(parts[-1])
        except ValueError:
            return

        if idx < 0 or idx >= len(items):
            return

        item = items[idx]
        file_path = item.get('path', '')

        if not file_path:
            return

        # Find the corresponding selectable tag
        if list_type == "recent":
            selectable_tag = f"recent_file_{idx}"
        else:
            selectable_tag = f"template_{idx}"

        # Call on_file_selected with the selectable as sender
        on_file_selected(selectable_tag, app_data, {'path': file_path, 'type': list_type})

    except Exception as e:
        logger.debug(f"Row click error: {e}")

def clear_all_selections():
    """Clear selection state from all selectables in both lists."""
    # Clear recent files selections
    i = 0
    while dpg.does_item_exist(f"recent_file_{i}"):
        dpg.set_value(f"recent_file_{i}", False)
        i += 1
    # Clear template selections
    i = 0
    while dpg.does_item_exist(f"template_{i}"):
        dpg.set_value(f"template_{i}", False)
        i += 1


def on_file_selected(sender, app_data, user_data):
    """Callback when a file is selected from recent files or templates."""
    global selected_file_path, last_click_time, last_clicked_path, countdown_enabled

    file_path = user_data.get('path', '')
    current_time = time.time()

    # Clear all other selections, keep only the clicked one selected
    clear_all_selections()
    if sender and dpg.does_item_exist(sender):
        dpg.set_value(sender, True)

    # For double-click: must be same file AND within time window
    # Reset tracking if clicking a different file
    if file_path != last_clicked_path:
        # Different file clicked - just select it, reset double-click tracking
        last_click_time = current_time
        last_clicked_path = file_path

        if os.path.exists(file_path):
            selected_file_path = file_path
            update_version_panel()
            countdown_enabled = False
        return

    # Same file clicked again - check timing for double-click
    time_since_last = current_time - last_click_time

    # Ignore duplicate callbacks from same physical click (< 50ms)
    if time_since_last < 0.05:
        return

    # Double-click detection: 50ms to 500ms between clicks on same file
    if 0.05 <= time_since_last < 0.5:
        if os.path.exists(file_path):
            selected_file_path = file_path
            countdown_enabled = False
            update_version_panel()
            launch_from_unified_ui(sender, app_data)
        # Reset tracking after launch
        last_click_time = 0
        last_clicked_path = None
        return

    # Too slow for double-click - treat as new first click
    last_click_time = current_time
    # last_clicked_path already equals file_path

    if os.path.exists(file_path):
        selected_file_path = file_path
        update_version_panel()
        countdown_enabled = False
        try:
            items = get_current_list_items()
            for i, item in enumerate(items):
                if item.get('path') == file_path:
                    global picker_selection_index
                    picker_selection_index = i
                    update_picker_selection()
                    break
        except Exception:
            pass
            
    else:
        selected_file_path = None
        update_version_panel()

def confirm_and_remove_from_list(file_path: str, list_type: str):
    """Confirm and remove a file from either recent files or templates list."""
    global app_config

    filename = os.path.basename(file_path)

    # Check if we should show confirmation
    if app_config.get('confirm_remove_from_list', True):
        confirmed, never_ask = show_remove_confirmation(filename)
        if not confirmed:
            return
        if never_ask:
            app_config = set_confirm_remove_preference(True, config=app_config)

    # Remove from the appropriate list
    if list_type == 'recent':
        app_config = remove_recent_file(file_path, config=app_config)
        build_recent_files_list()
    elif list_type == 'template':
        app_config = remove_template(file_path, config=app_config)
        build_templates_list()

    # Clear selection if we removed the selected file
    global selected_file_path
    if selected_file_path and os.path.abspath(selected_file_path) == os.path.abspath(file_path):
        selected_file_path = None
        if dpg.does_item_exist("open_selected_btn"):
            dpg.configure_item("open_selected_btn", enabled=False)
            dpg.configure_item("open_selected_btn", label="Open Selected File")

def on_remove_template(sender, app_data, user_data):
    """Remove a template from the list."""
    file_path = user_data
    confirm_and_remove_from_list(file_path, 'template')

def on_remove_recent_file(sender, app_data, user_data):
    """Remove a file from the recent files list."""
    file_path = user_data
    confirm_and_remove_from_list(file_path, 'recent')

def show_native_file_picker(prompt: str = "Select TouchDesigner File") -> Optional[str]:
    """Show native OS file picker and return selected path, or None if cancelled."""
    file_path = None

    if platform.system() == 'Darwin':  # macOS - use AppleScript
        try:
            script = f'''
            set theFile to choose file with prompt "{prompt}" of type {{"toe"}}
            return POSIX path of theFile
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                file_path = result.stdout.strip()
        except Exception as e:
            logger.error(f"Failed to open file dialog: {e}")

    else:  # Windows - use tkinter
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        file_path = filedialog.askopenfilename(
            title=prompt,
            filetypes=[("TouchDesigner Files", "*.toe"), ("All Files", "*.*")],
            initialdir=os.path.expanduser("~")
        )

        root.destroy()

    return file_path if file_path and file_path.lower().endswith('.toe') else None

def show_add_template_dialog(sender, app_data):
    """Show native OS file picker dialog for adding templates."""
    global app_config

    file_path = show_native_file_picker("Select TouchDesigner Project Template")

    if file_path:
        app_config = add_template(file_path, config=app_config)
        logger.info(f"Added template: {file_path}")
        build_templates_list()

def browse_and_open_file(sender, app_data):
    """Browse for a .toe file and select it (updates version panel)."""
    global selected_file_path, last_clicked_path

    file_path = show_native_file_picker("Open TouchDesigner File")

    if file_path:
        selected_file_path = file_path
        last_clicked_path = file_path
        update_version_panel()

def build_recent_files_list():
    """Populate the recent files list."""
    global app_config

    # Clear existing children
    if dpg.does_item_exist("recent_files_list"):
        dpg.delete_item("recent_files_list", children_only=True)

    recent_files = app_config.get('recent_files', [])

    if not recent_files:
        dpg.add_text(
            "No recent files yet.\nOpen a .toe file to add it here.",
            parent="recent_files_list",
            color=[150, 150, 150, 255]
        )
        return

    for i, rf in enumerate(recent_files):
        file_path = rf.get('path', '')
        filename = os.path.basename(file_path)
        directory = os.path.dirname(file_path)

        # Check if file still exists
        exists = os.path.exists(file_path)
        modified = format_file_modified_time(file_path) if exists else ""

        with dpg.group(horizontal=True, parent="recent_files_list"):
            # Show icon if enabled
            if show_icons and PIL_AVAILABLE:
                texture_tag = None
                if exists:
                    icon_path = find_project_icon(file_path)
                    if icon_path:
                        texture_tag = load_icon_texture(icon_path, size=50)
                
                # Use default icon if no project icon found
                if texture_tag is None:
                    texture_tag = load_default_icon(size=50)
                
                if texture_tag:
                    dpg.add_image(texture_tag, width=50, height=50, tag=f"recent_icon_{i}")
                    dpg.bind_item_handler_registry(f"recent_icon_{i}", "row_click_handler")
            
            # Wrap text elements in a vertical group for centering
            with dpg.group():
                # Add some vertical spacing to center text with icon
                if show_icons and PIL_AVAILABLE:
                    dpg.add_spacer(height=15)
                
                with dpg.group(horizontal=True):
                    dpg.add_selectable(
                        label=filename,
                        tag=f"recent_file_{i}",
                        callback=on_file_selected,
                        user_data={'path': file_path, 'type': 'recent'},
                        width=200
                    )
                    dpg.add_text(
                        f"  {modified}",
                        color=[100, 150, 100, 255] if exists else [100, 50, 50, 255],
                        tag=f"recent_mod_{i}"
                    )
                    dpg.bind_item_handler_registry(f"recent_mod_{i}", "row_click_handler")
                    
                    dpg.add_text(
                        f"  {directory}",
                        color=[150, 150, 150, 255] if exists else [100, 50, 50, 255],
                        tag=f"recent_path_{i}"
                    )
                    dpg.bind_item_handler_registry(f"recent_path_{i}", "row_click_handler")

                    if not exists:
                        dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"recent_missing_{i}")
                        dpg.bind_item_handler_registry(f"recent_missing_{i}", "row_click_handler")

                    # Remove button (on the right)
                    dpg.add_button(
                        label="X",
                        tag=f"remove_recent_{i}",
                        callback=on_remove_recent_file,
                        user_data=file_path,
                        small=True
                    )

def build_templates_list():
    """Populate the templates list."""
    global app_config

    if dpg.does_item_exist("templates_list"):
        dpg.delete_item("templates_list", children_only=True)

    templates = app_config.get('templates', [])

    if not templates:
        dpg.add_text(
            "No templates added yet.\nClick 'Add Template...' or drag a .toe file onto the app icon.",
            parent="templates_list",
            color=[150, 150, 150, 255]
        )
        return

    for i, t in enumerate(templates):
        file_path = t.get('path', '')
        name = t.get('name', os.path.basename(file_path))
        exists = os.path.exists(file_path)
        modified = format_file_modified_time(file_path) if exists else ""

        with dpg.group(horizontal=True, parent="templates_list"):
            # Show icon if enabled
            if show_icons and PIL_AVAILABLE:
                texture_tag = None
                if exists:
                    icon_path = find_project_icon(file_path)
                    if icon_path:
                        texture_tag = load_icon_texture(icon_path, size=50)
                
                # Use default icon if no project icon found
                if texture_tag is None:
                    texture_tag = load_default_icon(size=50)
                
                if texture_tag:
                    dpg.add_image(texture_tag, width=50, height=50, tag=f"template_icon_{i}")
                    dpg.bind_item_handler_registry(f"template_icon_{i}", "row_click_handler")
            
            # Wrap text elements in a vertical group for centering
            with dpg.group():
                # Add some vertical spacing to center text with icon
                if show_icons and PIL_AVAILABLE:
                    dpg.add_spacer(height=15)
                
                with dpg.group(horizontal=True):
                    dpg.add_selectable(
                        label=name,
                        tag=f"template_{i}",
                        callback=on_file_selected,
                        user_data={'path': file_path, 'type': 'template'},
                        width=220
                    )
                    dpg.add_text(f"  {modified}", color=[100, 150, 100, 255], tag=f"template_mod_{i}")
                    dpg.bind_item_handler_registry(f"template_mod_{i}", "row_click_handler")
                    
                    dpg.add_text(f"  {file_path}", color=[150, 150, 150, 255], tag=f"template_path_{i}")
                    dpg.bind_item_handler_registry(f"template_path_{i}", "row_click_handler")

                    if not exists:
                        dpg.add_text(" (missing)", color=[255, 50, 0, 255], tag=f"template_missing_{i}")
                        dpg.bind_item_handler_registry(f"template_missing_{i}", "row_click_handler")

                    # Remove button on the right
                    dpg.add_button(
                        label="X",
                        tag=f"remove_template_{i}",
                        callback=on_remove_template,
                        user_data=file_path,
                        small=True
                    )

def update_readme_panel():
    """Update the side panel with README content if available."""
    print(f"[README DEBUG] Updating panel. show_readme={show_readme}, selected_file={selected_file_path}")
    
    # We update content even if hidden, so it's ready when toggled? 
    # Or strict check? Strict check is fine.
    if not show_readme:
        return
        
    # Check if items exist (safe check)
    if not dpg.does_item_exist("readme_status_text") or not dpg.does_item_exist("readme_content_text"):
        print("[README DEBUG] Readme UI items invalid")
        return
    
    if selected_file_path and os.path.exists(selected_file_path):
         readme_path = find_readme(selected_file_path)
         
         if readme_path:
             content = read_readme_content(readme_path)
             print(f"[README DEBUG] Read content length: {len(content)}")
             if len(content) > 5000:
                 content = content[:5000] + "\n\n... (content truncated)"
                 
             # Update status title
             dpg.set_value("readme_status_text", f"File: {os.path.basename(readme_path)}")
             dpg.configure_item("readme_status_text", color=[100, 255, 100, 255])
             
             # Update content
             dpg.set_value("readme_content_text", content)
             print("[README DEBUG] Content updated via set_value.")
         else:
             print("[README DEBUG] Readme path not found")
             dpg.set_value("readme_status_text", "No README found.")
             dpg.configure_item("readme_status_text", color=[200, 100, 100, 255])
             dpg.set_value("readme_content_text", "")
    else:
         dpg.set_value("readme_status_text", "Select a file...")
         dpg.configure_item("readme_status_text", color=[150, 150, 150, 255])
         dpg.set_value("readme_content_text", "")

def update_version_panel():
    """Update the version panel when a file is selected."""
    global build_info, build_year, td_url, td_uri, td_filename, countdown_enabled

    # Clear existing version panel content
    if dpg.does_item_exist("version_panel"):
        dpg.delete_item("version_panel", children_only=True)

    if selected_file_path is None or not os.path.exists(selected_file_path):
        # No file selected - show placeholder
        dpg.add_text(
            "Select a file above to see version info",
            parent="version_panel",
            color=[150, 150, 150, 255]
        )
        dpg.configure_item("launch_button", enabled=False)
        dpg.configure_item("launch_button", label="Select a file to launch")
        countdown_enabled = False
        return

    # Analyze the selected file
    try:
        # Temporarily set td_file_path for inspect_toe_v2
        global td_file_path
        old_td_file_path = td_file_path
        td_file_path = selected_file_path

        build_info = inspect_toe_v2()
        build_year = int(build_info.split('.')[1])

        td_url = generate_td_url(build_info)
        td_filename = td_url.split("/")[-1]

        if platform.system() == 'Darwin':
            toe_directory = os.path.dirname(os.path.abspath(td_file_path))
            td_uri = os.path.join(toe_directory, td_filename)
        else:
            td_uri = os.path.join(os.getcwd(), td_filename)

        logger.info(f"Selected file: {td_file_path}")
        logger.info(f"Required version: {build_info}")

    except Exception as e:
        logger.error(f"Failed to analyze TOE file: {e}")
        dpg.add_text(
            f"Error analyzing file: {e}",
            parent="version_panel",
            color=[255, 50, 0, 255]
        )
        dpg.configure_item("launch_button", enabled=False)
        dpg.configure_item("launch_button", label="Error analyzing file")
        return

    # Show version info
    filename = os.path.basename(selected_file_path)
    dpg.add_text(f'File: {filename}', parent="version_panel", color=[50, 255, 0, 255])

    version_installed = build_info in list(td_key_id_dict.keys())
    
    # Update Readme Panel as well
    update_readme_panel()

    if not version_installed:
        dpg.add_text(
            f'Required: {build_info} (NOT INSTALLED)',
            parent="version_panel",
            color=[255, 50, 0, 255],
            tag="detected_version"
        )

        # Download/install controls
        with dpg.group(parent="version_panel"):
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, row_background=True,
                          resizable=False, no_host_extendX=False, hideable=True,
                          borders_innerV=False, delay_search=True, borders_outerV=False,
                          borders_innerH=False, borders_outerH=False, width=-1):
                dpg.add_table_column(width_stretch=True)
                with dpg.table_row():
                    with dpg.filter_set(id="download_filter"):
                        if build_year > 2019:
                            dpg.set_value("download_filter", 'a')
                        else:
                            dpg.set_value("download_filter", 'c')
                        dpg.add_button(label=f'Download: {build_info}', width=-1, callback=start_download, filter_key="a")
                        dpg.add_progress_bar(overlay=f'downloading 0.0%', tag='download_progress_bar', width=-1, default_value=download_progress, filter_key="b")
                        dpg.add_text(f'TD versions from 2019 and earlier are not yet compatible.', color=[255, 50, 0, 255], filter_key="c")
                        dpg.add_text(f'Error downloading - go to derivative.ca to download manually', color=[255, 50, 0, 255], filter_key="d")

            with dpg.filter_set(id="install_filter"):
                dpg.set_value("install_filter", 'z')
                dpg.add_button(label=f'Install: {build_info}', width=-1, enabled=True, filter_key="a", callback=install_touchdesigner_version)

        countdown_enabled = False
    else:
        dpg.add_text(
            f'Required: {build_info} (installed)',
            parent="version_panel",
            color=[50, 255, 0, 255],
            tag="detected_version"
        )
        countdown_enabled = True
        # Reset the countdown timer when selecting a new file
        global seconds_started
        seconds_started = time.time()

    dpg.add_separator(parent="version_panel")

    # Version selection
    dpg.add_text("Override version:", parent="version_panel", color=[150, 150, 150, 255])
    with dpg.child_window(height=150, width=-1, parent="version_panel", tag="version_list_panel"):
        dpg.add_radio_button(
            version_keys,
            default_value=build_info if build_info in version_keys else (version_keys[0] if version_keys else None),
            tag="td_version",
            horizontal=False
        )

    # Update launch button
    dpg.configure_item("launch_button", enabled=True)
    dpg.configure_item("launch_button", label=f"Launch {filename}")


def build_unified_ui():
    """Build the unified file picker + version picker UI."""
    global app_config, seconds_started, show_icons, show_readme
    app_config = load_config()
    show_icons = app_config.get('show_icons', False)
    show_readme = app_config.get('show_readme', False)

    # Create Item Handler Registry for row clicks
    if dpg.does_item_exist("row_click_handler"):
        dpg.delete_item("row_click_handler")
        
    with dpg.item_handler_registry(tag="row_click_handler"):
        dpg.add_item_clicked_handler(callback=on_row_clicked)

    with dpg.window(tag="Primary Window"):
        dpg.add_text(f'TD Launcher {app_version}', color=[50, 255, 0, 255])
        dpg.add_separator()

        # Use table for side-by-side layout (more reliable than horizontal groups)
        with dpg.table(tag="main_layout_table", header_row=False, borders_innerV=False,
                       borders_outerV=False, borders_innerH=False, borders_outerH=False,
                       no_pad_outerX=True, no_pad_innerX=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(width_stretch=True, init_width_or_weight=1.0)
            dpg.add_table_column(tag="readme_column", width_fixed=True, init_width_or_weight=310 if show_readme else 0)

            with dpg.table_row():
                # LEFT COLUMN: Main UI
                with dpg.group(tag="main_ui_group"):
                    # ===== FILE SELECTION SECTION =====
                    with dpg.tab_bar(tag="file_picker_tabs"):
                        # ===== RECENT FILES TAB =====
                        with dpg.tab(label="Recent Files", tag="recent_files_tab"):
                            with dpg.group(horizontal=True):
                                dpg.add_button(
                                    label="Browse...",
                                    tag="browse_btn_recent",
                                    callback=browse_and_open_file
                                )
                                dpg.add_checkbox(
                                    label="Show Icons",
                                    tag="show_icons_checkbox",
                                    default_value=show_icons,
                                    callback=on_toggle_icons
                                )
                                dpg.add_checkbox(
                                    label="Show Info",
                                    tag="show_readme_checkbox",
                                    default_value=show_readme,
                                    callback=on_toggle_readme
                                )
                            with dpg.child_window(height=150, width=-1, tag="recent_files_list"):
                                build_recent_files_list()

                        # ===== TEMPLATES TAB =====
                        with dpg.tab(label="Templates", tag="templates_tab"):
                            with dpg.group(horizontal=True):
                                dpg.add_button(
                                    label="Add Template...",
                                    callback=show_add_template_dialog,
                                    tag="add_template_btn"
                                )
                                dpg.add_checkbox(
                                    label="Show Icons",
                                    tag="show_icons_checkbox_templates",
                                    default_value=show_icons,
                                    callback=on_toggle_icons
                                )
                                dpg.add_checkbox(
                                    label="Show Info",
                                    tag="show_readme_checkbox_templates",
                                    default_value=show_readme,
                                    callback=on_toggle_readme
                                )
                            with dpg.child_window(height=150, width=-1, tag="templates_list"):
                                build_templates_list()

                    dpg.add_separator()

                    # ===== VERSION PANEL SECTION =====
                    with dpg.child_window(height=250, width=-1, tag="version_panel"):
                        dpg.add_text(
                            "Select a file above to see version info",
                            color=[150, 150, 150, 255]
                        )

                    dpg.add_separator()

                    # ===== LAUNCH BUTTON =====
                    dpg.add_button(
                        label="Select a file to launch",
                        tag="launch_button",
                        width=-1,
                        height=40,
                        callback=launch_from_unified_ui,
                        enabled=False
                    )

                # RIGHT COLUMN: Readme Panel (always created, visibility controlled by show_readme)
                with dpg.group(tag="readme_panel_group", show=show_readme):
                    dpg.add_text("Project Info", color=[200, 200, 200, 255])
                    dpg.add_separator()
                    dpg.add_text("Select a file...", tag="readme_status_text", color=[150, 150, 150, 255], wrap=280)
                    dpg.add_separator()
                    with dpg.child_window(width=290, height=400, tag="readme_scroll_area", border=False):
                        dpg.add_text("", tag="readme_content_text", wrap=270, color=[255, 255, 255, 255])
    
    dpg.set_primary_window("Primary Window", True)
    seconds_started = time.time()

    dpg.set_primary_window("Primary Window", True)
    seconds_started = time.time()


def launch_from_unified_ui(sender, app_data):
    """Launch the selected file from the unified UI."""
    global td_file_path, app_config

    if selected_file_path is None:
        return

    td_file_path = selected_file_path

    # Log as recent file
    app_config = add_recent_file(td_file_path, config=app_config)

    # Refresh the recent files list
    build_recent_files_list()

    # Launch with selected version
    launch_toe_with_version(sender, app_data)

# ============================================================================

# build the UI
logger.info("🖥️  Initializing GUI...")
if picker_mode:
    logger.info("📂 Mode: File picker (no file specified)")
else:
    logger.info(f"📄 TOE file to display: {td_file_path}")
    logger.info(f"🔧 Required version: {build_info}")
logger.info(f"📊 Available versions: {list(td_key_id_dict.keys())}")

dpg.create_context()

with dpg.handler_registry():
    dpg.add_mouse_click_handler(callback=cancel_countdown)
    dpg.add_key_press_handler(callback=on_key_press)

# Build unified UI (always use the same UI)
build_unified_ui()

# If a file was passed via command line, pre-select it
if not picker_mode and td_file_path:
    selected_file_path = td_file_path
    last_clicked_path = td_file_path
    update_version_panel()
    # Log as recent file
    app_config = add_recent_file(td_file_path, config=app_config)
    build_recent_files_list()

logger.info("🪟 Creating GUI viewport...")
initial_width = 650
if app_config and app_config.get('show_readme', False):
    initial_width += 300
dpg.create_viewport(title=f'TD Launcher {app_version}', width=initial_width, height=550, resizable=True)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.set_primary_window("Primary Window", True)

logger.info("✅ GUI initialized successfully!")

# record the starting time after the time intensive functions above have completed.
seconds_started = time.time()

if picker_mode:
    countdown_enabled = False
    logger.info("📂 File picker mode - no auto-launch")
elif build_info not in list(td_key_id_dict.keys()):
    countdown_enabled = False
    logger.info("⏸️  Auto-launch disabled - required version not installed")
else:
    logger.info("⏰ Auto-launch enabled - will launch in 5 seconds")

logger.info("🔄 Starting main GUI loop...")

while dpg.is_dearpygui_running():
    
    # Check for graceful exit flag (macOS)
    if should_exit:
        logger.info("🔚 Exit flag detected, shutting down gracefully...")
        dpg.stop_dearpygui()
        break

    if countdown_enabled == True:

        # calc elapsed time.
        num_sec_elapsed = int((time.time() - seconds_started) * 10) / 10
        num_sec_remaining = max( num_sec_until_autostart - (num_sec_elapsed*countdown_enabled) , 0 )
        num_sec_remaining_label = str(num_sec_remaining)[0:3]

        if dpg.does_item_exist("launch_button"):
            dpg.configure_item("launch_button", label=f'Open with selected version in {num_sec_remaining_label} seconds')
        
        # if countdown has ended, start toe
        if num_sec_remaining <= 0:
            logger.info(f"⏰ Auto-launch timeout reached, launching {build_info}")
            launch_toe_with_version({}, {})
        
    else:

        if dpg.does_item_exist("launch_button"):
            dpg.configure_item("launch_button", label=f'Open with selected version')

    dpg.render_dearpygui_frame()

else:
    logger.info("🔚 GUI loop ended, cleaning up...")
    # if os.path.isfile( td_uri ):
    #     os.remove( td_uri )
    
    try:
        dpg.destroy_context()
        logger.info("✅ GUI context destroyed")
    except Exception as e:
        logger.warning(f"GUI cleanup warning: {e}")
    
    logger.info("👋 TD Launcher shutdown complete")
    
    # Final graceful exit
    if platform.system() == 'Darwin':
        logger.info("🍎 macOS graceful exit")
        sys.exit(0)
    else:
        logger.info("💻 Windows exit")


