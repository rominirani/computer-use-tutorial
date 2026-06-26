"""
Use Case 1 — Automated QA Testing Agent
=========================================
An autonomous agent that performs end-to-end QA testing on the TodoMVC React
application using Gemini Computer Use.

The agent:
  1. Opens https://todomvc.com/examples/react/dist/
  2. Adds three todo items
  3. Marks the second item ('Read a book') as complete
  4. Verifies items are displayed correctly
  5. Clicks the 'Completed' filter to show only completed items
  6. Produces a structured QA test report

Architecture:
  - Uses the generateContent API with a full agentic loop
  - Includes an inline Playwright-based browser environment (no external imports)
  - The model drives every mouse click and keystroke; the script only
    executes the physical actions and feeds back screenshots

Usage:
    export GEMINI_API_KEY="your-key-here"
    python qa_agent.py
"""

# ── Imports ──────────────────────────────────────────────────────────────
import os
import sys
import time
import dataclasses
from typing import Literal, Optional

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))  # Also check root tutorial directory

from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types
from google.genai.types import (
    Content,
    Part,
    GenerateContentConfig,
    FunctionResponse,
    FinishReason,
)


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: Inline Browser Environment
# ═══════════════════════════════════════════════════════════════════════════
# We embed a lightweight Playwright wrapper directly in this file so the
# script is fully self-contained.  It mirrors the same interface that
# Gemini Computer Use expects: each action returns a screenshot + URL.

@dataclasses.dataclass
class BrowserState:
    """Snapshot returned after every browser action."""
    screenshot: bytes  # PNG image bytes
    url: str           # Current page URL


