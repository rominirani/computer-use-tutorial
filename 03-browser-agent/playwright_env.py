"""
playwright_env.py — Reusable Playwright browser environment for Gemini Computer Use.

This module provides a context-managed wrapper around Playwright's synchronous
API.  Every method maps to a single browser interaction (click, type, scroll …)
and returns a PNG screenshot of the resulting page state.

Usage:
    with PlaywrightEnvironment(width=1280, height=800) as env:
        env.navigate("https://example.com")
        png = env.screenshot()
"""

from __future__ import annotations

import os
import time
from typing import Literal

from playwright.sync_api import sync_playwright, Page
import playwright.sync_api


# ---------------------------------------------------------------------------
# Key-name translation table
# ---------------------------------------------------------------------------
# The Gemini model emits key names in its own vocabulary — typically
# lowercase, human-readable names like "enter", "control", or "esc".
# Playwright, however, expects its own canonical key names (e.g.
# "Enter", "ControlOrMeta", "Escape"). This translation table bridges
# the gap between what the model says and what Playwright understands.
#
# Without this mapping, a model action like press_key(key="enter")
# would fail because Playwright doesn't recognise lowercase "enter".
#
# Note: "control" maps to "ControlOrMeta" — a Playwright convenience
# that automatically uses Cmd on macOS and Ctrl on other platforms,
# so keyboard shortcuts like Ctrl+C / Cmd+C work cross-platform.
PLAYWRIGHT_KEY_MAP: dict[str, str] = {
    # Modifier keys
    "control":   "ControlOrMeta",   # maps to Cmd on macOS, Ctrl elsewhere
    "ctrl":      "ControlOrMeta",
    "shift":     "Shift",
    "alt":       "Alt",
    "option":    "Alt",             # macOS alias
    "meta":      "Meta",
    "command":   "Meta",
    "cmd":       "Meta",

    # Whitespace / navigation
    "enter":     "Enter",
    "return":    "Enter",
    "tab":       "Tab",
    "space":     "Space",
    "backspace": "Backspace",
    "delete":    "Delete",
    "escape":    "Escape",
    "esc":       "Escape",

    # Arrow keys
    "left":      "ArrowLeft",
    "right":     "ArrowRight",
    "up":        "ArrowUp",
    "down":      "ArrowDown",

    # Page navigation
    "pageup":    "PageUp",
    "pagedown":  "PageDown",
    "home":      "Home",
    "end":       "End",
    "insert":    "Insert",

    # Function keys (F1-F12)
    **{f"f{n}": f"F{n}" for n in range(1, 13)},

    # Numpad operators
    "multiply":  "Multiply",
    "add":       "Add",
    "subtract":  "Subtract",
    "decimal":   "Decimal",
    "divide":    "Divide",
    "separator": "Separator",

    # Punctuation shortcuts
    "semicolon": ";",
    "equals":    "=",
}


def _resolve_key(raw: str) -> str:
    """Translate a raw key name into the Playwright-compatible name."""
    return PLAYWRIGHT_KEY_MAP.get(raw.lower(), raw)


