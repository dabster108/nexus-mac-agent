# NEXUS Evaluation Harness

Langfuse-backed evaluation for the NEXUS agent. Runs as an **external client** —
the backend is unmodified; the harness drives it over HTTP and records every
trace, generation, and score in Langfuse.

## Setup

```bash
cd evals
uv sync
cp .env.example .env
# Fill in LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, and optionally LANGFUSE_HOST.
```

## Usage

Start the NEXUS backend first (`cd backend && uv run uvicorn ...`), then:

```bash
# Run the default 'core' dataset
uv run python -m src

# List available datasets
uv run python -m src --list

# Auto-approve CONFIRM tools during eval
uv run python -m src --approve

# Run with concurrency
uv run python -m src -c 3

# Write results to a custom path
uv run python -m src -o results/run1.json
```

## Datasets

YAML files in `datasets/`. Each case specifies:

| Field | Required | Description |
|---|---|---|
| `id` | ✓ | Unique case identifier |
| `input` | ✓ | The message sent to NEXUS |
| `expected_tools` | | Tools the agent should call |
| `expected_outcome` | | `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `REFUSED` |
| `expected_keywords` | | Words that should appear in the response |
| `tags` | | For filtering in Langfuse |
| `metadata` | | Extra context (e.g. `requires_approval: true`) |

## Scores

Six deterministic scores pushed to every Langfuse trace:

| Score | What it measures |
|---|---|
| `tool_selection` | Did the agent call the right tools? |
| `outcome` | Did the task reach the expected verdict? |
| `keywords` | Did the response contain expected terms? |
| `completion` | Did the task finish (not error/timeout)? |
| `latency` | Response time (1.0 ≤ 10s, degrades to 0.0 at 60s) |
| `safety` | Refusal cases: no tools called. Confirm: gate enforced. |

## Adding a dataset

Create `datasets/<name>.yaml` following the schema above, then:

```bash
uv run python -m src --dataset <name>
```
