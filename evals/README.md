# NEXUS Evaluation Harness

External eval client for NEXUS. Drives the live backend over HTTP, scores
deterministically, writes local JSON/markdown, and records observations in
**Langfuse** (Python SDK v4).

```text
evals/datasets/*.yaml
        │
        ▼
   nexus-evals ── HTTP ──► NEXUS backend (:8000)
        │
        ├── results/*.json + *.md
        └── Langfuse traces + scores + Datasets
```

## Quick start (keys already in `.env`)

```bash
cd evals
uv sync

# 1. Confirm Langfuse
uv run python -m src --check

# 2. Start NEXUS backend (other terminal)
cd ../backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3. Smoke eval (default dataset) — syncs cases, runs, pushes traces
cd ../evals
uv run python -m src --approve
```

Default dataset is **`smoke`** (4 cases). Full set: `-d core`.

In Langfuse: **Traces** filtered by tag `run:<run-name>`, or **Datasets** →
`nexus-evals-smoke`.

## Commands

| Command | Purpose |
| --- | --- |
| `uv run python -m src --check` | Verify Langfuse API keys |
| `uv run python -m src --sync -d smoke` | Upsert YAML → Langfuse Dataset only |
| `uv run python -m src --approve` | Live smoke run + Langfuse (auto-sync) |
| `uv run python -m src -d core --approve` | Full core suite |
| `uv run python -m src --dry-run --approve` | Local scores only (no Langfuse) |
| `uv run python -m src --list` | List YAML datasets |
| `uv run python -m src --run-name demo-1 --approve` | Named run for dashboard filtering |

Live runs auto-sync the dataset unless you pass `--no-sync`.

## What gets recorded in Langfuse

Per case:

- Root observation `eval::<case_id>` with input/output, tools, latency
- Nested `agent_response` generation
- Numeric scores: `tool_selection`, `outcome`, `keywords`, `completion`,
  `latency`, `safety`, plus `overall`
- Tags: `eval`, `run:<run_name>`, `dataset:<name>`, case tags
- Metadata: `dataset_item_id`, `langfuse_dataset`, `task_id`

Local always:

- `results/<dataset>-<run_name>.json` (+ alias `results/<dataset>.json`)
- Matching `.md` scorecard

## Datasets

| File | Use |
| --- | --- |
| `datasets/smoke.yaml` | First pass after wiring Langfuse (default) |
| `datasets/core.yaml` | Broader regression suite |

Case fields: `id`, `input`, `expected_tools`, `expected_outcome`,
`expected_keywords`, `tags`, `metadata`.

Remote Langfuse name: `nexus-evals-<local>` with stable item ids
`nexus-<local>-<case_id>` (re-sync is an upsert).

## Scores

| Score | Measures |
| --- | --- |
| `tool_selection` | Expected tools called |
| `outcome` | Verdict from `/api/tasks/{id}/trace` |
| `keywords` | Expected terms in the response |
| `completion` | Status is `completed` |
| `latency` | 1.0 ≤ 10s → 0.0 at 60s |
| `safety` | Refusal / confirm-gate behaviour |
| `overall` | Mean of the above (Langfuse only) |

## Env

```env
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://us.cloud.langfuse.com   # EU: https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=dev
NEXUS_API_URL=http://127.0.0.1:8000
```

## Offline tests

```bash
uv run pytest
```

## Layout

```text
evals/
├── datasets/{smoke,core}.yaml
├── src/
│   ├── __main__.py   CLI
│   ├── client.py     Langfuse singleton
│   ├── config.py
│   ├── dataset.py    YAML loader
│   ├── sync.py       YAML → Langfuse Datasets
│   ├── runner.py     HTTP driver + Langfuse record
│   ├── scorers.py
│   └── report.py     markdown scorecard
└── tests/
```
