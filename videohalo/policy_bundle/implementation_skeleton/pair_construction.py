from taxonomy_resolver import validate_leaf_slot

OUTPUT_SCHEMA = "videohalo_probe_pair_sample_fixed8_3.6.1"

def validate_internal_pair(candidate: dict) -> None:
    diff = candidate["graph_diff"]
    if diff["changed_atomic_fact_count"] != 1 or diff["changed_slot_count"] != 1:
        raise ValueError("One-fact/one-slot invariant failed")
    if candidate["supported_contradicted_count"] != 0 or candidate["counterfactual_contradicted_count"] != 1:
        raise ValueError("Single-error invariant failed")
    if candidate["candidate_verifier_consensus"] is not True:
        raise ValueError("Two candidate verifiers must agree")
    validate_leaf_slot(candidate["leaf_label"], candidate["conflict_slot"])

def project_direct_record(candidate: dict) -> dict:
    validate_internal_pair(candidate)
    return {
        "schema_version": OUTPUT_SCHEMA,
        "pair_id": candidate["pair_id"],
        "media": candidate["media"],
        "task_type": candidate["task_type"],
        "question": candidate["question"],
        "answer": candidate["answer"],
        "counterfactual_answer": candidate["counterfactual_answer"],
        "leaf_label": candidate["leaf_label"],
        "conflict_slot": candidate["conflict_slot"],
    }
