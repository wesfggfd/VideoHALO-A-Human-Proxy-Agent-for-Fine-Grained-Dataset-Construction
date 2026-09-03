# VideoHALO

VideoHALO is the human-proxy agentic workflow used to construct the 2,000 samples
VidHalLoc video hallucination benchmark. This repository contains the public
credential-free release of the exact hallucination diagnostic framework construction runtime, policy
bundle, selection utilities, Enterprise execution tools, monitors, and tests.

The benchmark data and source videos are not included in this repository.

## Construction setting

The released workflow was used with the following frozen setting:

- 1,090 cleaned candidate videos;
- a target of 2,000 accepted natural/counterfactual pairs;
- at most two accepted pairs per source video;
- one semantic model, `gemini-3.6-flash`, accessed through the Google Cloud
  Enterprise/Vertex transport with ADC

The runtime exposes exactly six roles: `<planner_agent>`,
`<extraction_agent>`, `<reflection_agent>`, `<generation_agent>`,
`<verification_agent>`, and `<monitor_agent>`. They use role-specific prompts,
media scopes, and reasoning settings while sharing the same base model. No
API-key-based fallback or secondary foundation model is part of the production
path.

## Hallucination taxonomy

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

The production graph is organized as four structured subtasks:

1. **Hallucination Category Retrieval** — `<planner_agent>` reads the video and
   scans all eight frozen leaves for constructible evidence intervals.
2. **Fact Extraction and Reflection** — `<extraction_agent>` inherits the
   retrieval output and extracts grounded atomic facts; `<reflection_agent>`
   independently rereads the video and challenges their support, grounding,
   leaf assignment, and mutation viability.
3. **Generation and Verification of Adversarial Pairs** —
   `<generation_agent>` inherits reflected facts, applies the selected
   leaf-specific template and realizes the natural/counterfactual pair;
   `<verification_agent>` back-parses both answers into structured facts and
   enforces the one-fact, one-slot GraphDiff contract.
4. **Comprehensive Reliability Validation** — `<monitor_agent>` independently
   rereads the original video, evaluates the complete pair, and permits the
   atomic nine-field JSONL append only when every reliability gate passes.

Every subtask emits a versioned structured stage envelope consumed by the next
subtask. All six agents read and contribute to the append-only dual-layer
memory: `system_cognitive_memory` for cross-stage operational cognition and
`category_memory` for Fixed-8 category-conditioned experience. Memory traces
remain internal audit artifacts and never alter the public pair schema.

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
