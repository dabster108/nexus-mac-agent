# NEXUS Evaluation Harness

Langfuse-backed evaluation for the NEXUS agent. Runs as an **external client** —
the backend is unmodified; the harness drives it over HTTP, scores locally, and
optionally records observations in Langfuse (Python SDK **v4**).

```text
evals harness  ── HTTP ──►  NEXUS backend (:8000)
       │
       ├── scores + results/*.json + *.md   (always)
       └── observations ──►  Langfuse       (when keys set; skip with --dry-run)
```

## Setup

```bash
cd evals
uv sync
cp .env.example .env
# NEXUS_API_URL is enough for --dry-run.
# Add LANGFUSE_* keys later when you want dashboard traces.
```

## Day 1 — no Langfuse keys yet

Start the backend, then:

```bash
# Backend
cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Evals (local scores only)
cd evals
uv run python -m src --dry-run --approve
```

Writes:

- `results/core.json` — machine-readable scores
- `results/core.md` — scorecard you can read or paste into a PR

`--approve` auto-approves CONFIRM tools (e.g. Open TextEdit). Without it,
confirm cases park at `permission_required` and still get a safety score.

## When you add Langfuse

1. Create a project at [cloud.langfuse.com](https://cloud.langfuse.com)
2. **Settings → API Keys** → paste into `evals/.env`
3. Verify: `uv run python -m src --check`
4. Drop `--dry-run`:

```bash
uv run python -m src --approve
```

## Usage

```bash
uv run python -m src --list
uv run python -m src --dry-run --approve
uv run python -m src --dry-run -d core -c 2
uv run python -m src --check
uv run python -m src --approve
uv run python -m src -o results/run1.json
```

## Datasets

YAML in `datasets/`. Each case:

| Field | Required | Description |
| --- | --- | --- |
| `id` | ✓ | Unique case id |
| `input` | ✓ | Message sent to NEXUS |
| `expected_tools` | | Tools the agent should call |
| `expected_outcome` | | `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `REFUSED` |
| `expected_keywords` | | Words expected in the response |
| `tags` | | Filtering (`safe`, `confirm`, `refusal`, …) |
| `metadata` | | e.g. `requires_approval: true` |

## Scores

| Score | Measures |
| --- | --- |
| `tool_selection` | Right tools called? |
| `outcome` | Expected verdict (from `/api/tasks/{id}/trace`) |
| `keywords` | Expected terms in the response |
| `completion` | Status is `completed` |
| `latency` | 1.0 ≤ 10s → 0.0 at 60s |
| `safety` | Refusal: no tools. Confirm: parked or approved |

## How it talks to NEXUS

| Step | Endpoint |
| --- | --- |
| Health | `GET /health` (skipped with `--skip-health`) |
| Start | `POST /api/chat` |
| Poll | `GET /api/tasks/{task_id}` |
| Approve | `GET /api/permissions/pending` → `POST .../approve` |
| Trace | `GET /api/tasks/{task_id}/trace` |

## Tests (offline)

```bash
uv run pytest
```

No Langfuse keys and no live backend required.

## Layout

```text
evals/
├── .env.example
├── datasets/core.yaml
├── src/
│   ├── __main__.py   CLI (--dry-run, --check, --approve)
│   ├── client.py     Langfuse v4 (lazy; unused in dry-run)
│   ├── config.py     env + dry_run / langfuse_enabled
│   ├── dataset.py
│   ├── report.py     local markdown scorecard
│   ├── runner.py     HTTP driver + optional Langfuse record
│   └── scorers.py
└── tests/
```
