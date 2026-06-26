"""
Use Case 2 — Multi-Site Price Comparison Agent
================================================
An autonomous agent that uses Gemini Computer Use **combined with custom
function calling** to search for products, extract prices, and build a
structured comparison table.

This demonstrates **multi-tool composition**: the model can interleave
browser-driving actions (click, type, scroll, navigate) with custom
structured-data functions (save_product) in a single conversation.

The agent:
  1. Opens Amazon
  2. Searches for 'wireless noise cancelling headphones'
  3. Extracts product names and prices from the results
  4. Calls `save_product()` to store each finding
  5. Displays a formatted comparison table using the `rich` library

Usage:
    export GEMINI_API_KEY="your-key-here"
    python price_agent.py
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

# rich — for the beautiful comparison table at the end
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

console = Console()


# ═══════════════════════════════════════════════════════════════════════════
# Section 1: Inline Browser Environment
# ═══════════════════════════════════════════════════════════════════════════
# Self-contained Playwright wrapper — identical pattern to Use Case 1 but
# defined independently so this script runs standalone.

@dataclasses.dataclass
class ScreenCapture:
    """Result returned after every browser action: screenshot + current URL."""
    screenshot: bytes
    url: str


class BrowserSession:
    """Playwright-based browser environment for Gemini Computer Use.

    Supports the full gemini-3.5-flash action vocabulary for
    ENVIRONMENT_BROWSER.
    """

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
        self._ctx.on("page", self._redirect_new_tab)
        self._page.goto(self._start_url)
        return self

    def __exit__(self, *exc):
        self._ctx.close()
        self._browser.close()
        self._pw.stop()

    def _redirect_new_tab(self, new_page):
        url = new_page.url
        new_page.close()
        self._page.goto(url)

    @property
    def dimensions(self) -> tuple[int, int]:
        vp = self._page.viewport_size
        return (vp["width"], vp["height"]) if vp else (self._width, self._height)

    def _capture(self) -> ScreenCapture:
        self._page.wait_for_load_state()
        time.sleep(0.4)
        png = self._page.screenshot(type="png", full_page=False)
        return ScreenCapture(screenshot=png, url=self._page.url)

    def _key(self, k: str) -> str:
        return self._KEY_MAP.get(k.lower(), k)

    # ── All browser actions ──────────────────────────────────────────
    def click(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.click(x, y)
        self._page.wait_for_load_state()
        return self._capture()

    def double_click(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.dblclick(x, y)
        self._page.wait_for_load_state()
        return self._capture()

    def triple_click(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.click(x, y, click_count=3)
        self._page.wait_for_load_state()
        return self._capture()

    def middle_click(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.click(x, y, button="middle")
        self._page.wait_for_load_state()
        return self._capture()

    def right_click(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.click(x, y, button="right")
        self._page.wait_for_load_state()
        return self._capture()

    def mouse_down(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.move(x, y)
        self._page.mouse.down()
        return self._capture()

    def mouse_up(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.move(x, y)
        self._page.mouse.up()
        return self._capture()

    def move(self, x: int, y: int) -> ScreenCapture:
        self._page.mouse.move(x, y)
        return self._capture()

    def type_text(self, text: str, press_enter: bool = False) -> ScreenCapture:
        self._page.keyboard.type(text)
        if press_enter:
            self._page.keyboard.press("Enter")
        self._page.wait_for_load_state()
        return self._capture()

    def press_key(self, key: str) -> ScreenCapture:
        self._page.keyboard.press(self._key(key))
        self._page.wait_for_load_state()
        return self._capture()

    def key_down(self, key: str) -> ScreenCapture:
        self._page.keyboard.down(self._key(key))
        return self._capture()

    def key_up(self, key: str) -> ScreenCapture:
        self._page.keyboard.up(self._key(key))
        return self._capture()

    def hotkey(self, keys: list[str]) -> ScreenCapture:
        norm = [self._key(k) for k in keys]
        for k in norm[:-1]:
            self._page.keyboard.down(k)
        self._page.keyboard.press(norm[-1])
        for k in reversed(norm[:-1]):
            self._page.keyboard.up(k)
        self._page.wait_for_load_state()
        return self._capture()

    def scroll(self, x: int, y: int, direction: str, magnitude: int = 3) -> ScreenCapture:
        self._page.mouse.move(x, y)
        dx, dy = 0, 0
        scroll_px = magnitude * 100
        if direction == "up":      dy = -scroll_px
        elif direction == "down":  dy = scroll_px
        elif direction == "left":  dx = -scroll_px
        elif direction == "right": dx = scroll_px
        self._page.mouse.wheel(dx, dy)
        self._page.wait_for_load_state()
        return self._capture()

    def navigate(self, url: str) -> ScreenCapture:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._page.wait_for_load_state()
        return self._capture()

    def go_back(self) -> ScreenCapture:
        self._page.go_back()
        self._page.wait_for_load_state()
        return self._capture()

    def go_forward(self) -> ScreenCapture:
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self._capture()

    def wait(self, seconds: int = 1) -> ScreenCapture:
        self._page.wait_for_timeout(seconds * 1000)
        return self._capture()

    def take_screenshot(self) -> ScreenCapture:
        return self._capture()

    def drag_and_drop(
        self, x: int, y: int, dest_x: int, dest_y: int
    ) -> ScreenCapture:
        self._page.mouse.move(x, y)
        self._page.mouse.down()
        self._page.mouse.move(dest_x, dest_y)
        self._page.mouse.up()
        return self._capture()


# ═══════════════════════════════════════════════════════════════════════════
# Section 2: Product Data Store & Custom Function
# ═══════════════════════════════════════════════════════════════════════════
# This is the key differentiator: a custom function that the model calls
# alongside browser actions to store structured product data.
#
# How multi-tool composition works in practice:
#   The model SEES a product listing on screen (via screenshot) and must
#   decide: "should I scroll/click to find more products, or should I call
#   save_product() to record what I see?"
#
#   The model makes this decision autonomously — we don't write any
#   if/else logic to choose.  It naturally interleaves:
#     Turn 1: type("wireless headphones"), press_key("Enter")  ← browser
#     Turn 2: scroll(…, direction="down")                       ← browser
#     Turn 3: save_product(name="Sony WH-1000XM5", price="$278") ← custom
#     Turn 4: scroll(…, direction="down")                       ← browser
#     Turn 5: save_product(name="Bose QC45", price="$249")      ← custom
#     Turn 6: (text response — "comparison complete")           ← done

# Global list that accumulates product findings across the session.
# save_product() appends here; the rich table reads from here at the end.
product_findings: list[dict] = []


def save_product(name: str, price: str, source: str) -> dict:
    """Save a product finding for the comparison report.

    The Gemini model calls this function when it identifies a product
    name and price on the page. The data is accumulated and used to
    build the final comparison table.

    Args:
        name: The product name (e.g. 'Sony WH-1000XM5').
        price: The price as displayed (e.g. '$278.00').
        source: Where the data was found (e.g. 'Amazon').

    Returns:
        Confirmation dict with save status and running total.
    """
    product_findings.append({
        "name": name,
        "price": price,
        "source": source,
    })
    print(f"     💾 Saved: {name} — {price} ({source})")
    return {
        "status": "saved",
        "total_products": len(product_findings),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Section 3: Price Comparison Agent
# ═══════════════════════════════════════════════════════════════════════════

# All browser action names used by gemini-3.5-flash
BROWSER_ACTIONS = {
    "click", "double_click", "triple_click", "middle_click", "right_click",
    "mouse_down", "mouse_up", "move", "type", "drag_and_drop", "wait",
    "press_key", "key_down", "key_up", "hotkey", "take_screenshot",
    "scroll", "go_back", "navigate", "go_forward",
}


def step_banner(n: int, title: str, detail: str = "") -> None:
    """Print a formatted step header."""
    print(f"\n{'━'*64}")
    print(f"  Step {n} → {title}")
    if detail:
        print(f"  {detail}")
    print(f"{'━'*64}")


class PriceComparisonAgent:
    """Drives Gemini Computer Use to find and compare product prices.

    This agent demonstrates multi-tool composition: it uses both
    Computer Use (for browsing) and a custom function (save_product)
    in the same conversation.
    """

    # ── What makes this use case special ──────────────────────────────
    #
    # API surface:   generateContent (full conversation history managed
    #                in self._contents — we append every model response
    #                and every FunctionResponse ourselves)
    # Environment:   ENVIRONMENT_BROWSER (Playwright headless Chromium)
    # Key pattern:   MULTI-TOOL COMPOSITION
    #
    # Unlike a basic Computer Use agent that only drives a browser,
    # this agent ALSO has a custom `save_product()` function.  This
    # lets the model extract structured data (product name, price,
    # source) from what it sees on screen and store it programmatically.
    #
    # How the model decides which tool to use:
    #   - Browser actions when it needs to NAVIGATE (search, scroll,
    #     click links) or OBSERVE (take_screenshot to see page content)
    #   - save_product() when it has IDENTIFIED a product + price and
    #     wants to record it for the comparison table
    #
    # The model makes this decision based on its instructions (the
    # system prompt) and what it sees in the current screenshot.
    # ─────────────────────────────────────────────────────────────────

    def __init__(
        self,
        browser: BrowserSession,
        task_prompt: str,
        model: str = "gemini-3.5-flash",
    ):
        self._browser = browser
        self._model = model

        # Validate API key
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY before running.")
            sys.exit(1)
        self._client = genai.Client(api_key=api_key)

        # Build initial conversation
        self._contents: list[Content] = [
            Content(role="user", parts=[Part(text=task_prompt)]),
        ]

        # ── Tool declaration: Computer Use + custom function ──────────
        # The `tools` list carries TWO separate Tool objects:
        #
        #   Tool 1 — computer_use:  Unlocks the browser action set
        #            (click, type, scroll, navigate, etc.)
        #
        #   Tool 2 — function_declarations:  Our custom save_product()
        #            function, auto-declared from its Python signature.
        #
        # RULE: computer_use and function_declarations must live in
        # SEPARATE Tool objects.  You cannot combine them in one Tool.
        # The model sees both and freely calls either type.
        self._config = GenerateContentConfig(
            temperature=0.5,
            max_output_tokens=8192,
            tools=[
                # Tool 1: Browser control — the model can click, type,
                # scroll, navigate, take screenshots, etc.
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    ),
                ),
                # Tool 2: Custom structured-data function.
                # from_callable() introspects the Python function to
                # auto-generate the JSON schema (name, parameters,
                # descriptions) that the model needs.
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration.from_callable(
                            client=self._client,
                            callable=save_product,
                        ),
                    ],
                ),
            ],
            # ThinkingConfig reveals the model's chain-of-thought.
            # Thought parts have part.thought == True.
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

    # ── Coordinate conversion ────────────────────────────────────────
    def _px_x(self, norm: int) -> int:
        return int(norm / 1000 * self._browser.dimensions[0])

    def _px_y(self, norm: int) -> int:
        return int(norm / 1000 * self._browser.dimensions[1])

    # ── Action dispatcher ────────────────────────────────────────────
    def _dispatch(self, fc: types.FunctionCall):
        """Route a function call to the browser or custom handler.

        This is the central dispatcher for multi-tool composition.
        Every function_call from the model arrives here, and we decide:
          - Custom function → execute locally, return JSON dict
          - Browser action  → execute via Playwright, return screenshot

        The boolean first element tells the caller whether to include
        a screenshot in the FunctionResponse sent back to the model.

        Returns:
            (is_browser: bool, result: ScreenCapture | dict)
        """
        name = fc.name
        args = fc.args or {}

        # ── Custom function ──────────────────────────────────────────
        # The model calls save_product() when it has visually identified
        # a product name + price on screen.  This doesn't change the
        # browser state, so no screenshot is needed in the response.
        if name == "save_product":
            result = save_product(
                name=args.get("name", "Unknown"),
                price=args.get("price", "N/A"),
                source=args.get("source", "Unknown"),
            )
            return False, result  # False = not a browser action, no screenshot

        # ── Browser actions ──────────────────────────────────────────
        if name == "click":
            return True, self._browser.click(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "double_click":
            return True, self._browser.double_click(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "triple_click":
            return True, self._browser.triple_click(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "middle_click":
            return True, self._browser.middle_click(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "right_click":
            return True, self._browser.right_click(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "mouse_down":
            return True, self._browser.mouse_down(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "mouse_up":
            return True, self._browser.mouse_up(self._px_x(args["x"]), self._px_y(args["y"]))
        if name == "move":
            return True, self._browser.move(self._px_x(args["x"]), self._px_y(args["y"]))
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
            x = self._px_x(args["x"])
            y = self._px_y(args["y"])
            direction = args["direction"]
            magnitude = args.get("magnitude", 3)
            if direction in ("up", "down"):
                magnitude = self._px_y(magnitude)
            elif direction in ("left", "right"):
                magnitude = self._px_x(magnitude)
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
                self._px_x(args["x"]), self._px_y(args["y"]),
                self._px_x(args["destination_x"]), self._px_y(args["destination_y"]),
            )

        raise ValueError(f"Unknown action: {name}")

    # ── Single turn ──────────────────────────────────────────────────
    def _run_turn(self, turn: int) -> Literal["CONTINUE", "DONE"]:
        print(f"\n{'─'*64}")
        print(f"  🤖  Agent Turn {turn}")
        print(f"{'─'*64}")

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
            print("  ⚠  Empty response")
            return "DONE"

        candidate = response.candidates[0]
        if candidate.content:
            self._contents.append(candidate.content)

        # Extract parts
        texts, fcs = [], []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    texts.append(part.text)
                if part.function_call:
                    fcs.append(part.function_call)

        reasoning = " ".join(texts) if texts else None

        if not fcs:
            if candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
                print("  ⚠  Malformed FC — retrying")
                return "CONTINUE"
            print(f"\n  ✅  Agent finished.")
            if reasoning:
                short = reasoning[:400] + "…" if len(reasoning) > 400 else reasoning
                print(f"  Summary: {short}")
            return "DONE"

        if reasoning:
            short = reasoning[:200] + "…" if len(reasoning) > 200 else reasoning
            print(f"  💭  {short}")

        # Execute each function call and build FunctionResponse objects.
        # The model may emit multiple calls per turn — e.g., scrolling
        # AND saving a product it spotted during that scroll.
        fn_responses: list[FunctionResponse] = []
        for fc in fcs:
            args_str = ", ".join(f"{k}={v}" for k, v in (fc.args or {}).items())
            print(f"  ▶  {fc.name}({args_str})")

            is_browser, result = self._dispatch(fc)

            # ── Bifurcated FunctionResponse ──────────────────────────
            # Browser actions and custom functions need different
            # response shapes — this is the key multi-tool detail:
            if is_browser:
                # Browser action: include a screenshot so the model
                # can see the result (the "Observe" phase).
                cap: ScreenCapture = result
                fn_responses.append(
                    FunctionResponse(
                        name=fc.name,
                        response={"url": cap.url},
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=cap.screenshot,
                                )
                            )
                        ],
                    )
                )
                print(f"     📸 Screenshot ({len(cap.screenshot)/1024:.0f} KB)")
            else:
                # Custom function: just a JSON dict confirming the
                # data was saved.  No screenshot — browser unchanged.
                fn_responses.append(
                    FunctionResponse(name=fc.name, response=result)
                )

        # All FunctionResponses go back as a single "user" turn.
        self._contents.append(
            Content(
                role="user",
                parts=[Part(function_response=fr) for fr in fn_responses],
            )
        )

        # ── Screenshot pruning ───────────────────────────────────────
        # Screenshots are ~100-300 KB each.  Over 20+ turns they can
        # push past the model's context window.  We strip binary blobs
        # from all but the 3 most recent turns, keeping the text
        # metadata (URL, action name) so the model retains context.
        self._prune_screenshots(keep=3)
        return "CONTINUE"

    def _prune_screenshots(self, keep: int = 3) -> None:
        count = 0
        for content in reversed(self._contents):
            if content.role != "user" or not content.parts:
                continue
            has_ss = any(
                p.function_response and p.function_response.parts
                and p.function_response.name in BROWSER_ACTIONS
                for p in content.parts
            )
            if has_ss:
                count += 1
                if count > keep:
                    for p in content.parts:
                        if (p.function_response and p.function_response.parts
                                and p.function_response.name in BROWSER_ACTIONS):
                            p.function_response.parts = None

    def run(self, max_turns: int = 50) -> None:
        turn = 0
        status = "CONTINUE"
        while status == "CONTINUE" and turn < max_turns:
            turn += 1
            status = self._run_turn(turn)
        if turn >= max_turns:
            print(f"  ⚠  Hit max turns ({max_turns})")


# ═══════════════════════════════════════════════════════════════════════════
# Section 4: Rich Comparison Table
# ═══════════════════════════════════════════════════════════════════════════

def print_comparison_table(products: list[dict]) -> None:
    """Render a beautiful comparison table using the rich library."""
    console.print()

    if not products:
        console.print(
            Panel(
                "[yellow]No products were saved by the agent.\n"
                "This can happen if Amazon blocked automated access\n"
                "or the page layout didn't match what the model expected.\n\n"
                "Try running again — the model may take a different path.[/yellow]",
                title="⚠ No Results",
                border_style="yellow",
            )
        )
        return

    # Build the rich table
    table = Table(
        title="🔍 PRICE COMPARISON RESULTS",
        title_style="bold cyan",
        border_style="bright_blue",
        show_lines=True,
        pad_edge=True,
        expand=False,
    )
    table.add_column("Product", style="white bold", min_width=30, max_width=50)
    table.add_column("Price", style="green bold", justify="right", min_width=12)
    table.add_column("Source", style="dim", min_width=18)

    for p in products:
        table.add_row(p["name"], p["price"], p["source"])

    console.print(table)
    console.print(f"\n  📊 Total products found: [bold]{len(products)}[/bold]\n")


# ═══════════════════════════════════════════════════════════════════════════
# Section 5: Main — Wire everything together
# ═══════════════════════════════════════════════════════════════════════════

SEARCH_TASK_PROMPT = """\
You are a price comparison agent. Your job is to search for products and
extract pricing information.

