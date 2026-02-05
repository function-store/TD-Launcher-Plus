# TD Launcher Plus
A focused project dashboard for TouchDesigner. Launch .toe files with the correct version automatically, open recent project files, or custom template projects (startup files). With optional icon preview, and project documentation viewer and editor.

### Key Features:
- **Version Detection:** Automatically finds the right TD build for any `.toe` file.
- **Unified Grid:** A clean layout with split project/info views.
- **Tab Memory:** Remembers your selection when switching between Recent Files and Templates.
- **Docs Editor:** Built-in README panel for project documentation.
- **Cross-Platform:** Works on macOS and Windows.

---

## What's this for

If you work on a lot of TouchDesigner projects, or maintain a library of legacy work, you know the frustration of managing multiple concurrent installations. Guessing which version a project requires—or worse, accidentally upgrading a project and losing work—is a constant risk.

## How this works

TD Launcher Plus operates in two primary modes depending on how it's opened:

### 1. Automatic Launch Mode
When you open a `.toe` file with TD Launcher Plus (via double-click or drag-and-drop), it instantly analyzes the file to find the required TouchDesigner version. It then presents a 5-second countdown timer.
- **Auto-launch:** If left undisturbed, the project opens in the detected version automatically.
- **Interruption:** Clicking anywhere or pressing a key stops the timer, allowing you to manually override the TD version or view project notes.

### 2. Dashboard Mode (Project Manager)
Launching the app directly opens the project dashboard. Here you can browse your **Recent Files** and **Templates** library. 
- **Smart Discovery:** The tool scans your system for all installed TouchDesigner versions and presents them as options.
- **Integrated Docs:** Selecting a project instantly loads its project info and README.md (if present) into the side panel. 
- **Keyboard Workflow:** Designed for speed with full keyboard navigation, tab memory, and debounced analysis for a smooth browsing experience.

## How to use

### Windows
1. Download the installer from the releases page on the right
2. Run the installer to install TD Launcher Plus
3. Set Windows to open `.toe` files with TD Launcher Plus by default
4. Double-clicking `.toe` files will now launch them with TD Launcher Plus

### macOS
1. Download the `.dmg` file from the releases page
2. Open the DMG and drag "TD Launcher Plus" to the "Applications" folder
3. **File association is automatic!** TD Launcher Plus will appear as an option for `.toe` files
4. **Optional:** To make it the default, right-click any `.toe` file → "Get Info" → set "Open with" to "TD Launcher Plus" → "Change All..."
5. Double-clicking `.toe` files will now launch them with TD Launcher Plus

### Alternative Usage
You can also drag and drop `.toe` files directly onto the TD Launcher Plus app icon.

---

## Features

### Automatic Version Detection
TD Launcher Plus analyzes each `.toe` file to determine which TouchDesigner version it was created with, then launches it with the correct version automatically.

- **Auto-launch timer:** After selecting a file, a 5-second countdown begins before launching
- **Click to interrupt:** Click anywhere to stop the countdown and manually select a different version
- **Missing version handling:** If the required version isn't installed, TD Launcher Plus shows a download link and lets you choose an alternative version

### Recent Files
TD Launcher Plus keeps track of recently opened projects. When you launch a `.toe` file, it's automatically added to the Recent Files list for quick access later.

**Versioned files:** TouchDesigner auto-saves create versioned files like `project.7.toe`, `project.8.toe`, etc. TD Launcher Plus intelligently handles these:
- Versioned files are displayed as their non-versioned counterpart (e.g., `project.7.toe` shows as `project.toe`)
- Multiple versions of the same project appear only once in the list
- Files in a `Backup/` folder are shown with a `Backup/` prefix

### Templates
Save frequently-used project templates for quick access. Templates appear in a separate tab alongside Recent Files.

- Click **"Add Template..."** to add a `.toe` file as a template
- Templates persist between sessions
- Remove templates with the **X** button

### Project Icons
TD Launcher Plus can display project icons next to each file. Enable with the **"Show Icons"** checkbox.

**Icon search order** (first found is used):
1. `icon.png` / `icon.jpg` / `icon.jpeg` in the project folder
2. `icon_temp.png` / `icon_temp.jpg` / `icon_temp.jpeg` (for auto-generated icons)
3. `<projectname>.png` / `.jpg` / `.jpeg` (e.g., `MyProject.png` for `MyProject.toe`)
4. `<projectname_without_version>.png` (e.g., `MyProject.png` for `MyProject.7.toe`)
5. Falls back to the TD Launcher Plus app icon

### Project Info Panel
Enable **"Show Info"** to display an editable README panel alongside the file picker.

- If a `README.md` exists in the project folder, it's loaded for viewing and editing
- If no README exists, you can create one by typing and clicking **Save**
- Changes are indicated with an asterisk (*) on the Save button
- Click **View** to open the README rendered as HTML in your default browser

### TouchDesigner Utility Component
A companion TouchDesigner component (`TDLauncherUtility.toe`) is included that integrates with TD Launcher Plus:

- **Export project icon:** Automatically exports a thumbnail from your project as `icon_temp.png`
- **Update recent files:** Notifies TD Launcher Plus when you save, keeping the recent files list current
- **Quick access:** Open TD Launcher Plus directly from within TouchDesigner

To use: Import `TDLauncherUtility.toe` into your project or add it to your palette.

---

