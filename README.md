# Gemini Computer Use Tutorial

> Companion code for the blog post: *Mastering Gemini Computer Use: A Comprehensive Hands-On Guide*

Build AI agents that can see, understand, and interact with any screen — browsers, mobile devices, and desktops — using **Gemini 3.5 Flash** and the `google-genai` SDK.

<!-- TODO: Add blog post link once published -->
<!-- 📖 **Read the full tutorial:** [Blog Post Title](https://link-to-blog-post) -->

---

## How Computer Use Works: Brain, Eyes, and Hands

Every Computer Use agent has three parts:

| Role | What It Does | Who Provides It |
|---|---|---|
| 🧠 **Brain** | Looks at the screen, decides what to do next, returns a structured action like `click(x=396, y=185)` | **Gemini 3.5 Flash** — this is the model |
| 👁️ **Eyes** | Captures a screenshot of the current screen and sends it to the Brain | **Your code** — `page.screenshot()` or `adb screencap` |
| 🖐️ **Hands** | Executes the Brain's action on the actual screen (click, type, scroll, tap) | **Playwright** (browser), **ADB** (mobile), or **CDP** (enterprise sandbox) |

The Brain is always the same — Gemini 3.5 Flash. But the **Hands change** depending on what you're controlling:

```
┌─────────────────────────────────────────────────────────────────┐
│                    🧠 BRAIN (always the same)                   │
│                      Gemini 3.5 Flash                           │
│           "Look at this screenshot, what should I do?"          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              Model returns: click(x=396, y=185)
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   🖐️ Browser        🖐️ Mobile       🖐️ Enterprise
   Playwright         ADB              CDP Sandbox
   page.mouse         adb shell        Remote browser
   .click(506,148)    input tap        in the cloud
                      506 148
```

**Why this matters:** The model doesn't know or care what "hands" you're using. It just sees screenshots and returns actions. You can swap Playwright for Selenium, ADB for a physical device, or a local browser for a cloud sandbox — the model's output is identical. The only thing that changes is the `environment` parameter you declare (`browser`, `mobile`, or `desktop`), which tells the model what *kind* of screen it's looking at.

---

## What's Inside

This repository contains **5 progressive tutorial steps** and **5 real-world use cases**, each in its own directory with a dedicated README.

### Tutorial Steps

| Directory | What You'll Build | API Used |
|---|---|---|
| [`01-hello-screenshot/`](01-hello-screenshot/) | Send a screenshot to Gemini and get a visual description — no Computer Use yet | `generateContent` |
| [`02-single-action/`](02-single-action/) | Your first Computer Use action: screenshot → model → click → verify | `generateContent` |
| [`03-browser-agent/`](03-browser-agent/) | Full autonomous browser agent with agentic loop, history management, and screenshot pruning | `generateContent` |
| [`04-mobile-agent/`](04-mobile-agent/) | Android agent using the Interactions API and ADB | `interactions.create` |
| [`05-enterprise-platform/`](05-enterprise-platform/) | Migrate to Vertex AI with IAM auth and managed browser sandboxes | `generateContent` (Vertex AI) |

### Real-World Use Cases

| Directory | Scenario | Key Pattern |
|---|---|---|
| [`06-use-cases/usecase1_qa_testing/`](06-use-cases/usecase1_qa_testing/) | QA test a TodoMVC app | Computer Use + custom `report_qa_result` function |
| [`06-use-cases/usecase2_price_comparison/`](06-use-cases/usecase2_price_comparison/) | Compare product prices on Amazon | Multi-tool composition (`save_product`) |
| [`06-use-cases/usecase3_mobile_testing/`](06-use-cases/usecase3_mobile_testing/) | Toggle dark mode and read Android version | Interactions API + mobile environment |
| [`06-use-cases/usecase4_web_research/`](06-use-cases/usecase4_web_research/) | Research a topic and generate a Markdown report | Dual custom functions (`save_finding` + `generate_report`) |
| [`06-use-cases/usecase5_form_filling/`](06-use-cases/usecase5_form_filling/) | Fill a complex HTML form (radio, checkbox, autocomplete) | ACTION_DISPATCH table pattern |

---

## Quick Start

### Prerequisites

- Python 3.10+ (3.12+ recommended)
- A [Gemini API key](https://aistudio.google.com/apikey) (free)
- For mobile steps: Android SDK + Emulator (see [`04-mobile-agent/README.md`](04-mobile-agent/README.md))
- For enterprise step: Google Cloud project (see [`05-enterprise-platform/README.md`](05-enterprise-platform/README.md))

### Setup

```bash
# 1. Clone and enter
git clone https://github.com/rominirani/computer-use-tutorial.git
cd computer-use-tutorial

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Chromium for Playwright
playwright install chromium

# 5. Configure your API key
cp .env.example .env
# Edit .env and add your Gemini API key

# 6. Run the first example
cd 01-hello-screenshot
python hello_screenshot.py
```

---

## Repository Structure

```
computer-use-tutorial/
├── README.md                          ← You are here
├── index.html                         ← Single-page HTML version of the tutorial
├── requirements.txt                   ← Python dependencies
├── .env.example                       ← Template for API keys
│
├── 01-hello-screenshot/               ← Step 1: Visual understanding (no Computer Use)
│   ├── hello_screenshot.py
│   └── README.md
│
├── 02-single-action/                  ← Step 2: One screenshot → one click
│   ├── single_action.py
│   └── README.md
│
├── 03-browser-agent/                  ← Step 3: Full agentic browser loop
│   ├── browser_agent.py
│   ├── playwright_env.py
│   └── README.md
│
├── 04-mobile-agent/                   ← Step 4: Android agent + Interactions API
│   ├── mobile_agent.py
│   ├── adb_bridge.py
│   ├── setup_emulator.sh
│   └── README.md
│
├── 05-enterprise-platform/            ← Step 5: Vertex AI + managed sandboxes
│   ├── enterprise_agent.py
│   └── README.md
│
└── 06-use-cases/                      ← 5 real-world use cases
    ├── usecase1_qa_testing/
    ├── usecase2_price_comparison/
    ├── usecase3_mobile_testing/
    ├── usecase4_web_research/
    └── usecase5_form_filling/
```

Each directory has its own `README.md` with detailed instructions, expected output, and troubleshooting.

---

## Key Concepts at a Glance

| Concept | What It Means |
|---|---|
| **Normalized Coordinates** | Model returns positions in 0–999 range. You convert: `pixel = int(norm / 1000 * screen_dim)` |
| **Agentic Loop** | Screenshot → model → action → screenshot → repeat until model returns text |
| **FunctionResponse** | After each action, send back the result AND a fresh screenshot |
| **Screenshot Pruning** | Keep only 2–3 recent screenshots in context to avoid token limits |
| **Multi-tool Composition** | Combine Computer Use with custom function declarations in the same conversation |
| **Interactions API** | Stateful alternative to `generateContent` — server manages history via `previous_interaction_id` |

---

## Resources

- [Gemini API — Computer Use docs](https://ai.google.dev/gemini-api/docs/computer-use)
- [Vertex AI — Computer Use docs](https://cloud.google.com/vertex-ai/generative-ai/docs/computer-use)
- [google-genai Python SDK](https://github.com/googleapis/python-genai)
- [Playwright for Python](https://playwright.dev/python/)
- [Google Reference Implementation](https://github.com/google-gemini/computer-use-preview)

---

*Built with ❤️ using [Gemini 3.5 Flash](https://ai.google.dev) and [Playwright](https://playwright.dev)*
