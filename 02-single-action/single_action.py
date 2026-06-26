"""
Step 02 — Single Action
========================
Minimal viable Computer Use example: one screenshot → one click.

This script demonstrates the complete Computer Use round-trip:
  1. Open Wikipedia's portal page in Playwright.
  2. Screenshot the page and send it to Gemini 3.5 Flash with the
     Computer Use tool enabled.
  3. Ask the model to click the English Wikipedia link.
  4. The model responds with a `click` function_call containing
     normalized coordinates (0-999).
  5. Denormalize those coordinates to actual pixel values and
     execute the click via Playwright.
  6. Take a verification screenshot to confirm the action worked.

Usage:
    export GEMINI_API_KEY="your-key-here"
    python single_action.py
"""

# ── Imports ──────────────────────────────────────────────────────────────
import os
import sys
import time

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory

from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types

# ── Constants ────────────────────────────────────────────────────────────

# Wikipedia's portal page — the multilingual landing page with links to
# every language edition.  A perfect target because the English link is
# prominent and visually distinct.
TARGET_URL = "https://www.wikipedia.org"

# Fixed viewport — Computer Use needs consistent, known dimensions so
# we can accurately convert the model's normalised coordinates.
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800

# Gemini model with Computer Use support.
MODEL_NAME = "gemini-3.5-flash"


# ── Helper: step logger ─────────────────────────────────────────────────

def log_step(step_number: int, action: str, detail: str = "") -> None:
    """Print a clearly formatted step marker."""
    print(f"\n{'='*64}")
    print(f"  Step {step_number} → {action}")
    if detail:
        print(f"  {detail}")
    print(f"{'='*64}\n")


# ── Helper: coordinate denormalisation ───────────────────────────────────

def denormalize(norm_x: float, norm_y: float) -> tuple[int, int]:
    """Convert Gemini's 0-999 normalised coordinates to real pixels.

    The Computer Use model always outputs coordinates in a 0-999 space
    regardless of the actual screen size.  To map them back:

        pixel = int(normalised_value / 1000 * screen_dimension)

    For a 1280×800 viewport:
        norm 500, 500  →  pixel 640, 400  (centre of the screen)
    """
    pixel_x = int(norm_x / 1000 * SCREEN_WIDTH)
    pixel_y = int(norm_y / 1000 * SCREEN_HEIGHT)
    return pixel_x, pixel_y


# ── Helper: capture a screenshot from Playwright ────────────────────────

def capture_screenshot(page) -> bytes:
    """Wait for the page to settle, then grab a PNG screenshot."""
    page.wait_for_load_state("load")
    # Brief pause so any late JS rendering finishes.
    time.sleep(0.5)
    return page.screenshot(type="png", full_page=False)


# ── Helper: save screenshot to disk ─────────────────────────────────────

def save_screenshot(data: bytes, filename: str) -> str:
    """Write raw PNG bytes to a file next to this script.  Returns the path."""
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


# ── Main logic ───────────────────────────────────────────────────────────

