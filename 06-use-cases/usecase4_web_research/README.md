# Use Case 4 — Web Research & Report Agent 🔬

> Combine **Computer Use** with **Custom Function Calling** for structured web research

## What This Does

The agent searches the web via DuckDuckGo, reads articles, and **programmatically extracts** structured findings using custom tool functions — then compiles everything into a Markdown report.

| Step | Action | What to Expect |
|------|--------|----------------|
| 1 | Opens DuckDuckGo | Browser launches at html.duckduckgo.com/html/ |
| 2 | Searches for the query | Types the search query and presses Enter |
| 3 | Visits result pages | Clicks on 2-3 search results |
| 4 | Extracts findings | Calls `save_finding()` with title, URL, key point, category |
| 5 | Signals completion | Calls `generate_report()` |
| 6 | Saves report | Writes a structured `.md` file |

## The Key Pattern: Computer Use + Custom Functions

This use case demonstrates a powerful pattern — the model uses **two types of tools simultaneously**:

```python
tools=[
    # 1. Browser automation (predefined by Gemini)
    types.Tool(
        computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER,
        ),
    ),
    # 2. Custom data-extraction functions (defined by you)
    types.Tool(
        function_declarations=[save_finding_decl, generate_report_decl],
    ),
]
```

### Custom Functions

```python
def save_finding(title, source_url, key_point, category) -> dict:
    """Model calls this to store each finding in a structured list."""

def generate_report() -> dict:
    """Model calls this when research is complete."""
```

The model decides *when* to call each function — it reads the page content through screenshots, then uses `save_finding` to extract specific facts.

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
# Default search: "quantum computing breakthroughs 2026"
python research_agent.py

# Custom search query
python research_agent.py --search "AI safety regulations 2026"

# Headless mode (no visible browser)
python research_agent.py --headless

# Limit turns
python research_agent.py --max-turns 30
```

## Expected Console Output

```
╔══════════════════════════════════════════════════╗
║ Use Case 4 — Web Research & Report Agent        ║
║ Search: "quantum computing breakthroughs 2026"  ║
╚══════════════════════════════════════════════════╝

✓ Gemini client ready
✓ Chromium launched

──────────────────── Turn 1 ────────────────────
  ▶ click(x=500, y=400)
    → URL: https://html.duckduckgo.com/html/

──────────────────── Turn 2 ────────────────────
  ▶ type(text='quantum computing breakthroughs 2026', press_enter=True)
    → URL: https://html.duckduckgo.com/html/?q=...

──────────────────── Turn 3 ────────────────────
  ▶ click(x=400, y=280)
    → URL: https://example.com/quantum-article

──────────────────── Turn 4 ────────────────────
  ▶ save_finding(title='Major breakthrough ...', source_url='https://...', ...)
  📌 Finding #1 saved: Major breakthrough ... (hardware)

... (more turns) ...

  ▶ generate_report()
  📋 Report requested — 5 findings collected

✓ Browser closed
✓ Report saved to: report_quantum_computing_2026-06-26_143022.md

╭──────── Collected Findings (5) ────────╮
│ # │ Title              │ Category  │ … │
│ 1 │ Major breakthrough … │ hardware  │ … │
│ 2 │ IBM announces …      │ algorithm │ … │
│ 3 │ …                  │ …         │ … │
╰────────────────────────────────────────╯
```

## Generated Report Format

The script saves a Markdown file like this:

```markdown
# Research Report: Quantum Computing Breakthroughs 2026

**Generated:** 2026-06-26 14:30:22
**Model:** gemini-3.5-flash
**Total Findings:** 5

---

## Finding 1: Major Quantum Processor Breakthrough
**Source:** https://example.com/article
**Category:** hardware
**Collected:** 2026-06-26T14:28:15

Researchers announced a new 1000-qubit processor that achieves ...

---

## Finding 2: ...
```

## Key Concepts Demonstrated

- **Dual tool registration** — Computer Use actions + custom FunctionDeclarations
- **Structured data extraction** — model calls `save_finding()` with typed arguments
- **generateContent API** — multi-turn conversation with screenshot feedback
- **Screenshot memory management** — old screenshots pruned to control context size
- **Report generation** — findings compiled into a clean Markdown document
