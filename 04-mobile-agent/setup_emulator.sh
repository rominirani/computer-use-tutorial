#!/bin/bash
# =============================================================================
# setup_emulator.sh — Idempotent Android Emulator Setup for macOS
# =============================================================================
#
# This script prepares a macOS machine to run an Android emulator for the
# Gemini Computer Use tutorial. It is safe to re-run: every step checks
# whether its work has already been done before taking action.
#
# What it does:
#   1. Detects CPU architecture (Apple Silicon arm64 vs Intel x86_64)
#   2. Installs Java (Eclipse Temurin) via Homebrew if missing
#   3. Installs Android Command Line Tools via Homebrew if missing
#   4. Sets ANDROID_HOME and PATH for the current session
#   5. Accepts Android SDK licenses non-interactively
#   6. Installs SDK packages: platform-tools, emulator, platform, system-image
#   7. Creates an AVD named 'ComputerUseTutorial' (skipped if it exists)
#   8. Prints the export lines the user should add to ~/.zshrc
#
# Usage:
#   chmod +x setup_emulator.sh
#   ./setup_emulator.sh
# =============================================================================

# Exit immediately on any command failure
set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────────────────
# AVD name used by the tutorial agent
AVD_NAME="ComputerUseTutorial"

# Target Android API level
API_LEVEL="35"

# ─── Step 1: Detect CPU Architecture ───────────────────────────────────────
# Apple Silicon Macs use arm64; Intel Macs use x86_64.
# The system image architecture must match the host CPU.
MACHINE_ARCH="$(uname -m)"

if [[ "$MACHINE_ARCH" == "arm64" ]]; then
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  Detected: Apple Silicon (arm64)                 ║"
    echo "╚══════════════════════════════════════════════════╝"
    SYSTEM_IMAGE="system-images;android-${API_LEVEL};google_apis;arm64-v8a"
    # Homebrew on Apple Silicon installs to /opt/homebrew
    ANDROID_HOME_DEFAULT="/opt/homebrew/share/android-commandlinetools"
elif [[ "$MACHINE_ARCH" == "x86_64" ]]; then
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  Detected: Intel (x86_64)                        ║"
    echo "╚══════════════════════════════════════════════════╝"
    SYSTEM_IMAGE="system-images;android-${API_LEVEL};google_apis;x86_64"
    # Homebrew on Intel installs to /usr/local
    ANDROID_HOME_DEFAULT="/usr/local/share/android-commandlinetools"
else
    echo "ERROR: Unsupported architecture '$MACHINE_ARCH'. This script supports macOS only."
    exit 1
fi

echo ""

# ─── Step 2: Install Java (Eclipse Temurin) ────────────────────────────────
# The Android SDK tools require a JDK. Temurin is the recommended free build.
if java -version &>/dev/null; then
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo "✅ Java already installed: $JAVA_VER"
else
    echo "📦 Java not found — installing Eclipse Temurin via Homebrew..."
    brew install --cask temurin
    echo "✅ Java (Temurin) installed."
fi

echo ""

# ─── Step 3: Install Android Command Line Tools ───────────────────────────
# The 'android-commandlinetools' cask provides sdkmanager, avdmanager, etc.
if [[ -d "$ANDROID_HOME_DEFAULT" ]]; then
    echo "✅ Android Command Line Tools already installed at $ANDROID_HOME_DEFAULT"
else
    echo "📦 Android CLI tools not found — installing via Homebrew..."
    brew install --cask android-commandlinetools
    echo "✅ Android Command Line Tools installed."
fi

echo ""

# ─── Step 4: Set Environment Variables for This Session ────────────────────
# These exports make sdkmanager, avdmanager, adb, and emulator available
# in the current shell. The user will also need them permanently (see Step 8).
export ANDROID_HOME="$ANDROID_HOME_DEFAULT"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
export PATH="$ANDROID_HOME/emulator:$PATH"
export PATH="$ANDROID_HOME/platform-tools:$PATH"

