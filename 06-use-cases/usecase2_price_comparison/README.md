# Use Case 2: Multi-Site Price Comparison Agent

## What This Demonstrates

This use case shows **multi-tool composition** — using Gemini Computer Use
alongside custom function calling in the same conversation. The model
interleaves browser actions (navigate, click, type, scroll) with structured
data extraction via a custom `save_product()` function.

**Key concepts:**
- Two tools registered simultaneously:
  1. `computer_use` (ENVIRONMENT_BROWSER) — browse the web
  2. `save_product` — custom function to store structured product data
- The model autonomously decides *when* to switch between browsing and
  data extraction
- Rich library for formatted table output
- Full agentic loop with `generateContent`

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  price_agent.py                                              │
│                                                              │
│  ┌──────────────┐     ┌────────────────────────────────┐    │
│  │ Browser      │     │  PriceComparisonAgent          │    │
│  │ Session      │◄───►│  (agentic loop)                │    │
│  │ (Playwright) │     │                                │    │
│  └──────────────┘     │  Tools:                        │    │
│                        │  ┌──────────────────────────┐ │    │
│  ┌──────────────┐     │  │ 1. computer_use (browser) │ │    │
│  │ Product      │     │  │ 2. save_product (custom)  │ │    │
│  │ Findings     │◄────│  └──────────────────────────┘ │    │
│  │ (list)       │     └────────────────────────────────┘    │
│  └──────┬───────┘                                           │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────┐                                           │
│  │ Rich Table   │                                           │
│  │ Output       │                                           │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

## Multi-Tool Composition Pattern

The key innovation is registering two separate tools:

```python
config = GenerateContentConfig(
    tools=[
        # Tool 1: Browser control
        types.Tool(
            computer_use=types.ComputerUse(
                environment=types.Environment.ENVIRONMENT_BROWSER,
            ),
        ),
        # Tool 2: Custom data extraction function
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration.from_callable(
                    client=client,
                    callable=save_product,
                ),
            ],
        ),
    ],
)
```

The model naturally interleaves these tools:
1. `navigate(url="www.amazon.com")` → browser action
2. `type(text="wireless noise cancelling headphones")` → browser action
3. `click(x=700, y=400)` → browser action
4. `save_product(name="Sony WH-1000XM5", price="$278", source="Amazon")` → custom function
5. `scroll(direction="down")` → browser action
6. `save_product(name="Bose QC Ultra", price="$329", source="Amazon")` → custom function

## What Happens Step-by-Step

### Step 1: Environment Validation
- Checks `GEMINI_API_KEY`

### Step 2: Browser Launch
- Starts headless Chromium at `https://www.amazon.com/`
- Captures initial screenshot

### Step 3: Agent Initialization
- Creates `PriceComparisonAgent` with multi-tool config
- Prints registered tools for transparency

### Step 4: Autonomous Search & Extraction
The agent loop runs:
1. Model sees the Amazon page
2. Finds the search box, types "wireless noise cancelling headphones", presses Enter
3. Waits for results to load
4. Reads product names and prices from the screenshot
5. Calls `save_product()` for each product found (3-5 products)
6. May scroll down to find more products
7. Signals completion

### Step 5: Comparison Table
Renders a rich-formatted table:
```
                 🔍 PRICE COMPARISON RESULTS
┌────────────────────────────────┬─────────────┬──────────────────┐
│ Product                        │       Price │ Source           │
├────────────────────────────────┼─────────────┼──────────────────┤
│ Sony WH-1000XM5                │     $278.00 │ Amazon  │
│ Bose QuietComfort Ultra        │     $329.00 │ Amazon  │
│ Apple AirPods Max              │     $449.00 │ Amazon  │
│ Sennheiser Momentum 4          │     $299.95 │ Amazon  │
└────────────────────────────────┴─────────────┴──────────────────┘

  📊 Total products found: 4
```

## How to Run

```bash
# 1. Navigate to the tutorial root
cd /path/to/computer-use-tutorial

# 2. Activate your virtual environment
source .venv/bin/activate

# 3. Install dependencies
pip install google-genai playwright rich termcolor pydantic python-dotenv
playwright install chromium

# 4. Set your API key
export GEMINI_API_KEY="your-key-here"

# 5. Run the price comparison agent
python 06-use-cases/usecase2_price_comparison/price_agent.py
```

### Optional: Watch the agent work
```bash
PLAYWRIGHT_HEADLESS= python 06-use-cases/usecase2_price_comparison/price_agent.py
```

## Expected Console Output

```
╭──────────────────────────────────────────────────────────────╮
│ Use Case 2: Multi-Site Price Comparison Agent                │
│ Demonstrates multi-tool composition: Computer Use + custom   │
│ functions                                                    │
╰──────────────────────────────────────────────────────────────╯

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Step 1 → Validate environment
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ API key found

  ...

  ▶  type(text=wireless noise cancelling headphones, press_enter=True)
     📸 Screenshot (186 KB)

  ▶  save_product(name=Sony WH-1000XM5, price=$278.00, source=Amazon)
     💾 Saved: Sony WH-1000XM5 — $278.00 (Amazon)

  ▶  save_product(name=Bose QuietComfort Ultra, price=$329.00, source=Amazon)
     💾 Saved: Bose QuietComfort Ultra — $329.00 (Amazon)

  ...

                 🔍 PRICE COMPARISON RESULTS
┌────────────────────────────────┬─────────────┬──────────────────┐
│ Product                        │       Price │ Source           │
├────────────────────────────────┼─────────────┼──────────────────┤
│ Sony WH-1000XM5                │     $278.00 │ Amazon  │
│ Bose QuietComfort Ultra        │     $329.00 │ Amazon  │
│ ...                            │             │                  │
└────────────────────────────────┴─────────────┴──────────────────┘

  📊 Total products found: 4

✓ Browser closed. Price comparison complete.
```

## Key Takeaways

1. **Multi-tool composition** — Register multiple tools and let the model
   decide which to use at each step. No hard-coded interleaving needed.

2. **Structured data extraction** — Custom functions let the model output
   structured data (product name, price, source) alongside visual browsing.

3. **Real-world applicability** — This pattern generalises to any
   "browse + extract" workflow: competitor monitoring, lead generation,
   content aggregation, etc.

4. **Graceful degradation** — The script handles cases where Amazon
   may block automated access by showing a helpful message rather than crashing.

## Notes on Amazon

Amazon may occasionally show CAPTCHAs or different layouts for
automated browsers. If the agent struggles:
- Try running again (different session)
- Try with `PLAYWRIGHT_HEADLESS=` to watch and debug
- The pattern works identically with any product listing site — adjust the
  `start_url` and prompt as needed
