# Use Case 1: Automated QA Testing Agent

## What This Demonstrates

This use case shows how to build an **autonomous QA testing agent** powered by
Gemini Computer Use. Instead of writing brittle CSS-selector-based tests, you
give the model a natural-language test plan and it figures out where to click,
what to type, and how to verify results — just like a human tester would.

**Key concepts:**
- Full agentic loop with `generateContent` (not the Interactions API)
- Gemini Computer Use driving a headless Playwright browser
- Custom function calling (`report_qa_result`) alongside browser actions
- Screenshot-based feedback loop: every action returns a screenshot
- Structured QA reporting

## Architecture

```
┌──────────────────────────────────────────────────┐
│  qa_agent.py                                      │
│                                                    │
│  ┌────────────┐    ┌──────────────────────────┐  │
│  │ Headless   │◄──►│  QATestingAgent           │  │
│  │ Browser    │    │  (agentic loop)           │  │
│  │ (Playwright)│    │                          │  │
│  └────────────┘    │  ┌──────────────────────┐│  │
│                     │  │ Gemini 3.5 Flash     ││  │
│                     │  │ + Computer Use       ││  │
│                     │  │ + report_qa_result() ││  │
│                     │  └──────────────────────┘│  │
│                     └──────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

## What Happens Step-by-Step

### Step 1: Environment Validation
- Checks that `GEMINI_API_KEY` is set

### Step 2: Browser Launch
- Starts a headless Chromium browser via Playwright
- Navigates to `https://todomvc.com/examples/react/dist/`
- Captures an initial screenshot (1440×900 viewport)

### Step 3: Agent Initialisation
- Creates the `QATestingAgent` with the QA test plan prompt
- Registers two tools with Gemini:
  1. `computer_use` (ENVIRONMENT_BROWSER) — for clicks, typing, scrolling
  2. `report_qa_result` — a custom function for structured test reporting
- Attaches the initial screenshot to the first message

### Step 4: Autonomous Test Execution
The agent runs in a loop, where each iteration:
1. Sends the conversation history (with screenshots) to Gemini
2. Receives back one or more function calls (e.g., `click(x, y)`, `type(text)`)
3. Executes the actions in the Playwright browser
4. Captures a new screenshot after each action
5. Sends the screenshot back as a `FunctionResponse`
6. Repeats until the model signals completion

**Test 1: Add Todo Items**
- Agent clicks the "What needs to be done?" input
- Types "Buy groceries" + Enter
- Types "Read a book" + Enter
- Types "Learn Gemini Computer Use" + Enter
- Verifies all three items appear in the list
- Calls `report_qa_result_schema(test_name="Add Todo Items", passed=True, ...)`

**Test 2: Mark Complete**
- Agent clicks the toggle checkbox next to "Read a book"
- Verifies the item appears with strikethrough styling
- Reports result

**Test 3: Filter Completed**
- Agent clicks the "Completed" filter link
- Verifies only "Read a book" is shown
- Reports result

### Step 5: QA Report
Prints a formatted summary:
```
================================================
           QA TEST REPORT
================================================
  Test: Add Todo Items                [PASS] ✅
  Test: Mark Complete                 [PASS] ✅
  Test: Filter Completed              [PASS] ✅
================================================
  Overall: 3/3 PASSED
================================================
```

## How to Run

```bash
# 1. Navigate to the tutorial root
cd /path/to/computer-use-tutorial

# 2. Activate your virtual environment
source .venv/bin/activate

# 3. Install dependencies (if not already)
pip install google-genai playwright rich termcolor pydantic python-dotenv
playwright install chromium

# 4. Set your API key
export GEMINI_API_KEY="your-key-here"

# 5. Run the QA agent
python 06-use-cases/usecase1_qa_testing/qa_agent.py
```

### Optional: Run with a visible browser
```bash
# Unset the headless flag to watch the agent work
PLAYWRIGHT_HEADLESS= python 06-use-cases/usecase1_qa_testing/qa_agent.py
```

## Expected Console Output

```
╔══════════════════════════════════════════════════════════════╗
║   Use Case 1: Automated QA Testing Agent — TodoMVC          ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Step 1 → Validate environment
  Checking GEMINI_API_KEY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ API key found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Step 2 → Launch browser
  Opening https://todomvc.com/examples/react/dist/
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Browser launched — viewport (1440, 900)
  ✓ Page loaded

  ...

  ▶  Action: click(x=500, y=320)
     📸 Screenshot captured (145 KB)
  ▶  Action: type(text=Buy groceries, press_enter=True)
     📸 Screenshot captured (148 KB)
  ...

  📋 QA Result: Add Todo Items → [PASS ✅]
     Details : All three items visible in the list

  ...

================================================
           QA TEST REPORT
================================================
  Test: Add Todo Items                [PASS] ✅
  Test: Mark Complete                 [PASS] ✅
  Test: Filter Completed              [PASS] ✅
================================================
  Overall: 3/3 PASSED
================================================

✓ Browser closed. QA session complete.
```

## Key Takeaways

1. **No selectors needed** — The agent uses visual understanding (screenshots)
   rather than CSS selectors or XPaths, making tests resilient to UI changes.

2. **Natural language test plans** — Write tests in English, not code. The model
   interprets the intent and determines the right actions.

3. **Custom functions + Computer Use** — You can mix browser actions with
   structured data-reporting functions in the same agent.

4. **Screenshot memory management** — Old screenshots are pruned to keep
   context size manageable over long test sessions.
