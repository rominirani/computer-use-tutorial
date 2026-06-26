"""
Step 05 — Enterprise Agent Platform (Vertex AI)
=================================================
Production-grade Computer Use via Google Cloud's Vertex AI.

This script demonstrates TWO approaches for running Gemini Computer Use
through the Enterprise Agent Platform:

  Approach 1 — Vertex AI + Self-Managed Browser
      Use your own local Playwright instance, but authenticate through
      Vertex AI instead of an API key.  Ideal for development and CI/CD
      pipelines where you control the runtime environment.

  Approach 2 — Vertex AI + Managed Sandbox
      Provision an isolated, cloud-hosted browser sandbox via the Sandbox
      API.  Connect to it over Chrome DevTools Protocol (CDP).  Ideal for
      multi-tenant production systems that need security isolation.

Prerequisites:
    # Google Cloud SDK authenticated
    gcloud auth application-default login

    # Python packages
    pip install google-genai playwright google-cloud-aiplatform
    python -m playwright install chromium

    # Environment variables
    export GCP_PROJECT_ID="your-project-id"
    export GCP_LOCATION="us-central1"         # optional, defaults shown

Usage:
    # Approach 1 — self-managed browser
    python enterprise_agent.py --approach self-managed

    # Approach 2 — managed sandbox
    python enterprise_agent.py --approach managed-sandbox

    # Custom task
    python enterprise_agent.py --approach self-managed \
        --task "Search for 'Vertex AI pricing' and summarise the first result"
"""

# ── Imports ──────────────────────────────────────────────────────────────
import argparse
import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv

# Load .env file (searches current dir and parent dirs)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Also check parent directory

from google import genai
from google.genai import types
from google.genai.types import (
    Content,
    Part,
    FunctionResponse,
    GenerateContentConfig,
)
from playwright.sync_api import sync_playwright, Page

# ── Configuration ────────────────────────────────────────────────────────
# These are read from environment variables with sensible defaults.
# For a real deployment, pull them from Secret Manager or a config file.

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "YOUR_PROJECT_ID")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# Browser dimensions — the model will receive screenshots at this size
# and its normalised 0-999 coordinates will be mapped against these.
SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900

# The Gemini model that supports Computer Use.
MODEL = "gemini-3.5-flash"

# Default task if none is provided via CLI.
DEFAULT_TASK = (
    "Navigate to https://cloud.google.com/vertex-ai and tell me the "
    "three main product categories listed on the page."
)

# Maximum agent turns before we force-stop to prevent runaway loops.
MAX_AGENT_TURNS = 25

# How many recent turns should retain their screenshot images.
# Older screenshots are stripped to stay within context limits.
SCREENSHOT_RETENTION_WINDOW = 3

# Actions the Computer Use tool can emit (gemini-3.5-flash style).
BUILTIN_ACTIONS = frozenset([
    "click", "double_click", "triple_click", "middle_click", "right_click",
    "mouse_down", "mouse_up", "move", "type", "drag_and_drop", "wait",
    "press_key", "key_down", "key_up", "hotkey", "take_screenshot",
    "scroll", "go_back", "navigate", "go_forward",
])


# ── Pretty Printing ─────────────────────────────────────────────────────

def banner(title: str) -> None:
    """Print a prominent section banner."""
    width = 64
    print("\n" + "═" * width)
    print(f"  {title}")
    print("═" * width + "\n")


def step_log(number: int, action: str, detail: str = "") -> None:
    """Print a numbered step marker."""
    print(f"\n{'─'*52}")
    print(f"  Step {number} → {action}")
    if detail:
        print(f"  {detail}")
    print(f"{'─'*52}\n")


# ── Coordinate Helpers ───────────────────────────────────────────────────
# The model outputs coordinates in a normalised 0-999 space.
# We must convert them to actual pixel positions for Playwright.

def denorm_x(normalised: int) -> int:
    """Convert a 0-999 x-coordinate to a pixel position."""
    return int(normalised / 1000 * SCREEN_WIDTH)


