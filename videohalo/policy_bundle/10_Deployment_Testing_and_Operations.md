# Deployment, Testing, and Operations

## Required tests

1. Schema tests for pair outputs.
2. Resolver tests for all eight leaf/slot mappings.
3. Negative tests proving removed fact kinds cannot enter build output.
4. Mutation property tests: one fact, one slot, one contradiction.
5. High-thinking fact and candidate reflection tests.
6. JSONL append idempotency and duplicate-pair rejection.
7. Private-GCS object identity, idempotent reuse, and generation tests.
8. ADC/IAM/project failure circuit-breaker and secret-redaction tests.
9. Smooth cross-worker request pacing tests.

## CLI

```text
videohalo register --input videos.jsonl
videohalo build --profile probe_build --output public_probe_items.jsonl
videohalo build --profile evalbench_build --output public_evalbench_pairs.jsonl
videohalo validate --input public_probe_items.jsonl
```

## Observability

Record API latency, retries, token usage, candidate rejection reasons, per-leaf yield, and direct-output append status. Do not record hidden reasoning text as dataset content.

## Production compliance guardrails

- Use only a Google-approved, billing-enabled project; never switch projects to
  circumvent a suspension or enforcement action.
- Use ADC/IAM and private GCS. Reject API-key variables in production.
- Run one text preflight and one video smoke before enabling multiple workers.
- Smooth requests across workers. Do not send second-level traffic spikes.
- Retry only transient 429/5xx capacity failures with bounded exponential
  backoff.
- Any 401 or project/auth/billing/IAM 403 opens a process-wide circuit and
  stops uploads, inference, retries, and automatic resume.
- Redact API keys and bearer tokens before writing events, errors, or status.
- Preserve Google safety filters. Safety-blocked or policy-ineligible media is
  skipped rather than retried or routed around the filter.
