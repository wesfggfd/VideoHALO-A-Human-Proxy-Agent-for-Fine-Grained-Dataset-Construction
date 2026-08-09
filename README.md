# VideoHALO

VideoHALO is the human-proxy agentic workflow used to construct the 2,000-pair
VidHalLoc video hallucination benchmark. This repository contains the public,
credential-free release of the exact Fixed-8 construction runtime, policy
bundle, selection utilities, Enterprise execution tools, monitors, and tests.

The benchmark data and source videos are not included in this repository.

## Construction setting

The released workflow was used with the following frozen setting:

- 2,600 cleaned candidate videos;
- a distribution-preserving 1,200-video active pool, balanced as 600 VideoQA
  and 600 video-captioning sources;
- a target of 2,000 accepted natural/counterfactual pairs;
- at most two accepted pairs per source video;
- one semantic model, `gemini-3.6-flash`, accessed through the Google Cloud
  Enterprise/Vertex transport with ADC; and
- deterministic hashing, selection, mutation, graph-difference validation,
  deduplication, atomic JSONL output, and budget enforcement outside the model.

Different agent roles use different prompts, media scopes, and reasoning
settings, but all model-based roles use the same base model. No API-key-based
fallback or secondary foundation model is part of the production path.

## Fixed-8 taxonomy

VideoHALO constructs visually decidable errors over eight mutually exclusive
atomic-fact leaves:

1. Entity Existence
2. Entity Category
3. Entity Quantity
4. Attribute Value
5. Static Relation
6. Action Predicate
7. Temporal Relation
8. Camera Predicate

Each accepted pair contains a video-supported natural answer and a
counterfactual answer that changes exactly one leaf-specific slot.

## Workflow

The production graph follows these stages:

1. Verify canonical media identity and private same-project GCS transport.
2. Scan all eight taxonomy leaves for constructible opportunities.
3. Extract at most one grounded atomic fact per constructible leaf.
4. Reflect on evidence support, unique grounding, leaf correctness, and
   mutation viability.
5. Select verified facts under task, diversity, uniqueness, and per-video caps.
6. Apply a deterministic, leaf-specific one-slot mutation.
7. Realize VideoQA or captioning text and jointly back-parse both answers.
8. Enforce a one-fact, one-slot graph difference with no unexpected changes.
9. Re-read the complete source video to verify that the natural answer is
   supported and the counterfactual is contradicted.
10. Append the exact nine-field public record atomically.

The full normative specification is under `videohalo/policy_bundle/`.

## Repository layout

- `videohalo/`: production Python package and LangGraph runtime.
- `videohalo/policy_bundle/`: Fixed-8 prompts, contracts, schemas, and frozen
  policy configuration.
- `tools/`: source selection, preflight, smoke tests, Enterprise launch,
  monitoring, interrupted-run repair, and release assembly utilities used by
  the 2K workflow.
- `tests/`: unit and integration tests with synthetic media references.
- `configs/formal_run_config.example.json`: credential-free formal-run example.
- `.env.example`: deployment variable template containing placeholders only.

## Installation

Python 3.9 or later is required.

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

`ffmpeg` and `ffprobe` must be available on `PATH`, or configured through
`VIDEOHALO_FFMPEG` and `VIDEOHALO_FFPROBE`.

## Authentication and private media

Copy `.env.example` to `.env` and replace placeholders locally. Never commit
the resulting file. Authenticate with ADC rather than an API key:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

The ADC identity, quota project, Enterprise project, and private GCS bucket
must belong to the approved deployment boundary. Review `SECURITY.md` before
running or publishing changes.

## Running the workflow

Prepare your private selection manifest, budget policy, resume status, runtime
preflight, and smoke gate. Copy the example config and replace the run ID and
paths. The public runner resolves relative paths from the repository working
directory and verifies every frozen argument before it starts:

```bash
cp configs/formal_run_config.example.json formal_run_config.json
python tools/preflight_vidhalloc_enterprise.py --runtime-access-check --live-model-check --output runs/formal_run_2000_enterprise/runtime_preflight.json
python tools/run_vidhalloc_enterprise.py --config formal_run_config.json --selection VidHalLoc_1200_budget500.json --output runs/formal_run_2000_enterprise/public_probe_items.jsonl --status runs/formal_run_2000_enterprise/status.json --budget-policy VidHalLoc_1200_budget500_build/budget_policy.json --run-id replace-with-your-run-id
```

Run the independent monitors in separate processes when performing a formal
construction run:

```bash
python tools/monitor_vidhalloc_enterprise_efficiency.py --run-dir runs/formal_run_2000_enterprise --policy VidHalLoc_1200_budget500_build/budget_policy.json
python tools/monitor_vidhalloc_budget_guard.py --run-dir runs/formal_run_2000_enterprise --policy VidHalLoc_1200_budget500_build/budget_policy.json
```

The repository does not ship the private selection, videos, GCS bucket, run
state, accepted JSONL records, or cost logs.

## Tests

```bash
python -m pytest -q
```

The tests use synthetic paths, synthetic GCS URIs, and mocked model clients;
they do not require access to the private dataset or cloud resources.