def denorm_y(normalised: int) -> int:
    """Convert a 0-999 y-coordinate to a pixel position."""
    return int(normalised / 1000 * SCREEN_HEIGHT)


# ═════════════════════════════════════════════════════════════════════════
#  VERTEX AI CLIENT FACTORY
# ═════════════════════════════════════════════════════════════════════════

def build_vertex_client() -> genai.Client:
    """
    Create a Gemini client authenticated via Vertex AI (IAM).

    This uses Application Default Credentials (ADC).  In production you
    would typically attach a service account to your Cloud Run / GKE
    workload; for local development, run:

        gcloud auth application-default login

    The key difference from the Gemini Developer API is:
      - No API key needed
      - Access controlled by IAM roles
      - Requests are billed to your GCP project
      - Additional enterprise features (VPC-SC, CMEK, audit logs)
    """
    if PROJECT_ID == "YOUR_PROJECT_ID":
        print("⚠  WARNING: GCP_PROJECT_ID is not set.")
        print("   Set it via:  export GCP_PROJECT_ID='my-project'")
        print("   Or pass --project on the command line.\n")

    client = genai.Client(
        vertexai=True,          # ← this single flag switches from API-key
        project=PROJECT_ID,     #   to Vertex AI / IAM authentication
        location=LOCATION,
    )
    return client


# ═════════════════════════════════════════════════════════════════════════
#  BROWSER ACTION DISPATCHER
# ═════════════════════════════════════════════════════════════════════════

def capture_state(page: Page) -> tuple[bytes, str]:
    """
    Take a PNG screenshot and return (png_bytes, current_url).

    Every action must end with a fresh screenshot so the model can see
    the result.  We add a small delay to let animations/fetches settle.
    """
    page.wait_for_load_state()
    time.sleep(0.5)  # let renders finish
    png = page.screenshot(type="png", full_page=False)
    return png, page.url


def dispatch_action(page: Page, fc: types.FunctionCall) -> tuple[bytes, str]:
    """
    Execute a single Computer Use action on the Playwright page.

    Parameters
    ----------
    page : Page
        The Playwright page to act on.
    fc : types.FunctionCall
        The function call emitted by the model.

    Returns
    -------
    (screenshot_bytes, url) after the action is complete.
    """
    name = fc.name
    args = fc.args or {}

    # ── Click variants ───────────────────────────────────────────────
    if name == "click":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.click(x, y)

    elif name == "double_click":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.dblclick(x, y)

    elif name == "triple_click":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.click(x, y, click_count=3)

    elif name == "middle_click":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.click(x, y, button="middle")

    elif name == "right_click":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.click(x, y, button="right")

    # ── Mouse movement / drag ────────────────────────────────────────
    elif name == "move":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.move(x, y)

    elif name == "mouse_down":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.move(x, y)
        page.mouse.down()

    elif name == "mouse_up":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        page.mouse.move(x, y)
        page.mouse.up()

    elif name == "drag_and_drop":
        sx, sy = denorm_x(args["x"]), denorm_y(args["y"])
        dx, dy = denorm_x(args["destination_x"]), denorm_y(args["destination_y"])
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(dx, dy)
        page.mouse.up()

    # ── Keyboard ─────────────────────────────────────────────────────
    elif name == "type":
        page.keyboard.type(args["text"])
        if args.get("press_enter", False):
            page.keyboard.press("Enter")

    elif name == "press_key":
        page.keyboard.press(args["key"])

    elif name == "key_down":
        page.keyboard.down(args["key"])

    elif name == "key_up":
        page.keyboard.up(args["key"])

    elif name == "hotkey":
        # "hotkey" receives a list of keys to press simultaneously.
        keys = args["keys"]
        for k in keys[:-1]:
            page.keyboard.down(k)
        page.keyboard.press(keys[-1])
        for k in reversed(keys[:-1]):
            page.keyboard.up(k)

    # ── Scrolling ────────────────────────────────────────────────────
    elif name == "scroll":
        x, y = denorm_x(args["x"]), denorm_y(args["y"])
        direction = args["direction"]
        magnitude = args.get("magnitude", 800)
        # Convert normalised magnitude to pixels
        if direction in ("up", "down"):
            magnitude = denorm_y(magnitude)
        else:
            magnitude = denorm_x(magnitude)
        dx_scroll = 0
        dy_scroll = 0
        if direction == "up":
            dy_scroll = -magnitude
        elif direction == "down":
            dy_scroll = magnitude
        elif direction == "left":
            dx_scroll = -magnitude
        elif direction == "right":
            dx_scroll = magnitude
        page.mouse.move(x, y)
        page.mouse.wheel(dx_scroll, dy_scroll)

    # ── Navigation ───────────────────────────────────────────────────
    elif name == "navigate":
        url = args["url"]
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        page.goto(url)

    elif name == "go_back":
        page.go_back()

    elif name == "go_forward":
        page.go_forward()

    # ── Timing ───────────────────────────────────────────────────────
    elif name == "wait":
        seconds = int(args.get("seconds", 1))
        page.wait_for_timeout(seconds * 1000)

    elif name == "take_screenshot":
        pass  # capture_state below will do it

    else:
        print(f"  ⚠  Unknown action '{name}' — taking screenshot only")

    return capture_state(page)


