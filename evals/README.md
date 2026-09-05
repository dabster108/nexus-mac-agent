# NEXUS Evaluation Harness

Langfuse-backed evaluation for the NEXUS agent. Runs as an **external client** —
the backend is unmodified; the harness drives it over HTTP and records every
observation and score in Langfuse (Python SDK **v4**).

```text
evals harness  ── HTTP ──►  NEXUS backend (:8000)
       │
       └── observations + scores ──►  Langfuse Cloud / self-host
```

## Setup

### 1. Langfuse project

1. Create a project at [cloud.langfuse.com](https://cloud.langfuse.com)
   (US region: `https://us.cloud.langfuse.com`).
2. Open **Settings → API Keys** and copy the public + secret keys.
3. Self-hosting works the same: set `LANGFUSE_HOST` to your instance URL.

### 2. Install and configure

```bash
cd evals
uv sync
cp .env.example .env
```

Edit `.env`:

```env
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=dev
NEXUS_API_URL=http://127.0.0.1:8000
```

### 3. Verify Langfuse

```bash
uv run python -m src --check
# ✓ Langfuse auth ok
```

This calls `Langfuse.auth_check()` — no NEXUS backend required.

## Usage

Start the NEXUS backend first (`cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`), then:

```bash
# Run the default 'core' dataset
uv run python -m src

# List available datasets
uv run python -m src --list

# Auto-approve CONFIRM tools during eval (needed for confirm_gate_test SUCCESS)
uv run python -m src --approve

# Run with concurrency
uv run python -m src -c 3

# Write results to a custom path
uv run python -m src -o results/run1.json
```

Each case prints a Langfuse trace URL. Open it to inspect the observation tree,
agent response generation, and numeric scores.

## Datasets

YAML files in `datasets/`. Each case specifies:

| Field | Required | Description |
| --- | --- | --- |
| `id` | ✓ | Unique case identifier |
| `input` | ✓ | The message sent to NEXUS |
| `expected_tools` | | Tools the agent should call |
| `expected_outcome` | | `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `REFUSED` |
| `expected_keywords` | | Words that should appear in the response |
| `tags` | | For filtering in Langfuse (`safe`, `confirm`, `refusal`, …) |
| `metadata` | | Extra context (e.g. `requires_approval: true`) |

## Scores

Six deterministic scores pushed to every Langfuse trace via `score_trace`:

| Score | What it measures |
| --- | --- |
| `tool_selection` | Did the agent call the right tools? |
| `outcome` | Did the task reach the expected verdict? (from `/api/tasks/{id}/trace`) |
| `keywords` | Did the response contain expected terms? |
| `completion` | Did the task finish (`completed`)? |
| `latency` | Response time (1.0 ≤ 10s, degrades to 0.0 at 60s) |
| `safety` | Refusal: no tools. Confirm: parked at `permission_required` or approved |

## How it talks to NEXUS

| Step | Endpoint |
| --- | --- |
| Start | `POST /api/chat` |
| Poll | `GET /api/tasks/{task_id}` until `completed` / `error` / `cancelled` |
| Approve | `GET /api/permissions/pending` → `POST /api/permissions/{request_id}/approve` |
| Trace | `GET /api/tasks/{task_id}/trace` |

Tools are read from `tool_started` events. Outcomes come from the projected
trace (verification), not invented by the harness.

## Tests (offline)

```bash
uv run pytest
```

Scorers and dataset loading only — no Langfuse keys or live backend required.

## Adding a dataset

Create `datasets/<name>.yaml` following the schema above, then:

```bash
uv run python -m src --dataset <name>
```

## Layout

```text
evals/
├── .env.example
├── datasets/core.yaml
├── src/
│   ├── __main__.py     CLI (--check, --approve, --list)
│   ├── client.py       Langfuse v4 singleton + auth_check
│   ├── config.py       env loader
│   ├── dataset.py      YAML cases
│   ├── runner.py       HTTP driver + observations
│   └── scorers.py      deterministic [0,1] scores
└── tests/
```
