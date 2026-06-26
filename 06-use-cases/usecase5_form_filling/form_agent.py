#!/usr/bin/env python3
"""
=============================================================================
Use Case 5 — Automated Form Filling Agent
=============================================================================
Demonstrates how Gemini Computer Use can handle diverse HTML form controls:
text inputs, radio buttons, checkboxes, dropdowns, and text areas.

Target form: https://demoqa.com/automation-practice-form

Workflow
--------
1. Navigate to the practice form page
2. Fill in text fields (First Name, Last Name, Email, Mobile)
3. Select a Gender radio button (Female)
4. Enter a Subject (Computer Science)
5. Check a Hobby checkbox (Reading)
6. Fill in Current Address (text area)
7. Submit the form
8. Verify the confirmation modal appears
9. Report what was filled and the result

Uses the **generateContent API** with browser environment.

Prerequisites
-------------
* ``GEMINI_API_KEY`` environment variable
* Python packages: google-genai, playwright, rich, python-dotenv
* Playwright browsers: ``python -m playwright install chromium``

Run
---
    python form_agent.py
    python form_agent.py --headless
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import os
import sys
import time
from datetime import datetime

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
from google.genai import types
from google.genai.types import (
    Content,
    Part,
    GenerateContentConfig,
    FunctionResponse,
    FinishReason,
)
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_NAME = "gemini-3.5-flash"
FORM_URL = "https://demoqa.com/automation-practice-form"
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900

console = Console()

# ---------------------------------------------------------------------------
# Sample data to fill into the form
# ---------------------------------------------------------------------------
FORM_DATA = {
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane.smith@example.com",
    "gender": "Female",
    "mobile": "1234567890",
    "subjects": "Computer Science",
    "hobbies": "Reading",
    "address": "123 AI Street, Tech City",
}

# ---------------------------------------------------------------------------
# Playwright key mapping (same as reference but defined locally)
# ---------------------------------------------------------------------------
PW_KEY_MAP = {
    "backspace": "Backspace", "tab": "Tab", "enter": "Enter",
    "return": "Enter", "shift": "Shift", "control": "ControlOrMeta",
    "alt": "Alt", "escape": "Escape", "space": "Space",
    "pageup": "PageUp", "pagedown": "PageDown", "end": "End",
    "home": "Home", "left": "ArrowLeft", "up": "ArrowUp",
    "right": "ArrowRight", "down": "ArrowDown", "insert": "Insert",
    "delete": "Delete", "command": "Meta",
}


# ---------------------------------------------------------------------------
# Lightweight browser wrapper
# ---------------------------------------------------------------------------
class FormBrowser:
    """
    Playwright-based browser tailored for form-filling.
    Every action returns ``(png_bytes, current_url)`` for the screenshot loop.
    """

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def launch(self):
        console.print("[bold]Step 1 →[/bold] Launching Chromium browser …")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-extensions",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = self._browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        self._page = ctx.new_page()
        # Redirect popups into the same tab
        ctx.on("page", lambda p: (p.close(), self._page.goto(p.url)))
        console.print("[green]✓[/green] Browser ready\n")

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # -- coordinate helpers -------------------------------------------------

    def _dx(self, x: int) -> int:
        """Denormalise x from 0-999 to pixel coordinate."""
        return int(x / 1000 * VIEWPORT_WIDTH)

    def _dy(self, y: int) -> int:
        """Denormalise y from 0-999 to pixel coordinate."""
        return int(y / 1000 * VIEWPORT_HEIGHT)

    def _snap(self) -> tuple[bytes, str]:
        """Wait for stability and capture a PNG screenshot."""
        self._page.wait_for_load_state()
        time.sleep(0.4)
        png = self._page.screenshot(type="png", full_page=False)
        return png, self._page.url

    # -- actions the model can invoke ---------------------------------------

    def navigate(self, url: str) -> tuple[bytes, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url, timeout=60000, wait_until="domcontentloaded")
        self._page.wait_for_load_state("domcontentloaded")
        return self._snap()

    def click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y))
        self._page.wait_for_load_state()
        return self._snap()

    def double_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.dblclick(self._dx(x), self._dy(y))
        self._page.wait_for_load_state()
        return self._snap()

    def triple_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y), click_count=3)
        self._page.wait_for_load_state()
        return self._snap()

    def middle_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y), button="middle")
        self._page.wait_for_load_state()
        return self._snap()

    def right_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y), button="right")
        self._page.wait_for_load_state()
        return self._snap()

    def mouse_down(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.move(self._dx(x), self._dy(y))
        self._page.mouse.down()
        return self._snap()

    def mouse_up(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.move(self._dx(x), self._dy(y))
        self._page.mouse.up()
        return self._snap()

    def move(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.move(self._dx(x), self._dy(y))
        return self._snap()

    def type_text(self, text: str, press_enter: bool = False) -> tuple[bytes, str]:
        self._page.keyboard.type(text)
        if press_enter:
            self._page.keyboard.press("Enter")
        self._page.wait_for_load_state()
        return self._snap()

    def scroll(self, x: int, y: int, direction: str,
               magnitude: int = 800) -> tuple[bytes, str]:
        px, py = self._dx(x), self._dy(y)
        self._page.mouse.move(px, py)
        dx = dy = 0
        if direction == "down":
            dy = self._dy(magnitude)
        elif direction == "up":
            dy = -self._dy(magnitude)
        elif direction == "right":
            dx = self._dx(magnitude)
        elif direction == "left":
            dx = -self._dx(magnitude)
        self._page.mouse.wheel(dx, dy)
        self._page.wait_for_load_state()
        return self._snap()

    def press_key(self, key: str) -> tuple[bytes, str]:
        mapped = PW_KEY_MAP.get(key.lower(), key)
        self._page.keyboard.press(mapped)
        self._page.wait_for_load_state()
        return self._snap()

    def key_down(self, key: str) -> tuple[bytes, str]:
        mapped = PW_KEY_MAP.get(key.lower(), key)
        self._page.keyboard.down(mapped)
        return self._snap()

    def key_up(self, key: str) -> tuple[bytes, str]:
        mapped = PW_KEY_MAP.get(key.lower(), key)
        self._page.keyboard.up(mapped)
        return self._snap()

    def hotkey(self, keys: list[str]) -> tuple[bytes, str]:
        mapped = [PW_KEY_MAP.get(k.lower(), k) for k in keys]
        for k in mapped[:-1]:
            self._page.keyboard.down(k)
        self._page.keyboard.press(mapped[-1])
        for k in reversed(mapped[:-1]):
            self._page.keyboard.up(k)
        self._page.wait_for_load_state()
        return self._snap()

    def go_back(self) -> tuple[bytes, str]:
        self._page.go_back()
        self._page.wait_for_load_state()
        return self._snap()

    def go_forward(self) -> tuple[bytes, str]:
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self._snap()

    def wait_action(self, seconds: int = 1) -> tuple[bytes, str]:
        self._page.wait_for_timeout(seconds * 1000)
        return self._snap()

    def take_screenshot(self) -> tuple[bytes, str]:
        return self._snap()

    def drag_and_drop(self, x: int, y: int,
                      dest_x: int, dest_y: int) -> tuple[bytes, str]:
        sx, sy = self._dx(x), self._dy(y)
        ex, ey = self._dx(dest_x), self._dy(dest_y)
        self._page.mouse.move(sx, sy)
        self._page.mouse.down()
        self._page.mouse.move(ex, ey)
        self._page.mouse.up()
        return self._snap()


# ---------------------------------------------------------------------------
# Map model action names → browser methods  (ACTION_DISPATCH table)
# ---------------------------------------------------------------------------
# This is a DATA-DRIVEN alternative to the long if/elif chains used in
# the other use cases.  Each entry maps a Computer Use action name to a
# lambda that calls the corresponding browser method with the right args.
#
# Advantages of the dispatch-table pattern:
#   • Adding a new action = adding one dict entry (no code branching)
#   • The dispatcher loop (below) is just 3 lines: look up → call → done
#   • Easy to see at a glance which actions are supported
#
# Every lambda takes (browser, args_dict) and returns (png_bytes, url).
# The args dict comes directly from the model's function_call.args.
#
# Note: coordinates in args are in normalised 0-999 space.  The browser
# methods (_dx/_dy) handle denormalisation internally.
ACTION_DISPATCH = {
    "click":           lambda b, a: b.click(a["x"], a["y"]),
    "double_click":    lambda b, a: b.double_click(a["x"], a["y"]),
    "triple_click":    lambda b, a: b.triple_click(a["x"], a["y"]),
    "middle_click":    lambda b, a: b.middle_click(a["x"], a["y"]),
    "right_click":     lambda b, a: b.right_click(a["x"], a["y"]),
    "mouse_down":      lambda b, a: b.mouse_down(a["x"], a["y"]),
    "mouse_up":        lambda b, a: b.mouse_up(a["x"], a["y"]),
    "move":            lambda b, a: b.move(a["x"], a["y"]),
    # type() handles both regular text fields AND textarea controls —
    # the model just clicks the field and types; it doesn't need to
    # know the underlying HTML element type.
    "type":            lambda b, a: b.type_text(a["text"], a.get("press_enter", False)),
    "scroll":          lambda b, a: b.scroll(a["x"], a["y"], a["direction"],
                                              a.get("magnitude", 800)),
    "navigate":        lambda b, a: b.navigate(a["url"]),
    "go_back":         lambda b, a: b.go_back(),
    "go_forward":      lambda b, a: b.go_forward(),
    "press_key":       lambda b, a: b.press_key(a["key"]),
    "key_down":        lambda b, a: b.key_down(a["key"]),
    "key_up":          lambda b, a: b.key_up(a["key"]),
    "hotkey":          lambda b, a: b.hotkey(a["keys"]),
    "wait":            lambda b, a: b.wait_action(int(a.get("seconds", 1))),
    "take_screenshot": lambda b, a: b.take_screenshot(),
    "drag_and_drop":   lambda b, a: b.drag_and_drop(
                           a["x"], a["y"], a["destination_x"], a["destination_y"]),
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
def run_form_agent(headless: bool = False, max_turns: int = 50) -> dict:
    """
    Drive the form-filling agent using the **generateContent** API.

    Returns a dict summarising what was filled.

    ── Architecture overview ──────────────────────────────────────────
    API:         generateContent (full conversation history managed
                 client-side in `contents` list)
    Environment: ENVIRONMENT_BROWSER (headless Chromium via Playwright)
    Tools:       Computer Use ONLY — no custom function_declarations

    What makes this use case special:
      • Pure visual form interaction — the model handles ALL HTML input
        types (text fields, radio buttons, checkboxes, autocomplete
        dropdowns, textareas) using only click() and type() actions.
        It doesn't use DOM selectors or JavaScript — it "sees" the form
        in the screenshot and interacts like a human would.

      • Radio buttons:    model clicks the visible label text/circle
      • Checkboxes:       model clicks the checkbox element
      • Autocomplete:     model types text, then clicks a dropdown item
                          or presses Enter to confirm
      • Textarea:         model clicks inside the textarea and types —
                          same type() action as regular input fields
      • Scrolling:        model scrolls down to reach below-the-fold
                          fields and the Submit button

      • ACTION_DISPATCH table pattern replaces the verbose if/elif
        chains used in other use cases, making the dispatcher loop
        just 3 lines.
    ──────────────────────────────────────────────────────────────────
    """

    # -- Banner ------------------------------------------------------------
    console.print(Panel(
        "[bold cyan]Use Case 5 — Automated Form Filling Agent[/bold cyan]\n"
        f"Target: {FORM_URL}",
        box=box.DOUBLE,
    ))
    console.print(f"[dim]Timestamp: {datetime.now().isoformat()}[/dim]\n")

    # -- Print the data we will fill ----------------------------------------
    data_table = Table(title="Form Data to Fill", box=box.SIMPLE, show_lines=True)
    data_table.add_column("Field", style="bold")
    data_table.add_column("Value")
    for field, value in FORM_DATA.items():
        data_table.add_row(field.replace("_", " ").title(), value)
    console.print(data_table)
    console.print()

    # -- Validate API key ---------------------------------------------------
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]ERROR:[/bold red] GEMINI_API_KEY not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    console.print("[green]✓[/green] Gemini client initialised\n")

    # -- Model config -------------------------------------------------------
    # This use case uses Computer Use ONLY — no custom function_declarations.
    # The model's entire job is visual interaction with the form.
    # All the intelligence about HOW to fill radio buttons, checkboxes,
    # and autocomplete fields comes from the model's understanding of
    # the screenshot — we don't need to teach it about HTML input types.
    gen_config = GenerateContentConfig(
        temperature=0.5,
        max_output_tokens=8192,
        tools=[
            # Single tool: Computer Use with browser environment.
            # No custom functions needed — the model only clicks and types.
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                ),
            ),
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    # -- System prompt describing the task ----------------------------------
    # Notice how the prompt gives the model HINTS about HTML input types
    # ("click the radio button", "click the checkbox") but doesn't tell it
    # HOW to interact with them at a low level.  The model figures out the
    # visual mechanics (where to click, whether to type or click) from
    # the screenshot.
    system_text = f"""\
