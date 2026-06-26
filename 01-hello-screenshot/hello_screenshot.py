"""
Step 01 — Hello Screenshot
===========================
Foundation step: capture a browser screenshot and ask Gemini to describe it.

This script does NOT use Computer Use.  It demonstrates the two building
blocks that every later step depends on:
  1. Launching a headless browser with Playwright and grabbing a PNG screenshot.
  2. Sending that screenshot to Gemini 3.5 Flash as inline image data and
     reading back the model's free-text description.

Usage:
    export GEMINI_API_KEY="your-key-here"
    python hello_screenshot.py
"""

# ── Imports ──────────────────────────────────────────────────────────────
import os
import sys
import base64
import time

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory

from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types

# ── Constants ────────────────────────────────────────────────────────────

# The page we'll screenshot — Hacker News is fast, public, and text-heavy,
# which gives the model plenty to describe.
TARGET_URL = "https://news.ycombinator.com"

# Browser viewport — a standard laptop-size window.
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 800

# Gemini model to use for description.
MODEL_NAME = "gemini-3.5-flash"


# ── Helper: pretty step printer ─────────────────────────────────────────

def log_step(step_number: int, action: str, detail: str = "") -> None:
    """Print a clearly formatted step marker to stdout."""
    print(f"\n{'='*60}")
    print(f"  Step {step_number} → {action}")
    if detail:
        print(f"  {detail}")
    print(f"{'='*60}\n")


# ── Main logic ───────────────────────────────────────────────────────────

def main() -> None:
    # ------------------------------------------------------------------
    # 0.  Validate that the API key is available
    # ------------------------------------------------------------------
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set the GEMINI_API_KEY environment variable first.")
        print("  export GEMINI_API_KEY='your-key-here'")
        sys.exit(1)

    # Create the Gemini client once — it's reused for every request.
    client = genai.Client(api_key=api_key)
    print("✓ Gemini client initialised")

    # ------------------------------------------------------------------
    # Step 1.  Launch browser & navigate to Hacker News
    # ------------------------------------------------------------------
    log_step(1, "Launch browser", f"Opening {TARGET_URL}")

    pw = sync_playwright().start()

    # Chromium in headless mode — no visible window needed.
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
    )
    page = context.new_page()
    page.goto(TARGET_URL, wait_until="networkidle")

    print(f"  → Page loaded: {page.title()}")
    print(f"  → Viewport   : {VIEWPORT_WIDTH}×{VIEWPORT_HEIGHT}")

    # ------------------------------------------------------------------
    # Step 2.  Capture a PNG screenshot
    # ------------------------------------------------------------------
    log_step(2, "Capture screenshot", "Taking a full-viewport PNG snapshot")

    screenshot_bytes: bytes = page.screenshot(type="png", full_page=False)
    screenshot_size_kb = len(screenshot_bytes) / 1024

    # Also save to disk so the learner can inspect it manually.
    output_path = os.path.join(os.path.dirname(__file__), "screenshot.png")
    with open(output_path, "wb") as f:
        f.write(screenshot_bytes)

    print(f"  → Screenshot captured: {screenshot_size_kb:.1f} KB")
    print(f"  → Saved to           : {output_path}")

    # ------------------------------------------------------------------
    # Step 3.  Send screenshot to Gemini and ask for a description
    # ------------------------------------------------------------------
    log_step(3, "Send to Gemini", "Asking the model to describe the screenshot")

    # Build the prompt: one text part + one inline-image part.
    # The image is sent as raw bytes with the correct MIME type — no need
    # to base64-encode it manually; the SDK handles that.
    prompt_text = (
        "You are looking at a screenshot of a webpage. "
        "Describe what you see in detail: the site name, layout, "
        "the top stories or headlines visible, any navigation elements, "
        "and the overall colour scheme."
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        # Text instruction
                        types.Part(text=prompt_text),
                        # Inline screenshot image
                        types.Part(
                            inline_data=types.Blob(
                                mime_type="image/png",
                                data=screenshot_bytes,
                            )
                        ),
                    ],
                )
            ],
        )
    except Exception as exc:
        print(f"  ✗ Gemini API call failed: {exc}")
        # Clean up browser resources before exiting
        context.close()
        browser.close()
        pw.stop()
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 4.  Print the model's description
    # ------------------------------------------------------------------
    log_step(4, "Model response", "Gemini's description of the screenshot")

    # Extract the text from the response — the model returns one or more
    # text parts; we concatenate them.
    if response.candidates and response.candidates[0].content:
        description_parts = []
        for part in response.candidates[0].content.parts:
            if part.text:
                description_parts.append(part.text)
        description = "\n".join(description_parts)
    else:
        description = "(No description returned by the model)"

    print(description)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    print(f"\n{'─'*60}")
    print("Cleaning up browser resources...")
    context.close()
    browser.close()
    pw.stop()
    print("✓ Done — screenshot saved to screenshot.png")


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
