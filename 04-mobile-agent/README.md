# Step 04 — Android Mobile Agent with Gemini Computer Use

This tutorial step builds an **autonomous Android agent** that uses the
Gemini 3.5 Flash model to control an Android device or emulator through ADB.
It demonstrates the **Interactions API** — a different (and simpler) approach
than the `generateContent` API used in the browser agent.

## Architecture Overview

```
┌─────────────────┐    natural language     ┌──────────────────┐
│   You (User)    │ ──────────────────────► │  mobile_agent.py │
└─────────────────┘                         └────────┬─────────┘
                                                     │
                                          ┌──────────┴──────────┐
                                          │                     │
                                          ▼                     ▼
                                   ┌─────────────┐     ┌──────────────┐
                                   │ Gemini API  │     │  adb_bridge  │
                                   │ Interactions│     │  .py         │
                                   │ API         │     └──────┬───────┘
                                   └─────────────┘            │
                                          ▲             ADB commands
                                          │                   │
                                    screenshots               ▼
                                          │           ┌──────────────┐
                                          └────────── │   Android    │
                                                      │   Emulator   │
                                                      └──────────────┘
```

**The loop:**
1. Capture a screenshot of the Android screen via ADB
2. Send the screenshot + task to Gemini 3.5 Flash
3. Model returns structured tool calls (`click`, `type`, `drag_and_drop`, etc.)
4. `ADBBridge` converts normalized coordinates (0–999) to pixel coordinates and executes via ADB
5. Capture a new screenshot and send it back as a `function_result`
6. Repeat until the model responds with text (task complete)

---

## File Structure

| File | Purpose |
|------|---------|
| `setup_emulator.sh` | Idempotent macOS script to install Java, Android SDK, and create the AVD |
| `adb_bridge.py` | ADB abstraction layer — translates model actions to ADB commands |
| `mobile_agent.py` | Main agent script using the Interactions API |
| `README.md` | This file |

---

## Setup

### Prerequisites

- **macOS** with [Homebrew](https://brew.sh/) installed
- **Python 3.10+**
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey)

### 1. Set Up the Android Emulator

The `setup_emulator.sh` script handles everything:

```bash
# Make executable and run
chmod +x setup_emulator.sh
./setup_emulator.sh
```

The script will:
- Detect your CPU (Apple Silicon or Intel) and pick the right system image
- Install Java (Temurin) via Homebrew if missing
- Install Android Command Line Tools via Homebrew if missing
- Accept SDK licenses
- Install platform-tools, emulator, Android 35 platform, and system image
- Create an AVD named `ComputerUseTutorial`
- Print the export lines to add to your `~/.zshrc`

> **Important:** Add the printed export lines to your shell profile and reload:
> ```bash
> source ~/.zshrc
> ```

**Option B: Already have Android Studio / SDK installed?**

Skip `setup_emulator.sh` and just set your PATH:

```bash
# Find where your SDK lives (common locations on macOS):
export ANDROID_HOME=~/Library/Android/sdk                      # Android Studio default
# OR: export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools  # Homebrew (Apple Silicon)
# OR: export ANDROID_HOME=/usr/local/share/android-sdk                  # Homebrew (Intel)

# Add emulator and platform-tools to PATH
export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"

# Add to ~/.zshrc so it persists:
echo 'export ANDROID_HOME=~/Library/Android/sdk' >> ~/.zshrc
echo 'export PATH="$ANDROID_HOME/emulator:$ANDROID_HOME/platform-tools:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 2. Start the Emulator

```bash
# List your available AVDs first
emulator -list-avds

# Start one (use the name from the list above)
emulator -avd <your-avd-name>

# For headless mode (no GUI window):
emulator -avd <your-avd-name> -no-window -no-audio -gpu swiftshader_indirect
```

Wait for the emulator to fully boot. Verify with:

```bash
adb devices                          # Should show: emulator-5554  device
adb shell getprop sys.boot_completed # Should return: 1
```

> **⏳ First boot** can take 15-30 seconds. Subsequent boots are faster.

### 3. Install Dependencies

From the project root:

```bash
pip install google-genai rich python-dotenv
```

### 4. Set Your API Key

```bash
export GEMINI_API_KEY="your-api-key-here"
# Or set it in the .env file at the project root
```

---

## Running the Agent

### Default Task

```bash
python mobile_agent.py
```

This runs the default task: *"Open Settings and check the current Android version"*

### Custom Task

```bash
python mobile_agent.py "Open Chrome and search for the weather in Tokyo"
```

### With a Specific Device

```bash
python mobile_agent.py "Enable dark mode" --device emulator-5554
```

### Limit Turns

```bash
python mobile_agent.py "Check battery level" --max-turns 20
```

---

## Expected Output

```
╔══════════════════════════════════════════════════════════╗
║  Gemini Computer Use — Android Mobile Agent             ║
║  Model: gemini-3.5-flash | API: Interactions            ║
╚══════════════════════════════════════════════════════════╝

Step 1 → Configuring Android SDK path...
         ANDROID_HOME = /opt/homebrew/share/android-commandlinetools
Step 2 → Checking for connected devices...
         Using device: emulator-5554
Step 3 → Verifying GEMINI_API_KEY...
         API key found ✓

