#!/usr/bin/env python3
"""
=============================================================================
Use Case 4 — Web Research & Report Agent
=============================================================================
Demonstrates **Computer Use + Custom Function Calling** to perform structured
web research.  The agent browses DuckDuckGo, visits search results, and calls
custom ``save_finding`` / ``generate_report`` functions so findings are stored
programmatically rather than as free-form text.

Workflow
--------
1. Open DuckDuckGo and search for "quantum computing breakthroughs 2026"
2. Visit the first 2-3 search results
3. For each page, call ``save_finding(title, source_url, key_point, category)``
4. When done, call ``generate_report()`` to signal completion
5. The script compiles all findings into a Markdown report and saves it

Prerequisites
-------------
* ``GEMINI_API_KEY`` environment variable
* Python packages: google-genai, playwright, rich, python-dotenv
* Playwright browsers installed: ``python -m playwright install chromium``

Run
---
    python research_agent.py
    python research_agent.py --search "AI safety regulations 2026"
    python research_agent.py --headless          # run without visible browser
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import os
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
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = "gemini-3.5-flash"
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800
DEFAULT_SEARCH_QUERY = "quantum computing breakthroughs 2026"

# Rich console
console = Console()

# ---------------------------------------------------------------------------
# Research data store — custom functions write here
# ---------------------------------------------------------------------------
# This list is the bridge between the model's visual browsing and the
# final structured report.  The model calls save_finding() whenever it
# reads something noteworthy on screen; each call appends a dict here.
# At the end, _write_report() iterates over this list to produce Markdown.
#
# Dual custom function pattern:
#   save_finding()     — called N times (once per insight extracted)
#   generate_report()  — called exactly once to signal "I'm done researching"
#
# The model decides when enough findings have been collected by reading
# the system prompt ("collect from 2-3 pages, then call generate_report").
findings: list[dict] = []


# ── Custom function 1 of 2: save_finding ─────────────────────────────
# The model calls this each time it spots a noteworthy insight on a web
# page.  Unlike browser actions (which change the screen), this function
# only records data — so its FunctionResponse is a plain JSON dict with
# no screenshot attached.
def save_finding(
    title: str,
    source_url: str,
    key_point: str,
    category: str,
) -> dict:
    """
    Save a research finding extracted from a web page.

    Args:
        title:      Short descriptive title of the finding.
        source_url: URL where the information was found.
        key_point:  The main insight or fact extracted.
        category:   Category tag (e.g. "hardware", "algorithm", "funding").

    Returns:
        Confirmation dict with the finding number.
    """
    entry = {
        "title": title,
        "source_url": source_url,
        "key_point": key_point,
        "category": category,
        "timestamp": datetime.now().isoformat(),  # stamp when collected
    }
    # Accumulate into the global list — _write_report() reads this later
    findings.append(entry)

    console.print(
        f"  [green]📌 Finding #{len(findings)} saved:[/green] {title} "
        f"[dim]({category})[/dim]"
    )
    # Return a confirmation so the model knows the save succeeded
    # and can see the running total of findings collected
    return {"status": "saved", "finding_number": len(findings)}


# ── Custom function 2 of 2: generate_report ─────────────────────────
# This is a "signal" function — it doesn't do heavy work itself, but
# its invocation tells the agentic loop to stop browsing and compile
# the findings into a Markdown file.  This pattern (data-collection
# function + completion-signal function) is a clean way to let the
# model control when research is "done enough".
def generate_report() -> dict:
    """
    Signal that research is complete and a report should be generated.

    Returns:
        Status dict with total number of findings collected.
    """
    console.print(
        f"\n  [bold green]📋 Report requested — {len(findings)} findings collected[/bold green]"
    )
    return {"status": "report_ready", "total_findings": len(findings)}


# ---------------------------------------------------------------------------
# Playwright browser helpers
# ---------------------------------------------------------------------------
class BrowserSession:
    """
    Minimal Playwright wrapper that exposes the Computer-Use action set
    and returns (screenshot_bytes, current_url) after every action.
    """

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self):
        """Launch Chromium and open a blank page."""
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-extensions",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
            ],
        )
        ctx = self._browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        )
        self._page = ctx.new_page()
        # Redirect new-tab navigations into the current tab
        ctx.on("page", self._redirect_new_tab)
        self._page.goto("https://html.duckduckgo.com/html/")
        console.print("[green]✓[/green] Chromium launched\n")

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _redirect_new_tab(self, new_page):
        url = new_page.url
        new_page.close()
        self._page.goto(url)

    # -- Denormalisation (0-999 → pixels) -----------------------------------

    def _dx(self, x: int) -> int:
        return int(x / 1000 * VIEWPORT_WIDTH)

    def _dy(self, y: int) -> int:
        return int(y / 1000 * VIEWPORT_HEIGHT)

    # -- Snapshot -----------------------------------------------------------

    def snapshot(self) -> tuple[bytes, str]:
        """Return (png_bytes, current_url)."""
        self._page.wait_for_load_state()
        time.sleep(0.5)
        shot = self._page.screenshot(type="png", full_page=False)
        return shot, self._page.url

    # -- Actions ------------------------------------------------------------

    def click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y))
        self._page.wait_for_load_state()
        return self.snapshot()

    def double_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.dblclick(self._dx(x), self._dy(y))
        self._page.wait_for_load_state()
        return self.snapshot()

    def triple_click(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.click(self._dx(x), self._dy(y), click_count=3)
        self._page.wait_for_load_state()
        return self.snapshot()

    def type_text(self, text: str, press_enter: bool = False) -> tuple[bytes, str]:
        self._page.keyboard.type(text)
        if press_enter:
            self._page.keyboard.press("Enter")
        self._page.wait_for_load_state()
        return self.snapshot()

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
        return self.snapshot()

    def navigate(self, url: str) -> tuple[bytes, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._page.goto(url)
        self._page.wait_for_load_state()
        return self.snapshot()

    def go_back(self) -> tuple[bytes, str]:
        self._page.go_back()
        self._page.wait_for_load_state()
        return self.snapshot()

    def go_forward(self) -> tuple[bytes, str]:
        self._page.go_forward()
        self._page.wait_for_load_state()
        return self.snapshot()

    def press_key(self, key: str) -> tuple[bytes, str]:
        key_map = {
            "enter": "Enter", "tab": "Tab", "escape": "Escape",
            "backspace": "Backspace", "delete": "Delete",
            "space": "Space", "control": "Control",
        }
        self._page.keyboard.press(key_map.get(key.lower(), key))
        self._page.wait_for_load_state()
        return self.snapshot()

    def hotkey(self, keys: list[str]) -> tuple[bytes, str]:
        for k in keys[:-1]:
            self._page.keyboard.down(k)
        self._page.keyboard.press(keys[-1])
        for k in reversed(keys[:-1]):
            self._page.keyboard.up(k)
        self._page.wait_for_load_state()
        return self.snapshot()

    def move(self, x: int, y: int) -> tuple[bytes, str]:
        self._page.mouse.move(self._dx(x), self._dy(y))
        return self.snapshot()

    def wait_action(self, seconds: int = 1) -> tuple[bytes, str]:
        self._page.wait_for_timeout(seconds * 1000)
        return self.snapshot()

    def take_screenshot(self) -> tuple[bytes, str]:
        return self.snapshot()


# ---------------------------------------------------------------------------
# List of predefined Computer-Use actions (model may call these)
# ---------------------------------------------------------------------------
BROWSER_ACTIONS = {
    "click", "double_click", "triple_click", "middle_click", "right_click",
    "mouse_down", "mouse_up", "move", "type", "drag_and_drop",
    "wait", "press_key", "key_down", "key_up", "hotkey",
    "take_screenshot", "scroll", "go_back", "navigate", "go_forward",
}


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------
def run_research_agent(
    search_query: str = DEFAULT_SEARCH_QUERY,
    headless: bool = False,
    max_turns: int = 50,
) -> str:
    """
    Run the web-research agent.  Returns the path to the generated report.

    ── Architecture overview ──────────────────────────────────────────
    API:         generateContent (full conversation history managed
                 client-side in `contents` list)
    Environment: ENVIRONMENT_BROWSER (headless Chromium via Playwright)
    Tools:       Computer Use  +  TWO custom functions:
                   • save_finding()     — called N times to accumulate data
                   • generate_report()  — called once to signal completion

    What makes this special vs. a basic Computer Use agent:
      • Dual custom function pattern — save_finding() lets the model
        extract structured research data from web pages it browses,
        while generate_report() gives the model an explicit "I'm done"
        signal rather than relying on the absence of function_calls.
      • Findings are accumulated in a Python list and compiled into a
        Markdown report file — demonstrating how Computer Use bridges
        the gap between visual web browsing and structured output.
      • The model navigates Google, visits result pages, reads content
        visually from screenshots, and decides what's worth saving.
    ──────────────────────────────────────────────────────────────────
    """

    # -- Banner -------------------------------------------------------------
    console.print(Panel(
        "[bold cyan]Use Case 4 — Web Research & Report Agent[/bold cyan]\n"
        f'Search: "{search_query}"',
        box=box.DOUBLE,
    ))
    console.print(f"[dim]Timestamp: {datetime.now().isoformat()}[/dim]\n")

    # -- Validate key -------------------------------------------------------
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[bold red]ERROR:[/bold red] GEMINI_API_KEY not set.")
        sys.exit(1)

    # -- SDK client ---------------------------------------------------------
    client = genai.Client(api_key=api_key)
    console.print("[green]✓[/green] Gemini client ready")

    # -- Custom function declarations for the model -------------------------
    # from_callable() inspects the Python function's signature, type hints,
    # and docstring to auto-generate a JSON schema.  The model uses this
    # schema to know what arguments each function accepts.
    save_finding_decl = types.FunctionDeclaration.from_callable(
        client=client, callable=save_finding,
    )
    generate_report_decl = types.FunctionDeclaration.from_callable(
        client=client, callable=generate_report,
    )

    # -- GenerateContent config with Computer Use + custom tools ------------
    # Three tool types available to the model in this conversation:
    #   1. Browser actions (click, type, scroll, …) — from computer_use
    #   2. save_finding()     — custom data-extraction function
    #   3. generate_report()  — custom completion-signal function
    #
    # IMPORTANT: computer_use and function_declarations must be in
    # SEPARATE Tool objects.  Multiple function_declarations CAN share
    # a single Tool (as shown here with save_finding + generate_report).
    gen_config = GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=8192,
        tools=[
            # Tool 1: Computer Use — unlocks the full browser action set
            types.Tool(
                computer_use=types.ComputerUse(
                    environment=types.Environment.ENVIRONMENT_BROWSER,
                ),
            ),
            # Tool 2: Both custom functions in ONE Tool object.
            # (Multiple function_declarations can coexist in the same Tool,
            # unlike computer_use which must be alone in its Tool.)
            types.Tool(
                function_declarations=[save_finding_decl, generate_report_decl],
            ),
        ],
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )

    # -- System prompt ------------------------------------------------------
    system_text = f"""\
