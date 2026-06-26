"""
mobile_agent.py — Gemini Computer Use Agent for Android (Interactions API)
==========================================================================

This script implements a fully autonomous Android agent that uses the
Gemini 3.5 Flash model's Computer Use capability to control an Android
device or emulator through ADB.

Key Architectural Differences from the Browser Agent:
  - Uses the **Interactions API** (`client.interactions.create()`) instead
    of `client.models.generate_content()`.
  - State is managed via `previous_interaction_id` rather than building
    a manual conversation history.
  - Tool configuration uses the dict format: {'type': 'computer_use',
    'environment': 'mobile'} instead of types.Tool(...) objects.

Agent Loop:
  1. Capture a screenshot of the Android device via ADB
  2. Send the screenshot + task description to Gemini 3.5 Flash
  3. Model returns structured tool calls (click, type, swipe, etc.)
  4. Execute each tool call via ADBBridge
  5. Capture a new screenshot after each action
  6. Send the screenshot + result back as function_result
  7. Repeat until the model returns a text response (task complete)

Usage:
  export GEMINI_API_KEY="your-key-here"

  # Default task (check Android version in Settings)
  python mobile_agent.py

  # Custom task
  python mobile_agent.py "Open Chrome and search for weather"

  # With a specific device serial
  python mobile_agent.py "Enable dark mode" --device emulator-5554
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory

# The google-genai SDK provides both generateContent and Interactions APIs.
# This mobile agent uses the Interactions API (client.interactions.create()),
# which manages conversation state server-side. See run_mobile_agent() for details.
from google import genai

# Import our ADB abstraction layer
from adb_bridge import ADBBridge


# ─── System Prompt ─────────────────────────────────────────────────────────
# This prompt gives the model context about what it's controlling and
# establishes behavioral guidelines for reliable operation.
SYSTEM_INSTRUCTION = """You are an AI agent controlling an Android phone through ADB.

