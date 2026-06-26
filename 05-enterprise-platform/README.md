# Step 05 — Enterprise Agent Platform (Vertex AI)

## What You'll Learn

This step shows how to run Gemini Computer Use through the **Enterprise Agent
Platform** — Google Cloud's production-grade infrastructure for deploying AI
agents.  You'll learn:

| Concept | What it covers |
|---|---|
| **Vertex AI authentication** | IAM-based access instead of API keys — project-level billing, audit logs, VPC Service Controls |
| **Self-managed environment** | Use your own Playwright browser with Vertex AI as the backend (Approach 1) |
| **Managed sandboxes** | Provision isolated cloud-hosted browsers via the Sandbox API (Approach 2) |
| **CDP connection** | Connect Playwright to a remote browser over Chrome DevTools Protocol |
| **Sandbox lifecycle** | Create → use → delete pattern for ephemeral browser environments |

## When to Use the Enterprise Platform

The Gemini Developer API (API key) is great for prototyping.  Move to the
Enterprise Platform when you need:

- **IAM & access control** — fine-grained permissions via Google Cloud IAM
- **Audit logging** — every API call logged to Cloud Audit Logs
- **VPC Service Controls** — restrict data to your network perimeter
- **CMEK** — customer-managed encryption keys for data at rest
- **SLA** — production-grade availability guarantees
- **Billing controls** — project-level budgets and quotas
- **Managed sandboxes** — secure, isolated browser environments in the cloud

## Gemini API vs Enterprise Platform

| Feature | Gemini API (Developer) | Enterprise Platform (Vertex AI) |
|---|---|---|
| **Authentication** | API key | Google Cloud IAM (OAuth / Service Account) |
| **Setup complexity** | `export GEMINI_API_KEY=...` | `gcloud auth application-default login` + project |
| **Billing** | Per-key usage | Project-level billing with budgets & alerts |
| **Access control** | API key holder has full access | IAM roles: viewer, editor, admin |
| **Audit trail** | Limited | Full Cloud Audit Logs integration |
| **Network security** | Public internet | VPC Service Controls, private endpoints |
| **Encryption** | Google-managed | CMEK option available |
| **Managed sandboxes** | ✗ | ✓ (cloud-hosted isolated browsers) |
| **SLA** | Best-effort | Production SLA |
| **Code change needed** | — | One-line client config change |

## Prerequisites

### 1. Google Cloud Project

```bash
# Install gcloud CLI if you haven't already
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
```

### 2. Enable Required APIs

```bash
# Core API for Gemini
gcloud services enable aiplatform.googleapis.com

# Required for managed sandboxes
gcloud services enable iam.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com
```

### 3. IAM Permissions

Your user or service account needs these roles:

| Role | Purpose |
|---|---|
| `roles/aiplatform.user` | Call Gemini models |
| `roles/aiplatform.admin` | Create/delete sandboxes (Approach 2 only) |
| `roles/iam.serviceAccountUser` | Act as a service account (Approach 2 only) |

```bash
# Grant Vertex AI user role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="user:you@example.com" \
    --role="roles/aiplatform.user"
```

### 4. Python Dependencies

```bash
pip install google-genai playwright google-cloud-aiplatform google-auth
python -m playwright install chromium
```

### 5. Environment Variables

```bash
export GCP_PROJECT_ID="your-project-id"
export GCP_LOCATION="global"          # optional, this is the default
```

## Architecture

### Approach 1: Self-Managed Browser

```
┌─────────────────────────────────────────────────────────┐
│  Your Machine / Cloud Run / GKE                         │
│                                                         │
│  ┌──────────────┐     ┌──────────────┐                  │
│  │  enterprise   │────→│  Chromium     │                 │
│  │  _agent.py    │←────│  (Playwright) │                 │
│  └──────┬───────┘     └──────────────┘                  │
│         │                                               │
│         │  Vertex AI SDK (IAM auth)                     │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────┐
│  Vertex AI              │
│  ┌───────────────────┐  │
│  │  Gemini 3.5 Flash  │  │
│  │  (Computer Use)    │  │
│  └───────────────────┘  │
└─────────────────────────┘
```

- You control the browser — install it, update it, configure it
- Same code as earlier steps, just swap the client config
- Best for: development, CI/CD, self-hosted production

### Approach 2: Managed Sandbox

```
┌────────────────────────────────────────────────────────────┐
│  Your Machine / Cloud Run                                  │
│                                                            │
│  ┌──────────────┐                                          │
│  │  enterprise   │──── Playwright connect_over_cdp() ──┐   │
│  │  _agent.py    │                                     │   │
│  └──────┬───────┘                                     │   │
│         │                                              │   │
└─────────┼──────────────────────────────────────────────┼───┘
          │ Vertex AI SDK                                │ CDP (WebSocket)
          ▼                                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Google Cloud                                               │
│                                                             │
│  ┌───────────────────┐    ┌────────────────────────────┐    │
│  │  Gemini 3.5 Flash  │    │  Managed Sandbox           │   │
│  │  (Computer Use)    │    │  ┌──────────────────────┐  │   │
│  └───────────────────┘    │  │  Isolated Chromium    │  │   │
│                            │  │  (ephemeral VM)       │  │   │
│                            │  └──────────────────────┘  │   │
│                            └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

- Google manages the browser — provisioned on demand, auto-cleaned
- Connected via CDP WebSocket — Playwright works identically
- Best for: multi-tenant SaaS, security-sensitive workloads, serverless

## Running the Script

### Approach 1: Self-Managed Browser

```bash
# Minimal — uses defaults
python enterprise_agent.py --approach self-managed

