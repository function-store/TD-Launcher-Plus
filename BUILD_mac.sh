#!/bin/bash
# Mac build script for TD Launcher Plus
# Creates a standalone Mac app bundle for Apple Silicon (arm64)

set -e  # Exit on any error

echo "Building TD Launcher Plus for Mac..."

# Activate virtual environment if it exists
if [ -d "td_launcher_env" ]; then
    echo "Activating virtual environment..."
    source td_launcher_env/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "⚠️  No virtual environment found. Using system Python."
fi

# Check if pyinstaller is available
if ! command -v pyinstaller &> /dev/null && ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Error: pyinstaller not found. Install with: pip3 install pyinstaller"
    exit 1
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/
rm -rf dist/

# Build the app bundle
echo "Running PyInstaller..."
pyinstaller --noconfirm --log-level=WARN "TD Launcher Plus.spec"

# Ad-hoc codesign the app bundle
# This helps with Gatekeeper and permissions on macOS
if command -v codesign &> /dev/null; then
    echo "Ad-hoc codesigning the app bundle..."
    codesign --force --deep --sign - "dist/TD Launcher Plus.app"
    echo "✅ Codesigning completed"
else
    echo "⚠️  codesign tool not found. Skipping signing."
fi

echo "Build completed!"
echo "App bundle created at: dist/TD Launcher Plus.app"

# Optional: Create a DMG (requires create-dmg or similar tool)
if command -v create-dmg &> /dev/null; then
    echo "Creating DMG installer..."
    
    # Create a temporary directory with only the app
    DMG_TEMP_DIR="dist/dmg_temp"
    rm -rf "$DMG_TEMP_DIR"
    mkdir -p "$DMG_TEMP_DIR"
    
    # Copy only the app bundle to temp directory
    cp -R "dist/TD Launcher Plus.app" "$DMG_TEMP_DIR/"
    
    # Create the DMG from the clean temp directory
    # Note: create-dmg sometimes adds .VolumeIcon.icns automatically
    create-dmg \
        --volname "TD Launcher Plus Installer" \
        --window-pos 200 120 \
        --window-size 600 300 \
        --icon-size 100 \
        --icon "TD Launcher Plus.app" 175 120 \
        --hide-extension "TD Launcher Plus.app" \
        --app-drop-link 425 120 \
        --no-internet-enable \
        "dist/TD_Launcher_Installer.arm64.dmg" \
        "$DMG_TEMP_DIR"
    
    echo "DMG creation completed"
    echo "Note: .VolumeIcon.icns may appear grayed out - this is normal for DMG files"
    
    # Clean up temp directory
    rm -rf "$DMG_TEMP_DIR"
    
    echo "DMG created at: dist/TD_Launcher_Installer.dmg"
else
    echo "Note: install 'create-dmg' for DMG creation: brew install create-dmg"
fi

echo ""
echo "Build Summary:"
echo "=============="
echo "App Bundle: dist/TD Launcher Plus.app"
if [ -f "dist/TD_Launcher_Installer.arm64.dmg" ]; then
    echo "DMG Installer: dist/TD_Launcher_Installer.arm64.dmg"
fi
echo ""
echo "To test the app:"
echo "  open 'dist/TD Launcher Plus.app'"
echo "  or"
echo "  open 'dist/TD Launcher Plus.app' --args /path/to/test.toe"