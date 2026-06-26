# Real-World Use Cases

This directory contains five complete, self-contained use cases demonstrating practical applications of Gemini Computer Use.

## Use Cases

| # | Use Case | Environment | API | Key Feature |
|---|---|---|---|---|
| 1 | [QA Testing (TodoMVC)](usecase1_qa_testing/) | Browser | `generateContent` | Multi-step visual QA testing |
| 2 | [Price Comparison](usecase2_price_comparison/) | Browser | `generateContent` | **Multi-tool**: Computer Use + custom functions |
| 3 | [Mobile App Testing](usecase3_mobile_testing/) | Mobile | `interactions.create` | Android emulator automation |
| 4 | [Web Research & Report](usecase4_web_research/) | Browser | `generateContent` | **Multi-tool**: browsing + structured data extraction |
| 5 | [Form Filling](usecase5_form_filling/) | Browser | `generateContent` | Complex form inputs (radio, checkbox, dropdown) |

## Running a Use Case

Each use case is self-contained. Navigate to the directory and run the Python script:

```bash
# Make sure you're in the tutorial root with the venv activated
cd /path/to/computer-use-tutorial
source .venv/bin/activate

# Run any use case
cd 06-use-cases/usecase1_qa_testing
python qa_agent.py
```

> **Note:** Ensure your `GEMINI_API_KEY` is set via `.env` file or environment variable before running.
