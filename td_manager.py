"""TouchDesigner version discovery and .toe file inspection."""

import os
import platform
import re
import glob
import plistlib
import subprocess
import logging
from typing import Dict, Optional, Tuple
from utils import get_resource_path

logger = logging.getLogger(__name__)


class TDManager:
    """Manages TouchDesigner version discovery and .toe file operations."""

    def __init__(self):
        self.versions: Dict[str, dict] = {}
        self.player_versions: Dict[str, dict] = {}
        self.discover_versions()

    def discover_versions(self) -> Dict[str, dict]:
        """Discover installed TouchDesigner and TouchPlayer versions."""
        if platform.system() == 'Windows':
            self.versions = self._query_windows_registry("TouchDesigner")
            # On Windows TouchPlayer.exe lives next to TouchDesigner.exe
            self.player_versions = self._derive_windows_player_versions()
        else:
            self.versions = self._query_mac_applications("TouchDesigner")
            self.player_versions = self._query_mac_applications("TouchPlayer")
        return self.versions

    def _derive_windows_player_versions(self) -> Dict[str, dict]:
        """Derive TouchPlayer versions from existing TD installations on Windows.
        TouchPlayer.exe sits alongside TouchDesigner.exe in each install's bin/ folder.
        """
        player_dict = {}
        for td_key, info in self.versions.items():
            install_path = info.get('install_path', '')
            player_exe = os.path.join(install_path, "bin", "TouchPlayer.exe")
            if os.path.exists(player_exe):
                # Convert key from TouchDesigner.X.Y to TouchPlayer.X.Y
                numeric = td_key.split('.', 1)[1] if '.' in td_key else td_key
                player_key = f"TouchPlayer.{numeric}"
                player_dict[player_key] = {
                    'install_path': install_path,
                    'executable': player_exe
                }
        return player_dict

    def _query_windows_registry(self, product: str = "TouchDesigner") -> Dict[str, dict]:
        """Query Windows registry for TouchDesigner or TouchPlayer installations.

        Registry layout: HKLM\\SOFTWARE\\Derivative\\<product>
        Values are version numbers (e.g. '2025.32280') and corresponding
        paths stored as 'Path', 'Path_3', 'Path_6', etc.
        """
        try:
            import winreg
        except ImportError:
            return {}

        td_dict = {}

        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SOFTWARE\Derivative\{product}"
            )

            num_values = winreg.QueryInfoKey(key)[1]

            # Collect all values: version numbers and their path entries
            versions = []
            paths = {}
            for i in range(num_values):
                name, value, vtype = winreg.EnumValue(key, i)
                if name.startswith('Path'):
                    paths[name] = value
                elif re.match(r'^\d{4}\.\d+$', name):
                    versions.append(name)

            # Match each version to its install path
            for version in versions:
                install_path = None
                # Check all path entries for one containing this version
                for path_name, path_value in paths.items():
                    if version in path_value:
                        install_path = path_value
                        break

                if install_path:
                    exe_path = os.path.join(install_path, "bin", f"{product}.exe")
                    if os.path.exists(exe_path):
                        td_key = f"{product}.{version}"
                        td_dict[td_key] = {
                            'install_path': install_path,
                            'executable': exe_path
                        }

            winreg.CloseKey(key)

        except (WindowsError, FileNotFoundError):
            pass

        return td_dict

    def _query_mac_applications(self, product: str = "TouchDesigner") -> Dict[str, dict]:
        """Query macOS Applications folder for TouchDesigner or TouchPlayer installations.

        Reads Info.plist to get actual version info.
        """
        td_dict = {}
        applications_dir = "/Applications"

        td_pattern = os.path.join(applications_dir, f"{product}*")
        logger.debug(f"Searching pattern: {td_pattern}")
        td_apps = glob.glob(td_pattern)
        logger.debug(f"Found {len(td_apps)} potential {product} apps")

        for app_path in td_apps:
            if not app_path.endswith('.app'):
                continue

            app_name = os.path.basename(app_path)
            info_plist_path = os.path.join(app_path, "Contents", "Info.plist")
            logger.debug(f"Processing app: {app_name}")

            try:
                # Read the Info.plist file
                with open(info_plist_path, 'rb') as f:
                    plist_data = plistlib.load(f)

                # Extract version information
                bundle_version = plist_data.get('CFBundleVersion', '')
                logger.debug(f"Bundle version: {bundle_version}")

                if bundle_version:
                    version_parts = bundle_version.split('.')
                    if len(version_parts) >= 2:
                        year = version_parts[0]
                        build = version_parts[1] if len(version_parts) > 1 else "0"
                        td_key = f"{product}.{year}.{build}"

                        executable_path = os.path.join(app_path, "Contents", "MacOS", product)

                        td_dict[td_key] = {
                            'executable': executable_path,
                            'app_path': app_path,
                            'bundle_version': bundle_version
                        }
                        logger.debug(f"Found {product}: {td_key} at {executable_path}")
                    else:
                        logger.warning(f"Could not parse version from {bundle_version}")
                else:
                    logger.warning(f"No bundle version found for {app_name}")

            except (FileNotFoundError, plistlib.InvalidFileException, KeyError) as e:
                logger.error(f"Could not read Info.plist for {app_path}: {e}")

        return td_dict

    @staticmethod
    def parse_version_string(version_str: str) -> Tuple[int, int]:
        """Parse version string into (year, build) tuple.
        Handles 'TouchDesigner.2025.32280', 'TouchPlayer.2025.32280', or just '2025.32280'.
        """
        try:
            # Remove product prefix if present
            for prefix in ('TouchDesigner.', 'TouchPlayer.'):
                if version_str.startswith(prefix):
                    version_str = version_str[len(prefix):]
                    break

            parts = version_str.split('.')
            year = int(parts[0]) if len(parts) > 0 else -1
            build = int(parts[1]) if len(parts) > 1 else -1
            return (year, build)
        except Exception:
            return (-1, -1)

    # --- TouchDesigner accessors ---

    def get_sorted_version_keys(self) -> list:
        """Get version keys sorted by year and build number."""
        return sorted(list(self.versions.keys()), key=self.parse_version_string)

    def is_version_installed(self, version: str) -> bool:
        """Check if a specific version is installed."""
        return version in self.versions

    def get_executable(self, version: str) -> Optional[str]:
        """Get the executable path for a version."""
        if version in self.versions:
            return self.versions[version].get('executable')
        return None

    def get_app_path(self, version: str) -> Optional[str]:
        """Get the .app bundle path for a version on macOS."""
        if version in self.versions:
            return self.versions[version].get('app_path')
        return None

    # --- TouchPlayer accessors ---

    def get_sorted_player_keys(self) -> list:
        """Get player version keys sorted by year and build number."""
        return sorted(list(self.player_versions.keys()), key=self.parse_version_string)

    def is_player_installed(self, version: str) -> bool:
        """Check if a matching TouchPlayer version is installed.
        Accepts either 'TouchDesigner.X.Y' or 'TouchPlayer.X.Y' — matches by numeric part.
        """
        target = self.parse_version_string(version)
        return any(self.parse_version_string(k) == target for k in self.player_versions)

    def get_player_executable(self, version: str) -> Optional[str]:
        """Get the TouchPlayer executable path for a version."""
        if version in self.player_versions:
            return self.player_versions[version].get('executable')
        return None

    def get_player_app_path(self, version: str) -> Optional[str]:
        """Get the TouchPlayer .app bundle path for a version on macOS."""
        if version in self.player_versions:
            return self.player_versions[version].get('app_path')
        return None

    def get_toeexpand_path(self) -> Optional[str]:
        """Get path to toeexpand tool from an installed TD version."""
        if platform.system() == 'Windows':
            # On Windows, look for bundled toeexpand
            toeexpand_path = get_resource_path(os.path.join("toeexpand", "toeexpand.exe"))
            if os.path.exists(toeexpand_path):
                return toeexpand_path
        else:
            # On Mac, use toeexpand from the first available TD installation
            if self.versions:
                first_app = list(self.versions.values())[0]
                app_path = first_app.get('app_path')
                if app_path:
                    toeexpand_path = os.path.join(app_path, "Contents", "MacOS", "toeexpand")
                    if os.path.exists(toeexpand_path):
                        return toeexpand_path
        return None

    def inspect_toe_file(self, file_path: str) -> Optional[str]:
        """Inspect a .toe file to determine its required TD version.

        Uses toeexpand tool from TouchDesigner installation.
        Returns version string like 'TouchDesigner.2023.12370' or None on error.
        """
        if not os.path.exists(file_path):
            logger.error(f"File does not exist: {file_path}")
            return None

        toeexpand_path = self.get_toeexpand_path()
        if not toeexpand_path:
            logger.error("No toeexpand found - need TouchDesigner installation")
            return None

        logger.info("Analyzing TOE file version...")
        logger.debug(f"Using toeexpand: {toeexpand_path}")

        command = [toeexpand_path, '-b', file_path]
        logger.debug(f"Running command: {command}")

        try:
            startupinfo = None
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )
            out, err = process.communicate()

            raw_output = out.decode('utf-8')
            raw_error = err.decode('utf-8')

            logger.debug(f"toeexpand stdout: {repr(raw_output)}")
            if raw_error:
                logger.debug(f"toeexpand stderr: {repr(raw_error)}")

            # toeexpand often returns 1 even with valid output
            if process.returncode != 0:
                logger.debug(f"toeexpand returned exit code {process.returncode} (often normal)")

            build_info = raw_output.replace('\r', '')
            logger.debug(f"Cleaned build_info: {repr(build_info)}")

            if not build_info or len(build_info.strip()) < 5:
                logger.error("toeexpand produced no useful output")
                return None

            info_split = [line.strip() for line in build_info.split('\n') if line.strip()]
            logger.debug(f"Filtered info: {info_split}")

            if len(info_split) < 2:
                logger.error(f"Unexpected toeexpand output format: {info_split}")
                return None

            version_line = info_split[1]
            logger.debug(f"Version line: {version_line}")
            version_number = version_line.split(" ")[-1]
            build_option = f'TouchDesigner.{version_number}'

            logger.info(f"TOE file requires {build_option}")
            return build_option

        except Exception as e:
            logger.error(f"Error running toeexpand: {e}")
            return None

    def generate_download_url(self, build_option: str) -> Optional[str]:
        """Generate download URL for a TD version."""
        try:
            split_options = build_option.split('.')
            if len(split_options) < 3:
                return None

            product = split_options[0]
            year = split_options[1]
            build = split_options[2]

            # Platform and architecture-specific file extension
            if platform.system() == 'Windows':
                extension = '.exe'
                arch_suffix = ''
            else:  # Mac
                extension = '.dmg'
                machine = platform.machine().lower()
                if machine in ['arm64', 'aarch64']:
                    arch_suffix = '.arm64'
                elif machine in ['x86_64', 'amd64']:
                    arch_suffix = '.intel'
                else:
                    arch_suffix = '.intel'
                    logger.warning(f"Unknown Mac architecture '{machine}', defaulting to Intel")

            # Generate URL based on build option and platform
            if year in ["2017", "2018"] and platform.system() == 'Windows':
                url = f'https://download.derivative.ca/TouchDesigner099.{year}.{build}.64-Bit{extension}'
            elif year == "2019" and platform.system() == 'Windows':
                url = f'https://download.derivative.ca/TouchDesigner099.{year}.{build}{extension}'
            else:
                url_product = product if product == 'TouchPlayer' and platform.system() != 'Windows' else 'TouchDesigner'
                url = f'https://download.derivative.ca/{url_product}.{year}.{build}{arch_suffix}{extension}'

            return url

        except Exception as e:
            logger.error(f"Error generating download URL: {e}")
            return None
