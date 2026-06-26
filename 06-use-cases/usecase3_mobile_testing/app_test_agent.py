#!/usr/bin/env python3
"""
=============================================================================
Use Case 3 — Mobile App Testing Agent
=============================================================================
Demonstrates how to automate Android UI testing through Gemini Computer Use
with the **Interactions API** and a mobile (ADB) environment.

Workflow
--------
1. Launch the Android Settings app on an emulator
2. Navigate to Display settings
3. Check the current dark mode status
4. Toggle dark mode on / off
5. Go back and navigate to "About Phone"
6. Read and report the Android version
7. Print a structured summary of all findings

Prerequisites
-------------
* A running Android emulator (or physical device reachable via ADB)
* ``GEMINI_API_KEY`` environment variable set
* Python packages: google-genai, rich, python-dotenv

Run
---
    python app_test_agent.py
    python app_test_agent.py --device emulator-5554   # specific device
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))  # Also check root tutorial directory

from google import genai

# ---------------------------------------------------------------------------
# Rich console for formatted terminal output
# ---------------------------------------------------------------------------
console = Console()

# ---------------------------------------------------------------------------
# ADB Bridge — lightweight wrapper around ADB for screen interaction
# ---------------------------------------------------------------------------
class ADBBridge:
    """
    Thin wrapper that translates normalised (0-999) coordinates and high-level
    actions into ``adb shell`` commands.

    Coordinate convention
    ---------------------
    Gemini Computer Use outputs coordinates normalised to 0-999.
    We denormalise them: ``pixel = normalised / 1000 * screen_dimension``
    """

    def __init__(self, device_id: Optional[str] = None):
        # Build the ADB command prefix, optionally targeting a specific device
        self._prefix = ["adb"] + (["-s", device_id] if device_id else [])

        # Query the real screen dimensions once
        self.screen_width, self.screen_height = self._query_screen_size()
        console.print(
            f"[dim]ADB connected — screen {self.screen_width}×{self.screen_height}[/dim]"
        )

    # -- internal helpers ---------------------------------------------------

    def _exec(self, args: list[str], check: bool = True) -> str:
        """Run an ADB command and return stdout."""
        result = subprocess.run(
            self._prefix + args, capture_output=True, text=True
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"ADB error: {result.stderr.strip()}")
        return result.stdout

    def _query_screen_size(self) -> tuple[int, int]:
        """Ask the device for its physical screen resolution."""
        raw = self._exec(["shell", "wm", "size"])
        match = re.search(r"(\d+)x(\d+)", raw)
        if match:
            return int(match.group(1)), int(match.group(2))
        # Sensible fallback for a typical phone emulator
        return 1080, 2400

    def _to_pixels(self, norm_x: int, norm_y: int) -> tuple[int, int]:
        """Convert 0-999 normalised coords to real pixel coords."""
        px = int(norm_x / 1000 * self.screen_width)
        py = int(norm_y / 1000 * self.screen_height)
        return px, py

    # -- public actions the model can call ----------------------------------

    def click(self, y: int, x: int, **_) -> dict:
        """Tap at normalised (x, y). Note: Interactions API sends y first."""
        px, py = self._to_pixels(x, y)
        self._exec(["shell", "input", "tap", str(px), str(py)])
        return {"status": "ok"}

    def type(self, text: str, press_enter: bool = False, **_) -> dict:
        """Type text on the device (spaces encoded as %s for ADB)."""
        escaped = text.replace(" ", "%s")
        self._exec(["shell", "input", "text", escaped])
        if press_enter:
            self._exec(["shell", "input", "keyevent", "66"])
        return {"status": "ok"}

    def open_app(self, app_name: str = None, package_name: str = None, **_) -> dict:
        """Launch an app by package name using monkey."""
        pkg = package_name or app_name
        if not pkg:
            raise ValueError("open_app requires app_name or package_name")
        stdout = self._exec(
            ["shell", "monkey", "--pct-syskeys", "0",
             "-p", pkg,
             "-c", "android.intent.category.LAUNCHER", "1"],
            check=False,
        )
        if "No activities found" in stdout or "monkey aborted" in stdout:
            raise RuntimeError(f"Cannot launch {pkg} — not installed or no launcher activity.")
        return {"status": "ok"}

    def press_key(self, key: str, **_) -> dict:
        """Press a named key (home, back, enter, etc.)."""
        keymap = {
            "home": "3", "back": "4", "enter": "66",
            "app_switch": "187", "menu": "82",
        }
        code = keymap.get(key.lower(), key)
        self._exec(["shell", "input", "keyevent", code])
        return {"status": "ok"}

    def go_back(self, **_) -> dict:
        """Press the device Back button."""
        self._exec(["shell", "input", "keyevent", "4"])
        return {"status": "ok"}

    def scroll(self, direction: str = "down", **_) -> dict:
        """Swipe to scroll. direction: up | down."""
        cx = self.screen_width // 2
        if direction == "down":
            self._exec(["shell", "input", "swipe",
                         str(cx), str(self.screen_height * 3 // 4),
                         str(cx), str(self.screen_height // 4), "300"])
        else:
            self._exec(["shell", "input", "swipe",
                         str(cx), str(self.screen_height // 4),
                         str(cx), str(self.screen_height * 3 // 4), "300"])
        return {"status": "ok"}

    def long_press(self, y: int, x: int, seconds: int = 2, **_) -> dict:
        """Long-press at normalised coords."""
        px, py = self._to_pixels(x, y)
        self._exec(["shell", "input", "swipe",
                     str(px), str(py), str(px), str(py), str(seconds * 1000)])
        return {"status": "ok"}

    def drag_and_drop(self, start_y: int, start_x: int,
                      end_y: int, end_x: int, **_) -> dict:
        """Swipe/drag from one normalised point to another."""
        sx, sy = self._to_pixels(start_x, start_y)
        ex, ey = self._to_pixels(end_x, end_y)
        self._exec(["shell", "input", "swipe",
                     str(sx), str(sy), str(ex), str(ey), "300"])
        return {"status": "ok"}

    def wait(self, seconds: int = 1, **_) -> dict:
        """Pause execution for a number of seconds."""
        time.sleep(seconds)
        return {"status": "ok"}

    def take_screenshot(self, **_) -> dict:
        """No-op — screenshot is always captured separately."""
        return {"status": "ok"}

    def list_apps(self, **_) -> dict:
        """List third-party packages on the device."""
        raw = self._exec(["shell", "pm", "list", "packages", "-3"])
        pkgs = [
            line.split(":")[1]
            for line in raw.splitlines()
            if line.startswith("package:")
        ]
        return {"apps": pkgs or ["(none)"]}

    # -- screenshot (binary) ------------------------------------------------

    def capture_screen(self) -> bytes:
        """Capture a PNG screenshot via ``adb exec-out screencap -p``."""
        result = subprocess.run(
            self._prefix + ["exec-out", "screencap", "-p"],
            capture_output=True,
        )
        return result.stdout


# ---------------------------------------------------------------------------
# System prompt — tells the model what it is doing
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = """\
You are an automated QA agent testing an Android device.

