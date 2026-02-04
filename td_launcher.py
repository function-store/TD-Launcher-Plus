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

# ============================================================================
# Config Module - Persistent storage for recent files and templates
# ============================================================================

DEFAULT_CONFIG = {
    'version': 1,
    'recent_files': [],  # List of dicts: [{'path': str, 'last_opened': timestamp}, ...]
    'templates': [],  # List of dicts: [{'path': str, 'name': str, 'added': timestamp}, ...]
    'max_recent_files': 20,
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
        if key_code == getattr(dpg, 'mvKey_Up', None):
            move_selection(-1)
        elif key_code == getattr(dpg, 'mvKey_Down', None):
            move_selection(1)
        elif key_code in (
            getattr(dpg, 'mvKey_Enter', None),
            getattr(dpg, 'mvKey_Return', None),
            getattr(dpg, 'mvKey_KeyPadEnter', None),
            getattr(dpg, 'mvKey_KeypadEnter', None),
        ):
            launch_toe_with_version(sender, app_data)
        elif key_code == getattr(dpg, 'mvKey_Escape', None):
            exit_gui()
    except Exception as e:
        logger.debug(f"on_key_press error: {e}")

# ============================================================================
# File Picker UI (when no file is specified)
# ============================================================================

def on_file_selected(sender, app_data, user_data):
    """Callback when a file is selected from recent files or templates."""
    global selected_file_path

    file_path = user_data.get('path', '')

    if os.path.exists(file_path):
        selected_file_path = file_path
        dpg.configure_item("open_selected_btn", enabled=True)

        # Update button label to show selected file
        filename = os.path.basename(file_path)
        dpg.configure_item("open_selected_btn", label=f"Open: {filename}")
    else:
        selected_file_path = None
        dpg.configure_item("open_selected_btn", enabled=False)
        dpg.configure_item("open_selected_btn", label="Open Selected File")

def on_remove_template(sender, app_data, user_data):
    """Remove a template from the list."""
    global app_config

    file_path = user_data
    app_config = remove_template(file_path, config=app_config)
    build_templates_list()

def show_add_template_dialog(sender, app_data):
    """Show native OS file picker dialog for adding templates."""
    global app_config

    file_path = None

    if platform.system() == 'Darwin':  # macOS - use AppleScript
        try:
            script = '''
            set theFile to choose file with prompt "Select TouchDesigner Project Template" of type {"toe"}
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
            title="Select TouchDesigner Project Template",
            filetypes=[("TouchDesigner Files", "*.toe"), ("All Files", "*.*")],
            initialdir=os.path.expanduser("~")
        )

        root.destroy()

    if file_path and file_path.lower().endswith('.toe'):
        app_config = add_template(file_path, config=app_config)
        logger.info(f"Added template: {file_path}")
        build_templates_list()
    elif file_path:
        logger.warning(f"Invalid template file (must be .toe): {file_path}")

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

        with dpg.group(horizontal=True, parent="recent_files_list"):
            dpg.add_selectable(
                label=filename,
                tag=f"recent_file_{i}",
                callback=on_file_selected,
                user_data={'path': file_path, 'type': 'recent'},
                width=300
            )
            dpg.add_text(
                f"  {directory}",
                color=[150, 150, 150, 255] if exists else [100, 50, 50, 255]
            )

            if not exists:
                dpg.add_text(" (missing)", color=[255, 50, 0, 255])

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

        with dpg.group(horizontal=True, parent="templates_list"):
            dpg.add_selectable(
                label=name,
                tag=f"template_{i}",
                callback=on_file_selected,
                user_data={'path': file_path, 'type': 'template'},
                width=300
            )
            dpg.add_text(f"  {file_path}", color=[150, 150, 150, 255])

            # Remove button
            dpg.add_button(
                label="X",
                tag=f"remove_template_{i}",
                callback=on_remove_template,
                user_data=file_path,
                small=True
            )

            if not exists:
                dpg.add_text(" (missing)", color=[255, 50, 0, 255])

def open_selected_file(sender, app_data):
    """Open the selected file - this transitions to the version picker UI."""
    global td_file_path, picker_mode, app_config, build_info, build_year, td_url, td_uri, td_filename, countdown_enabled

    if selected_file_path is None:
        return

    td_file_path = selected_file_path
    picker_mode = False

    # Log as recent file
    app_config = add_recent_file(td_file_path, config=app_config)

    # Run the version detection
    try:
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
        # Show error in the UI instead of exiting
        dpg.configure_item("open_selected_btn", label=f"Error: {e}")
        return

    # Delete the picker UI and rebuild with version picker
    dpg.delete_item("Primary Window")

    # Rebuild with version picker UI
    build_version_picker_ui()

    # Set countdown state
    if build_info not in list(td_key_id_dict.keys()):
        countdown_enabled = False
    else:
        countdown_enabled = True

def build_file_picker_ui():
    """Build the tabbed recent files / templates picker UI."""
    global app_config
    app_config = load_config()

    with dpg.window(tag="Primary Window"):
        dpg.add_text(f'TD Launcher {app_version}', color=[50, 255, 0, 255])
        dpg.add_text('Select a recent file or template to open:',
                     color=[200, 200, 200, 255])
        dpg.add_separator()

        # Tab bar with Recent Files and Templates tabs
        with dpg.tab_bar(tag="file_picker_tabs"):

            # ===== RECENT FILES TAB =====
            with dpg.tab(label="Recent Files", tag="recent_files_tab"):
                with dpg.child_window(height=300, width=-1, tag="recent_files_list"):
                    build_recent_files_list()

            # ===== TEMPLATES TAB =====
            with dpg.tab(label="Templates", tag="templates_tab"):
                # Add Template button and drag-drop instructions
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Add Template...",
                        callback=show_add_template_dialog,
                        tag="add_template_btn"
                    )
                    dpg.add_text("  (drag .toe onto app icon to open)", color=[150, 150, 150, 255])

                dpg.add_separator()

                with dpg.child_window(height=260, width=-1, tag="templates_list"):
                    build_templates_list()

        dpg.add_separator()

        # Open button (disabled until selection)
        dpg.add_button(
            label="Open Selected File",
            tag="open_selected_btn",
            width=-1,
            height=-1,
            callback=open_selected_file,
            enabled=False
        )

def build_version_picker_ui():
    """Build the version picker UI (existing UI, refactored into a function)."""
    global seconds_started

    with dpg.window(tag="Primary Window"):
        dpg.add_text(f'Detected TD File: {td_file_path}', color=[50,255,0,255])

        if build_info not in list(td_key_id_dict.keys()):
            dpg.add_text(f'Detected TD Version: {build_info} (NOT INSTALLED)', color=[255,50,0,255], tag="detected_version")
            with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, row_background=True, resizable=False, no_host_extendX=False, hideable=True,
                       borders_innerV=False, delay_search=True, borders_outerV=False, borders_innerH=False,
                       borders_outerH=False, width=-1):
                dpg.add_table_column(width_stretch=True)
                with dpg.table_row():
                    with dpg.filter_set(id="download_filter"):
                        if build_year > 2019:
                            dpg.set_value("download_filter", 'a')
                        else:
                            dpg.set_value("download_filter", 'c')
                        dpg.add_button(label=f'Download : {build_info}', width=-1, callback=start_download, filter_key="a")
                        dpg.add_progress_bar(overlay=f'downloading 0.0%', tag='download_progress_bar', width=-1, default_value=download_progress, filter_key="b")
                        dpg.add_text(f'TD versions from 2019 and earlier are not yet compatible with this launcher.', color=[255,50,0,255], filter_key="c")
                        dpg.add_text(f'Error downloading build... go to derivative.ca to manually download', color=[255,50,0,255], filter_key="d")

            with dpg.filter_set(id="install_filter"):
                dpg.set_value("install_filter", 'z')
                dpg.add_button(label=f'Install : {build_info}', width=-1, enabled=True, filter_key="a", callback=install_touchdesigner_version)

        else:
            dpg.add_text(f'Detected TD Version: {build_info}', color=[50,255,0,255], tag="detected_version")

        dpg.add_separator()

        with dpg.child_window(height=200, width=-1):
            dpg.add_radio_button(version_keys, default_value=build_info, label='TD Version', tag="td_version", horizontal=False)

        dpg.add_separator()
        dpg.add_button(label=f'Open with selected version in {5} seconds', tag="launch_button", width=-1, height=-1, callback=launch_toe_with_version)

    dpg.set_primary_window("Primary Window", True)

    # Reset countdown timer
    seconds_started = time.time()

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

# Build appropriate UI based on mode
if picker_mode:
    build_file_picker_ui()
    countdown_enabled = False  # No countdown in picker mode
else:
    build_version_picker_ui()

logger.info("🪟 Creating GUI viewport...")
dpg.create_viewport(title=f'TD Launcher {app_version}', width=800, height=442, resizable=True)
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


