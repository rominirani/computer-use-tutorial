# Step 02 — Single Action

## What You'll Learn

This is the **first real Computer Use step**.  You'll see the complete
round-trip that makes Gemini Computer Use work:

```
Screenshot → Gemini → function_call → Denormalize → Playwright click → Verify
```

| Concept | How it's used here |
|---|---|
| **Computer Use tool** | `types.Tool(computer_use=types.ComputerUse(environment=ENVIRONMENT_BROWSER))` enables built-in actions |
| **Normalised coordinates** | The model returns x, y in a 0-999 space; the script converts to real pixels |
| **Function call parsing** | The response contains `function_call` parts that describe the action |
| **Action execution** | Playwright's `page.mouse.click()` performs the click at the computed pixel position |

## Prerequisites

```bash
pip install google-genai playwright
python -m playwright install chromium
export GEMINI_API_KEY="your-key-here"
```

## Run

```bash
python single_action.py
```

## Expected Output

```
✓ Gemini client initialised

================================================================
  Step 1 → Launch browser
  Navigating to https://www.wikipedia.org
================================================================

  → Page loaded : Wikipedia
  → Viewport    : 1280×800

================================================================
  Step 2 → Capture screenshot
  Grabbing the Wikipedia portal page
================================================================

  → Screenshot size : 185.2 KB

================================================================
  Step 3 → Ask Gemini to click
  Sending screenshot + instruction with Computer Use tool
================================================================

  → Response received from Gemini

================================================================
  Step 4 → Parse response
  Extracting the function call from the model
================================================================

  Function call received:
    Name : click
    x    : 501
    y    : 280

================================================================
  Step 5 → Execute click
  Converting coordinates and clicking
================================================================

  Coordinate conversion:
    Normalised  : (501, 280)  [0-999 space]
    Pixel       : (641, 224)  [1280×800 viewport]

  → Click executed at pixel (641, 224)
  → Page navigated to: https://en.wikipedia.org/wiki/Main_Page

================================================================
  Step 6 → Verify result
  Taking a post-click screenshot
================================================================

  → Current URL  : https://en.wikipedia.org/wiki/Main_Page
  → Page title   : Wikipedia, the free encyclopedia

  ✅ SUCCESS — Navigated to English Wikipedia!
```

## Key Concepts

### The Computer Use Tool

Enabling Computer Use is a single line in the tool config:

```python
types.Tool(
    computer_use=types.ComputerUse(
        environment=types.Environment.ENVIRONMENT_BROWSER,
    )
)
```

This tells Gemini that it's controlling a browser and unlocks built-in
action functions like `click`, `type`, `scroll`, `navigate`, etc.

### Coordinate System (0-999 → pixels)

The model always outputs coordinates in a **normalised 0-999 space**,
regardless of actual screen dimensions.  To convert:

```python
pixel_x = int(norm_x / 1000 * screen_width)
pixel_y = int(norm_y / 1000 * screen_height)
```

For a 1280×800 viewport, `(500, 500)` maps to `(640, 400)` — the centre.

### Response Structure

The model returns `Part` objects that can be:
- **`part.text`** — the model's reasoning or explanation
- **`part.function_call`** — an action the model wants to perform

A `function_call` has:
- `.name` — e.g. `"click"`, `"type"`, `"scroll"`
- `.args` — a dict of arguments, e.g. `{"x": 501, "y": 280}`

### Why Wikipedia?

- The portal page has a clearly visible "English" link
- The page is fast, public, and has a stable layout
- Success is easy to verify — the URL changes to `en.wikipedia.org`

## What's Next?

In **Step 03 — Action Loop** you'll extend this into a multi-turn
conversation where the model can perform *multiple* actions in sequence,
receiving a new screenshot after each one.