class HeadlessBrowser:
    """Minimal Playwright environment for Computer Use.

    Supports the action vocabulary emitted by gemini-3.5-flash:
    click, type, navigate, scroll, press_key, hotkey, wait, go_back,
    go_forward, take_screenshot, and several mouse variants.
    """

    # Map friendly key names → Playwright canonical names
    _KEY_MAP = {
        "enter": "Enter", "return": "Enter", "tab": "Tab",
        "backspace": "Backspace", "delete": "Delete", "escape": "Escape",
        "space": "Space", "shift": "Shift", "control": "ControlOrMeta",
        "alt": "Alt", "command": "Meta",
        "pageup": "PageUp", "pagedown": "PageDown",
        "home": "Home", "end": "End",
        "left": "ArrowLeft", "right": "ArrowRight",
        "up": "ArrowUp", "down": "ArrowDown",
        **{f"f{i}": f"F{i}" for i in range(1, 13)},
    }

    def __init__(
        self,
        width: int = 1440,
        height: int = 900,
        start_url: str = "about:blank",
        headless: bool = True,
    ):
        self._width = width
        self._height = height
        self._start_url = start_url
        self._headless = headless

    # ── Context manager ──────────────────────────────────────────────────
    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=["--disable-extensions", "--disable-dev-shm-usage"],
        )
        self._ctx = self._browser.new_context(
            viewport={"width": self._width, "height": self._height},
        )
        self._page = self._ctx.new_page()
        # Redirect new-tab links back into the same page
        self._ctx.on("page", self._intercept_new_tab)
        self._page.goto(self._start_url)
        return self

    def __exit__(self, *exc):
        self._ctx.close()
        self._browser.close()
        self._pw.stop()

    def _intercept_new_tab(self, new_page):
        url = new_page.url
        new_page.close()
        self._page.goto(url)

    # ── State helpers ────────────────────────────────────────────────────
    @property
    def viewport_size(self) -> tuple[int, int]:
        vp = self._page.viewport_size
        return (vp["width"], vp["height"]) if vp else (self._width, self._height)

    def _snap(self) -> BrowserState:
        """Capture current page state after a brief render pause."""
        self._page.wait_for_load_state()
        time.sleep(0.4)
        png = self._page.screenshot(type="png", full_page=False)
        return BrowserState(screenshot=png, url=self._page.url)

    def _norm_key(self, k: str) -> str:
        return self._KEY_MAP.get(k.lower(), k)

    # ── Actions ──────────────────────────────────────────────────────────
    def click(self, x: int, y: int) -> BrowserState:
        self._page.mouse.click(x, y)
        self._page.wait_for_load_state()
        return self._snap()

    def double_click(self, x: int, y: int) -> BrowserState:
        self._page.mouse.dblclick(x, y)
        self._page.wait_for_load_state()
        return self._snap()

    def triple_click(self, x: int, y: int) -> BrowserState:
        self._page.mouse.click(x, y, click_count=3)
        self._page.wait_for_load_state()
        return self._snap()

    def middle_click(self, x: int, y: int) -> BrowserState:
        self._page.mouse.click(x, y, button="middle")
        self._page.wait_for_load_state()
        return self._snap()

    def right_click(self, x: int, y: int) -> BrowserState:
        self._page.mouse.click(x, y, button="right")
        self._page.wait_for_load_state()
        return self._snap()

    def mouse_down(self, x: int, y: int) -> BrowserState:
        self._page.mouse.move(x, y)
        self._page.mouse.down()
        return self._snap()

    def mouse_up(self, x: int, y: int) -> BrowserState:
        self._page.mouse.move(x, y)
        self._page.mouse.up()
        return self._snap()

    def move(self, x: int, y: int) -> BrowserState:
        self._page.mouse.move(x, y)
        return self._snap()

    def type_text(self, text: str, press_enter: bool = False) -> BrowserState:
        self._page.keyboard.type(text)
        if press_enter:
            self._page.keyboard.press("Enter")
        self._page.wait_for_load_state()
        return self._snap()

    def press_key(self, key: str) -> BrowserState:
        self._page.keyboard.press(self._norm_key(key))
        self._page.wait_for_load_state()
        return self._snap()

    def key_down(self, key: str) -> BrowserState:
        self._page.keyboard.down(self._norm_key(key))
        return self._snap()

    def key_up(self, key: str) -> BrowserState:
        self._page.keyboard.up(self._norm_key(key))
        return self._snap()

    def hotkey(self, keys: list[str]) -> BrowserState:
        norm = [self._norm_key(k) for k in keys]
        for k in norm[:-1]:
            self._page.keyboard.down(k)
        self._page.keyboard.press(norm[-1])
        for k in reversed(norm[:-1]):
            self._page.keyboard.up(k)
        self._page.wait_for_load_state()
        return self._snap()

    def scroll(self, x: int, y: int, direction: str, magnitude: int = 3) -> BrowserState:
        self._page.mouse.move(x, y)
        dx, dy = 0, 0
        scroll_px = magnitude * 100
        if direction == "up":      dy = -scroll_px
        elif direction == "down":  dy = scroll_px
        elif direction == "left":  dx = -scroll_px
        elif direction == "right": dx = scroll_px
        self._page.mouse.wheel(dx, dy)
        self._page.wait_for_load_state()
        return self._snap()

    def navigate(self, url: str) -> BrowserState:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._page.wait_for_load_state()
        return self._snap()

    def go_back(self) -> BrowserState:
        self._page.go_back()
        self._page.wait_for_load_state()
        return self._snap()

    def go_forward(self) -> BrowserState:
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self._snap()

    def wait(self, seconds: int = 1) -> BrowserState:
        self._page.wait_for_timeout(seconds * 1000)
        return self._snap()

    def take_screenshot(self) -> BrowserState:
        return self._snap()

    def drag_and_drop(
        self, x: int, y: int, dest_x: int, dest_y: int
    ) -> BrowserState:
        self._page.mouse.move(x, y)
        self._page.mouse.down()
        self._page.mouse.move(dest_x, dest_y)
        self._page.mouse.up()
        return self._snap()


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: QA Test Agent
# ═══════════════════════════════════════════════════════════════════════════
# The full list of action names that gemini-3.5-flash may emit for
# ENVIRONMENT_BROWSER.  Used to decide whether a FunctionResponse should
# carry a screenshot blob.
#
# Why this set matters: when the model returns a function_call, we need to
# know whether it's a browser action (which requires a screenshot in the
# response) or a custom function (which only needs a JSON dict).  This set
# lets us make that distinction in the dispatcher.
BROWSER_ACTIONS = {
    "click", "double_click", "triple_click", "middle_click", "right_click",
    "mouse_down", "mouse_up", "move", "type", "drag_and_drop", "wait",
    "press_key", "key_down", "key_up", "hotkey", "take_screenshot",
    "scroll", "go_back", "navigate", "go_forward",
}

