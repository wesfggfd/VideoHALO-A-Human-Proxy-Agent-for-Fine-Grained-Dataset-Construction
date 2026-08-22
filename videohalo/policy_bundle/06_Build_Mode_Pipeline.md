# Four-Subtask Build Pipeline

## 1. Hallucination Category Retrieval

`<planner_agent>` receives the canonical original video and frozen Fixed-8
search plan. It evaluates every hallucination category exactly once, returning
`constructible`, `not_constructible`, or `uncertain`. A constructible entry must
include a decisive evidence interval, canonical anchor, fact kind, conflict
slot, and viable one-slot counterfactual. It emits the structured opportunity
matrix to the next subtask and contributes it to both memory layers.

Before the call, deterministic code verifies local SHA-256, canonical manifest,
private GCS lease, object metadata, MIME type, and request-media fingerprint.

## 2. Fact Extraction and Reflection

`<extraction_agent>` inherits only constructible opportunities, rereads their
evidence intervals, and extracts at most one normalized atomic fact per leaf.
It preserves the planned category, fact kind, conflict slot, time scope, and
anchors.

`<reflection_agent>` independently rereads the original video. It rejects facts
without direct support, unique grounding, a matching evidence interval, correct
Fixed-8 boundaries, or a viable mutation. Only reflected facts enter the
FactGraph and evidence-faithful selection. The stage emits the FactGraph,
reflection reports, and eligibility records.

## 3. Generation and Verification of Adversarial Pairs

`<generation_agent>` inherits a reflected fact, applies the frozen leaf-specific
single-slot operator, retrieves the task-compatible question template, and
realizes a complete natural/counterfactual question-answer pair. Non-target
anchors and the verified natural answer remain fixed.

`<verification_agent>` jointly back-parses both answers into normalized facts.
Deterministic validation requires:

```text
changed_atomic_fact_count = 1
changed_slot_count = 1
supported_contradicted_count = 0
counterfactual_contradicted_count = 1
resolved_leaf = planned_leaf
resolved_slot = planned_slot
unexpected_claim_count = 0
```

The stage emits the complete pair, reconstructed supported/counterfactual
facts, and GraphDiff.

## 4. Comprehensive Reliability Validation

`<monitor_agent>` receives the complete upstream output and independently
rereads the original video. It verifies natural-answer support, evidence-scope
overlap, hallucination-category correctness, counterfactual contradiction,
single-target-slot mutation, and the absence of additional errors. Only an
accepted monitor report permits projection to the exact nine-field public
record and atomic JSONL append.

## Shared memory and output boundary

All six agents read bounded snapshots and append schema-validated contributions
to `system_cognitive_memory` and `category_memory`. Stage envelopes and memory
traces are internal audit artifacts; the public dataset schema is unchanged.
