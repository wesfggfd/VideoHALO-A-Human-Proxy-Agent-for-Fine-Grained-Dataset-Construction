# Dual-Layer Memory System

VideoHALO uses two append-only memory layers shared by all six agents. Memory
supports structured coordination; it never replaces direct video evidence and
never changes the frozen Fixed-8 semantics.

## System Cognitive Memory Layer

`system_cognitive_memory` records bounded, versioned operational traces across
the four subtasks: producer agent, stage, video identity, structured result,
validation outcome, and retry/audit context. The next agent receives only a
bounded task-relevant snapshot. This layer enables cross-stage continuity while
preserving independent rereading by `<reflection_agent>` and `<monitor_agent>`.

## Category Memory Layer

`category_memory` indexes the same contributions by Fixed-8 hallucination
category. It stores category-conditioned constructibility evidence, normalized
fact patterns, mutation constraints, back-parsing checks, and reliability
outcomes. A call receives only the categories relevant to its current input.

## Contribution contract

`<planner_agent>`, `<extraction_agent>`, `<reflection_agent>`,
`<generation_agent>`, `<verification_agent>`, and `<monitor_agent>` all read a
bounded snapshot and append their structured output to both layers. Entries are
never edited in place. Stage envelopes contain a snapshot reference so the
reasoning chain remains reproducible.

## Isolation and publication

Media URIs, credentials, and unrestricted prompts are excluded from memory.
Sample-specific traces remain internal artifacts and are not a hidden scoring
reference. Published pairs continue to contain only the exact nine-field public
schema.