# ═════════════════════════════════════════════════════════════════════════
#  SCREENSHOT PRUNING
# ═════════════════════════════════════════════════════════════════════════

def prune_old_screenshots(
    conversation: list[Content],
    keep_recent: int = SCREENSHOT_RETENTION_WINDOW,
) -> None:
    """
    Strip screenshot blobs from older turns to stay within context limits.

    We walk the conversation in reverse.  The first `keep_recent` user
    turns that contain function-response screenshots keep their images;
    all earlier ones have the image data set to None.

    This is critical for long sessions — each PNG screenshot is 100-300 KB,
    and the context window is finite.
    """
    turns_with_images = 0
    for content in reversed(conversation):
        if content.role != "user" or not content.parts:
            continue

        has_screenshot = any(
            p.function_response
            and p.function_response.parts
            and p.function_response.name in BUILTIN_ACTIONS
            for p in content.parts
        )
        if not has_screenshot:
            continue

        turns_with_images += 1
        if turns_with_images > keep_recent:
            # Remove the binary data but keep the function response metadata
            for p in content.parts:
                if (
                    p.function_response
                    and p.function_response.parts
                    and p.function_response.name in BUILTIN_ACTIONS
                ):
                    p.function_response.parts = None


# ═════════════════════════════════════════════════════════════════════════
#  APPROACH 1 — VERTEX AI + SELF-MANAGED BROWSER
# ═════════════════════════════════════════════════════════════════════════