def main() -> None:
    # ------------------------------------------------------------------
    # 0.  Validate the API key
    # ------------------------------------------------------------------
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set the GEMINI_API_KEY environment variable first.")
        print("  export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    print("✓ Gemini client initialised")

    # ------------------------------------------------------------------
    # Step 1.  Launch browser & open Wikipedia portal
    # ------------------------------------------------------------------
    log_step(1, "Launch browser", f"Navigating to {TARGET_URL}")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT}
    )
    page = context.new_page()
    page.goto(TARGET_URL, wait_until="networkidle")

    print(f"  → Page loaded : {page.title()}")
    print(f"  → Current URL : {page.url}")
    print(f"  → Viewport    : {SCREEN_WIDTH}×{SCREEN_HEIGHT}")

    # ------------------------------------------------------------------
    # Step 2.  Take initial screenshot
    # ------------------------------------------------------------------
    log_step(2, "Capture screenshot", "Grabbing the Wikipedia portal page")

    initial_screenshot = capture_screenshot(page)
    saved_path = save_screenshot(initial_screenshot, "01_before_click.png")

    print(f"  → Screenshot size : {len(initial_screenshot) / 1024:.1f} KB")
    print(f"  → Saved to        : {saved_path}")

    # ------------------------------------------------------------------
    # Step 3.  Send screenshot to Gemini with Computer Use enabled
    # ------------------------------------------------------------------
    log_step(
        3,
        "Ask Gemini to click",
        "Sending screenshot + instruction with Computer Use tool",
    )

    # ── COMPUTER USE CONCEPT: Tool Declaration ──────────────────────
    # Unlike regular function calling where you define your own functions,
    # Computer Use is a BUILT-IN tool type. When you include it, the model
    # gains the ability to:
    #   - Analyze screenshots to understand what's on screen
    #   - Return function_calls like click(x, y), type(text), scroll(), etc.
    #   - Plan multi-step interactions based on visual feedback
    #
    # The `environment` parameter tells the model what kind of UI it's
    # controlling, which affects the available actions:
    #   - ENVIRONMENT_BROWSER: click, type, scroll, navigate, go_back, etc.
    #   - ENVIRONMENT_MOBILE:  tap, swipe, long_press, open_app, etc.
    #   - ENVIRONMENT_DESKTOP: similar to browser but with OS-level actions
    # ─────────────────────────────────────────────────────────────────
    computer_use_tool = types.Tool(
        computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER,
        )
    )

    # Build the request contents:
    #   - A text instruction telling the model what to do
    #   - The screenshot as inline image data so the model can see the page
    request_contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=(
                    "I'm on the Wikipedia portal page. "
                    "Please click on the English Wikipedia link."
                )),
                types.Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial_screenshot,
                    )
                ),
            ],
        )
    ]

    # Send the request with Computer Use enabled.
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=request_contents,
            config=types.GenerateContentConfig(
                tools=[computer_use_tool],
            ),
        )
    except Exception as exc:
        print(f"  ✗ Gemini API call failed: {exc}")
        context.close()
        browser.close()
        pw.stop()
        sys.exit(1)

    print("  → Response received from Gemini")

    # ------------------------------------------------------------------
    # Step 4.  Parse the model's response — find the function_call
    # ------------------------------------------------------------------
    log_step(4, "Parse response", "Extracting the function call from the model")

    if not response.candidates or not response.candidates[0].content:
        print("  ✗ No candidates returned — the model may have been blocked.")
        context.close()
        browser.close()
        pw.stop()
        sys.exit(1)

    # Walk through the response parts.  The model may return a mix of:
    #   - text parts (its reasoning / thinking)
    #   - function_call parts (the action it wants to perform)
    function_call = None
    model_reasoning = []

    for part in response.candidates[0].content.parts:
        if part.text:
            model_reasoning.append(part.text)
        if part.function_call:
            function_call = part.function_call

    # Print any reasoning the model shared.
    if model_reasoning:
        print("  Model reasoning:")
        for line in model_reasoning:
            # Truncate very long reasoning to keep output readable
            display = line.strip()[:200]
            print(f"    → {display}")
        print()

    if function_call is None:
        print("  ✗ No function_call found in the response.")
        print("    The model responded with text only — it may not have")
        print("    understood the instruction. Try running again.")
        context.close()
        browser.close()
        pw.stop()
        sys.exit(1)

    # ── COMPUTER USE CONCEPT: Function Call Response ──────────────
    # The model returns a function_call with:
    #   - name: the action type ("click", "type", "scroll", etc.)
    #   - args: a dict with action-specific parameters
    #     - For click: x, y (normalized 0-999), intent (explanation)
    #     - For type: text, press_enter (bool), intent
    #     - For scroll: x, y, direction, amount, intent
    #   - The "intent" field is the model's explanation of WHY it chose
    #     this action — useful for debugging and logging
    # ─────────────────────────────────────────────────────────────────
    print(f"  Function call received:")
    print(f"    Name : {function_call.name}")
    if function_call.args:
        for key, value in function_call.args.items():
            print(f"    {key:5}: {value}")

    # ------------------------------------------------------------------
    # Step 5.  Denormalize coordinates & execute the click
    # ------------------------------------------------------------------
    log_step(5, "Execute click", "Converting coordinates and clicking")

    # ── COMPUTER USE CONCEPT: Coordinate Denormalization ──────────
    # The model ALWAYS returns coordinates in a 0-999 grid, regardless
    # of the actual screen resolution. This makes the model resolution-
    # independent — the same coordinates mean the same relative position
    # on a 1280x800 screen or a 3840x2160 screen.
    #
    # YOU are responsible for converting to actual pixels:
    #   pixel_x = int(norm_x / 1000 * screen_width)
    #   pixel_y = int(norm_y / 1000 * screen_height)
    #
    # Example with our 1280x800 viewport:
    #   norm (500, 500) → pixel (640, 400) — center of screen
    #   norm (0, 0)     → pixel (0, 0)     — top-left corner
    #   norm (999, 999) → pixel (1278, 799) — bottom-right corner
    #
    # CRITICAL: Forgetting to denormalize is the #1 cause of "clicks
    # landing in the wrong place" bugs!
    # ─────────────────────────────────────────────────────────────────
    norm_x = function_call.args.get("x", 0)
    norm_y = function_call.args.get("y", 0)

    pixel_x, pixel_y = denormalize(norm_x, norm_y)

    print(f"  Coordinate conversion:")
    print(f"    Normalised  : ({norm_x}, {norm_y})  [0-999 space]")
    print(f"    Pixel       : ({pixel_x}, {pixel_y})  [{SCREEN_WIDTH}×{SCREEN_HEIGHT} viewport]")
    print()

    # Perform the actual click in the browser.
    page.mouse.click(pixel_x, pixel_y)

    # Give the page a moment to navigate.
    page.wait_for_load_state("load")
    time.sleep(1.0)

    print(f"  → Click executed at pixel ({pixel_x}, {pixel_y})")
    print(f"  → Page navigated to: {page.url}")

    # ------------------------------------------------------------------
    # Step 6.  Verification screenshot
    # ------------------------------------------------------------------
    log_step(6, "Verify result", "Taking a post-click screenshot")

    after_screenshot = capture_screenshot(page)
    after_path = save_screenshot(after_screenshot, "02_after_click.png")

    print(f"  → Screenshot size : {len(after_screenshot) / 1024:.1f} KB")
    print(f"  → Saved to        : {after_path}")
    print(f"  → Current URL     : {page.url}")
    print(f"  → Page title      : {page.title()}")

    # Quick sanity check — did we actually leave the portal page?
    if "en.wikipedia.org" in page.url:
        print("\n  ✅ SUCCESS — Navigated to English Wikipedia!")
    else:
        print(f"\n  ⚠  Ended up at {page.url} — the click may have missed.")
        print("     This can happen if the page layout shifted. Try again.")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    print(f"\n{'─'*64}")
    print("Cleaning up browser resources...")
    context.close()
    browser.close()
    pw.stop()
    print("✓ Done — screenshots saved to 01_before_click.png & 02_after_click.png")


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