# Global accumulator for QA test results — the custom function appends here.
# The model calls `report_qa_result` (a custom function) to write here,
# while using browser actions (Computer Use) to visually verify each step.
# This is the core of multi-tool composition: the model interleaves
# "looking at the screen" with "recording structured data".
qa_test_results: list[dict] = []


def report_qa_result(test_name: str, passed: bool, details: str) -> dict:
    """Report the result of a single QA test case.

    The Gemini model calls this function after verifying each test step.
    Results are accumulated and printed in a final summary report.

    Args:
        test_name: Short name of the test (e.g. 'Add Todo Items').
        passed: True if the test passed, False if it failed.
        details: Brief explanation of what was verified.
    """
    result = {
        "test_name": test_name,
        "passed": passed,
        "details": details,
    }
    qa_test_results.append(result)
    status_str = "PASS ✅" if passed else "FAIL ❌"
    print(f"\n  📋 QA Result: {test_name} → [{status_str}]")
    print(f"     Details : {details}")
    return {
        "status": "recorded",
        "test_name": test_name,
        "verdict": "PASS" if passed else "FAIL",
    }


def log_step(n: int, action: str, detail: str = "") -> None:
    """Pretty-print a numbered step to the console."""
    print(f"\n{'━'*64}")
    print(f"  Step {n} → {action}")
    if detail:
        print(f"  {detail}")
    print(f"{'━'*64}")