# Verify sdkmanager is accessible
if ! command -v sdkmanager &>/dev/null; then
    echo "ERROR: sdkmanager not found after setting PATH."
    echo "       Expected location: $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
    echo "       Please check your android-commandlinetools installation."
    exit 1
fi

echo "✅ ANDROID_HOME set to: $ANDROID_HOME"
echo "✅ sdkmanager found at: $(command -v sdkmanager)"
echo ""

# ─── Step 5: Accept SDK Licenses ──────────────────────────────────────────
# Pipe 'yes' to auto-accept all licenses. Suppress stdout since it's verbose.
echo "📋 Accepting SDK licenses (if not already accepted)..."
if yes | sdkmanager --licenses > /dev/null 2>&1; then
    echo "✅ All SDK licenses accepted."
else
    echo "⚠️  License acceptance returned a non-zero exit. Continuing anyway..."
fi

echo ""

# ─── Step 6: Install SDK Components ───────────────────────────────────────
# We need four packages:
#   - platform-tools   : adb, fastboot
#   - emulator          : the Android emulator binary
#   - platforms;android-XX : the Android platform library
#   - system-images;... : the OS image for the virtual device
REQUIRED_PACKAGES=(
    "platform-tools"
    "emulator"
    "platforms;android-${API_LEVEL}"
    "$SYSTEM_IMAGE"
)

# Get list of currently installed packages (one per line)
# Use --list_installed if available, otherwise parse --list output
INSTALLED_LIST=$(sdkmanager --list_installed 2>/dev/null || \
                 sdkmanager --list 2>/dev/null | sed -n '/Installed/,/Available/p')

# Build an array of packages that still need installing
TO_INSTALL=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if echo "$INSTALLED_LIST" | grep -q "$pkg"; then
        echo "✅ Already installed: $pkg"
    else
        echo "📦 Needs install:     $pkg"
        TO_INSTALL+=("$pkg")
    fi
done

echo ""

# Install any missing packages in a single sdkmanager invocation
if [[ ${#TO_INSTALL[@]} -gt 0 ]]; then
    echo "⬇️  Installing ${#TO_INSTALL[@]} package(s): ${TO_INSTALL[*]}"
    sdkmanager "${TO_INSTALL[@]}"
    echo "✅ All SDK components installed."
else
    echo "✅ All SDK components already up to date."
fi

echo ""

# ─── Step 7: Create AVD (Android Virtual Device) ─────────────────────────
# The AVD is the virtual phone the agent will control. We skip creation
# if an AVD with the same name already exists.
if emulator -list-avds 2>/dev/null | grep -q "^${AVD_NAME}$"; then
    echo "✅ AVD '$AVD_NAME' already exists — skipping creation."
else
    echo "📱 Creating AVD '$AVD_NAME' with system image: $SYSTEM_IMAGE"
    # Answer 'no' to the custom hardware profile question
    echo "no" | avdmanager create avd \
        --name "$AVD_NAME" \
        --package "$SYSTEM_IMAGE" \
        --force
    echo "✅ AVD '$AVD_NAME' created successfully."
fi

echo ""

# ─── Step 8: Print Shell Export Lines ─────────────────────────────────────
# The user needs to add these to their shell profile so that adb, emulator,
# and sdkmanager are available in every new terminal session.
echo "════════════════════════════════════════════════════════════════"
echo "  🎉  Setup Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Add the following lines to your shell profile (~/.zshrc or ~/.bash_profile):"
echo ""
echo "  # Android SDK (Gemini Computer Use tutorial)"
echo "  export ANDROID_HOME=\"$ANDROID_HOME\""
echo "  export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$PATH\""
echo "  export PATH=\"\$ANDROID_HOME/emulator:\$PATH\""
echo "  export PATH=\"\$ANDROID_HOME/platform-tools:\$PATH\""
echo ""
echo "Then reload your shell and launch the emulator:"
echo ""
echo "  source ~/.zshrc"
echo "  emulator -avd $AVD_NAME"
echo ""
echo "════════════════════════════════════════════════════════════════"
