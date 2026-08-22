# Dataset Planning and Faithful Relative Allocation

VideoHALO builds only from verified facts found in source videos after the
`<planner_agent>` has scanned all eight leaves. It does not force equal counts
across leaves or Task x Leaf cells.

## Constraints

- one source fact is used once;
- one video contributes at most one pair to the same leaf;
- profile-defined per-video pair caps apply;
- near-duplicate videos are separated where possible;
- task, source, and question-template diversity are preserved;
- insufficient or out-of-scope facts never fill a quota.

## Selection priority

The planner selects only real, independently verified supply and applies a
deterministic tie-break under the per-video cap. Leaf counts are an observed
output, not an optimization requirement. A real verified claim from a clearly
underrepresented leaf may be selected first, but no target may alter taxonomy
boundaries, opportunity decisions, FactBank contents, mutation semantics, or
independent agent judgments. `probe_build` uses a smaller total-pair target;
`evalbench_build` uses a larger one.