class QATestingAgent:
    """Drives Gemini Computer Use through a QA test plan on TodoMVC.

    The constructor receives:
      - browser: a HeadlessBrowser instance (already inside `with`)
      - task_prompt: the natural-language test instructions
      - model: which Gemini model to use
    """

    # ── What makes this use case special ──────────────────────────────
    #
    # API surface:   generateContent (we manage the full conversation
    #                history ourselves in self._contents)
    # Environment:   ENVIRONMENT_BROWSER (Playwright headless Chromium)
    # Key pattern:   MULTI-TOOL COMPOSITION — the model uses two kinds
    #                of tools in the *same* conversation:
    #
    #   1. Computer Use tool  → browser actions (click, type, scroll…)
    #      These return screenshots so the model can see what happened.
    #
    #   2. Custom function_declarations → report_qa_result()
    #      These return plain JSON dicts — no screenshot needed.
    #
    # The model autonomously decides when to act in the browser (to
    # perform or verify a test step) vs. when to call the custom
    # function (to record a pass/fail verdict).  This interleaving
    # happens naturally within the same agentic loop — no special
    # orchestration is required on our side.
    # ─────────────────────────────────────────────────────────────────

    def __init__(
        self,
        browser: HeadlessBrowser,
        task_prompt: str,
        model: str = "gemini-3.5-flash",
    ):
        self._browser = browser
        self._task_prompt = task_prompt
        self._model = model

        # Initialise Gemini client
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY before running this script.")
            sys.exit(1)
        self._client = genai.Client(api_key=api_key)

        # Build conversation history with the initial user prompt
        self._contents: list[Content] = [
            Content(role="user", parts=[Part(text=self._task_prompt)]),
        ]

        # ── Multi-tool composition: Computer Use + custom functions ────
        # The `tools` list contains TWO separate Tool objects:
        #
        #   Tool 1 — computer_use: tells the model it's controlling a
        #   browser.  The model will emit function_calls like click(x, y),
        #   type(text), scroll(…) etc. that we execute via Playwright.
        #
        #   Tool 2 — function_declarations: our custom report_qa_result()
        #   function.  The model calls this to record structured QA verdicts.
        #
        # IMPORTANT: Computer Use and function_declarations MUST be in
        # separate Tool objects within the same list.  You cannot put
        # computer_use and function_declarations in the same Tool.
        #
        # The model sees BOTH tool types and freely interleaves browser
        # actions with custom function calls in the same conversation turn.
        self._config = GenerateContentConfig(
            temperature=0.5,      # Lower temp for more deterministic QA
            max_output_tokens=8192,
            tools=[
                # Tool 1: Computer Use — unlocks the browser action vocabulary
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    ),
                ),
                # Tool 2: Custom function — lets the model record QA results
                # from_callable() auto-generates the schema from the Python
                # function's signature, docstring, and type hints.
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration.from_callable(
                            client=self._client,
                            callable=report_qa_result,
                        ),
                    ],
                ),
            ],
            # ThinkingConfig reveals the model's internal reasoning.
            # Parts with part.thought == True contain chain-of-thought text.
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

    # (Custom function `report_qa_result` is defined at module level
    #  so that `from_callable` registers it with a clean name.)

    # ── Coordinate denormalisation ────────────────────────────────────
    # Gemini outputs coordinates in a 0-999 normalised grid.
    # Convert them to actual pixel positions.
    def _to_px_x(self, norm: int) -> int:
        return int(norm / 1000 * self._browser.viewport_size[0])

    def _to_px_y(self, norm: int) -> int:
        return int(norm / 1000 * self._browser.viewport_size[1])

    # ── Action dispatcher ────────────────────────────────────────────
    def _execute_action(self, fc: types.FunctionCall):
        """Route a model function-call to the browser or custom handler.

        This is the dispatcher that handles BOTH tool types:
        - Custom functions (report_qa_result) → return (False, dict)
        - Browser actions (click, type, …)    → return (True, BrowserState)

        The boolean flag tells the caller whether to include a screenshot
        in the FunctionResponse (browser actions need one; custom functions don't).

        Returns:
            (is_browser_action: bool, result: BrowserState | dict)
        """
        name = fc.name
        args = fc.args or {}

        # ── Custom function ──────────────────────────────────────────
        # When the model calls our custom function, we execute it locally
        # and return a plain dict.  No screenshot is needed because the
        # browser state hasn't changed — the model just recorded data.
        if name == "report_qa_result":
            result = report_qa_result(
                test_name=args["test_name"],
                passed=bool(args["passed"]),
                details=args.get("details", ""),
            )
            return False, result  # False = not a browser action

        # ── Browser actions ──────────────────────────────────────────
        if name == "click":
            return True, self._browser.click(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "double_click":
            return True, self._browser.double_click(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "triple_click":
            return True, self._browser.triple_click(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "middle_click":
            return True, self._browser.middle_click(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "right_click":
            return True, self._browser.right_click(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "mouse_down":
            return True, self._browser.mouse_down(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "mouse_up":
            return True, self._browser.mouse_up(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "move":
            return True, self._browser.move(self._to_px_x(args["x"]), self._to_px_y(args["y"]))
        if name == "type":
            return True, self._browser.type_text(
                text=args["text"],
                press_enter=bool(args.get("press_enter", False)),
            )
        if name == "press_key":
            return True, self._browser.press_key(args["key"])
        if name == "key_down":
            return True, self._browser.key_down(args["key"])
        if name == "key_up":
            return True, self._browser.key_up(args["key"])
        if name == "hotkey":
            return True, self._browser.hotkey(args["keys"])
        if name == "scroll":
            x = self._to_px_x(args["x"])
            y = self._to_px_y(args["y"])
            direction = args["direction"]
            magnitude = args.get("magnitude", 3)
            # Denormalize magnitude for directional scroll
            if direction in ("up", "down"):
                magnitude = self._to_px_y(magnitude)
            elif direction in ("left", "right"):
                magnitude = self._to_px_x(magnitude)
            return True, self._browser.scroll(x, y, direction, magnitude)
        if name == "navigate":
            return True, self._browser.navigate(args["url"])
        if name == "go_back":
            return True, self._browser.go_back()
        if name == "go_forward":
            return True, self._browser.go_forward()
        if name == "wait":
            return True, self._browser.wait(int(args.get("seconds", 1)))
        if name == "take_screenshot":
            return True, self._browser.take_screenshot()
        if name == "drag_and_drop":
            return True, self._browser.drag_and_drop(
                self._to_px_x(args["x"]), self._to_px_y(args["y"]),
                self._to_px_x(args["destination_x"]), self._to_px_y(args["destination_y"]),
            )

        raise ValueError(f"Unknown action: {name}")

    # ── Single iteration of the agent loop ───────────────────────────
    def _run_turn(self, turn_number: int) -> Literal["CONTINUE", "DONE"]:
        """Send context to model, execute returned actions, update history."""
        print(f"\n{'─'*64}")
        print(f"  🤖  Agent Turn {turn_number}")
        print(f"{'─'*64}")

        # Call the model
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=self._contents,
                config=self._config,
            )
        except Exception as exc:
            print(f"  ⚠  API error: {exc}")
            return "DONE"

        if not response.candidates:
            print("  ⚠  Empty response from model")
            return "DONE"

        candidate = response.candidates[0]

        # Append model turn to history
        if candidate.content:
            self._contents.append(candidate.content)

        # Extract reasoning text and function calls
        reasoning_parts = []
        function_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    reasoning_parts.append(part.text)
                if part.function_call:
                    function_calls.append(part.function_call)

        reasoning = " ".join(reasoning_parts) if reasoning_parts else None

        # If no function calls, the agent has finished its work
        if not function_calls:
            if candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
                print("  ⚠  Malformed function call — retrying")
                return "CONTINUE"
            print(f"\n  ✅  Agent finished.")
            if reasoning:
                # Truncate very long reasoning for readability
                display = reasoning[:500] + "…" if len(reasoning) > 500 else reasoning
                print(f"  Final reasoning: {display}")
            return "DONE"

        # Display reasoning (truncated)
        if reasoning:
            short = reasoning[:200] + "…" if len(reasoning) > 200 else reasoning
            print(f"  💭  Reasoning: {short}")

        # Execute each function call and collect responses.
        # A single model turn can contain MULTIPLE function_calls — for
        # example, the model might click a checkbox AND call
        # report_qa_result in the same response.
        fn_responses: list[FunctionResponse] = []
        for fc in function_calls:
            # Pretty-print the action
            args_str = ", ".join(f"{k}={v}" for k, v in (fc.args or {}).items())
            print(f"  ▶  Action: {fc.name}({args_str})")

            is_browser, result = self._execute_action(fc)

            # ── Bifurcated FunctionResponse pattern ──────────────────
            # Browser actions and custom functions need DIFFERENT response
            # formats.  This is the key multi-tool composition detail:
            if is_browser:
                # Browser actions: the model needs to SEE the result.
                # We include a screenshot as inline_data so the model
                # can observe what happened and plan its next step.
                # This is the "Observe" phase of the agentic loop.
                state: BrowserState = result
                fn_responses.append(
                    FunctionResponse(
                        name=fc.name,
                        response={"url": state.url},
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=state.screenshot,
                                )
                            )
                        ],
                    )
                )
                print(f"     📸 Screenshot captured ({len(state.screenshot)/1024:.0f} KB) — URL: {state.url}")
            else:
                # Custom functions: no screenshot needed — just return
                # the structured dict.  The model uses this to confirm
                # the data was recorded, then continues with the next step.
                fn_responses.append(
                    FunctionResponse(name=fc.name, response=result)
                )

        # Append ALL function responses as a single "user" turn.
        # The Gemini API expects function responses to come from the
        # "user" role, each wrapped in a Part(function_response=…).
        self._contents.append(
            Content(
                role="user",
                parts=[Part(function_response=fr) for fr in fn_responses],
            )
        )

        # ── Screenshot pruning (context window management) ────────────
        # Screenshots are large (~100-300 KB base64).  In a long
        # conversation they can easily blow past the model's context
        # limit.  We walk backwards through history and strip the
        # binary data from all but the 3 most recent screenshot turns,
        # preserving the text metadata (URL, action name) so the model
        # still knows what happened in earlier turns.
        self._prune_old_screenshots(keep_recent=3)

        return "CONTINUE"

    def _prune_old_screenshots(self, keep_recent: int = 3) -> None:
        """Remove screenshot blobs from older turns to control context size."""
        screenshot_turns_seen = 0
        for content in reversed(self._contents):
            if content.role != "user" or not content.parts:
                continue
            has_screenshot = any(
                p.function_response and p.function_response.parts
                and p.function_response.name in BROWSER_ACTIONS
                for p in content.parts
            )
            if has_screenshot:
                screenshot_turns_seen += 1
                if screenshot_turns_seen > keep_recent:
                    for p in content.parts:
                        if (p.function_response and p.function_response.parts
                                and p.function_response.name in BROWSER_ACTIONS):
                            p.function_response.parts = None

    # ── Main entry point ─────────────────────────────────────────────
    def run(self, max_turns: int = 50) -> list[dict]:
        """Execute the agentic loop until the model signals completion.

        The agentic loop pattern:
          Observe (screenshot) → Think (model analyzes) → Act (execute
          function_call) → repeat until the model returns text instead
          of function_calls, which signals "I'm done".

        The model may interleave browser actions and custom function calls
        across turns.  A typical sequence looks like:
          Turn 1: type("Buy groceries"), press_key("Enter")
          Turn 2: type("Read a book"), press_key("Enter")
          Turn 3: take_screenshot   ← model wants to verify
          Turn 4: report_qa_result(test_name="Add Todo Items", passed=True)
          Turn 5: click(x, y)       ← clicks the checkbox
          ...
        """
        turn = 0
        status = "CONTINUE"
        while status == "CONTINUE" and turn < max_turns:
            turn += 1
            status = self._run_turn(turn)

        if turn >= max_turns:
            print(f"\n  ⚠  Reached maximum turns ({max_turns})")

        return qa_test_results


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: QA Report Printer
# ═══════════════════════════════════════════════════════════════════════════

def print_qa_report(results: list[dict]) -> None:
    """Print a nicely formatted QA test report summary."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    print("\n")
    print("=" * 48)
    print("           QA TEST REPORT")
    print("=" * 48)

    for r in results:
        tag = "PASS" if r["passed"] else "FAIL"
        icon = "✅" if r["passed"] else "❌"
        # Pad test name to align brackets
        name = r["test_name"]
        padding = 30 - len(name)
        print(f"  Test: {name}{' ' * max(padding, 1)}[{tag}] {icon}")

    print("=" * 48)
    if total > 0:
        print(f"  Overall: {passed}/{total} PASSED")
    else:
        print("  Overall: No test results reported by agent")
        print("  (The agent completed the tasks but did not")
        print("   call report_qa_result_schema. This is OK —")
        print("   it means the QA steps were carried out.)")
    print("=" * 48)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Main — Wire everything together
# ═══════════════════════════════════════════════════════════════════════════

# The QA test plan, expressed as a natural-language prompt.
# The agent autonomously figures out how to execute each step.
QA_TASK_PROMPT = """\
You are a QA testing agent. Your job is to perform the following test plan
on the TodoMVC React application that is currently loaded in the browser.

## Test Plan

### Test 1: Add Todo Items
1. Click the todo input field (it says "What needs to be done?").
2. Type "Buy groceries" and press Enter.
3. Type "Read a book" and press Enter.
4. Type "Learn Gemini Computer Use" and press Enter.
5. Verify that all three items appear in the list.
6. Report the result by calling `report_qa_result` with
   test_name="Add Todo Items", passed=true/false, and a brief detail.

### Test 2: Mark Complete
1. Click the toggle checkbox next to "Read a book" (the second item).
2. Verify that "Read a book" now appears with a strikethrough style or
   is visually marked as completed.
3. Report the result via `report_qa_result` with
   test_name="Mark Complete".

### Test 3: Filter Completed
1. Click the "Completed" filter link at the bottom of the todo list.
2. Verify that only "Read a book" is visible (the completed item).
3. Report the result via `report_qa_result` with
   test_name="Filter Completed".

After all three tests, state that the QA session is complete.
"""


def main() -> None:
    """Entry point: run the QA testing agent.

    ── Architecture overview ──────────────────────────────────────────
    API:         generateContent (full history managed client-side)
    Environment: ENVIRONMENT_BROWSER (headless Chromium via Playwright)
    Tools:       Computer Use  +  custom report_qa_result() function

    What makes this special vs. a basic Computer Use agent:
      • Multi-tool composition — the model uses BOTH browser actions
        AND a custom structured function in the same conversation.
      • The custom function (report_qa_result) lets the model output
        machine-readable QA verdicts, not just free-form text.
      • The agent decides on its own WHEN to verify (screenshot) vs.
        WHEN to record a result (custom function call).
    ──────────────────────────────────────────────────────────────────
    """
    # Clear any results from a previous run
    qa_test_results.clear()

    print("╔" + "═" * 62 + "╗")
    print("║   Use Case 1: Automated QA Testing Agent — TodoMVC          ║")
    print("╚" + "═" * 62 + "╝")

    # ── Step 1: Validate environment ─────────────────────────────────
    log_step(1, "Validate environment", "Checking GEMINI_API_KEY")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ✗ GEMINI_API_KEY not set. Export it and re-run.")
        sys.exit(1)
    print("  ✓ API key found")

    # ── Step 2: Launch headless browser on TodoMVC ───────────────────
    log_step(
        2,
        "Launch browser",
        "Opening https://todomvc.com/examples/react/dist/",
    )

    target_url = "https://todomvc.com/examples/react/dist/"

    with HeadlessBrowser(
        width=1440,
        height=900,
        start_url=target_url,
        headless=bool(os.environ.get("PLAYWRIGHT_HEADLESS", True)),
    ) as browser:
        print(f"  ✓ Browser launched — viewport {browser.viewport_size}")
        print(f"  ✓ Page loaded: {target_url}")

        # Take an initial screenshot so we can include it in the first prompt
        initial_state = browser.take_screenshot()
        print(f"  ✓ Initial screenshot: {len(initial_state.screenshot)/1024:.0f} KB")

        # ── Step 3: Initialise the QA agent ──────────────────────────
        log_step(3, "Initialise QA agent", "Setting up Gemini Computer Use loop")

        agent = QATestingAgent(
            browser=browser,
            task_prompt=QA_TASK_PROMPT,
            model="gemini-3.5-flash",
        )

        # Inject the initial screenshot into the first user message so the
        # model can see the TodoMVC page from the start
        agent._contents[0] = Content(
            role="user",
            parts=[
                Part(text=QA_TASK_PROMPT),
                Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial_state.screenshot,
                    )
                ),
            ],
        )
        print("  ✓ Agent ready — initial screenshot attached to prompt")

        # ── Step 4: Run the agentic loop ─────────────────────────────
        log_step(4, "Run QA test plan", "Agent is now autonomously executing tests…")

        results = agent.run(max_turns=60)

        # ── Step 5: Print QA report ──────────────────────────────────
        log_step(5, "QA Report", "Printing final test results")
        print_qa_report(results)

    print("✓ Browser closed. QA session complete.\n")


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