Your current test plan:
1. Open the Android Settings app (package: com.android.settings).
2. Navigate to "Display" settings.
3. Check whether Dark theme / Dark mode is currently ON or OFF.
4. Toggle Dark mode (turn it ON if it is OFF, or OFF if it is ON).
5. Press Back to return to the main Settings screen.
6. Navigate to "About phone" (scroll down if needed).
7. Read the Android version string shown on that page.
8. Report a test summary with: dark mode before, dark mode after, Android version.

Rules:
* Use the tools provided.  Scroll down before assuming an item is missing.
* When the task is complete, output a **Test Summary** with all findings.
* Do NOT use the on-screen keyboard — use the `type` tool instead.
"""

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
def run_mobile_test_agent(
    device_id: Optional[str] = None,
    max_turns: int = 40,
) -> dict:
    """
    Drive the Gemini model through an Android Settings test flow using the
    **Interactions API** with ``environment = "mobile"``.

    Returns a dict with the final findings.
    """

    # -- Step 0: Initialise --------------------------------------------------
    console.print(Panel(
        "[bold cyan]Use Case 3 — Mobile App Testing Agent[/bold cyan]\n"
        "Testing Android Settings: Dark Mode toggle + About Phone",
        box=box.DOUBLE,
    ))
    console.print(f"[dim]Timestamp: {datetime.now().isoformat()}[/dim]\n")

    # Verify API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]ERROR:[/bold red] GEMINI_API_KEY not set.")
        sys.exit(1)

    # Create SDK client
    client = genai.Client(api_key=api_key)
    console.print("[green]✓[/green] Gemini client initialised\n")

    # Connect to the device
    console.print("[bold]Step 0 →[/bold] Connecting to Android device via ADB …")
    bridge = ADBBridge(device_id)
    console.print("[green]✓[/green] ADB bridge ready\n")

    # -- Step 1: Initial screenshot ------------------------------------------
    console.print("[bold]Step 1 →[/bold] Capturing initial screenshot …")
    screenshot_bytes = bridge.capture_screen()
    console.print(
        f"  Screenshot captured: {len(screenshot_bytes):,} bytes\n"
    )

    # Build the first user input for the Interactions API
    user_input = [
        {"type": "text", "text": "Begin the test plan now."},
        {
            "type": "image",
            "data": base64.b64encode(screenshot_bytes).decode(),
            "mime_type": "image/png",
        },
    ]

    # -- Agent turn loop -----------------------------------------------------
    previous_interaction_id = None
    turn = 0
    final_text = ""

    while turn < max_turns:
        turn += 1
        console.rule(f"[bold yellow]Turn {turn}[/bold yellow]")

        # ---- Call the Interactions API ----
        try:
            interaction = client.interactions.create(
                model="gemini-3.5-flash",
                system_instruction=SYSTEM_INSTRUCTION,
                input=user_input,
                tools=[{"type": "computer_use", "environment": "mobile"}],
                previous_interaction_id=previous_interaction_id,
            )
        except Exception as exc:
            console.print(f"[bold red]API error:[/bold red] {exc}")
            break

        # ---- Check for function calls ----
        has_actions = any(
            step.type == "function_call" for step in interaction.steps
        )

        # If no function calls → model has finished
        if not has_actions:
            text_parts = []
            for step in interaction.steps:
                if step.type == "model_output":
                    for block in step.content:
                        if block.type == "text":
                            text_parts.append(block.text)
            final_text = " ".join(text_parts)
            console.print(Panel(
                final_text,
                title="[bold green]Agent Final Report[/bold green]",
                box=box.ROUNDED,
            ))
            break

        # ---- Execute each function call ----
        function_responses = []
        for step in interaction.steps:
            if step.type != "function_call":
                continue

            fn_name = step.name
            fn_args = step.arguments

            # Pretty-print what the model wants to do
            args_str = ", ".join(f"{k}={v!r}" for k, v in fn_args.items())
            console.print(
                f"  [cyan]▶ {fn_name}[/cyan]({args_str})"
            )

            # Dispatch to the ADB bridge
            handler = getattr(bridge, fn_name, None)
            result_payload = {"status": "ok"}

            if handler:
                try:
                    res = handler(**fn_args)
                    if isinstance(res, dict):
                        result_payload.update(res)
                except Exception as exc:
                    result_payload = {"status": "error", "error": str(exc)}
                    console.print(f"    [red]✗ {exc}[/red]")
            else:
                result_payload = {
                    "status": "error",
                    "error": f"Unknown action: {fn_name}",
                }
                console.print(f"    [red]✗ Unknown action: {fn_name}[/red]")

            console.print(f"    [dim]→ {result_payload}[/dim]")

            # Auto-acknowledge safety prompts if present
            if "safety_decision" in fn_args:
                result_payload["safety_acknowledgement"] = True

            # Capture a fresh screenshot after every action
            time.sleep(0.5)
            screenshot_bytes = bridge.capture_screen()

            # Build the function result payload (text + screenshot)
            function_responses.append({
                "type": "function_result",
                "name": fn_name,
                "call_id": step.id,
                "result": [
                    {"type": "text", "text": json.dumps(result_payload)},
                    {
                        "type": "image",
                        "data": base64.b64encode(screenshot_bytes).decode(),
                        "mime_type": "image/png",
                    },
                ],
            })

        # Feed the results back as the next user input
        user_input = function_responses
        previous_interaction_id = interaction.id

        if not function_responses:
            console.print("[yellow]No actions executed — stopping.[/yellow]")
            break

    # -- Summary table -------------------------------------------------------
    console.print()
    summary_table = Table(
        title="Test Execution Summary",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value")
    summary_table.add_row("Total turns", str(turn))
    summary_table.add_row("Device", device_id or "(default)")
    summary_table.add_row("Model", "gemini-3.5-flash")
    summary_table.add_row("API", "Interactions API (mobile)")
    console.print(summary_table)

    return {"turns": turn, "report": final_text}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Mobile App Testing Agent — Gemini Computer Use"
    )
    parser.add_argument(
        "--device", "-d",
        default=None,
        help="ADB device serial (e.g. emulator-5554). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--max-turns", "-t",
        type=int, default=40,
        help="Maximum agent turns before stopping (default 40).",
    )
    args = parser.parse_args()

    results = run_mobile_test_agent(
        device_id=args.device,
        max_turns=args.max_turns,
    )

    console.print("\n[bold green]✓ Test complete.[/bold green]")
