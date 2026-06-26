# Use Case 5 — Automated Form Filling Agent 📝

> Fill in web forms with text fields, radio buttons, checkboxes, and text areas using Gemini Computer Use

## What This Does

The agent navigates to [practice_form.html](practice_form.html (local file)) and fills in a complex form that includes multiple input types:

| Step | Action | Input Type Demonstrated |
|------|--------|------------------------|
| 1 | Opens the form page | Navigation |
| 2 | Fills First Name → `Jane` | Text input |
| 3 | Fills Last Name → `Smith` | Text input |
| 4 | Fills Email → `jane.smith@example.com` | Email input |
| 5 | Selects Gender → `Female` | **Radio button** |
| 6 | Fills Mobile → `1234567890` | Number input |
| 7 | Enters Subject → `Computer Science` | Autocomplete/dropdown |
| 8 | Selects Hobby → `Reading` | **Checkbox** |
| 9 | Fills Address → `123 AI Street, Tech City` | **Text area** |
| 10 | Clicks **Submit** | Button click |
| 11 | Verifies confirmation modal | Visual verification |
| 12 | Reports results | Summary output |

## Why This Use Case Matters

Forms are one of the trickiest UI patterns for automation because they combine:
- **Text fields** (click → type)
- **Radio buttons** (click the label or the dot)
- **Checkboxes** (click to toggle)
- **Autocomplete dropdowns** (type → select from suggestions)
- **Text areas** (multi-line input)
- **Submit buttons** (may trigger validation)

Gemini Computer Use handles all of these through **visual understanding** — it sees the form as a screenshot and decides where to click and what to type.

## Architecture

```
┌──────────────┐      generateContent API      ┌────────────────┐
│   Gemini     │  ◄──────────────────────────►  │  form_agent.py │
│   3.5 Flash  │   (browser environment)        │                │
└──────────────┘                                └───────┬────────┘
                                                        │
                                                  FormBrowser
                                                  (Playwright)
                                                        │
                                                ┌───────▼────────┐
                                                │   Chromium     │
                                                │   the local practice form   │
                                                └────────────────┘
```

## Prerequisites

1. **API Key**
   ```bash
   export GEMINI_API_KEY="your-api-key"
   ```

2. **Python dependencies**
   ```bash
   pip install google-genai playwright rich python-dotenv
   python -m playwright install chromium
   ```

## Running

```bash
# With visible browser (recommended for watching the agent work)
python form_agent.py

# Headless mode
python form_agent.py --headless

# Limit turns
python form_agent.py --max-turns 30
```

## Expected Console Output

```
╔══════════════════════════════════════════════════╗
║ Use Case 5 — Automated Form Filling Agent       ║
║ Target: practice_form.html (local file) ║
╚══════════════════════════════════════════════════╝

┌─────────── Form Data to Fill ───────────┐
│ Field          │ Value                   │
├────────────────┼─────────────────────────┤
│ First Name     │ Jane                    │
│ Last Name      │ Smith                   │
│ Email          │ jane.smith@example.com  │
│ Gender         │ Female                  │
│ Mobile         │ 1234567890              │
│ Subjects       │ Computer Science        │
│ Hobbies        │ Reading                 │
│ Address        │ 123 AI Street, Tech City│
└────────────────┴─────────────────────────┘

✓ Gemini client initialised

Step 1 → Launching Chromium browser …
✓ Browser ready

Step 2 → Navigating to practice form …
  URL: practice_form.html (local file)
  Screenshot: 198,432 bytes

──────────────────── Turn 1 ────────────────────
  ▶ click(x=350, y=220)         # clicks First Name field
    → practice_form.html (local file)
  ▶ type(text='Jane')
    → practice_form.html (local file)

──────────────────── Turn 2 ────────────────────
  ▶ click(x=650, y=220)         # clicks Last Name field
    → ...
  ▶ type(text='Smith')
    → ...

... (more turns — radio buttons, checkboxes, etc.) ...

──────────────────── Turn 8 ────────────────────
  ▶ scroll(x=500, y=500, direction='down')
  ▶ click(x=500, y=700)         # clicks Submit button

╭──────────── Agent Report ────────────╮
│ Form filling complete!               │
│                                      │
│ Fields filled:                       │
│ ✓ First Name: Jane                   │
│ ✓ Last Name: Smith                   │
│ ✓ Email: jane.smith@example.com      │
│ ✓ Gender: Female (radio)             │
│ ✓ Mobile: 1234567890                 │
│ ✓ Subject: Computer Science          │
│ ✓ Hobby: Reading (checkbox)          │
│ ✓ Address: 123 AI Street, Tech City  │
│                                      │
│ Result: Confirmation modal appeared  │
│ with submitted data. Success!        │
╰──────────────────────────────────────╯

✓ Browser closed

┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric      ┃ Value                                    ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Target URL  │ practice_form.html (local file)│
│ Total turns │ 10                                       │
│ Model       │ gemini-3.5-flash                         │
│ API         │ generateContent (browser)                │
│ Data filled │ First Name: Jane, Last Name: Smith, ...  │
└─────────────┴──────────────────────────────────────────┘

✓ Form filling complete.
```

## Key Concepts Demonstrated

- **Multiple input types** — text, radio, checkbox, textarea, autocomplete
- **generateContent API** with `ENVIRONMENT_BROWSER`
- **Visual form understanding** — model reads labels and identifies input locations
- **Scroll handling** — form may extend below the fold
- **Submit verification** — model checks for the confirmation modal
- **Action dispatch table** — clean mapping from model actions to browser methods
- **Screenshot memory pruning** — keeps context size manageable across many turns

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Form page shows ads covering inputs | Agent should scroll past or close the ad overlay |
| Subject autocomplete doesn't work | Agent types text then presses Enter to confirm |
| Submit button not visible | Agent needs to scroll down before clicking |
| Modal doesn't appear | Check if all required fields were filled (email, mobile) |
| `Page.goto: Timeout 30000ms exceeded` | the local practice form can be slow. The script uses a 60-second timeout with `domcontentloaded` wait. If it persists, check your internet connection or try again later. |
| Agent takes 25-35 turns | This is normal — forms with many diverse input types require many individual actions (focus field, type, move to next) |