def run_self_managed(task: str) -> Optional[str]:
    """
    Run Computer Use against a local Playwright browser, authenticated
    through Vertex AI.

    This is architecturally identical to the Step 03 browser agent — the
    ONLY difference is how the Gemini client is created:

        # Step 03 (Gemini API):
        client = genai.Client(api_key="...")

        # Step 05 (Vertex AI):
        client = genai.Client(vertexai=True, project="...", location="...")

    Everything else — tool declaration, action loop, screenshot capture —
    is exactly the same.  This makes migration from prototyping to
    production a one-line change.
    """
    banner("APPROACH 1 — VERTEX AI + SELF-MANAGED BROWSER")
    print(f"  Project  : {PROJECT_ID}")
    print(f"  Location : {LOCATION}")
    print(f"  Model    : {MODEL}")
    print(f"  Viewport : {SCREEN_WIDTH}×{SCREEN_HEIGHT}")
    print(f"  Task     : {task}\n")

    # ── Step 1: Create the Vertex AI client ──────────────────────────
    step_log(1, "Create Vertex AI client",
             "Using Application Default Credentials (ADC)")

    client = build_vertex_client()
    print("  ✓ Client created with vertexai=True")

    # ── Step 2: Launch a local Playwright browser ────────────────────
    step_log(2, "Launch local Playwright browser",
             "Headless Chromium — same as Step 03")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--disable-extensions",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
        ],
    )
    context = browser.new_context(
        viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
    )
    page = context.new_page()
    page.goto("https://www.google.com", wait_until="networkidle")
    print(f"  ✓ Browser launched → {page.url}")

    # ── Step 3: Configure Computer Use tool ──────────────────────────
    step_log(3, "Configure Computer Use tool",
             "Same tool spec works for both Gemini API and Vertex AI")

    cu_tool = types.Tool(
        computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER,
        ),
    )
    gen_config = GenerateContentConfig(
        tools=[cu_tool],
        temperature=1.0,
        max_output_tokens=8192,
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )
    print("  ✓ Tool configured: ComputerUse(ENVIRONMENT_BROWSER)")

    # ── Step 4: Grab initial screenshot and start conversation ───────
    step_log(4, "Take initial screenshot",
             "The model needs a visual frame before it can act")

    initial_png, initial_url = capture_state(page)
    print(f"  ✓ Screenshot: {len(initial_png) / 1024:.1f} KB")

    # Seed the conversation with the user task + initial screenshot
    conversation: list[Content] = [
        Content(
            role="user",
            parts=[
                Part(text=task),
                Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial_png,
                    )
                ),
            ],
        )
    ]

    # ── Step 5: Agent loop ───────────────────────────────────────────
    step_log(5, "Run agent loop",
             f"Max {MAX_AGENT_TURNS} turns — model drives the browser")

    final_answer: Optional[str] = None

    for turn in range(1, MAX_AGENT_TURNS + 1):
        print(f"  ── Turn {turn} ──")

        # Ask the model what to do next
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=conversation,
                config=gen_config,
            )
        except Exception as exc:
            print(f"  ✗ API error: {exc}")
            # Retry once after a brief pause
            time.sleep(2)
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=conversation,
                    config=gen_config,
                )
            except Exception as retry_exc:
                print(f"  ✗ Retry also failed: {retry_exc}")
                break

        if not response.candidates:
            print("  ✗ Empty response — stopping")
            break

        candidate = response.candidates[0]

        # Append the model's turn to the conversation
        if candidate.content:
            conversation.append(candidate.content)

        # Extract any text the model said (reasoning / final answer)
        text_parts = []
        function_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.function_call:
                    function_calls.append(part.function_call)

        reasoning = " ".join(text_parts) if text_parts else None

        # If there are no function calls, the model is done
        if not function_calls:
            final_answer = reasoning
            print(f"  ✓ Agent finished: {(reasoning or '(no text)')[:120]}...")
            break

        # Log what the model wants to do
        for fc in function_calls:
            arg_summary = ", ".join(
                f"{k}={v}" for k, v in (fc.args or {}).items()
            )
            print(f"    → {fc.name}({arg_summary})")

        # Execute each action and collect FunctionResponses
        fn_responses: list[FunctionResponse] = []
        for fc in function_calls:
            # Handle any safety confirmation the model might request
            if fc.args and "safety_decision" in fc.args:
                print("    ⚠  Safety confirmation requested — auto-acknowledging")

            png_bytes, url = dispatch_action(page, fc)
            fn_responses.append(
                FunctionResponse(
                    name=fc.name,
                    response={"url": url},
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=png_bytes,
                            )
                        )
                    ],
                )
            )

        # Add the function responses as a user turn
        conversation.append(
            Content(
                role="user",
                parts=[Part(function_response=fr) for fr in fn_responses],
            )
        )

        # Prune old screenshots to keep context manageable
        prune_old_screenshots(conversation)

    else:
        print(f"\n  ⚠  Reached maximum turns ({MAX_AGENT_TURNS})")

    # ── Cleanup ──────────────────────────────────────────────────────
    step_log(6, "Cleanup", "Closing browser resources")
    context.close()
    browser.close()
    pw.stop()
    print("  ✓ Browser closed")

    return final_answer


