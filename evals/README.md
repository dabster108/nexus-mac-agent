# NEXUS Evaluation Harness

External eval harness for NEXUS. Drives the live backend over HTTP, scores
deterministically, writes versioned run artifacts, and records observations in
**Langfuse** (Python SDK v4).

```text
Cases (YAML) → Target (NEXUS HTTP) → Judges (scorers)
                    │
                    ├── Artifacts: results/<run>.json (nexus-evals/v1)
                    ├── Report:    results/<run>.md
                    └── Telemetry: Langfuse traces / scores / Datasets
```

Orchestration lives in ``src/harness.py``; the CLI only parses flags.

## Quick start

```bash
cd evals && uv sync

uv run python -m src --check                 # Langfuse keys
# or: uv run nexus-evals --check
# other terminal: backend on :8000
uv run python -m src --approve               # smoke + Langfuse (default)
uv run python -m src -d core --approve       # full suite
```

Filter Langfuse by tag `run:<run_name>` or environment `dev`. Dataset:
`nexus-evals-smoke`.

## Harness contract

Every run writes a **`nexus-evals/v1`** envelope:

| Field | Meaning |
| --- | --- |
| `run_name` / `dataset` / `dataset_version` | Identity of the run |
| `aggregates` | Per-score means + `overall` (excludes latency) |
| `passed` / `failed` | Cases with status `completed` and quality ≥ 0.7 |
| `cases[]` | Per-case scores, tools, trace URL, `passed` |

Exit code **1** if any case fails that bar.

## Commands

| Command | Purpose |
| --- | --- |
| `--check` | Verify Langfuse API keys |
| `--sync -d smoke` | Upsert YAML → Langfuse Dataset |
| `--approve` | Live run (auto-sync unless `--no-sync`) |
| `--dry-run --approve` | Local scores only |
| `--run-name demo-1` | Named run for dashboard filtering |
| `--list` | List YAML datasets |

Artifacts default to `results/<run_name>.json` (+ alias `results/<dataset>.json`).

## Scores

| Score | Role |
| --- | --- |
| `tool_selection` | Expected tools called |
| `outcome` | Verdict / completed SAFE fallback |
| `keywords` | Expected terms (apostrophe-normalized) |
| `completion` | Status is `completed` |
| `safety` | Refusal / confirm-gate |
| `latency` | Diagnostic only — **not** in `overall` |
| `overall` | Mean of quality scores above |

## Datasets

| File | Use |
| --- | --- |
| `datasets/smoke.yaml` (`version: "1"`) | Default first pass |
| `datasets/core.yaml` (`version: "1"`) | Broader regression |

Remote Langfuse name: `nexus-evals-<local>`; item id `nexus-<local>-<case_id>`.

## Layout

```text
evals/
├── datasets/{smoke,core}.yaml
├── src/
│   ├── __main__.py     CLI
│   ├── harness.py      orchestration (cases→target→judges→artifacts)
│   ├── schema.py       RUN_SCHEMA = nexus-evals/v1
│   ├── aggregates.py   quality means + pass/fail
│   ├── client.py       Langfuse singleton
│   ├── config.py
│   ├── dataset.py      validated YAML loader
│   ├── sync.py         YAML → Langfuse Datasets
│   ├── runner.py       HTTP driver + Langfuse record
│   ├── scorers.py
│   └── report.py       envelope + markdown
└── tests/
```

Entry points: ``uv run python -m src …`` or ``uv run nexus-evals …``.

## Offline tests

```bash
uv run pytest
```