# Custom task
python enterprise_agent.py --approach self-managed \
    --task "Go to github.com and find the trending repositories page"

# Override project settings via CLI
python enterprise_agent.py --approach self-managed \
    --project my-gcp-project \
    --location europe-west4
```

### Approach 2: Managed Sandbox

```bash
# Launch with managed sandbox
python enterprise_agent.py --approach managed-sandbox

# Custom task with sandbox
python enterprise_agent.py --approach managed-sandbox \
    --task "Search for 'machine learning' on Wikipedia and summarise the intro"
```

> **Note:** Approach 2 requires the Sandbox API to be enabled and your project
> to be allowlisted.  If the API is not available, the script will fall back to
> a mock/demo mode that shows the intended code flow with a local browser.

## Expected Output

```
════════════════════════════════════════════════════════════════
  GEMINI ENTERPRISE AGENT PLATFORM — COMPUTER USE
════════════════════════════════════════════════════════════════

  Approach : self-managed
  Project  : my-gcp-project
  Location : global
  Model    : gemini-3.5-flash
  Task     : Navigate to https://news.ycombinator.com and tell me...

════════════════════════════════════════════════════════════════
  APPROACH 1 — VERTEX AI + SELF-MANAGED BROWSER
════════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────
  Step 1 → Create Vertex AI client
  Using Application Default Credentials (ADC)
────────────────────────────────────────────────────────

  ✓ Client created with vertexai=True

────────────────────────────────────────────────────────
  Step 2 → Launch local Playwright browser
────────────────────────────────────────────────────────

  ✓ Browser launched → https://www.google.com

  ...

────────────────────────────────────────────────────────
  Step 5 → Run agent loop
────────────────────────────────────────────────────────

  ── Turn 1 ──
    → navigate(url=https://news.ycombinator.com)
  ── Turn 2 ──
    → scroll(x=500, y=500, direction=down, magnitude=400)
  ── Turn 3 ──
  ✓ Agent finished: The top 3 stories on Hacker News are...

════════════════════════════════════════════════════════════════
  SESSION SUMMARY
════════════════════════════════════════════════════════════════

  Approach : self-managed
  Duration : 18.3s
  Status   : ✓ Completed

  Final Answer:
    The top 3 stories currently on the Hacker News
    front page are...
```

## Key Concepts

### One-Line Migration

The entire difference between the Gemini Developer API and Vertex AI is how
you create the client:

```python
# ── Gemini Developer API (Steps 01-04) ──
client = genai.Client(api_key="AIza...")

# ── Vertex AI Enterprise (Step 05) ──
client = genai.Client(
    vertexai=True,
    project="my-project",
    location="global",
)
```

Everything else — tool declarations, the agent loop, action handling,
screenshot capture — is **identical**.

### CDP Connection (Managed Sandbox)

When using a managed sandbox, you connect via Chrome DevTools Protocol instead
of launching a local browser:

```python
# Local browser (self-managed):
browser = pw.chromium.launch(headless=True)

# Remote sandbox (managed):
browser = pw.chromium.connect_over_cdp("ws://sandbox-host:9222/devtools/...")
```

Once connected, the Playwright `page` object works identically — clicks,
screenshots, navigation all behave the same way.

### Sandbox Lifecycle

```python
# 1. Create
sandbox = create_sandbox(client)

# 2. Connect
browser = pw.chromium.connect_over_cdp(sandbox["cdp_endpoint"])

# 3. Use (run your agent loop)
# ... dispatch_action(page, fc) ...

# 4. Delete (stop billing!)
delete_sandbox(sandbox["sandbox_id"])
```

Always clean up your sandbox.  They bill for compute time until deleted or
until their TTL expires.

### Screenshot Pruning

Long agent sessions can exhaust the context window.  The script automatically
strips screenshots from older turns while keeping the most recent 3:

```python
def prune_old_screenshots(conversation, keep_recent=3):
    """Remove image data from old turns to save context space."""
    # Walks conversation in reverse, keeping the N most recent
    # screenshot-bearing turns intact
```

## Troubleshooting

| Problem | Solution |
|---|---|
| `DefaultCredentialsError` | Run `gcloud auth application-default login` |
| `Permission denied` | Check IAM roles — need `roles/aiplatform.user` |
| `API not enabled` | Run `gcloud services enable aiplatform.googleapis.com` |
| `Quota exceeded` | Check quotas in Cloud Console → IAM & Admin → Quotas |
| `Sandbox creation failed` | Verify project is allowlisted for Sandbox API |
| `CDP connection refused` | Check network/firewall rules allow WebSocket traffic |

## What's Next

You've now seen Computer Use across the full spectrum:

| Step | What you learned |
|---|---|
| 01 — Hello Screenshot | Playwright + Gemini vision basics |
| 02 — Single Action | One Computer Use action |
| 03 — Agent Loop | Multi-turn browser automation |
| 04 — Mobile Agent | Computer Use on Android via ADB |
| **05 — Enterprise** | **Production deployment via Vertex AI** |

From here, consider:
- Adding **custom tools** alongside Computer Use (database lookups, API calls)
- Implementing **safety confirmations** for sensitive actions
- Building a **web UI** to monitor agent sessions in real-time
- Deploying on **Cloud Run** with a managed sandbox for a fully serverless agent
