# Step 01 — Hello Screenshot

## What You'll Learn

This is the **foundation step** of the Gemini Computer Use tutorial. It does
**not** use Computer Use at all — instead it teaches the two building blocks
that every later step depends on:

| Concept | How it's used here |
|---|---|
| **Browser automation** | Playwright launches headless Chromium and navigates to Hacker News |
| **Visual understanding** | The screenshot is sent to Gemini 3.5 Flash as an inline image and the model describes what it sees |

By the end of this step you'll be confident that:

1. Playwright can capture pixel-perfect PNG screenshots of any webpage.
2. The Gemini SDK can accept raw image bytes and reason about their content.

## Prerequisites

```bash
pip install google-genai playwright
python -m playwright install chromium
export GEMINI_API_KEY="your-key-here"
```

## Run

```bash
python hello_screenshot.py
```

## Expected Output

```
✓ Gemini client initialised

============================================================
  Step 1 → Launch browser
  Opening https://news.ycombinator.com
============================================================

  → Page loaded: Hacker News
  → Viewport   : 1280×800

============================================================
  Step 2 → Capture screenshot
  Taking a full-viewport PNG snapshot
============================================================

  → Screenshot captured: 142.3 KB
  → Saved to           : screenshot.png

============================================================
  Step 3 → Send to Gemini
  Asking the model to describe the screenshot
============================================================

============================================================
  Step 4 → Model response
  Gemini's description of the screenshot
============================================================

The screenshot shows the Hacker News homepage...
```

## Key Concepts

### Sending Images to Gemini

The screenshot is sent as a `types.Part` with `inline_data`:

```python
types.Part(
    inline_data=types.Blob(
        mime_type="image/png",
        data=screenshot_bytes,   # raw PNG bytes
    )
)
```

The SDK handles base64 encoding internally — just pass the bytes.

### Why Hacker News?

- Publicly accessible, no login required
- Text-heavy — gives the model plenty to describe
- Fast to load, light on JavaScript
- Stable layout that won't change dramatically between runs

## What's Next?

In **Step 02 — Single Action** you'll enable the Computer Use tool and let
Gemini *click* on an element it identifies in the screenshot.
