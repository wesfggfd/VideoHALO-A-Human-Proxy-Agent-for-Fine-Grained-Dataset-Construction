# Memory System Design

## Working memory

Each LangGraph thread stores per-video or per-item intermediate state:

- VideoManifest and provider lease;
- proposed and verified facts;
- eligibility records;
- planned mutation;
- realized answer pair;
- backparse and GraphDiff;
- reflection reports;
- direct-output record;
- retry counters and error codes.

A checkpointer persists this state for recovery. Working memory expires according to run policy and is never injected into unrelated samples.

## Long-term memory

Long-term memory is read-only, versioned policy:

- Fixed-8 taxonomy;
- resolver mapping;
- mutation operators;
- system prompt;
- evidence policy;
- output schemas;
- model-role contracts.

No human audit history or sample-specific judgment is stored as long-term memory.

## Audit traces

Engineering traces may be retained for debugging, but the published pair output contains only the direct nine-field contract. Audit traces are not a hidden scoring reference and are not required by downstream users.