📱 Device: ADBBridge(device=['adb', '-s', 'emulator-5554'], screen=1080x2400)
🎯 Task: Open Settings and check the current Android version
════════════════════════════════════════════════════════════

📸 Capturing initial screenshot...

──────────────────────────────────────────────────────────
  Turn 1/50
──────────────────────────────────────────────────────────
  🔧 Action: open_app({'package_name': 'com.android.settings'})
  ✓ Result: {'status': 'ok'}

──────────────────────────────────────────────────────────
  Turn 2/50
──────────────────────────────────────────────────────────
  🔧 Action: click({'y': 850, 'x': 500})
  ✓ Result: {'status': 'ok'}

  ...

✅ Agent completed the task!
   Model response: The Android version is 15 (API level 35).
```

---

## Interactions API vs generateContent

This tutorial step uses the **Interactions API** — here's how it compares to the `generateContent` approach used in the browser agent (Step 03):

| Aspect | `generateContent` (Browser Agent) | `interactions.create` (Mobile Agent) |
|--------|-----------------------------------|--------------------------------------|
| **State Management** | You manually build and maintain a `contents[]` list with full conversation history | Server manages state via `previous_interaction_id` — you only send new input |
| **Screenshot History** | You must manually prune old screenshots to avoid context overflow | Server handles context management automatically |
| **Tool Configuration** | `types.Tool(computer_use=types.ComputerUse(environment=...))` with typed SDK objects | `{'type': 'computer_use', 'environment': 'mobile'}` as simple dicts |
| **Response Structure** | `response.candidates[0].content.parts` with `FunctionCall` parts | `interaction.steps` with typed step objects (`function_call`, `model_output`) |
| **Function Results** | Build `Content(role='user', parts=[Part(function_response=...)])` | Send `{'type': 'function_result', 'name': ..., 'call_id': ..., 'result': [...]}` |
| **Multi-turn Linking** | Implicit via the growing `contents[]` array | Explicit via `previous_interaction_id` chain |
| **Best For** | Fine-grained control, custom context management, complex browser workflows | Simpler agent loops, mobile/Android use cases, rapid prototyping |

### Key Code Difference

**generateContent (Browser Agent):**
```python
# You manage the full conversation history
contents = [Content(role="user", parts=[Part(text=query)])]
response = client.models.generate_content(
    model="gemini-3.5-flash",
    contents=contents,
    config=GenerateContentConfig(tools=[...])
)
contents.append(response.candidates[0].content)  # Manual history
```

**Interactions API (Mobile Agent):**
```python
# Server manages history — you just send new input each turn
interaction = client.interactions.create(
    model="gemini-3.5-flash",
    input=[{"type": "text", "text": task}, ...],
    tools=[{"type": "computer_use", "environment": "mobile"}],
    previous_interaction_id=previous_id,  # Links to prior turn
)
previous_id = interaction.id  # Chain for next turn
```

---

## The ADB Bridge

The `ADBBridge` class is a clean abstraction layer between the model's tool calls and the Android device:

### Coordinate System

The model outputs all coordinates in a **normalized 0–999 range**. The bridge converts them to actual pixel coordinates:

```
pixel_x = normalized_x / 1000 * screen_width
pixel_y = normalized_y / 1000 * screen_height
```

For a 1080×2400 screen, a model coordinate of `(500, 250)` becomes pixel `(540, 600)`.

> **Note:** The model sends coordinates in **(y, x)** order — `click(y=500, x=250)`. The bridge handles this convention.

### Supported Actions

| Action | Description | ADB Command |
|--------|-------------|-------------|
| `click(y, x)` | Tap at coordinates | `input tap <px> <py>` |
| `type(text, press_enter)` | Type text into focused field | `input text <text>` |
| `long_press(y, x, seconds)` | Long press | `input swipe <px> <py> <px> <py> <ms>` |
| `drag_and_drop(start_y, start_x, end_y, end_x)` | Swipe/scroll | `input swipe <sx> <sy> <ex> <ey> 300` |
| `press_key(key)` | Press a named key | `input keyevent <code>` |
| `go_back()` | Android Back button | `input keyevent 4` |
| `open_app(package_name)` | Launch an app | `monkey -p <pkg> -c LAUNCHER 1` |
| `list_apps()` | List third-party apps | `pm list packages -3` |
| `wait(seconds)` | Pause for animations | `time.sleep()` |
| `take_screenshot()` | No-op (screenshots are automatic) | — |
| `screenshot()` | Capture PNG bytes | `exec-out screencap -p` |

---

## Safety Decisions

The model may include a `safety_decision` field when it wants to perform
sensitive actions (e.g., making a purchase, sending a message). In this
tutorial, safety decisions are **auto-acknowledged** with a warning printed
to the console. In a production system, you would prompt the user for
confirmation.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `adb: command not found` | Run `./setup_emulator.sh` and add the exports to `~/.zshrc` |
| `No Android device connected` | Start the emulator: `emulator -avd ComputerUseTutorial` |
| `GEMINI_API_KEY not set` | `export GEMINI_API_KEY="your-key"` |
| Emulator is slow | Close other apps; ensure hardware acceleration is enabled |
| Model taps the wrong spot | This is normal — the model may need a few attempts to find UI elements |
| `App not installed` error | Use the correct package name (e.g., `com.android.chrome`, not `Chrome`) |