# ═════════════════════════════════════════════════════════════════════════
#  APPROACH 2 — VERTEX AI + MANAGED SANDBOX
# ═════════════════════════════════════════════════════════════════════════
#
# Prerequisites for Managed Sandbox:
# ───────────────────────────────────
# 1. Enable these APIs in Google Cloud Console:
#    - aiplatform.googleapis.com
#    - iam.googleapis.com
#    - cloudresourcemanager.googleapis.com
#
# 2. Create a service account with roles:
#    - roles/aiplatform.admin
#    - roles/iam.serviceAccountUser
#
# 3. Authenticate:
#    gcloud auth application-default login
#
# 4. The Sandbox API may require allowlisting for your project.
#    Check the Vertex AI documentation for current availability.
#
# ─────────────────────────────────────────────────────────────────────────

def create_sandbox(client: genai.Client) -> dict:
    """
    Provision a managed browser sandbox through the Vertex AI Sandbox API.

    The sandbox is a fully isolated, cloud-hosted Chromium instance.
    It runs in a secure VM with:
      - Network isolation (no access to your VPC unless configured)
      - Ephemeral storage (destroyed on cleanup)
      - A CDP (Chrome DevTools Protocol) endpoint for remote control

    Returns
    -------
    dict with keys:
      - "sandbox_id": unique identifier for lifecycle management
      - "cdp_endpoint": WebSocket URL to connect Playwright via CDP

    NOTE: This is a conceptual implementation.  The exact API surface may
    differ.  Consult the latest Vertex AI Sandbox documentation for the
    current request/response format.
    """
    banner("CREATING MANAGED SANDBOX")
    print("  Requesting isolated browser instance from Vertex AI...\n")

    # ── Build the sandbox creation request ───────────────────────────
    # The Sandbox API is accessed through the Vertex AI REST endpoint.
    # Here we show the conceptual Python SDK flow.

    # NOTE: As of this writing, the managed sandbox API may be accessed
    # through the google-cloud-aiplatform SDK or via REST.  The code
    # below illustrates the intended workflow.

    try:
        # Option A: If the genai SDK exposes sandbox management directly:
        #
        #   sandbox = client.sandboxes.create(
        #       config=types.SandboxConfig(
        #           environment="browser",
        #           timeout_seconds=600,       # 10-minute TTL
        #           viewport_width=SCREEN_WIDTH,
        #           viewport_height=SCREEN_HEIGHT,
        #       )
        #   )
        #   sandbox_id = sandbox.name
        #   cdp_endpoint = sandbox.cdp_endpoint
        #

        # Option B: Via the Vertex AI REST API using google-auth directly:
        import google.auth
        import google.auth.transport.requests
        import json
        import urllib.request

        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)

        # Construct the sandbox creation request
        sandbox_api_url = (
            f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{PROJECT_ID}/locations/{LOCATION}/sandboxes"
        )

        request_body = json.dumps({
            "displayName": "computer-use-tutorial-sandbox",
            "sandboxConfig": {
                "environment": "BROWSER",
                "timeoutSeconds": 600,
                "viewport": {
                    "width": SCREEN_WIDTH,
                    "height": SCREEN_HEIGHT,
                },
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            sandbox_api_url,
            data=request_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
        )

        print(f"  POST {sandbox_api_url}")
        print(f"  Viewport: {SCREEN_WIDTH}×{SCREEN_HEIGHT}")
        print(f"  Timeout : 600s\n")

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        sandbox_id = result.get("name", "unknown")
        cdp_endpoint = result.get("cdpEndpoint", "")

        print(f"  ✓ Sandbox created: {sandbox_id}")
        print(f"  ✓ CDP endpoint  : {cdp_endpoint[:60]}...")

        return {
            "sandbox_id": sandbox_id,
            "cdp_endpoint": cdp_endpoint,
        }

    except ImportError:
        print("  ✗ google-auth not installed.  Install with:")
        print("    pip install google-auth")
        print("  Returning mock sandbox for demonstration.\n")
        return _mock_sandbox()

    except Exception as exc:
        print(f"  ✗ Sandbox creation failed: {exc}")
        print("  This is expected if your project hasn't been allowlisted")
        print("  for the Sandbox API, or if the API surface has changed.")
        print("  Returning mock sandbox for demonstration.\n")
        return _mock_sandbox()


def _mock_sandbox() -> dict:
    """
    Return a placeholder sandbox result for demonstration purposes.

    When the real Sandbox API is unavailable, this lets the rest of the
    code path execute so learners can see the intended flow.
    """
    return {
        "sandbox_id": "projects/YOUR_PROJECT_ID/locations/us-central1/sandboxes/demo-12345",
        "cdp_endpoint": "ws://localhost:9222/devtools/browser/mock-guid",
        "is_mock": True,
    }


def delete_sandbox(sandbox_id: str) -> None:
    """
    Clean up a managed sandbox when the session is complete.

    This is critical — sandboxes consume compute resources and will
    continue to bill your project until explicitly deleted or until
    their TTL expires.
    """
    print(f"\n  Deleting sandbox: {sandbox_id}")

    try:
        import google.auth
        import google.auth.transport.requests
        import urllib.request

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)

        delete_url = (
            f"https://{LOCATION}-aiplatform.googleapis.com/"
            f"v1beta1/{sandbox_id}"
        )

        req = urllib.request.Request(
            delete_url,
            method="DELETE",
            headers={
                "Authorization": f"Bearer {credentials.token}",
            },
        )

        with urllib.request.urlopen(req) as resp:
            print(f"  ✓ Sandbox deleted (HTTP {resp.status})")

    except Exception as exc:
        print(f"  ⚠  Sandbox deletion failed: {exc}")
        print("  The sandbox will auto-expire after its TTL.")


def run_managed_sandbox(task: str) -> Optional[str]:
    """
    Run Computer Use inside a Vertex AI managed sandbox.

    Flow:
      1. Create sandbox → get CDP WebSocket URL
      2. Connect Playwright via connect_over_cdp()
      3. Run the agent loop (identical to Approach 1)
      4. Delete the sandbox

    The key advantage: your code never needs to install or manage a
    browser.  The sandbox provides a secure, isolated Chromium instance
    in the cloud with a consistent environment.
    """
    banner("APPROACH 2 — VERTEX AI + MANAGED SANDBOX")
    print(f"  Project  : {PROJECT_ID}")
    print(f"  Location : {LOCATION}")
    print(f"  Model    : {MODEL}")
    print(f"  Task     : {task}\n")

    # ── Step 1: Create the Vertex AI client ──────────────────────────
    step_log(1, "Create Vertex AI client",
             "Same client creation as Approach 1")

    client = build_vertex_client()
    print("  ✓ Client created")

    # ── Step 2: Provision a managed sandbox ──────────────────────────
    step_log(2, "Provision managed sandbox",
             "Requesting isolated browser from Vertex AI")

    sandbox_info = create_sandbox(client)
    sandbox_id = sandbox_info["sandbox_id"]
    cdp_endpoint = sandbox_info["cdp_endpoint"]
    is_mock = sandbox_info.get("is_mock", False)

    if is_mock:
        print("  ℹ  Running in DEMO mode with mock sandbox.")
        print("  ℹ  The code below shows the exact flow for a real sandbox.")
        print("  ℹ  To run for real, enable the Sandbox API and set your project.\n")

    # ── Step 3: Connect Playwright via CDP ───────────────────────────
    step_log(3, "Connect via Chrome DevTools Protocol",
             f"Endpoint: {cdp_endpoint[:50]}...")

    # This is the critical line — instead of launching a local browser,
    # we connect to the remote sandbox browser over CDP.
    #
    # In a real deployment:
    #   browser = pw.chromium.connect_over_cdp(cdp_endpoint)
    #
    # The connection gives us full Playwright control of the remote
    # browser, including navigation, screenshots, and input events.

    pw = sync_playwright().start()

    if is_mock:
        # For the demo, fall back to a local browser
        print("  ℹ  Mock mode: launching local browser instead of CDP")
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
        )
        page = context.new_page()
        owns_context = True
    else:
        # ── Real CDP connection ──────────────────────────────────────
        # connect_over_cdp returns a Browser object connected to the
        # remote Chromium instance.  We use its default context.
        print(f"  Connecting to CDP endpoint...")
        browser = pw.chromium.connect_over_cdp(cdp_endpoint)
        # The sandbox browser typically has one default context
        context = browser.contexts[0] if browser.contexts else browser.new_context(
            viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
        )
        page = context.pages[0] if context.pages else context.new_page()
        owns_context = False  # don't close the sandbox's default context

    page.goto("https://www.google.com", wait_until="networkidle")
    print(f"  ✓ Connected to browser → {page.url}")

    # ── Step 4: Configure tools (identical to Approach 1) ────────────
    step_log(4, "Configure Computer Use tool",
             "Exact same configuration for both approaches")

    cu_tool = types.Tool(
        computer_use=types.ComputerUse(
            environment=types.Environment.ENVIRONMENT_BROWSER,
        ),
    )
    gen_config = GenerateContentConfig(
        tools=[cu_tool],
        temperature=1.0,
        max_output_tokens=8192,
        thinking_config=types.ThinkingConfig(include_thoughts=True),
    )
    print("  ✓ Tool configured")

    # ── Step 5: Take initial screenshot ──────────────────────────────
    step_log(5, "Initial screenshot from sandbox browser")

    initial_png, initial_url = capture_state(page)
    print(f"  ✓ Screenshot from sandbox: {len(initial_png) / 1024:.1f} KB")

    conversation: list[Content] = [
        Content(
            role="user",
            parts=[
                Part(text=task),
                Part(
                    inline_data=types.Blob(
                        mime_type="image/png",
                        data=initial_png,
                    )
                ),
            ],
        )
    ]

    # ── Step 6: Agent loop ───────────────────────────────────────────
    step_log(6, "Run agent loop in sandbox",
             f"Max {MAX_AGENT_TURNS} turns")

    final_answer: Optional[str] = None

    for turn in range(1, MAX_AGENT_TURNS + 1):
        print(f"  ── Turn {turn} ──")

        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=conversation,
                config=gen_config,
            )
        except Exception as exc:
            print(f"  ✗ API error: {exc}")
            time.sleep(2)
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=conversation,
                    config=gen_config,
                )
            except Exception as retry_exc:
                print(f"  ✗ Retry failed: {retry_exc}")
                break

        if not response.candidates:
            print("  ✗ Empty response — stopping")
            break

        candidate = response.candidates[0]
        if candidate.content:
            conversation.append(candidate.content)

        text_parts = []
        function_calls = []
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.function_call:
                    function_calls.append(part.function_call)

        reasoning = " ".join(text_parts) if text_parts else None

        if not function_calls:
            final_answer = reasoning
            print(f"  ✓ Agent finished: {(reasoning or '(no text)')[:120]}...")
            break

        for fc in function_calls:
            arg_summary = ", ".join(
                f"{k}={v}" for k, v in (fc.args or {}).items()
            )
            print(f"    → {fc.name}({arg_summary})")

        fn_responses: list[FunctionResponse] = []
        for fc in function_calls:
            png_bytes, url = dispatch_action(page, fc)
            fn_responses.append(
                FunctionResponse(
                    name=fc.name,
                    response={"url": url},
                    parts=[
                        types.FunctionResponsePart(
                            inline_data=types.FunctionResponseBlob(
                                mime_type="image/png",
                                data=png_bytes,
                            )
                        )
                    ],
                )
            )

        conversation.append(
            Content(
                role="user",
                parts=[Part(function_response=fr) for fr in fn_responses],
            )
        )
        prune_old_screenshots(conversation)

    else:
        print(f"\n  ⚠  Reached maximum turns ({MAX_AGENT_TURNS})")

    # ── Step 7: Cleanup — browser + sandbox ──────────────────────────
    step_log(7, "Cleanup sandbox", "Disconnect browser, delete sandbox")

    if owns_context:
        context.close()
    browser.close()
    pw.stop()
    print("  ✓ Browser disconnected")

    # Delete the cloud sandbox to stop billing
    if not is_mock:
        delete_sandbox(sandbox_id)
    else:
        print(f"  ℹ  Mock mode: skipping sandbox deletion")
        print(f"  ℹ  Real sandbox ID would be: {sandbox_id}")

    print("  ✓ Cleanup complete")

    return final_answer


