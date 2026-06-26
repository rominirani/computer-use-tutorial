# Step 03 — Multi-Step Browser Agent

> **What you'll learn:** How to build a fully autonomous browser agent that
> observes, thinks, acts, and loops — all driven by Gemini Computer Use.

## Overview

This step ties everything together into a production-style agentic loop.
The agent receives a natural-language task, controls a real browser via
Playwright, and decides — on every iteration — whether to interact with the
page or declare the task complete.

```
┌──────────────────────────────────────────────────┐
│                  User provides task               │
└──────────────────┬───────────────────────────────┘
                   ▼
          ┌────────────────┐
          │  Take screenshot│ ◄──────────────┐
          └───────┬────────┘                 │
                  ▼                          │
         ┌────────────────┐                  │
         │ Call Gemini API │                  │
         └───────┬────────┘                  │
                 ▼                           │
        ┌─────────────────┐    Yes           │
        │ Function calls? ├────────►  Execute actions
        └───────┬─────────┘          + capture screenshot
                │ No                         │
                ▼                            │
        ┌──────────────┐                     │
        │ Return summary│                    │
        └──────────────┘                     │
```

## Files

| File | Purpose |
|---|---|
| `playwright_env.py` | Reusable context-managed browser environment with methods for every supported interaction |
| `browser_agent.py` | The agentic loop: model calls, action dispatch, screenshot pruning, safety gates, and rich CLI output |

## Key concepts

### 1. The agentic loop

The agent runs up to 25 iterations (configurable).  Each iteration:

1. **Observe** — capture a PNG screenshot of the viewport.
2. **Think** — send the screenshot + full conversation history to `gemini-3.5-flash`.
3. **Act** — execute each `FunctionCall` the model returns (click, type, scroll …).
4. **Loop** — feed the post-action screenshot back and repeat.

The loop exits when the model returns plain text instead of function calls.

### 2. Coordinate denormalization

The model outputs coordinates in a **normalized 0–999 space**.  The agent
translates them to real pixel coordinates before executing:

```python
pixel_x = int(normalized_x / 1000 * viewport_width)
pixel_y = int(normalized_y / 1000 * viewport_height)
```

### 3. Screenshot pruning

Sending every screenshot to the model on every turn would quickly exhaust the
context window.  The agent keeps only the **3 most recent** screenshot blobs
in the conversation history.  Older turns retain their textual metadata (URL,
function name) but have the binary PNG data removed.

### 4. Safety decision handling

Some actions may trigger a `safety_decision` field in the function call.  When
this happens, the agent pauses and asks the user for explicit confirmation
before proceeding.

### 5. Retry logic

API calls use exponential backoff (2s → 4s → 8s) with up to 3 retries to
handle transient errors gracefully.

## Running the agent

```bash
# 1. Make sure your API key is set
export GEMINI_API_KEY="your-key-here"

# 2. Install dependencies (from the repo root)
pip install -r requirements.txt
playwright install chromium

# 3. Run with the default task
cd 03-browser-agent
python browser_agent.py

# 4. Or specify a custom task
python browser_agent.py --task "Search Google for 'best Python libraries 2025' and tell me the top 3 results"

# 5. Run headless (no visible browser window)
python browser_agent.py --headless --task "Go to wikipedia.org and find the featured article title"
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--task` | *Top 3 Hacker News stories* | Natural-language task |
| `--model` | `gemini-3.5-flash` | Gemini model name |
| `--width` | `1280` | Viewport width (px) |
| `--height` | `800` | Viewport height (px) |
| `--headless` | `False` | Run without a visible browser |

## What the output looks like

```
╭─── Browser Agent Starting ────────────────────╮
│ Task: Go to https://news.ycombinator.com ...   │
╰────────────────────────────────────────────────╯

──── Iteration 1 ────────────────────────────────
╭── Model Thinking ─────────────────────────────╮
│ I need to navigate to Hacker News first...     │
╰────────────────────────────────────────────────╯
  ▶ navigate(url=https://news.ycombinator.com)
    → Screenshot captured  |  URL: https://news.ycombinator.com

──── Iteration 2 ────────────────────────────────
╭── Model Thinking ─────────────────────────────╮
│ I can see the front page. Let me read the ...  │
╰────────────────────────────────────────────────╯

──── Task Complete ──────────────────────────────
Agent Summary: The top 3 stories on HN are: ...
```

## Architecture notes

- **`PlaywrightEnvironment`** is a plain context manager — no base class, no
  abstract methods.  It can be reused in other scripts or tests independently.
- **`BrowserAgent`** only depends on the environment exposing the same method
  signatures.  You can swap in a different backend (Selenium, CDP, remote VM)
  by implementing the same interface.
- All 20 computer-use actions supported by `gemini-3.5-flash` are handled in
  the dispatch table: `click`, `double_click`, `triple_click`, `middle_click`,
  `right_click`, `mouse_down`, `mouse_up`, `move`, `type`, `drag_and_drop`,
  `wait`, `press_key`, `key_down`, `key_up`, `hotkey`, `take_screenshot`,
  `scroll`, `go_back`, `go_forward`, `navigate`.
