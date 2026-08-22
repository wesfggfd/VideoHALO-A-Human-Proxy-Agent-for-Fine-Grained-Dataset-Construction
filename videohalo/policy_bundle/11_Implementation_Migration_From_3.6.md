# Implementation Migration from 3.6

## Delete

```text
graphs/review_packaging.py
graphs/human_audit_unlock.py
services/review_metrics.py
services/machine_human_alignment.py
schemas/expert_*_review*.json
schemas/human_audit_report.schema.json
schemas/review_difference_record.schema.json
schemas/batch_unlock_record.schema.json
examples/sample_*review*.json
examples/sample_human_audit_report.json
examples/sample_batch_unlock_record.json
```

## Replace in the batch orchestrator

Remove:

```text
freeze_machine_candidate_batch
package_blind_review_automatic
human audit refs
batch unlock refs
private machine-reference manifest
```

Add:

```text
project_fixed8_pair_record
append_pair_jsonl_atomic
validate_pair_id_uniqueness
```

## Update taxonomy code

The resolver dictionary must contain exactly eight entries. Removed fact kinds must raise `Fixed8OutOfScopeError` rather than being remapped.

## Update public field filtering

`leaf_label` and `conflict_slot` are now intentional public fields. The old leakage policy that treated target leaf as private does not apply to the direct pair dataset contract.

## Preserve

- native stream registration;
- immutable private-GCS object reuse through Enterprise ADC;
- high-thinking `<reflection_agent>`;
- one-slot mutation;
- backparse and GraphDiff;
- high-thinking `<monitor_agent>`;
- system cognitive memory and category memory;