# ═════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Step 05 — Gemini Computer Use via Vertex AI Enterprise Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with self-managed browser (Approach 1)
  python enterprise_agent.py --approach self-managed

  # Run with managed sandbox (Approach 2)
  python enterprise_agent.py --approach managed-sandbox

  # Custom task
  python enterprise_agent.py --approach self-managed \\
      --task "Find the current weather in Tokyo on weather.gov"

  # Override project settings
  python enterprise_agent.py --approach self-managed \\
      --project my-gcp-project --location europe-west4
        """,
    )

    parser.add_argument(
        "--approach",
        choices=["self-managed", "managed-sandbox"],
        default="self-managed",
        help=(
            "Which approach to use.  'self-managed' runs a local Playwright "
            "browser (Approach 1).  'managed-sandbox' provisions a cloud "
            "sandbox (Approach 2).  Default: self-managed."
        ),
    )
    parser.add_argument(
        "--task",
        type=str,
        default=DEFAULT_TASK,
        help="The task for the agent to perform.",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="GCP project ID (overrides GCP_PROJECT_ID env var).",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="GCP location (overrides GCP_LOCATION env var).",
    )

    args = parser.parse_args()

    # Allow CLI overrides for project/location
    global PROJECT_ID, LOCATION
    if args.project:
        PROJECT_ID = args.project
    if args.location:
        LOCATION = args.location

    # ── Validate configuration ───────────────────────────────────────
    if PROJECT_ID == "YOUR_PROJECT_ID":
        banner("CONFIGURATION REQUIRED")
        print("  You need to set your Google Cloud project ID.")
        print()
        print("  Option 1 — Environment variable:")
        print("    export GCP_PROJECT_ID='my-gcp-project'")
        print()
        print("  Option 2 — Command line flag:")
        print("    python enterprise_agent.py --project my-gcp-project")
        print()
        print("  Option 3 — Edit this file:")
        print("    PROJECT_ID = 'my-gcp-project'  # line ~57")
        print()
        print("  Then run:  gcloud auth application-default login")
        print()

        # Continue anyway — will fail at API call time with a clear error
        print("  Continuing with placeholder project ID...\n")

    # ── Dispatch to the chosen approach ──────────────────────────────
    banner("GEMINI ENTERPRISE AGENT PLATFORM — COMPUTER USE")
    print(f"  Approach : {args.approach}")
    print(f"  Project  : {PROJECT_ID}")
    print(f"  Location : {LOCATION}")
    print(f"  Model    : {MODEL}")
    print(f"  Task     : {args.task[:80]}{'...' if len(args.task) > 80 else ''}")

    start_time = time.time()

    if args.approach == "self-managed":
        result = run_self_managed(args.task)
    else:
        result = run_managed_sandbox(args.task)

    elapsed = time.time() - start_time

    # ── Print summary ────────────────────────────────────────────────
    banner("SESSION SUMMARY")
    print(f"  Approach : {args.approach}")
    print(f"  Duration : {elapsed:.1f}s")
    print(f"  Status   : {'✓ Completed' if result else '✗ No final answer'}")
    if result:
        print(f"\n  Final Answer:")
        # Word-wrap the answer for readability
        words = result.split()
        line = "    "
        for word in words:
            if len(line) + len(word) + 1 > 72:
                print(line)
                line = "    " + word
            else:
                line += " " + word if line.strip() else "    " + word
        if line.strip():
            print(line)
    print()


# ── Entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
