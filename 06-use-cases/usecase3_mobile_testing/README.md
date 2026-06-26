# Use Case 3 — Mobile App Testing Agent 📱

> Automate Android UI testing with Gemini Computer Use + the **Interactions API**

## What This Does

This agent performs an automated QA test on an Android device (emulator or physical):

| Step | Action | What to Expect |
|------|--------|----------------|
| 1 | Opens **Settings** app | Agent launches `com.android.settings` via ADB |
| 2 | Navigates to **Display** | Model identifies and taps the Display menu item |
| 3 | Checks **Dark Mode** status | Model reads whether dark theme is ON or OFF |
| 4 | **Toggles** Dark Mode | Model taps the toggle switch |
| 5 | Presses **Back** | Returns to the main Settings screen |
| 6 | Navigates to **About Phone** | Scrolls down if needed, then taps About Phone |
| 7 | Reads **Android version** | Model reads the version string from the screen |
| 8 | Reports **summary** | Prints a structured test report |

## Architecture

```
┌──────────────────┐     Interactions API      ┌──────────────────┐
│                  │  ◄──────────────────────►  │                  │
│   Gemini 3.5     │    (mobile environment)    │  app_test_agent  │
│   Flash Model    │                            │      .py         │
│                  │                            │                  │
└──────────────────┘                            └────────┬─────────┘
                                                         │
                                                    ADBBridge
                                                         │
                                                ┌────────▼─────────┐
                                                │  Android Device  │
                                                │   (Emulator)     │
                                                └──────────────────┘
```

## Prerequisites

1. **Android SDK with `ANDROID_HOME` and PATH configured**

   You need `adb` and `emulator` on your PATH. If you haven't set this up yet, see the [Android Emulator Setup](../../README.md#android-emulator-setup-step-4--use-case-3) section in the main README.

   Quick check:
   ```bash
   # Ensure PATH is set
   export ANDROID_HOME=~/Library/Android/sdk        # adjust for your installation
   export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"

   # Start your emulator
   emulator -list-avds                              # list available AVDs
   emulator -avd <your-avd-name>                    # start it

   # Verify it's ready (wait for '1')
   adb devices                                      # should show 'emulator-5554  device'
   adb shell getprop sys.boot_completed             # should return '1'
   ```

2. **API Key**
   ```bash
   export GEMINI_API_KEY="your-api-key"
   # Or set it in the .env file at the project root
   ```

3. **Python dependencies** (installed if you followed the main setup)
   ```bash
   pip install google-genai rich python-dotenv
   ```

## Running

```bash
# Auto-detect the first connected device
python app_test_agent.py

# Target a specific device
python app_test_agent.py --device emulator-5554

# Limit the number of turns
python app_test_agent.py --max-turns 30
```

## Expected Console Output

```
╔══════════════════════════════════════════════════════════╗
║ Use Case 3 — Mobile App Testing Agent                   ║
║ Testing Android Settings: Dark Mode toggle + About Phone║
╚══════════════════════════════════════════════════════════╝

Step 0 → Connecting to Android device via ADB …
  ADB connected — screen 1080×2400
✓ ADB bridge ready

Step 1 → Capturing initial screenshot …
  Screenshot captured: 245,312 bytes

──────────────────── Turn 1 ────────────────────
  ▶ open_app(package_name='com.android.settings')
    → {'status': 'ok'}

──────────────────── Turn 2 ────────────────────
  ▶ click(x=500, y=350)          # taps "Display"
    → {'status': 'ok'}

... (more turns) ...

╭─────────────── Agent Final Report ───────────────╮
│ Test Summary:                                     │
│ • Dark Mode before: OFF                           │
│ • Dark Mode after:  ON                            │
│ • Android version:  14                            │
│ All test steps completed successfully.            │
╰───────────────────────────────────────────────────╯

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric        ┃ Value                    ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Total turns   │ 12                       │
│ Device        │ emulator-5554            │
│ Model         │ gemini-3.5-flash         │
│ API           │ Interactions API (mobile)│
└───────────────┴──────────────────────────┘
```

## Key Concepts Demonstrated

- **Interactions API** with `environment = "mobile"` for Android
- **ADB Bridge** pattern — translating normalised 0-999 coordinates to real pixels
- **Screenshot-after-every-action** loop for visual grounding
- Structured system instructions that guide the model through a test plan
- Rich terminal formatting for readable QA output