Guidelines for reliable operation:
- Use the provided tools (click, type, drag_and_drop, etc.) to interact with the phone.
- Always examine the full screen before deciding an element isn't visible — scroll down if needed.
- Launch apps using open_app with their package name (e.g., 'com.android.settings').
- Type text ONLY via the type tool. Do NOT attempt to use the on-screen virtual keyboard.
- Use go_back to navigate back. Use press_key with 'home' to go to the home screen.
- When scrolling, use drag_and_drop with appropriate start/end coordinates.
- Wait for animations and transitions to complete before taking the next action.
- If the task is already complete or the desired state is already shown, say so.
- Be precise with tap targets — aim for the center of buttons and text.
"""


# ─── Environment Setup ────────────────────────────────────────────────────
# Unlike a browser agent where Playwright is a pip dependency, the mobile
# agent relies on the Android SDK tools (particularly `adb`) being installed
# on the host machine. configure_android_sdk_path() bridges this gap by
# auto-detecting common SDK install locations so the user doesn't need to
# manually configure their shell before running the agent.

def configure_android_sdk_path():
    """Ensure ANDROID_HOME and PATH are set so ADB is accessible.

    Checks common Homebrew installation paths for the Android SDK.
    This allows the script to work even if the user hasn't yet added
    the exports to their shell profile.
    """
    # Why this function exists:
    # ADB (Android Debug Bridge) is the transport layer between this agent
    # and the Android device/emulator. It's part of the Android SDK, which
    # can be installed via Homebrew, Android Studio, or manually. The SDK's
    # `platform-tools/` directory (containing `adb`) is often not on PATH
    # by default, so we detect and add it automatically. Without this, every
    # subprocess call to `adb` would fail with "command not found".

    # Candidate paths in priority order:
    #   1. User's existing ANDROID_HOME environment variable
    #   2. Homebrew Apple Silicon path
    #   3. Homebrew Intel path
    candidate_paths = [
        os.environ.get("ANDROID_HOME"),
        "/opt/homebrew/share/android-commandlinetools",
        "/usr/local/share/android-commandlinetools",
    ]

    android_home = None
    for path in candidate_paths:
        if path and os.path.isdir(path):
            android_home = path
            break

    if not android_home:
        print("❌ ERROR: ANDROID_HOME not found.")
        print("   Run ./setup_emulator.sh first to install the Android SDK.")
        sys.exit(1)

    # Set for this process and any child processes (like ADB)
    os.environ["ANDROID_HOME"] = android_home

    # Add SDK tool directories to PATH so we can find adb, emulator, etc.
    # The key directory is `platform-tools/` which contains `adb`.
    sdk_bin_dirs = [
        os.path.join(android_home, "cmdline-tools", "latest", "bin"),
        os.path.join(android_home, "emulator"),
        os.path.join(android_home, "platform-tools"),
    ]
    current_path = os.environ.get("PATH", "")
    for bin_dir in sdk_bin_dirs:
        if bin_dir not in current_path:
            current_path = bin_dir + os.pathsep + current_path
    os.environ["PATH"] = current_path

    return android_home


def verify_device_connected() -> str:
    """Check that at least one Android device or emulator is connected.

    Returns:
        The device serial string (e.g. 'emulator-5554') of the first
        connected device.

    Exits:
        If no device is connected, prints instructions and exits.
    """
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        print("❌ ERROR: 'adb' command not found.")
        print("   Run ./setup_emulator.sh and add exports to your shell profile.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("❌ ERROR: 'adb devices' timed out.")
        sys.exit(1)

    # Parse the output. Format is:
    #   List of devices attached
    #   emulator-5554   device
    #   <serial>        <state>
    connected_devices = []
    for line in result.stdout.strip().splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            connected_devices.append(parts[0])

    if not connected_devices:
        print("❌ ERROR: No Android device or emulator connected.")
        print("   Start the emulator with:")
        print("     emulator -avd ComputerUseTutorial")
        print("   Or connect a physical device via USB with USB debugging enabled.")
        sys.exit(1)

    return connected_devices[0]


# ─── Interaction Output Parsing ────────────────────────────────────────────
# IMPORTANT: The Interactions API returns a fundamentally different response
# structure than generateContent. With generateContent, the response has
# `response.candidates[0].content.parts` — a flat list of Part objects.
# With the Interactions API, the response has `interaction.steps` — a list
# of step objects, each with a `.type` field that is either "model_output"
# (for text) or "function_call" (for tool invocations). These two helper
# functions parse that step-based structure.

def extract_text_from_interaction(interaction) -> str:
    """Pull all text content from the model's response steps.

    The Interactions API returns a list of 'steps', each of which may
    contain content blocks with text or function calls. This extracts
    only the text parts.

    Null-safe: handles None steps or None content gracefully.

    Args:
        interaction: The Interaction response object.

    Returns:
        Concatenated text from all model_output steps, or empty string.
    """
    text_parts = []
    # Guard: interaction.steps can be None on empty/malformed responses
    if not interaction or not interaction.steps:
        return ""
    for step in interaction.steps:
        # In the Interactions API, text lives inside steps of type
        # "model_output". Each model_output step has a .content list
        # of blocks, where each block has a .type ("text") and .text.
        # Compare with generateContent where text lives in part.text
        # inside response.candidates[0].content.parts.
        if step.type == "model_output" and step.content:
            for block in step.content:
                if block.type == "text" and block.text:
                    text_parts.append(block.text.strip())
    return " ".join(text_parts)


def extract_function_calls(interaction) -> list:
    """Extract all function_call steps from the interaction response.

    Each function call step has:
      - step.name: The tool name (e.g., 'click', 'type')
      - step.arguments: Dict of arguments (e.g., {'x': 500, 'y': 300})
      - step.id: Unique call ID needed for the function_result response

    Null-safe: handles None steps gracefully.

    Args:
        interaction: The Interaction response object.

    Returns:
        List of step objects where step.type == 'function_call'.
    """
    # Guard: interaction.steps can be None on empty/malformed responses
    if not interaction or not interaction.steps:
        return []
    calls = []
    for step in interaction.steps:
        # In the Interactions API, function calls are top-level steps
        # (step.type == "function_call"), each with .name, .arguments,
        # and .id attributes. This is different from generateContent
        # where function calls are Part objects with part.function_call
        # containing .name and .args.
        if step.type == "function_call":
            calls.append(step)
    return calls

# ─── API Call Helper with Retry ────────────────────────────────────────────
# Why we retry empty responses:
# The Computer Use model should always return either text ("task is done")
# or function_calls ("tap here next"). However, the model can intermittently
# return a response with *neither* — an empty response. This is a known
# transient behavior, not a permanent failure. Retrying with backoff almost
# always resolves it on the next attempt. Without this retry logic, the
# agent loop would halt prematurely on a perfectly recoverable hiccup.

def _call_with_retry(
    client,
    current_input: list,
    previous_interaction_id: str | None,
    max_retries: int = 3,
):
    """Call the Interactions API with exponential backoff retry.

    Retries on two conditions:
      1. The API raises an exception (network error, server error,
         or the "model output must contain either output text or tool
         calls" validation error).
      2. The API returns successfully but the response contains neither
         text nor function calls (empty/malformed model output).

    Args:
        client: The genai.Client instance.
        current_input: The input payload for the Interactions API.
        previous_interaction_id: ID of the prior interaction for chaining.
        max_retries: Maximum number of attempts (default: 3).

    Returns:
        A valid Interaction response, or None if all retries failed.
    """
    for attempt in range(max_retries):
        delay = 2 ** attempt  # 1s, 2s, 4s exponential backoff

        # ── Attempt the API call ──
        try:
            interaction = client.interactions.create(
                model="gemini-3.5-flash",
                system_instruction=SYSTEM_INSTRUCTION,
                input=current_input,
                # ── Mobile tool configuration ──
                # The tool config dict format {"type": "computer_use", "environment": "mobile"}
                # is specific to the Interactions API. Compare with generateContent which uses:
                #   types.Tool(computer_use=types.ComputerUse(
                #       environment=types.Environment.ENVIRONMENT_BROWSER))
                #
                # The "environment" value controls which action set the model can use:
                #   - "browser"  → click, type, scroll, navigate, new_tab, etc.
                #   - "mobile"   → click, type, drag_and_drop, open_app, press_key, etc.
                #   - "desktop"  → click, type, scroll, keypress, screenshot, etc.
                # Setting "mobile" tells the model it's controlling a phone, so it
                # generates mobile-appropriate actions (swipes, app launches, key events)
                # rather than browser actions (URL navigation, tabs).
                tools=[{"type": "computer_use", "environment": "mobile"}],
                previous_interaction_id=previous_interaction_id,
            )
        except Exception as api_err:
            print(f"  ❌ API Error (attempt {attempt + 1}/{max_retries}): {api_err}")
            if attempt < max_retries - 1:
                print(f"     Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                print("     All retries exhausted.")
                return None

        # ── Validate the response is non-empty ──
        # The model can intermittently return empty responses (no text,
        # no function calls). This is a transient condition we can retry.
        # A valid Computer Use response always has one or the other:
        #   - function_calls → the model wants to perform actions
        #   - text → the model is reporting task completion or status
        has_calls = bool(extract_function_calls(interaction))
        has_text = bool(extract_text_from_interaction(interaction))

        if has_calls or has_text:
            return interaction  # Valid response — use it

        # Empty response: retry
        print(f"  ⚠️  Empty model response (attempt {attempt + 1}/{max_retries})")
        print(f"     Model returned neither text nor tool calls.")
        if attempt < max_retries - 1:
            print(f"     Retrying in {delay} seconds...")
            time.sleep(delay)
        else:
            print("     All retries returned empty responses.")
            return None

    return None  # Should not reach here, but be safe


# ─── The Agent Loop ────────────────────────────────────────────────────────
# This is the core agentic loop: Observe (screenshot) → Think (model
# analyzes the screen) → Act (execute the function_call via ADB) → repeat.
# The loop terminates when the model returns text instead of function_calls,
# signaling that the task is complete (or cannot be completed).
#
# KEY ARCHITECTURAL CHOICE: Interactions API vs. generateContent
# ─────────────────────────────────────────────────────────────
# This agent uses `client.interactions.create()` (the Interactions API)
# instead of `client.models.generate_content()`. The difference:
#
#   generateContent (used in the browser agent examples):
#     - YOU manage the full conversation history as a list of Content objects.
#     - Each call sends the entire history (all prior turns) to the server.
#     - You must handle screenshot pruning yourself (stripping old base64 data)
#       to avoid sending hundreds of KB of stale images every turn.
#
#   Interactions API (used here):
#     - The SERVER manages conversation state. You only send new input each turn.
#     - Turns are chained via `previous_interaction_id` — the server reconstructs
#       the full history from its stored interaction chain.
#     - No need for local history management or screenshot pruning.
#     - Trade-off: you have less control over the history (can't edit or drop turns).
#
# For a mobile agent where conversations can be long (many taps and scrolls),
# the Interactions API is often simpler because it avoids the payload bloat
# problem that comes with carrying screenshots in the history.

def run_mobile_agent(
    task: str,
    device_id: str = None,
    max_turns: int = 50,
):
    """Run the autonomous mobile agent until the task is complete.

    This is the main agent loop. It:
      1. Takes an initial screenshot
      2. Sends the task + screenshot to the Interactions API
      3. Processes function calls by dispatching to ADBBridge
      4. Sends results + new screenshots back
      5. Repeats until the model returns text (no more function calls)

    Args:
        task: Natural language description of the task to perform.
        device_id: Optional ADB device serial to target.
        max_turns: Safety limit on the number of interaction rounds.
    """
    # ── Initialize the Gemini client ──
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY environment variable not set.")
        print("   Get an API key from https://aistudio.google.com/apikey")
        print("   Then: export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # ── Initialize the ADB bridge ──
    bridge = ADBBridge(device_id)
    print(f"📱 Device: {bridge}")
    print(f"🎯 Task: {task}")
    print("═" * 60)

    # ── Take the initial screenshot ──
    # The model needs to see the current screen state to plan its actions.
    # This is the "Observe" step of the first iteration.
    print("\n📸 Capturing initial screenshot...")
    initial_screenshot_bytes = bridge.screenshot()
    screenshot_b64 = base64.b64encode(initial_screenshot_bytes).decode("utf-8")

    # ── Build the initial input payload ──
    # The first message contains the task description and the initial screenshot.
    # Format follows the Interactions API input specification — note this uses
    # plain dicts ({"type": "text", ...}) rather than the types.Part objects
    # used by generateContent.
    current_input = [
        {"type": "text", "text": task},
        {
            "type": "image",
            "data": screenshot_b64,
            "mime_type": "image/png",
        },
    ]

    # ── State tracking via previous_interaction_id ──
    # This is the key to how the Interactions API maintains conversation state.
    # Each call to interactions.create() returns an interaction with an `.id`.
    # By passing that ID as `previous_interaction_id` in the NEXT call, we
    # create a linked chain:
    #
    #   Turn 1: previous_interaction_id=None       → interaction.id = "abc123"
    #   Turn 2: previous_interaction_id="abc123"    → interaction.id = "def456"
    #   Turn 3: previous_interaction_id="def456"    → interaction.id = "ghi789"
    #   ...and so on.
    #
    # The server uses this chain to reconstruct the full conversation history.
    # We never need to re-send old screenshots or prior turns — the server
    # already has them. This is a major simplification over generateContent.
    previous_interaction_id = None

    # ── Main agent loop ──
    for turn_number in range(1, max_turns + 1):
        print(f"\n{'─' * 60}")
        print(f"  Turn {turn_number}/{max_turns}")
        print(f"{'─' * 60}")

        # ── Call the Interactions API with retry logic ──
        # We use a helper that retries on:
        #   a) API exceptions (network errors, server errors)
        #   b) Empty model responses (no text AND no function calls)
        # The "model output must contain either output text or tool calls,
        # these cannot both be empty" error is transient and retryable.
        interaction = _call_with_retry(
            client=client,
            current_input=current_input,
            previous_interaction_id=previous_interaction_id,
            max_retries=3,
        )

        # If all retries failed, stop the agent
        if interaction is None:
            print("\n❌ Could not get a valid response. Stopping agent.")
            return

        # ── Extract results from the interaction ──
        function_calls = extract_function_calls(interaction)
        response_text = extract_text_from_interaction(interaction)

        # ── If no function calls, the model is done ──
        # When the model has completed the task (or determined it can't),
        # it responds with text instead of tool calls.
        if not function_calls:
            print(f"\n✅ Agent completed the task!")
            print(f"   Model response: {response_text}")
            return

        # ── Process each function call ──
        # The model may return multiple function calls in a single turn.
        # We execute each one sequentially, capture a screenshot after
        # each, and bundle all results into the next input.
        function_results = []

        for fc_step in function_calls:
            # In the Interactions API, each function_call step has:
            #   fc_step.name       → tool name, e.g., "click", "type"
            #   fc_step.arguments  → dict of args, e.g., {"x": 500, "y": 300}
            #   fc_step.id         → unique ID we must echo back in function_result
            # Compare with generateContent where these live in:
            #   part.function_call.name / part.function_call.args
            action_name = fc_step.name
            action_args = fc_step.arguments or {}
            call_id = fc_step.id

            # ── Handle safety decisions ──
            # The model may include a 'safety_decision' in the arguments
            # when it wants to perform a potentially sensitive action
            # (e.g., making a purchase, sending a message). In this
            # tutorial we auto-acknowledge with a warning.
            has_safety = "safety_decision" in action_args
            if has_safety:
                safety_info = action_args["safety_decision"]
                print(f"  ⚠️  SAFETY CHECK: {safety_info}")
                print(f"     Auto-acknowledging for tutorial purposes.")

            # ── Print what the model wants to do ──
            # Format arguments nicely, excluding large data
            args_display = {
                k: v for k, v in action_args.items()
                if k != "safety_decision"
            }
            print(f"  🔧 Action: {action_name}({args_display})")

            # ── Dispatch to the ADBBridge ──
            # Look up the method on the bridge by name and call it.
            handler_method = getattr(bridge, action_name, None)
            result_payload = {"status": "ok"}

            if handler_method is not None:
                try:
                    method_result = handler_method(**action_args)
                    # Some methods return a dict with extra info (e.g., list_apps)
                    if isinstance(method_result, dict):
                        result_payload.update(method_result)
                    print(f"  ✓ Result: {result_payload}")
                except Exception as action_err:
                    result_payload = {
                        "status": "error",
                        "error": str(action_err),
                    }
                    print(f"  ✗ Error: {action_err}")
            else:
                result_payload = {
                    "status": "error",
                    "error": f"Unknown action: {action_name}",
                }
                print(f"  ✗ Unknown action: {action_name}")

            # ── Add safety acknowledgement if needed ──
            if has_safety:
                result_payload["safety_acknowledgement"] = True

            # ── Capture a fresh screenshot after the action ──
            # CRITICAL PATTERN: Every function_result MUST include a fresh
            # screenshot so the model can see what changed. Without it, the
            # model is "blind" and can't plan its next move. This is the
            # "Observe" step that follows every "Act" step in the loop.
            # The brief pause lets Android animations and transitions settle.
            time.sleep(0.5)
            post_action_screenshot = bridge.screenshot()
            post_action_b64 = base64.b64encode(post_action_screenshot).decode("utf-8")

            # ── Build the function_result response ──
            # This is the format the Interactions API expects for returning
            # tool execution results. Each result includes:
            #   - type: "function_result"
            #   - name: The function that was called
            #   - call_id: Must match the function_call's step.id
            #   - result: Array of content blocks (text + screenshot)
            #
            # Note: With generateContent, the equivalent is a FunctionResponse
            # Part object: types.Part.from_function_response(name=..., response=...)
            # The Interactions API uses plain dicts instead.
            function_result = {
                "type": "function_result",
                "name": action_name,
                "call_id": call_id,    # Must echo the step.id from the function_call
                "result": [
                    {
                        "type": "text",
                        "text": json.dumps(result_payload),
                    },
                    {
                        # The screenshot is included as an inline base64 image.
                        # This is the model's "eyes" — it uses this to decide
                        # what to do next. Without it, the agent loop breaks.
                        "type": "image",
                        "data": post_action_b64,
                        "mime_type": "image/png",
                    },
                ],
            }
            function_results.append(function_result)

        # ── Prepare input for the next turn ──
        # The function results become the input for the next
        # interactions.create() call. Combined with previous_interaction_id,
        # this gives the model the full context of what happened.
        #
        # Notice how simple this is compared to generateContent:
        #   - generateContent: append function results to the full history list,
        #     then prune old screenshots to control payload size.
        #   - Interactions API: just set current_input to the new results and
        #     chain via previous_interaction_id. The server handles the rest.
        #
        # Guard: if function_results is somehow empty, stop the loop
        # to avoid sending an empty input to the API.
        if not function_results:
            print("\n⚠️  No function results to send. Stopping agent.")
            break

        current_input = function_results
        # Chain this turn to the previous one. The server uses this ID to
        # look up all prior turns, so we never need to resend old data.
        previous_interaction_id = interaction.id

    # ── Safety limit reached ──
    print(f"\n⚠️  Reached maximum turns ({max_turns}). Stopping agent.")
    print("   The task may not be fully complete.")


# ─── Entry Point ───────────────────────────────────────────────────────────

def main():
    """Parse CLI arguments and run the mobile agent.

    Usage:
      python mobile_agent.py                          # default task
      python mobile_agent.py "Open Chrome"            # custom task
      python mobile_agent.py "Open Chrome" --device emulator-5554
      python mobile_agent.py --max-turns 30 "Check battery level"
    """
    parser = argparse.ArgumentParser(
        description="Gemini Computer Use Agent for Android",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mobile_agent.py
  python mobile_agent.py "Open Settings and enable dark mode"
  python mobile_agent.py "Search for sushi restaurants in Chrome" --device emulator-5554
  python mobile_agent.py "Check battery level" --max-turns 20
        """,
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="Open Settings and check the current Android version",
        help="Task for the agent to perform (default: check Android version)",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="ADB device serial (e.g., emulator-5554). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Maximum number of interaction turns (default: 50)",
    )

    args = parser.parse_args()

    # ── Pre-flight checks ──
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Gemini Computer Use — Android Mobile Agent             ║")
    print("║  Model: gemini-3.5-flash | API: Interactions            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Step 1: Ensure Android SDK tools are on PATH
    print("Step 1 → Configuring Android SDK path...")
    android_home = configure_android_sdk_path()
    print(f"         ANDROID_HOME = {android_home}")

    # Step 2: Verify a device/emulator is connected
    print("Step 2 → Checking for connected devices...")
    detected_device = verify_device_connected()
    device_to_use = args.device or detected_device
    print(f"         Using device: {device_to_use}")

    # Step 3: Verify API key
    print("Step 3 → Verifying GEMINI_API_KEY...")
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY not set. Export it and try again.")
        sys.exit(1)
    print("         API key found ✓")

    print()

    # ── Launch the agent ──
    try:
        run_mobile_agent(
            task=args.task,
            device_id=device_to_use,
            max_turns=args.max_turns,
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Agent stopped by user (Ctrl+C).")
        sys.exit(0)
    except Exception as exc:
        print(f"\n❌ Unhandled error: {exc}")
        raise


if __name__ == "__main__":
    main()
