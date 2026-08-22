# Four-Stage LangGraph Engineering Architecture

## Runtime profiles

`probe_build` and `evalbench_build` share one four-stage BuildGraph. They differ
only in source pool, selection policy, and target scale.

## Public orchestration graph

```text
START
  -> hallucination_category_retrieval
  -> fact_extraction_and_reflection
  -> generation_and_verification_of_adversarial_pairs
  -> comprehensive_reliability_validation
  -> END
```

Each node may execute multiple deterministic gates, but it exposes exactly one
versioned structured stage output. The next node validates that envelope before
reading its payload.

| Subtask | Agents | Video access | Principal output |
|---|---|---|---|
| Hallucination Category Retrieval | `<planner_agent>` | original video | eight-leaf opportunity matrix |
| Fact Extraction and Reflection | `<extraction_agent>`, `<reflection_agent>` | independent original-video reads | reflected FactGraph and eligibility records |
| Generation and Verification of Adversarial Pairs | `<generation_agent>`, `<verification_agent>` | no direct video access | complete pair, reconstructed facts, GraphDiff |
| Comprehensive Reliability Validation | `<monitor_agent>` | independent original-video reread | reliability decision and public record |

## Structured communication protocol

Every envelope contains `schema_version`, `stage`, `video_id`,
`producer_agents`, `upstream_stages`, `payload`, and `memory_snapshot`. Producer
lists are fixed by the stage contract, which prevents a role from silently
performing another role's responsibility.

## Memory and deterministic gates

All agents contribute to `system_cognitive_memory` and `category_memory`.
Deterministic code still owns media identity, Fixed-8 resolution, eligibility,
one-slot mutation, GraphDiff, deduplication, budget enforcement, and atomic
JSONL output. Independent model observations do not share hidden chain of
thought; only schema-validated outputs enter memory.

## Recovery

Content-addressed artifacts, deterministic IDs, bounded retries, and a
checkpointer make stage replay idempotent. Recovery never rewrites an accepted
public sample.