You are a web research assistant.  Your job:

1. The browser is open to DuckDuckGo.  Search for: "{search_query}"
2. Browse the first 2-3 search result pages.
3. On each page, extract **key findings** and call the ``save_finding`` tool
   for each distinct insight (with a descriptive title, the page URL, the
   key point, and a category like "hardware", "algorithm", "partnership",
   "investment", or "breakthrough").
4. After collecting findings from 2-3 pages, call ``generate_report`` to
   signal you are done.
5. Finally, output a brief natural-language summary.

Rules:
* You MUST call ``save_finding`` at least once per page visited.
* Call ``generate_report`` exactly once when finished.
* Navigate with clicks and scrolls — read the page content on screen.
* If a page fails to load, use the browser back button and try the next result.
"""

    # -- Launch browser -----------------------------------------------------
    browser = BrowserSession(headless=headless)
    browser.start()

    # -- Initial screenshot -------------------------------------------------
    screenshot, url = browser.snapshot()
    console.print(f"[green]✓[/green] Initial page: {url}\n")

    # -- Conversation history -----------------------------------------------
    contents: list[Content] = [
        Content(role="user", parts=[Part(text=system_text)]),
    ]

    # -- Agent loop ---------------------------------------------------------
    turn = 0
    report_requested = False

    while turn < max_turns and not report_requested:
        turn += 1
        console.rule(f"[bold yellow]Turn {turn}[/bold yellow]")

        # ---- Call the model -----------------------------------------------
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
            console.print("[red]Empty response — retrying[/red]")
            continue

        candidate = response.candidates[0]

        # Append model turn to history
        if candidate.content:
            contents.append(candidate.content)

        # ---- Extract text & function calls --------------------------------
        text_parts = []
        fn_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.function_call:
                    fn_calls.append(part.function_call)

        reasoning = " ".join(text_parts) if text_parts else None

        # If the model is done (no function calls) → finish
        if not fn_calls:
            if candidate.finish_reason == FinishReason.MALFORMED_FUNCTION_CALL:
                continue  # retry
            if reasoning:
                console.print(Panel(reasoning, title="Agent says"))
            break

        # ---- Print reasoning + action summary -----------------------------
        if reasoning:
            console.print(f"  [dim]{reasoning[:200]}…[/dim]" if len(reasoning or "") > 200 else f"  [dim]{reasoning}[/dim]")

        # ---- Execute each function call -----------------------------------
        # The model may emit a MIX of browser actions and custom function
        # calls in a single turn.  For example, it might call
        # save_finding() for content it just read, then click() to
        # navigate to the next search result — all in one response.
        fn_response_parts = []
        for fc in fn_calls:
            args_str = ", ".join(f"{k}={v!r}" for k, v in (fc.args or {}).items())
            console.print(f"  [cyan]▶ {fc.name}[/cyan]({args_str})")

            # --- Custom functions (no screenshot needed) ---
            # These don't change the browser, so their FunctionResponse
            # is a plain JSON dict — no inline_data/screenshot blob.
            if fc.name == "save_finding":
                result = save_finding(**fc.args)  # appends to `findings` list
                fn_response_parts.append(
                    Part(function_response=FunctionResponse(
                        name=fc.name, response=result,
                    ))
                )
                continue

            if fc.name == "generate_report":
                result = generate_report()
                fn_response_parts.append(
                    Part(function_response=FunctionResponse(
                        name=fc.name, response=result,
                    ))
                )
                # generate_report() is our completion signal — set the
                # flag so the outer while-loop exits after this turn.
                report_requested = True
                continue

            # --- Browser (Computer-Use) actions ---
            # These DO change the screen, so every response MUST include
            # a fresh screenshot — the model needs to see what happened
            # (the "Observe" step of the agentic loop).
            screenshot_result = None
            try:
                if fc.name == "click":
                    screenshot_result = browser.click(fc.args["x"], fc.args["y"])
                elif fc.name == "double_click":
                    screenshot_result = browser.double_click(fc.args["x"], fc.args["y"])
                elif fc.name == "triple_click":
                    screenshot_result = browser.triple_click(fc.args["x"], fc.args["y"])
                elif fc.name == "type":
                    screenshot_result = browser.type_text(
                        fc.args["text"],
                        fc.args.get("press_enter", False),
                    )
                elif fc.name == "scroll":
                    screenshot_result = browser.scroll(
                        fc.args["x"], fc.args["y"],
                        fc.args["direction"],
                        fc.args.get("magnitude", 800),
                    )
                elif fc.name == "navigate":
                    screenshot_result = browser.navigate(fc.args["url"])
                elif fc.name == "go_back":
                    screenshot_result = browser.go_back()
                elif fc.name == "go_forward":
                    screenshot_result = browser.go_forward()
                elif fc.name == "press_key":
                    screenshot_result = browser.press_key(fc.args["key"])
                elif fc.name == "hotkey":
                    screenshot_result = browser.hotkey(fc.args["keys"])
                elif fc.name == "move":
                    screenshot_result = browser.move(fc.args["x"], fc.args["y"])
                elif fc.name == "wait":
                    screenshot_result = browser.wait_action(
                        int(fc.args.get("seconds", 1))
                    )
                elif fc.name == "take_screenshot":
                    screenshot_result = browser.take_screenshot()
                else:
                    console.print(f"    [yellow]⚠ Unhandled action: {fc.name}[/yellow]")
                    screenshot_result = browser.snapshot()
            except Exception as exc:
                console.print(f"    [red]✗ {exc}[/red]")
                # Even on error, capture a screenshot so the model can
                # see the current state and decide how to recover.
                screenshot_result = browser.snapshot()

            if screenshot_result:
                shot_bytes, page_url = screenshot_result
                console.print(f"    [dim]→ URL: {page_url}[/dim]")
                # Browser FunctionResponse includes a screenshot blob
                # so the model can visually observe the action's effect.
                fn_response_parts.append(
                    Part(function_response=FunctionResponse(
                        name=fc.name,
                        response={"url": page_url},
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=shot_bytes,
                                )
                            )
                        ],
                    ))
                )

        # Append ALL function responses as a single "user" turn.
        # The Gemini API requires FunctionResponse parts to have role="user".
        contents.append(Content(role="user", parts=fn_response_parts))

        # ── Screenshot pruning (context window management) ────────────
        # Screenshots are ~100-300 KB base64 each.  Over many turns they
        # can exceed the model's context window.  We strip binary data
        # from older turns, keeping text metadata (URL, action name)
        # so the model still knows what happened.
        _prune_old_screenshots(contents, keep_recent=3)

    # -- Shut down browser --------------------------------------------------
    browser.stop()
    console.print("\n[green]✓[/green] Browser closed")

    # -- Generate and save the markdown report ------------------------------
    # _write_report() reads from the global `findings` list that was
    # populated by save_finding() calls during the agentic loop.
    # This is the payoff of the dual-function pattern: the model
    # collected structured data while browsing, and now we compile it.
    report_path = _write_report(search_query)
    console.print(f"[green]✓[/green] Report saved to: {report_path}\n")

    # -- Findings table -----------------------------------------------------
    if findings:
        table = Table(
            title=f"Collected Findings ({len(findings)})",
            box=box.ROUNDED,
            show_lines=True,
        )
        table.add_column("#", style="bold", width=3)
        table.add_column("Title", ratio=2)
        table.add_column("Category", ratio=1)
        table.add_column("Source", ratio=2)
        for i, f in enumerate(findings, 1):
            table.add_row(
                str(i),
                f["title"],
                f["category"],
                f["source_url"][:60] + ("…" if len(f["source_url"]) > 60 else ""),
            )
        console.print(table)

    return report_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prune_old_screenshots(contents: list[Content], keep_recent: int = 3):
    """Remove screenshot blobs from all but the most recent N user turns."""
    screenshot_turn_count = 0
    for content in reversed(contents):
        if content.role != "user" or not content.parts:
            continue
        has_screenshot = any(
            p.function_response and p.function_response.parts
            for p in content.parts
            if p.function_response
        )
        if has_screenshot:
            screenshot_turn_count += 1
            if screenshot_turn_count > keep_recent:
                for p in content.parts:
                    if p.function_response and p.function_response.parts:
                        p.function_response.parts = None


def _write_report(search_query: str) -> str:
    """Compile all findings into a Markdown file and save it.

    This function reads from the global `findings` list that was
    populated by save_finding() calls during the agentic loop.
    Each finding dict contains: title, source_url, key_point,
    category, and timestamp — all structured data that the model
    extracted from visual screenshots and passed through the
    custom function interface.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_query = search_query.replace(" ", "_")[:40]
    filename = f"report_{safe_query}_{timestamp}.md"
    report_dir = os.path.dirname(os.path.abspath(__file__))
    report_path = os.path.join(report_dir, filename)

    # Build the Markdown report from the accumulated findings.
    # Each finding becomes a ## section with metadata and key insight.
    lines = [
        f"# Research Report: {search_query.title()}",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Model:** {MODEL_NAME}  ",
        f"**Total Findings:** {len(findings)}",
        "",
        "---",
        "",
    ]

    if not findings:
        lines.append("_No findings were collected during this session._")
    else:
        # Each dict in `findings` was created by a save_finding() call
        # that the model made while reading a web page's screenshot.
        for i, f in enumerate(findings, 1):
            lines.extend([
                f"## Finding {i}: {f['title']}",
                "",
                f"**Source:** {f['source_url']}  ",
                f"**Category:** {f['category']}  ",
                f"**Collected:** {f['timestamp']}",
                "",
                f"{f['key_point']}",
                "",
                "---",
                "",
            ])

    lines.extend([
        "## Methodology",
        "",
        "This report was generated automatically by the Web Research & Report Agent.",
        f'The agent searched DuckDuckGo for "{search_query}", visited the top results,',
        "and used the `save_finding` tool to programmatically extract key insights.",
        "",
    ])

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Web Research & Report Agent — Gemini Computer Use + Custom Functions"
    )
    parser.add_argument(
        "--search", "-s",
        default=DEFAULT_SEARCH_QUERY,
        help=f'Search query (default: "{DEFAULT_SEARCH_QUERY}").',
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium in headless mode (no visible window).",
    )
    parser.add_argument(
        "--max-turns", "-t",
        type=int,
        default=50,
        help="Maximum agent turns (default 50).",
    )
    args = parser.parse_args()

    path = run_research_agent(
        search_query=args.search,
        headless=args.headless,
        max_turns=args.max_turns,
    )
    console.print(f"\n[bold green]✓ Done — report at:[/bold green] {path}")