You are a form-filling automation agent.  A browser is open to a practice
form at {FORM_URL}.

Fill in the form with EXACTLY these values:
  • First Name: {FORM_DATA['first_name']}
  • Last Name:  {FORM_DATA['last_name']}
  • Email:      {FORM_DATA['email']}
  • Gender:     {FORM_DATA['gender']}  (click the radio button)
  • Mobile:     {FORM_DATA['mobile']}
  • Subjects:   {FORM_DATA['subjects']}
  • Hobbies:    {FORM_DATA['hobbies']}  (click the checkbox)
  • Current Address: {FORM_DATA['address']}

After filling every field, scroll down to find and click the **Submit** button.
Then check whether a confirmation modal/dialog appears.

Finally, report:
1. Which fields you successfully filled.
2. Whether the form was submitted successfully (modal appeared).

Tips:
* Scroll down if fields are below the fold.
* For the "Subjects" field, type the text then press Enter or select from the dropdown.
* The Gender and Hobbies inputs are radio/checkbox — click the label text.
* The page may have ads — ignore them.
"""

    # -- Launch browser & navigate ------------------------------------------
    browser = FormBrowser(headless=headless)
    browser.launch()

    console.print("[bold]Step 2 →[/bold] Navigating to practice form …")
    screenshot_bytes, page_url = browser.navigate(FORM_URL)
    console.print(f"  [dim]URL: {page_url}[/dim]")
    console.print(f"  Screenshot: {len(screenshot_bytes):,} bytes\n")

    # -- Build initial conversation -----------------------------------------
    contents: list[Content] = [
        Content(role="user", parts=[Part(text=system_text)]),
    ]

    # -- Agent loop ---------------------------------------------------------
    turn = 0
    final_text = ""

    while turn < max_turns:
        turn += 1
        console.rule(f"[bold yellow]Turn {turn}[/bold yellow]")

        # ---- Generate -----------------------------------------------------
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=gen_config,
            )
        except Exception as exc:
            console.print(f"[red]API error: {exc}[/red]")
            time.sleep(2)
            continue

        if not response.candidates:
            console.print("[red]Empty response[/red]")
            continue

        candidate = response.candidates[0]

        # Append model response to history
        if candidate.content:
            contents.append(candidate.content)

        # ---- Extract parts ------------------------------------------------
        text_chunks = []
        fn_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_chunks.append(part.text)
                if part.function_call:
                    fn_calls.append(part.function_call)

        reasoning = " ".join(text_chunks) if text_chunks else None

        # No function calls → model is finished
        if not fn_calls:
            if candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
                continue
            final_text = reasoning or "(no final text)"
            console.print(Panel(
                final_text,
                title="[bold green]Agent Report[/bold green]",
                box=box.ROUNDED,
            ))
            break

        # Show brief reasoning
        if reasoning:
            short = reasoning[:300] + "…" if len(reasoning) > 300 else reasoning
            console.print(f"  [dim]{short}[/dim]")

        # ---- Execute function calls using ACTION_DISPATCH table ────────
        # This is where the dispatch-table pattern pays off: instead of
        # a 40-line if/elif chain, we do a single dict lookup.
        # The model emits the SAME action vocabulary regardless of what
        # HTML element it's interacting with:
        #   • Text input  → click(x,y) then type("Jane")
        #   • Radio button → click(x,y) on the radio circle/label
        #   • Checkbox     → click(x,y) on the checkbox
        #   • Autocomplete → type("Computer Science") then sometimes
        #                    click(x,y) on a dropdown suggestion
        #   • Textarea     → click(x,y) then type("123 AI Street…")
        #
        # The model treats ALL of these as "click then type" — it doesn't
        # need to know the DOM structure.  It just sees the screenshot.
        fn_response_parts = []
        for fc in fn_calls:
            args = fc.args or {}
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            console.print(f"  [cyan]▶ {fc.name}[/cyan]({args_str})")

            # Look up the action in our dispatch table
            dispatcher = ACTION_DISPATCH.get(fc.name)
            if dispatcher:
                try:
                    # Call the lambda: dispatcher(browser, args) → (png, url)
                    shot, url = dispatcher(browser, args)
                    console.print(f"    [dim]→ {url}[/dim]")
                except Exception as exc:
                    console.print(f"    [red]✗ {exc}[/red]")
                    # On error, still capture a screenshot so the model
                    # can see the current state and try to recover
                    shot, url = browser.take_screenshot()
            else:
                # Graceful fallback for actions the model emits that we
                # haven't mapped.  Return a screenshot so it can continue.
                console.print(f"    [yellow]⚠ Unknown action: {fc.name}[/yellow]")
                shot, url = browser.take_screenshot()

            # Every browser action response includes a fresh screenshot
            # (the "Observe" phase of the agentic loop).  Since this
            # use case has NO custom functions, every response includes
            # a screenshot — there's no bifurcation like in Use Cases 1-4.
            fn_response_parts.append(
                Part(function_response=FunctionResponse(
                    name=fc.name,
                    response={"url": url},
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=shot,
                            )
                        )
                    ],
                ))
            )

        # Feed results back as a "user" turn (required by the API)
        contents.append(Content(role="user", parts=fn_response_parts))

        # ── Screenshot pruning ────────────────────────────────────────
        # Form filling can take 15-25+ turns (each field = click + type).
        # Without pruning, that's 15+ screenshots × ~150 KB each =
        # ~2+ MB of base64 in the conversation.  We keep only the 3
        # most recent screenshots so the model can see its recent work.
        _prune_screenshots(contents, keep=3)

    # -- Cleanup -----------------------------------------------------------
    browser.close()
    console.print("\n[green]✓[/green] Browser closed")

    # -- Summary table -----------------------------------------------------
    summary = Table(
        title="Form Filling Summary",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
    )
    summary.add_column("Metric", style="bold")
    summary.add_column("Value")
    summary.add_row("Target URL", FORM_URL)
    summary.add_row("Total turns", str(turn))
    summary.add_row("Model", MODEL_NAME)
    summary.add_row("API", "generateContent (browser)")

    fields_str = ", ".join(
        f"{k.replace('_', ' ').title()}: {v}" for k, v in FORM_DATA.items()
    )
    summary.add_row("Data filled", fields_str)
    console.print(summary)

    return {
        "turns": turn,
        "form_data": FORM_DATA,
        "final_report": final_text,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prune_screenshots(contents: list[Content], keep: int = 3):
    """Drop screenshot blobs from all but the ``keep`` most recent user turns."""
    count = 0
    for content in reversed(contents):
        if content.role != "user" or not content.parts:
            continue
        has_shot = any(
            getattr(p, "function_response", None)
            and getattr(p.function_response, "parts", None)
            for p in content.parts
        )
        if has_shot:
            count += 1
            if count > keep:
                for p in content.parts:
                    fr = getattr(p, "function_response", None)
                    if fr and fr.parts:
                        fr.parts = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Automated Form Filling Agent — Gemini Computer Use"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode.",
    )
    parser.add_argument(
        "--max-turns", "-t",
        type=int, default=50,
        help="Maximum agent turns (default 50).",
    )
    args = parser.parse_args()

    results = run_form_agent(
        headless=args.headless,
        max_turns=args.max_turns,
    )

    console.print(f"\n[bold green]✓ Form filling complete.[/bold green]")
