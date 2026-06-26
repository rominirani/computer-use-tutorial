"""
adb_bridge.py — ADB Abstraction Layer for Gemini Computer Use
=============================================================

This module provides the ADBBridge class, which translates high-level
actions from the Gemini Computer Use model into low-level ADB (Android
Debug Bridge) commands.

Key Concepts:
  - The model outputs coordinates in a **normalized 0–999 range**.
  - This bridge converts them to actual pixel coordinates using the
    formula: pixel = normalized / 1000 * screen_dimension
  - Every public method corresponds to a tool the model can invoke.
  - The screenshot() method captures the screen as PNG bytes for sending
    back to the model in the agent loop.

Architecture:
  ┌──────────────┐     tool calls      ┌──────────────┐
  │  Gemini API  │ ──────────────────► │  ADBBridge   │
  │  (model)     │                     │  (this file) │
  └──────────────┘                     └──────┬───────┘
                                              │ ADB commands
                                              ▼
                                       ┌──────────────┐
                                       │   Android    │
                                       │   Device /   │
                                       │   Emulator   │
                                       └──────────────┘
"""

import re
import subprocess
import time
from typing import Optional


class ADBBridge:
    """Translates Gemini Computer Use actions into ADB commands.

    Each public method maps to a tool the model can call. Methods accept
    keyword arguments so the agent can forward the model's arguments
    directly (with **kwargs tolerance for unknown extras).

    NOTE ON **_ IN METHOD SIGNATURES:
    Every tool method (click, type, drag_and_drop, etc.) includes `**_`
    as a catch-all for unexpected keyword arguments. This is important
    because the model may include extra fields in its function_call
    arguments (e.g., `safety_decision`, `intent`, or future fields we
    don't know about yet). Without **_, calling `handler(**action_args)`
    in the agent loop would raise TypeError for any unknown key. The
    underscore name `_` signals "we intentionally discard these".
    """

    # ─── Android Keyevent Code Mapping ─────────────────────────────────
    # Maps human-readable key names to Android KEYCODE_* integer codes.
    # Full list: https://developer.android.com/reference/android/view/KeyEvent
    KEY_MAP = {
        "home": 3,          # KEYCODE_HOME
        "back": 4,          # KEYCODE_BACK
        "call": 5,          # KEYCODE_CALL
        "end_call": 6,      # KEYCODE_ENDCALL
        "volume_up": 24,    # KEYCODE_VOLUME_UP
        "volume_down": 25,  # KEYCODE_VOLUME_DOWN
        "power": 26,        # KEYCODE_POWER
        "camera": 27,       # KEYCODE_CAMERA
        "tab": 61,          # KEYCODE_TAB
        "space": 62,        # KEYCODE_SPACE
        "enter": 66,        # KEYCODE_ENTER
        "delete": 67,       # KEYCODE_DEL (backspace)
        "menu": 82,         # KEYCODE_MENU
        "search": 84,       # KEYCODE_SEARCH
        "escape": 111,      # KEYCODE_ESCAPE
        "forward_del": 112, # KEYCODE_FORWARD_DEL
        "app_switch": 187,  # KEYCODE_APP_SWITCH (recent apps)
    }

    def __init__(self, device_id: Optional[str] = None):
        """Initialize the ADB bridge.

        Args:
            device_id: Optional ADB device serial (e.g. 'emulator-5554').
                       If None, ADB uses the only connected device.
                       Use `adb devices` to find available serials.
        """
        # Build the base ADB command prefix. When a device_id is given,
        # we add '-s <serial>' so commands target that specific device.
        self._cmd_prefix = ["adb"]
        if device_id:
            self._cmd_prefix += ["-s", device_id]

        # Query the device for its screen resolution on init.
        # This is ESSENTIAL because the Gemini model outputs all coordinates
        # in a normalized 0–999 grid, regardless of the actual screen size.
        # We need the real pixel dimensions to convert (denormalize) those
        # coordinates before sending them to ADB touch commands.
        self._screen_width, self._screen_height = self._query_screen_dimensions()

    # ─── Internal Helpers ──────────────────────────────────────────────

    def _execute(self, args: list[str], binary: bool = False) -> str | bytes:
        """Run an ADB command and return the output.

        Args:
            args: Command arguments to append after the ADB prefix.
                  Example: ['shell', 'input', 'tap', '540', '960']
            binary: If True, return raw stdout bytes (for screenshots).

        Returns:
            stdout as a string (or bytes if binary=True).

        Raises:
            RuntimeError: If the ADB command exits with a non-zero code.
        """
        full_cmd = self._cmd_prefix + args
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            # Don't decode if we need raw bytes (e.g., PNG screenshot)
            text=(not binary),
        )
        if result.returncode != 0:
            stderr = result.stderr if binary else result.stderr.strip()
            raise RuntimeError(
                f"ADB command failed: {' '.join(full_cmd)}\n"
                f"Exit code: {result.returncode}\n"
                f"Stderr: {stderr}"
            )
        return result.stdout

    def _query_screen_dimensions(self) -> tuple[int, int]:
        """Get the physical screen resolution from the device.

        Parses the output of 'adb shell wm size', which looks like:
            Physical size: 1080x2400

        Returns:
            (width, height) in pixels. Defaults to (1080, 1920) if
            parsing fails (common emulator resolution).
        """
        # Why we use `adb shell wm size`:
        # Android devices come in wildly different resolutions (720x1280,
        # 1080x2400, 1440x3200, etc.). The model's normalized coordinates
        # (0–999) need to map to the correct pixel range. For example,
        # normalized x=500 should map to pixel 540 on a 1080-wide screen,
        # but pixel 720 on a 1440-wide screen. `wm size` gives us the
        # physical resolution that the display is actually rendering at.
        try:
            output = self._execute(["shell", "wm", "size"])
            # Match the "Physical size: WxH" line (ignoring override lines)
            match = re.search(r"Physical size:\s*(\d+)x(\d+)", output)
            if match:
                width = int(match.group(1))
                height = int(match.group(2))
                return (width, height)
        except (RuntimeError, AttributeError):
            pass

        # Fallback for common Android emulator resolution
        return (1080, 1920)

    def _denormalize(self, norm_x: int, norm_y: int) -> tuple[int, int]:
        """Convert normalized coordinates (0–999) to actual pixel coordinates.

        The Gemini Computer Use model outputs all coordinates in a
        normalized 0–999 range. We scale them to the device's actual
        resolution with:
            pixel_x = norm_x / 1000 * screen_width
            pixel_y = norm_y / 1000 * screen_height

        Args:
            norm_x: Normalized x-coordinate (0–999).
            norm_y: Normalized y-coordinate (0–999).

        Returns:
            (pixel_x, pixel_y) in actual screen coordinates.
        """
        # NORMALIZED COORDINATES — the core coordinate concept in Computer Use:
        #
        # The model always outputs coordinates in a virtual 0–999 grid,
        # regardless of the actual screen resolution. This means:
        #   - (0, 0)     = top-left corner of the screen
        #   - (999, 999) = bottom-right corner of the screen
        #   - (500, 500) = approximately the center
        #
        # We divide by 1000 (not 999) to get a 0.0–0.999 fraction, then
        # multiply by the actual screen dimension. Examples on a 1080x2400 screen:
        #   norm_x=500 → int(500/1000 * 1080) = 540 pixels
        #   norm_y=250 → int(250/1000 * 2400) = 600 pixels
        #
        # This same formula applies to browser and desktop agents too —
        # it's a universal Computer Use concept, not mobile-specific.
        pixel_x = int(norm_x / 1000 * self._screen_width)
        pixel_y = int(norm_y / 1000 * self._screen_height)
        return (pixel_x, pixel_y)

    # ─── Tool Methods (called by the model) ────────────────────────────
    # Each method accepts **_ to silently ignore unexpected keyword args
    # that the model might include in its function calls. See the class
    # docstring above for why this pattern is essential.

    def click(self, y: int, x: int, **_) -> None:
        """Tap the screen at the given normalized coordinates.

        Note: The model sends coordinates in (y, x) order — this matches
        the Computer Use API convention where y comes first.

        Args:
            y: Normalized y-coordinate (0–999, top to bottom).
            x: Normalized x-coordinate (0–999, left to right).
        """
        px, py = self._denormalize(x, y)
        # `adb shell input tap <x> <y>` simulates a finger tap at the given
        # pixel coordinates. Under the hood, ADB injects a MotionEvent
        # (ACTION_DOWN + ACTION_UP) into the Android input system. The
        # coordinates here are in actual pixels (after denormalization),
        # not the model's normalized 0–999 values.
        self._execute(["shell", "input", "tap", str(px), str(py)])

    def type(self, text: str, press_enter: bool = False, **_) -> None:
        """Type text into the currently focused input field.

        ADB's `input text` command requires spaces to be encoded as '%s'.
        This method handles that conversion automatically.

        Args:
            text: The string to type.
            press_enter: If True, send KEYCODE_ENTER after typing.
        """
        # ADB interprets '%s' as a space character in input text
        sanitized = text.replace(" ", "%s")
        self._execute(["shell", "input", "text", sanitized])

        if press_enter:
            # KEYCODE_ENTER = 66
            self._execute(["shell", "input", "keyevent", "66"])

    def long_press(self, y: int, x: int, seconds: float = 2.0, **_) -> None:
        """Perform a long press at the given normalized coordinates.

        Implemented as a zero-distance swipe (same start and end point)
        with a duration, which ADB interprets as a long press.

        Args:
            y: Normalized y-coordinate (0–999).
            x: Normalized x-coordinate (0–999).
            seconds: How long to hold the press (default: 2 seconds).
        """
        px, py = self._denormalize(x, y)
        duration_ms = str(int(seconds * 1000))
        # A swipe from (px,py) to (px,py) over N ms = long press
        self._execute([
            "shell", "input", "swipe",
            str(px), str(py), str(px), str(py), duration_ms
        ])

    def drag_and_drop(
        self,
        start_y: int,
        start_x: int,
        end_y: int,
        end_x: int,
        **_,
    ) -> None:
        """Swipe (drag) from one point to another on screen.

        This is used for scrolling, dragging items, and swipe gestures.
        The swipe duration is fixed at 300ms for a natural feel.

        Args:
            start_y: Normalized start y-coordinate (0–999).
            start_x: Normalized start x-coordinate (0–999).
            end_y: Normalized end y-coordinate (0–999).
            end_x: Normalized end x-coordinate (0–999).
        """
        sx, sy = self._denormalize(start_x, start_y)
        ex, ey = self._denormalize(end_x, end_y)
        # `adb shell input swipe <x1> <y1> <x2> <y2> <duration_ms>`
        # simulates a finger drag from (x1,y1) to (x2,y2) over the
        # specified duration. ADB injects a MotionEvent sequence:
        # ACTION_DOWN at start → ACTION_MOVE interpolated → ACTION_UP at end.
        #
        # The model uses this for scrolling (e.g., swipe from bottom to top
        # to scroll down), dismissing notifications, and dragging UI elements.
        # Duration of 300ms gives a smooth, natural swipe — too fast and
        # Android may interpret it as a fling; too slow and it becomes a
        # long-press-and-drag.
        self._execute([
            "shell", "input", "swipe",
            str(sx), str(sy), str(ex), str(ey), "300"
        ])

    def press_key(self, key: str, **_) -> None:
        """Press a named key or send an Android keyevent code.

        Looks up the key name in KEY_MAP. If the key isn't recognized,
        it tries to use the raw value as a keyevent code string.

        Args:
            key: Key name ('home', 'back', 'enter', etc.) or numeric
                 keyevent code as a string.
        """
        keycode = self.KEY_MAP.get(key.lower(), key)
        self._execute(["shell", "input", "keyevent", str(keycode)])

    def go_back(self, **_) -> None:
        """Press the Android Back button (KEYCODE_BACK = 4)."""
        self._execute(["shell", "input", "keyevent", "4"])

    def go_home(self, **_) -> None:
        """Press the Android Home button (KEYCODE_HOME = 3)."""
        self._execute(["shell", "input", "keyevent", "3"])

    def open_app(
        self,
        app_name: Optional[str] = None,
        package_name: Optional[str] = None,
        **_,
    ) -> None:
        """Launch an app by its package name.

        Uses the `monkey` command with a LAUNCHER intent category to
        simulate tapping the app icon.

        Args:
            app_name: Alternative parameter name for the package
                      (the model sometimes uses 'app_name').
            package_name: Android package name, e.g. 'com.android.settings'.

        Raises:
            ValueError: If neither app_name nor package_name is provided.
            RuntimeError: If the app is not installed or has no launcher.
        """
        pkg = package_name or app_name
        if not pkg:
            raise ValueError(
                "open_app requires either 'package_name' or 'app_name'"
            )

        # monkey -p <package> -c LAUNCHER 1 → launch the app's main activity
        try:
            output = self._execute([
                "shell", "monkey",
                "--pct-syskeys", "0",
                "-p", pkg,
                "-c", "android.intent.category.LAUNCHER",
                "1",
            ])
        except RuntimeError:
            raise RuntimeError(f"Failed to launch app: {pkg}")

        # Check for common failure messages in monkey output
        if "No activities found" in output or "monkey aborted" in output:
            raise RuntimeError(
                f"App '{pkg}' is not installed or has no launcher activity."
            )

    def list_apps(self, **_) -> dict:
        """List all installed third-party (non-system) apps.

        Returns:
            Dict with an 'apps' key containing either a list of package
            names or a message if none are installed.
        """
        output = self._execute(["shell", "pm", "list", "packages", "-3"])

        # Each line looks like: "package:com.example.myapp"
        packages = []
        for line in output.strip().splitlines():
            if line.startswith("package:"):
                packages.append(line.split(":", 1)[1])

        if packages:
            return {"apps": packages}
        return {"apps": "No third-party apps installed on this device."}

    def wait(self, seconds: float = 1.0, **_) -> None:
        """Pause execution for the specified number of seconds.

        Used when the model wants to wait for an animation, page load,
        or transition to complete before taking the next action.

        Args:
            seconds: Duration to wait (default: 1 second).
        """
        time.sleep(float(seconds))

    def take_screenshot(self, **_) -> None:
        """No-op handler for the model's take_screenshot tool call.

        The agent loop always captures a screenshot after every action,
        so this method doesn't need to do anything extra. It exists
        so the model's function call can be dispatched without error.
        """
        return None

    def screenshot(self) -> bytes:
        """Capture the device screen as PNG image bytes.

        Uses `adb exec-out screencap -p` which streams raw PNG data
        directly to stdout — faster than writing to the device filesystem
        and pulling the file.

        Returns:
            Raw PNG image bytes.
        """
        # Why `exec-out screencap -p` instead of `shell screencap /sdcard/screen.png`:
        #
        # The naive approach would be:
        #   1. `adb shell screencap -p /sdcard/screenshot.png`  (save on device)
        #   2. `adb pull /sdcard/screenshot.png`                (download to host)
        #   3. Read the file locally
        #   4. `adb shell rm /sdcard/screenshot.png`            (clean up)
        #
        # `exec-out` is a single-step alternative: it runs `screencap -p`
        # on the device and streams the raw PNG bytes directly to stdout
        # over the ADB connection. No temp file, no pull, no cleanup.
        # The `-p` flag tells screencap to output PNG format (vs raw pixels).
        # We read the bytes with binary=True since this is image data,
        # not text. The agent loop then base64-encodes these bytes to
        # include in the function_result sent back to the model.
        return self._execute(["exec-out", "screencap", "-p"], binary=True)

    # ─── Utility Properties ────────────────────────────────────────────

    @property
    def screen_size(self) -> tuple[int, int]:
        """Return the device's screen resolution as (width, height)."""
        return (self._screen_width, self._screen_height)

    def __repr__(self) -> str:
        return (
            f"ADBBridge(device={self._cmd_prefix}, "
            f"screen={self._screen_width}x{self._screen_height})"
        )