class PlaywrightEnvironment:
    """Context-managed Playwright browser environment.

    Parameters
    ----------
    width : int
        Viewport width in pixels (default 1280).
    height : int
        Viewport height in pixels (default 800).
    headless : bool
        Run the browser without a visible window (default False).
    start_url : str
        The page loaded right after the browser starts.
    """

    def __init__(
        self,
        width: int = 1280,
        height: int = 800,
        headless: bool = False,
        start_url: str = "https://www.google.com",
    ) -> None:
        # Screen dimensions are used for coordinate denormalization by the agent
        self._width = width
        self._height = height
        self._headless = headless
        self._start_url = start_url

        # Playwright objects — initialised in __enter__
        self._pw: playwright.sync_api.Playwright | None = None
        self._browser: playwright.sync_api.Browser | None = None
        self._context: playwright.sync_api.BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Context manager — startup / teardown
    # ------------------------------------------------------------------
    def __enter__(self) -> "PlaywrightEnvironment":
        """Launch Chromium and open the start page."""
        self._pw = sync_playwright().start()

        # Launch with a minimal, sandboxed profile
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-extensions",
                "--disable-plugins",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
            ],
        )

        # Create a browser context with the exact viewport dimensions
        self._context = self._browser.new_context(
            viewport={"width": self._width, "height": self._height},
        )

        # Open a single page and navigate to the start URL
        self._page = self._context.new_page()
        self._page.goto(self._start_url)
        self._page.wait_for_load_state()

        # ── Pop-up interception ───────────────────────────────────────
        # Computer Use models can only see and interact with ONE tab at
        # a time — there's no mechanism for the model to switch between
        # tabs. If a link opens in a new tab (target="_blank"), the
        # model would lose sight of it entirely. To handle this, we
        # intercept the Playwright "page" event (fired when a new tab
        # opens), close the new tab, and navigate the current page to
        # that URL instead. This keeps everything in a single tab the
        # model can see.
        self._context.on("page", self._on_popup)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release all browser resources in reverse order."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _on_popup(self, new_page: Page) -> None:
        """Redirect new-tab navigations into the existing page.

        Grab the URL from the popup, close it, and navigate our single
        page there instead — keeping the model's view consistent.
        """
        target_url = new_page.url
        new_page.close()
        if self._page:
            self._page.goto(target_url)

    def _settle(self) -> None:
        """Wait for the page to be idle after an interaction.

        This is called after every browser action (click, type, scroll,
        etc.) for two reasons:

        1. wait_for_load_state() ensures any triggered navigation or
           network requests have completed, so we don't screenshot a
           half-loaded page.
        2. The extra 0.4s sleep lets CSS transitions, animations, and
           lazy-loaded content finish rendering. Without this, the
           screenshot might capture a mid-animation frame that confuses
           the model (e.g. a dropdown that's still sliding open).

        Getting the timing right is a balance — too short and the model
        sees stale/partial state; too long and the agent feels sluggish.
        """
        if self._page:
            self._page.wait_for_load_state()
            # Small extra pause so any visual transitions finish rendering
            time.sleep(0.4)

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------
    def screenshot(self) -> bytes:
        """Capture a viewport-only PNG screenshot and return raw bytes."""
        self._settle()
        assert self._page is not None
        return self._page.screenshot(type="png", full_page=False)

    @property
    def current_url(self) -> str:
        """Return the URL currently loaded in the browser."""
        assert self._page is not None
        return self._page.url

    # ------------------------------------------------------------------
    # Mouse actions
    # ------------------------------------------------------------------
    def click(self, x: int, y: int) -> None:
        """Left-click at pixel coordinates (x, y)."""
        assert self._page is not None
        self._page.mouse.click(x, y)
        self._settle()

    def double_click(self, x: int, y: int) -> None:
        """Double-click at pixel coordinates."""
        assert self._page is not None
        self._page.mouse.dblclick(x, y)
        self._settle()

    def triple_click(self, x: int, y: int) -> None:
        """Triple-click at pixel coordinates (selects an entire paragraph)."""
        assert self._page is not None
        self._page.mouse.click(x, y, click_count=3)
        self._settle()

    def right_click(self, x: int, y: int) -> None:
        """Right-click (context menu) at pixel coordinates."""
        assert self._page is not None
        self._page.mouse.click(x, y, button="right")
        self._settle()

    def middle_click(self, x: int, y: int) -> None:
        """Middle-click at pixel coordinates."""
        assert self._page is not None
        self._page.mouse.click(x, y, button="middle")
        self._settle()

    def move(self, x: int, y: int) -> None:
        """Move the mouse cursor to (x, y) without clicking (hover)."""
        assert self._page is not None
        self._page.mouse.move(x, y)
        self._settle()

    def mouse_down(self, x: int, y: int) -> None:
        """Press the mouse button down at (x, y) without releasing."""
        assert self._page is not None
        self._page.mouse.move(x, y)
        self._page.mouse.down()
        self._settle()

    def mouse_up(self, x: int, y: int) -> None:
        """Release the mouse button at (x, y)."""
        assert self._page is not None
        self._page.mouse.move(x, y)
        self._page.mouse.up()
        self._settle()

    def drag_and_drop(
        self, start_x: int, start_y: int, end_x: int, end_y: int
    ) -> None:
        """Drag from (start_x, start_y) to (end_x, end_y)."""
        assert self._page is not None
        self._page.mouse.move(start_x, start_y)
        self._page.mouse.down()
        time.sleep(0.15)  # brief hold before dragging
        self._page.mouse.move(end_x, end_y)
        self._page.mouse.up()
        self._settle()

    # ------------------------------------------------------------------
    # Keyboard actions
    # ------------------------------------------------------------------
    def type_text(self, text: str) -> None:
        """Type a string character-by-character (simulates real keystrokes)."""
        assert self._page is not None
        self._page.keyboard.type(text)
        self._settle()

    def press_key(self, key: str) -> None:
        """Press and release a single key (e.g. 'Enter', 'Tab')."""
        assert self._page is not None
        resolved = _resolve_key(key)
        self._page.keyboard.press(resolved)
        self._settle()

    def key_down(self, key: str) -> None:
        """Press a key down without releasing it."""
        assert self._page is not None
        self._page.keyboard.down(_resolve_key(key))
        self._settle()

    def key_up(self, key: str) -> None:
        """Release a previously held key."""
        assert self._page is not None
        self._page.keyboard.up(_resolve_key(key))
        self._settle()

    def hotkey(self, keys: list[str]) -> None:
        """Press a key combination (e.g. ['Control', 'c']).

        Holds each modifier key in order, presses the final key, then
        releases the modifiers in reverse.
        """
        assert self._page is not None
        resolved = [_resolve_key(k) for k in keys]

        # Hold down every key except the last one
        for k in resolved[:-1]:
            self._page.keyboard.down(k)

        # Press-and-release the final key
        self._page.keyboard.press(resolved[-1])

        # Release modifiers in reverse order
        for k in reversed(resolved[:-1]):
            self._page.keyboard.up(k)

        self._settle()

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------
    def scroll(
        self,
        x: int,
        y: int,
        direction: Literal["up", "down", "left", "right"],
        amount: int = 3,
    ) -> None:
        """Scroll at pixel position (x, y) in the given direction.

        Parameters
        ----------
        amount : int
            Number of "scroll ticks" — each tick is roughly 100px.

        The model specifies scroll magnitude in normalised 0-999 space
        (same as coordinates). The agent denormalises this to pixels
        and then converts to "ticks" before calling this method.

        Playwright's mouse.wheel(dx, dy) takes pixel deltas, so we
        multiply ticks × 100 to get smooth, predictable scroll
        distances. One tick ≈ one notch on a physical mouse wheel.
        """
        assert self._page is not None
        # Move the cursor to the scroll position first — Playwright
        # fires the wheel event wherever the cursor currently is.
        self._page.mouse.move(x, y)

        # Translate direction + amount into (dx, dy) pixel deltas.
        # Positive dy = scroll down, negative dy = scroll up (like a
        # real mouse wheel). Same logic applies horizontally.
        magnitude = amount * 100
        dx, dy = 0, 0
        if direction == "up":
            dy = -magnitude
        elif direction == "down":
            dy = magnitude
        elif direction == "left":
            dx = -magnitude
        elif direction == "right":
            dx = magnitude
        else:
            raise ValueError(f"Unknown scroll direction: {direction!r}")

        self._page.mouse.wheel(dx, dy)
        self._settle()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def navigate(self, url: str) -> None:
        """Navigate to an absolute URL."""
        assert self._page is not None
        # Auto-add scheme if missing
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._settle()

    def go_back(self) -> None:
        """Navigate to the previous page in the browser history."""
        assert self._page is not None
        self._page.go_back()
        self._settle()

    def go_forward(self) -> None:
        """Navigate to the next page in the browser history."""
        assert self._page is not None
        self._page.go_forward()
        self._settle()

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------
    def wait(self, seconds: float = 1.0) -> None:
        """Pause for *seconds* to allow slow pages to render."""
        assert self._page is not None
        self._page.wait_for_timeout(int(seconds * 1000))
