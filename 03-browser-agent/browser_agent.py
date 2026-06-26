#!/usr/bin/env python3
"""
browser_agent.py — Multi-step agentic browser automation with Gemini Computer Use.

This script implements a full observe-think-act loop:

    1. The user provides a natural-language task (e.g. "Find today's top HN stories").
    2. The agent takes a screenshot of the browser, sends it to the Gemini model
       together with the conversation history, and asks the model what to do next.
    3. The model returns one or more function calls (click, type, scroll …).
    4. The agent executes each action via the PlaywrightEnvironment, captures a
       fresh screenshot, and feeds the result back to the model.
    5. Steps 2-4 repeat until the model decides the task is done and responds
       with a plain-text summary.

Run:
    export GEMINI_API_KEY="your-key-here"
    python browser_agent.py --task "Go to https://news.ycombinator.com and tell me the top 3 stories"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory

from google import genai
from google.genai import types
from google.genai.types import (
    Content,
    FunctionResponse,
    GenerateContentConfig,
    Part,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Local import — the PlaywrightEnvironment lives in the same package
from playwright_env import PlaywrightEnvironment

# ---------------------------------------------------------------------------
# Rich console for formatted terminal output
# ---------------------------------------------------------------------------
console = Console()

# ---------------------------------------------------------------------------
# All computer-use function names the model may emit (gemini-3.5-flash)
# ---------------------------------------------------------------------------
# The model doesn't use a fixed schema you define — instead, when you pass
# the ComputerUse tool, the model has a *built-in* set of actions it knows
# how to emit as function_calls. This set lists every possible action name
# so we can identify computer-use FunctionResponses during screenshot pruning.
COMPUTER_USE_ACTIONS: set[str] = {
    "click",
    "double_click",
    "triple_click",
    "middle_click",
    "right_click",
    "mouse_down",
    "mouse_up",
    "move",
    "type",
    "drag_and_drop",
    "wait",
    "press_key",
    "key_down",
    "key_up",
    "hotkey",
    "take_screenshot",
    "scroll",
    "go_back",
    "go_forward",
    "navigate",
}


class BrowserAgent:
    """Autonomous browser agent powered by Gemini Computer Use.

    The agent maintains a full conversation history with the model, executes
    browser actions through a PlaywrightEnvironment, and prunes old screenshots
    from the context window to avoid hitting token limits.
    """

    # System-level instructions injected at the start of each conversation
    SYSTEM_PROMPT = (
        "You are a precise browser automation agent. You observe the current "
        "browser state via screenshots and control it with the provided tools.\n\n"
        "Operating guidelines:\n"
        "• Study the screenshot carefully before choosing an action.\n"
        "• Click on the exact visual centre of target elements.\n"
        "• After typing into a search box, press Enter to submit if needed.\n"
        "• If the page appears to be loading, use the wait action.\n"
        "• Do NOT repeat an identical action more than twice in a row.\n"
        "• When the task is fully complete, stop issuing function calls and "
        "return a concise text summary of what you accomplished and the "
        "information you found."
    )

    # How many recent turns may carry full screenshot blobs
    MAX_SCREENSHOTS_IN_HISTORY = 3

    # Hard cap on observe-act iterations to prevent infinite loops
    MAX_ITERATIONS = 25

    # API retry parameters
    MAX_API_RETRIES = 3
    INITIAL_RETRY_DELAY_S = 2.0

    def __init__(
        self,
        env: PlaywrightEnvironment,
        model: str = "gemini-3.5-flash",
    ) -> None:
        self._env = env
        self._model = model

        # Initialise the Gemini SDK client using the API key from env
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            console.print(
                "[bold red]ERROR:[/] GEMINI_API_KEY environment variable is not set."
            )
            sys.exit(1)
        self._client = genai.Client(api_key=api_key)

        # Conversation history — a list of Content objects
        self._history: list[Content] = []

        # ── GenerateContent Configuration ──────────────────────────────
        # This config object controls both the model's behaviour and the
        # tools it has access to.
        #
        # • temperature=1 is the *required* setting for Computer Use.
        #   Lower values (e.g. 0) degrade the model's ability to reason
        #   about visual layouts. The API may reject other values.
        #
        # • The `tools` list declares a single ComputerUse tool. The
        #   `environment` parameter tells the model what kind of surface
        #   it is controlling. ENVIRONMENT_BROWSER unlocks browser-specific
        #   actions (navigate, go_back, scroll, etc.) that wouldn't appear
        #   for ENVIRONMENT_DESKTOP or ENVIRONMENT_MOBILE.
        #
        # • ThinkingConfig(include_thoughts=True) enables "extended
        #   thinking" — the model produces internal chain-of-thought
        #   reasoning *before* deciding on an action. These thoughts are
        #   returned as parts with `part.thought == True` so you can
        #   display them for debugging without affecting the action flow.
        self._config = GenerateContentConfig(
            system_instruction=self.SYSTEM_PROMPT,
            temperature=1,
            top_p=0.95,
            max_output_tokens=8192,
            tools=[
                types.Tool(
                    computer_use=types.ComputerUse(
                        environment=types.Environment.ENVIRONMENT_BROWSER,
                    ),
                ),
            ],
            thinking_config=types.ThinkingConfig(include_thoughts=True),
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, task: str) -> str:
        """Execute *task* and return the model's final text summary.

        Parameters
        ----------
        task : str
            A natural-language description of what the agent should do.

        Returns
        -------
        str
            The model's concluding summary text.
        """
        console.rule("[bold cyan]Browser Agent Starting[/]")
        console.print(f"[bold]Task:[/] {task}\n")

        # Step 1 — Seed the conversation with the user's task
        self._history.append(
            Content(role="user", parts=[Part(text=task)])
        )

        # Step 2 — Capture an initial screenshot so the model sees the browser
        # The model is purely vision-based for Computer Use — it needs at
        # least one screenshot to understand the current browser state before
        # it can decide what action to take.
        initial_png = self._env.screenshot()
        self._history.append(
            Content(
                role="user",
                parts=[
                    Part(text="Here is the current browser screenshot:"),
                    Part.from_bytes(data=initial_png, mime_type="image/png"),
                ],
            ),
        )
        console.print("[dim]Initial screenshot captured.[/]\n")

        # ── Step 3 — The Agentic Loop ─────────────────────────────────
        # This is the core observe → think → act cycle:
        #
        #   1. OBSERVE: Send the conversation (with screenshots) to the model.
        #   2. THINK:   The model analyses the screenshot and decides what
        #               to do next, returning function_call(s) or plain text.
        #   3. ACT:     We execute each function_call in the browser, capture
        #               a fresh screenshot, and send the result back as a
        #               FunctionResponse.
        #   4. REPEAT:  Go back to step 1 until the model responds with
        #               plain text instead of function_calls (signalling
        #               the task is complete).
        #
        # The loop is capped at MAX_ITERATIONS to prevent runaway agents.
        for iteration in range(1, self.MAX_ITERATIONS + 1):
            console.rule(f"[bold magenta]Iteration {iteration}[/]")

            # 3a. Call the model
            response = self._call_model_with_retries()
            if response is None:
                console.print("[bold red]Model failed after retries. Aborting.[/]")
                return "Agent terminated — model API failures."

            # Validate the response has usable content
            if not response.candidates:
                console.print("[bold red]Empty response from model.[/]")
                return "Agent terminated — empty model response."

            candidate = response.candidates[0]

            # 3b. Append the model's turn to history
            if candidate.content:
                self._history.append(candidate.content)

            # 3c. Separate thoughts, text, and function calls
            thoughts, text_parts, fn_calls = self._parse_candidate(candidate)

            # Display the model's thinking (if any)
            if thoughts:
                console.print(
                    Panel(
                        thoughts,
                        title="[bold yellow]Model Thinking[/]",
                        border_style="yellow",
                        expand=False,
                    )
                )

            # 3d. If there are NO function calls → the task is done
            # This is how the agentic loop terminates naturally: when the
            # model believes the task is complete, it returns a plain-text
            # summary instead of function_calls. No special "done" signal
            # is needed — the *absence* of function_calls IS the signal.
            if not fn_calls:
                final_text = text_parts or "(no text returned)"
                console.print()
                console.rule("[bold green]Task Complete[/]")
                console.print(f"\n[bold]Agent Summary:[/] {final_text}\n")
                return final_text

            # 3e. Execute each function call and collect FunctionResponses
            fn_responses: list[FunctionResponse] = []
            for fc in fn_calls:
                # Safety-decision gate
                if not self._safety_gate(fc):
                    console.print("[bold red]User declined safety confirmation. Stopping.[/]")
                    return "Agent terminated by user (safety decision)."

                # Print action details
                self._print_action(fc)

                # Dispatch the action to the browser environment
                try:
                    self._dispatch_action(fc)
                except Exception as exc:
                    console.print(f"[red]Action error:[/] {exc}")

                # ── FunctionResponse with Screenshot ──────────────────
                # After every action, capture a fresh screenshot and send
                # it back to the model inside the FunctionResponse. This
                # is the "observe" half of the loop — the model needs to
                # *see* the result of its action to decide what to do next.
                #
                # The FunctionResponse carries two pieces of information:
                #   1. `response` — a dict of structured metadata (here,
                #      the current URL) the model can read as text.
                #   2. `parts` — a list with a FunctionResponseBlob
                #      containing the raw PNG screenshot bytes. This is
                #      the Computer-Use-specific mechanism for attaching
                #      a screenshot to a function response.
                post_png = self._env.screenshot()
                current_url = self._env.current_url

                console.print(
                    f"  [dim]→ Screenshot captured  |  URL: {current_url}[/]"
                )

                fn_responses.append(
                    FunctionResponse(
                        name=fc.name,
                        response={"url": current_url},
                        parts=[
                            types.FunctionResponsePart(
                                inline_data=types.FunctionResponseBlob(
                                    mime_type="image/png",
                                    data=post_png,
                                ),
                            ),
                        ],
                    )
                )

            # 3f. Append the function-response turn to the conversation
            # Note: FunctionResponse turns use role="user" — the model
            # treats them as observations from the environment, not as
            # model output. This is the generateContent (client-managed
            # history) approach where we own the full conversation list.
            self._history.append(
                Content(
                    role="user",
                    parts=[Part(function_response=fr) for fr in fn_responses],
                )
            )

            # 3g. Prune old screenshots to keep context manageable
            # Screenshots are large (~100-300 KB each as base64), so a
            # 25-iteration conversation could easily blow past token
            # limits. We strip binary data from all but the most recent
            # turns after every iteration. See _prune_old_screenshots().
            self._prune_old_screenshots()

            console.print()  # visual separator

        # If we exhaust iterations, return whatever we have
        console.print("[bold yellow]Maximum iterations reached.[/]")
        return "Agent stopped — maximum iteration limit reached."

    # ------------------------------------------------------------------
    # Model communication
    # ------------------------------------------------------------------
    def _call_model_with_retries(self) -> types.GenerateContentResponse | None:
        """Call generate_content with exponential-backoff retries.

        Computer Use conversations involve many sequential API calls (one
        per iteration of the agentic loop). Transient failures — rate
        limits (429), server errors (503) — are common, so retry logic
        is essential for a robust agent.

        We use exponential backoff: 2s → 4s → 8s between attempts.
        """
        delay = self.INITIAL_RETRY_DELAY_S

        for attempt in range(1, self.MAX_API_RETRIES + 1):
            try:
                with console.status(
                    f"[bold cyan]Calling Gemini ({self._model})…[/]",
                    spinner="dots",
                ):
                    # This is the generateContent (client-managed history)
                    # approach: we pass the full conversation list in
                    # `contents`. The alternative is the Interactions API,
                    # where the server manages state via
                    # `previous_interaction_id` and you only send the new
                    # turn each time.
                    response = self._client.models.generate_content(
                        model=self._model,
                        contents=self._history,
                        config=self._config,
                    )
                return response

            except Exception as exc:
                console.print(
                    f"[yellow]API attempt {attempt}/{self.MAX_API_RETRIES} "
                    f"failed:[/] {exc}"
                )
                if attempt < self.MAX_API_RETRIES:
                    console.print(f"[dim]Retrying in {delay:.0f}s…[/]")
                    time.sleep(delay)
                    delay *= 2  # exponential backoff

        return None  # all retries exhausted

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_candidate(
        candidate: types.Candidate,
    ) -> tuple[str, str, list[types.FunctionCall]]:
        """Extract thinking text, plain text, and function calls from a candidate.

        Returns (thoughts, text, function_calls).
        """
        thoughts_parts: list[str] = []
        text_parts: list[str] = []
        fn_calls: list[types.FunctionCall] = []

        if not candidate.content or not candidate.content.parts:
            return "", "", []

        # ── Three kinds of parts in a Computer Use response ───────────
        # A single model response can contain a mix of:
        #   1. Thought parts — internal chain-of-thought reasoning
        #      (only present when ThinkingConfig is enabled). These have
        #      `part.thought == True` AND `part.text` set.
        #   2. Text parts — the model's visible output. When the model
        #      returns text *without* function_calls, the task is done.
        #   3. Function-call parts — browser actions the model wants to
        #      execute. Each has a `.name` (e.g. "click") and `.args`
        #      dict with parameters (e.g. {"x": 450, "y": 320}).
        #      The `.args` may also include an `intent` string
        #      explaining what the model is trying to achieve.
        for part in candidate.content.parts:
            if part.thought and part.text:
                thoughts_parts.append(part.text)
            elif part.text:
                text_parts.append(part.text)
            elif part.function_call:
                fn_calls.append(part.function_call)

        return (
            "\n".join(thoughts_parts),
            " ".join(text_parts),
            fn_calls,
        )

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    # ── Coordinate Denormalization ─────────────────────────────────────
    # The Gemini model outputs ALL coordinates in a normalised 0-999
    # virtual grid, regardless of the actual screen resolution. This
    # decouples the model from specific viewport sizes.
    #
    # To convert to real pixel coordinates:
    #   pixel_x = int(normalised_x / 1000 * viewport_width)
    #   pixel_y = int(normalised_y / 1000 * viewport_height)
    #
    # Example: model says click(x=500, y=250) on a 1280×800 viewport:
    #   pixel_x = int(500 / 1000 * 1280) = 640
    #   pixel_y = int(250 / 1000 * 800)  = 200
    def _denorm_x(self, normalised: int | float) -> int:
        """Convert a 0-999 normalised X coordinate to a pixel coordinate."""
        return int(float(normalised) / 1000.0 * self._env._width)

    def _denorm_y(self, normalised: int | float) -> int:
        """Convert a 0-999 normalised Y coordinate to a pixel coordinate."""
        return int(float(normalised) / 1000.0 * self._env._height)

    def _dispatch_action(self, fc: types.FunctionCall) -> None:
        """Execute a single function-call on the PlaywrightEnvironment.

        Each branch denormalises any coordinates the model provided (which
        arrive in the 0-999 range) into actual pixel values, then calls the
        corresponding environment method.

        This is a straightforward dispatch pattern — match the function_call
        name to the corresponding environment method. The model's built-in
        ComputerUse tool defines the action vocabulary; we just translate
        each action into Playwright API calls.
        """
        name = fc.name
        args: dict[str, Any] = dict(fc.args) if fc.args else {}

        # --- Mouse clicks ---------------------------------------------------
        if name == "click":
            self._env.click(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "double_click":
            self._env.double_click(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "triple_click":
            self._env.triple_click(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "right_click":
            self._env.right_click(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "middle_click":
            self._env.middle_click(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        # --- Mouse movement / low-level controls ----------------------------
        elif name == "move":
            self._env.move(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "mouse_down":
            self._env.mouse_down(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "mouse_up":
            self._env.mouse_up(self._denorm_x(args["x"]), self._denorm_y(args["y"]))

        elif name == "drag_and_drop":
            self._env.drag_and_drop(
                start_x=self._denorm_x(args["x"]),
                start_y=self._denorm_y(args["y"]),
                end_x=self._denorm_x(args["destination_x"]),
                end_y=self._denorm_y(args["destination_y"]),
            )

        # --- Keyboard --------------------------------------------------------
        elif name == "type":
            text = args.get("text", "")
            self._env.type_text(text)
            # The model can optionally request an Enter press after typing
            if args.get("press_enter", False):
                self._env.press_key("Enter")

        elif name == "press_key":
            self._env.press_key(args["key"])

        elif name == "key_down":
            self._env.key_down(args["key"])

        elif name == "key_up":
            self._env.key_up(args["key"])

        elif name == "hotkey":
            keys = args.get("keys", [])
            if isinstance(keys, str):
                keys = keys.split("+")
            self._env.hotkey(keys)

        # --- Scrolling -------------------------------------------------------
        elif name == "scroll":
            px = self._denorm_x(args["x"])
            py = self._denorm_y(args["y"])
            direction = args["direction"]

            # The model sends magnitude in the 0-999 normalised space,
            # just like coordinates. We denormalise it into pixels using
            # the appropriate axis, then convert to discrete "ticks"
            # because Playwright's mouse.wheel() works in pixel deltas
            # and we want consistent scroll increments.
            raw_magnitude = args.get("magnitude", 300)
            if direction in ("up", "down"):
                pixel_mag = self._denorm_y(raw_magnitude)
            else:
                pixel_mag = self._denorm_x(raw_magnitude)

            # Convert pixel magnitude to "scroll ticks" (≈100px each)
            ticks = max(1, pixel_mag // 100)
            self._env.scroll(px, py, direction, amount=ticks)

        # --- Navigation ------------------------------------------------------
        elif name == "navigate":
            self._env.navigate(args["url"])

        elif name == "go_back":
            self._env.go_back()

        elif name == "go_forward":
            self._env.go_forward()

        # --- Timing / observation --------------------------------------------
        elif name == "wait":
            secs = float(args.get("seconds", 2))
            self._env.wait(secs)

        elif name == "take_screenshot":
            pass  # screenshot is taken automatically after every action

        else:
            console.print(f"[yellow]Warning: unrecognised action '{name}' — skipping.[/]")

    # ------------------------------------------------------------------
    # Screenshot pruning (context window management)
    # ------------------------------------------------------------------
    def _prune_old_screenshots(self) -> None:
        """Remove screenshot blobs from all but the most recent turns.

        Walking the history in reverse, count how many user turns carry
        a computer-use screenshot.  Any beyond MAX_SCREENSHOTS_IN_HISTORY
        have their binary blob stripped to save tokens.
        """
        # ── Why pruning is necessary ──────────────────────────────────
        # Each PNG screenshot is ~100-300 KB, which becomes a significant
        # number of tokens when base64-encoded for the API. Over a
        # 25-iteration session, that could be 2.5-7.5 MB of images —
        # easily exceeding the context window.
        #
        # Strategy: walk backwards through history, keep the N most
        # recent screenshots intact (the model needs recent context to
        # understand what just happened), and null out the binary blobs
        # in older turns. We preserve the textual `response` dict
        # (e.g. {"url": "..."}), so the model still knows *what*
        # happened, just not the visual details.
        screenshots_seen = 0

        for content in reversed(self._history):
            if content.role != "user" or not content.parts:
                continue

            # Does this turn contain a computer-use FunctionResponse with parts?
            has_screenshot = any(
                p.function_response
                and p.function_response.parts
                and p.function_response.name in COMPUTER_USE_ACTIONS
                for p in content.parts
            )
            if not has_screenshot:
                continue

            screenshots_seen += 1
            if screenshots_seen > self.MAX_SCREENSHOTS_IN_HISTORY:
                # Strip the binary data but keep the textual response dict
                # Setting parts to None removes the screenshot blob while
                # keeping the FunctionResponse itself (with its `response`
                # dict and `name`) intact in the conversation history.
                for part in content.parts:
                    if (
                        part.function_response
                        and part.function_response.parts
                        and part.function_response.name in COMPUTER_USE_ACTIONS
                    ):
                        part.function_response.parts = None

    # ------------------------------------------------------------------
    # Safety decision handling
    # ------------------------------------------------------------------
    def _safety_gate(self, fc: types.FunctionCall) -> bool:
        """Check if the function call contains a safety_decision.

        If the model flags an action as needing explicit user confirmation,
        prompt the user interactively.  Returns True to proceed, False to stop.
        """
        # ── What are safety decisions? ────────────────────────────────
        # For certain sensitive actions (e.g. submitting a form with
        # personal data, confirming a purchase, or clicking a
        # destructive button), the model may attach a `safety_decision`
        # field to the function_call's args. This is the model's way
        # of saying "I think this action has real-world consequences —
        # please confirm with the user before proceeding."
        #
        # The safety_decision dict typically contains:
        #   - "decision": a label like "confirm" or "block"
        #   - "explanation": why the model flagged this action
        #
        # It is the agent developer's responsibility to check for this
        # field and implement appropriate human-in-the-loop gating.
        if not fc.args:
            return True

        safety = fc.args.get("safety_decision")
        if not safety:
            return True

        # Display the safety warning
        console.print()
        console.print(
            Panel(
                f"[bold]Decision:[/] {safety.get('decision', 'unknown')}\n\n"
                f"[bold]Explanation:[/] {safety.get('explanation', 'No details.')}",
                title="⚠️  Safety Confirmation Required",
                border_style="bold yellow",
            )
        )

        # Ask the user whether to continue
        while True:
            choice = input("Proceed with this action? [y/n]: ").strip().lower()
            if choice in ("y", "yes"):
                return True
            if choice in ("n", "no"):
                return False
            print("Please enter 'y' or 'n'.")

    # ------------------------------------------------------------------
    # Pretty-printing helpers
    # ------------------------------------------------------------------
    def _print_action(self, fc: types.FunctionCall) -> None:
        """Display a formatted summary of a function call."""
        # Build a compact argument string
        arg_strs: list[str] = []
        if fc.args:
            for key, value in fc.args.items():
                if key == "safety_decision":
                    continue  # already handled separately
                # Denormalise coordinate values for display
                display_val = value
                if key in ("x", "destination_x") and isinstance(value, (int, float)):
                    display_val = f"{value} → {self._denorm_x(value)}px"
                elif key in ("y", "destination_y") and isinstance(value, (int, float)):
                    display_val = f"{value} → {self._denorm_y(value)}px"
                arg_strs.append(f"[cyan]{key}[/]={display_val}")

        args_display = ", ".join(arg_strs) if arg_strs else "[dim]none[/]"
        console.print(f"  [bold green]▶ {fc.name}[/]({args_display})")


# ===========================================================================
# CLI entry point
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gemini Computer Use — Multi-step Browser Agent (Tutorial Step 03)",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=(
            "Go to https://news.ycombinator.com and tell me the title "
            "of the top 3 stories on the front page right now."
        ),
        help="Natural-language task for the agent to perform.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.5-flash",
        help="Gemini model name (default: gemini-3.5-flash).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Browser viewport width in pixels.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=800,
        help="Browser viewport height in pixels.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser without a visible window.",
    )
    args = parser.parse_args()

    console.print(
        Panel(
            "[bold]Gemini Computer Use — Browser Agent[/]\n"
            f"Model: {args.model}  |  Viewport: {args.width}×{args.height}  |  "
            f"Headless: {args.headless}",
            border_style="blue",
        )
    )

    # Create the browser environment and run the agent
    with PlaywrightEnvironment(
        width=args.width,
        height=args.height,
        headless=args.headless,
    ) as env:
        agent = BrowserAgent(env=env, model=args.model)
        result = agent.run(task=args.task)

    # Final output
    console.print()
    console.rule("[bold blue]Final Result[/]")
    console.print(f"\n{result}\n")


if __name__ == "__main__":
    main()