## Instructions

1. You are on Amazon.com. In the search box, type "wireless noise
   cancelling headphones" and press Enter to search.

2. Wait for results to load. You should see product listings with names
   and prices.

3. Look at the search results. For each of the top 3-5 products you can
   see, call the `save_product` function with:
   - name: the product name (e.g. "Sony WH-1000XM5")
   - price: the displayed price (e.g. "$278.00")
   - source: "Amazon"

4. If you need to scroll down to see more products, do so.

5. Try to find at least 3 products with visible prices. Save each one
   using `save_product`.

6. After saving 3-5 products, state that the comparison is complete.

IMPORTANT: Call `save_product` once for each product you identify.
Do NOT try to save all products in one call.
"""


def main() -> None:
    """Entry point: run the price comparison agent.

    ── Architecture overview ──────────────────────────────────────────
    API:         generateContent (full conversation history managed
                 client-side in agent._contents)
    Environment: ENVIRONMENT_BROWSER (headless Chromium via Playwright)
    Tools:       Computer Use + custom save_product() function

    What makes this special vs. a basic Computer Use agent:
      • Multi-tool composition — the model interleaves browser actions
        (search, scroll, click) with a custom save_product() function
        that records structured price data.
      • The model decides WHEN to browse vs. WHEN to save — no
        hard-coded orchestration on our side.
      • The saved data is rendered in a rich comparison table at the end,
        demonstrating how custom functions bridge visual browsing and
        structured outputs.
    ──────────────────────────────────────────────────────────────────
    """
    console.print(
        Panel(
            "[bold white]Use Case 2: Multi-Site Price Comparison Agent[/bold white]\n"
            "[dim]Demonstrates multi-tool composition: Computer Use + custom functions[/dim]",
            border_style="bright_cyan",
        )
    )

    # ── Step 1: Validate environment ─────────────────────────────────
    step_banner(1, "Validate environment", "Checking GEMINI_API_KEY")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("  [red]✗ GEMINI_API_KEY not set.[/red] Export it and re-run.")
        sys.exit(1)
    console.print("  [green]✓[/green] API key found")

    # ── Step 2: Launch browser ───────────────────────────────────────
    step_banner(
        2,
        "Launch browser",
        "Opening Amazon",
    )

    start_url = "https://www.amazon.com/"

    # Clear any leftover product data from previous runs
    product_findings.clear()

    with BrowserSession(
        width=1440,
        height=900,
        start_url=start_url,
        headless=bool(os.environ.get("PLAYWRIGHT_HEADLESS", True)),
    ) as browser:
        console.print(f"  [green]✓[/green] Browser launched — viewport {browser.dimensions}")
        console.print(f"  [green]✓[/green] Page loaded: {start_url}")

        # Grab initial screenshot
        initial = browser.take_screenshot()
        console.print(f"  [green]✓[/green] Initial screenshot: {len(initial.screenshot)/1024:.0f} KB")

        # ── Step 3: Initialise agent ─────────────────────────────────
        step_banner(3, "Initialise price agent", "Setting up Computer Use + save_product")

        agent = PriceComparisonAgent(
            browser=browser,
            task_prompt=SEARCH_TASK_PROMPT,
            model="gemini-3.5-flash",
        )

        # Attach initial screenshot to the first user message
        agent._contents[0] = Content(
            role="user",
            parts=[
                Part(text=SEARCH_TASK_PROMPT),
                Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial.screenshot,
                    )
                ),
            ],
        )
        console.print("  [green]✓[/green] Agent ready — multi-tool config active")
        console.print("    Tool 1: [cyan]computer_use[/cyan] (ENVIRONMENT_BROWSER)")
        console.print("    Tool 2: [cyan]save_product[/cyan] (custom function)")

        # ── Step 4: Run the agent ────────────────────────────────────
        step_banner(4, "Run price search", "Agent is now searching and extracting prices…")
        agent.run(max_turns=60)

        # ── Step 5: Display results ──────────────────────────────────
        step_banner(5, "Comparison Results", "Rendering formatted table")
        print_comparison_table(product_findings)

    console.print("[green]✓ Browser closed. Price comparison complete.[/green]\n")


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