## How to build
This was built with Python 3.10. Pyinstaller, and the wonderful [DearPyGui](https://github.com/hoffstadt/DearPyGui) for UI amongst other things.

By default, Pyinstaller compiled programs when downloaded directly from the internet as an exe or zipped exe tend to get flagged as false positive viruses, for this one it showed up as Trojan:Win32/Wacatac.B!ml, which is of course nonsense. 

To get around this for those downloading releases, I bundled the executable into a windows installer using inno setup which conveniently compresses the contents into a format chrome, windows etc can't read at download time.

If you want to build from this repo, there's a few steps, but they are mostly automated.

1) download this repo
2) unzip the py directory from inside py.zip into the root of the repo. This is a full python install, with Pyinstaller DearPyGui, etc installed.
3) make your changes to td_launcher.py, the main script.
4) test td_launcher.py easily by just double clicking td_launcher.bat. (NOTE: when doubleclicking to run, it uses a bundled test.toe as a test file for simplicity.)
5) when ready to rebuild the single file exe with pyinstaller, run BUILD.bat. This will create the executable in dist\td_launcher.exe.
6) optionally if you also wish to bundle the exe into an installer, you can open the iss file inno\TD_Launcher_Inno_Compiler.iss, with [inno setup](https://jrsoftware.org/isinfo.php), and build from there. separate installer.exe will show up in the inno\Output\ directory.

### macOS Build

The macOS build is optimized for Apple Silicon (M1/M2/M3/etc) Macs and includes file association support for `.toe` files.

#### Prerequisites
1. **TouchDesigner installed** - Required for `toeexpand` utility
2. **Python 3.9+** with pip
3. **Xcode Command Line Tools**: `xcode-select --install`

#### Quick Setup
```bash
# 1. Clone the repository
git clone <repo-url>
cd TD-Launcher-Mac

# 2. Set up Python virtual environment
./setup_mac.sh

# 3. Build the app (simple version for development)
./BUILD_mac_simple.sh

# 4. Build creates automatic file association support
```

#### Build Options

**Development Build (Recommended):**
```bash
./BUILD_mac_simple.sh
```
- Quick build for testing
- Creates `dist/TD Launcher Plus.app`
- Includes debug logging support

**Distribution Build:**
```bash
./BUILD_mac.sh
```
- Full build with DMG creation
- Requires `brew install create-dmg` for DMG generation
- Creates both app bundle and installer DMG

#### Testing & Debugging

**Test the built app:**
```bash
# Test built app bundle with debug logging
export TD_LAUNCHER_DEBUG=1
open "dist/TD Launcher Plus.app" --args test.toe


```

**Run from source with debugging:**
```bash
# Enable debug logging
export TD_LAUNCHER_DEBUG=1
python3 td_launcher.py test.toe
```

#### File Association Setup

The built app automatically includes file association support for `.toe` files. After building:

1. **Install the app:**
   - Copy `dist/TD Launcher Plus.app` to `/Applications/`
   - Or install via the DMG (distribution build)

2. **Set as default (if needed):**
   - Right-click any `.toe` file
   - Select "Get Info"
   - In "Open with" section, select "TD Launcher Plus"
   - Click "Change All..." to set as default

**Note:** File associations activate automatically when the app is in `/Applications/`. No manual registration required.

#### Build Requirements

The build process requires these Python packages (automatically installed by `setup_mac.sh`):
- `dearpygui>=1.9.0` - GUI framework
- `pyinstaller>=5.0` - App bundling
- `Pillow>=9.0.0` - Icon processing

#### Architecture Notes

- **Apple Silicon**: Native ARM64 build for optimal performance
- **Intel Macs**: Can run via Rosetta 2 translation
- **Universal Binary**: Not supported due to dearpygui limitations

#### Troubleshooting


**TouchDesigner not detected:**
- Ensure TouchDesigner is installed in `/Applications/`
- Check that `toeexpand` exists in TouchDesigner.app bundle

**File association not working:**
- Ensure app is installed in `/Applications/`
- Try: Right-click `.toe` file → "Open With" → "TD Launcher Plus"
- Restart Finder: `killall Finder`
- Enable debug logging: `export TD_LAUNCHER_DEBUG=1` and check `~/Desktop/td_launcher_debug.log`

---

## Developer Notes

### Platform-Specific TOE File Analysis

TD Launcher Plus uses TouchDesigner's `toeexpand` utility to analyze `.toe` files and determine the required TouchDesigner version. The implementation differs between platforms:

#### Windows
- **Bundled approach**: Uses the `toeexpand.exe` included in the `toeexpand/` directory
- **Self-contained**: No dependency on installed TouchDesigner versions
- **Consistent**: Always uses the same `toeexpand` version regardless of system state

#### macOS
- **Dynamic discovery**: Searches for `toeexpand` within installed TouchDesigner applications
- **Location**: `TouchDesigner.app/Contents/MacOS/toeexpand`
- **Requirement**: At least one TouchDesigner installation must be present on the system
- **Fallback**: Uses the first available TouchDesigner installation found in `/Applications/`

#### Technical Details
```bash
# macOS: Dynamic path resolution
/Applications/TouchDesigner.2023.11600.app/Contents/MacOS/toeexpand -b file.toe

# Windows: Bundled utility
./toeexpand/toeexpand.exe -b file.toe
```

This approach ensures optimal compatibility on each platform while maintaining the core functionality of version detection.

# Contributors

- (Lucas Morgan)[https://www.enviral-design.com/] - original TD Launcher Plus with version picker
- (Dan Molnar / Function Store)[https://functionstore.xyz/link-in-bio](Cross platform implementation and "Plus" version including recent files, templates, icons, readme, utility
- (Keith Lostracco)[https://github.com/keithlostracco] - Daily build signature support

---

If you have any issues, please post a bug issue here.
