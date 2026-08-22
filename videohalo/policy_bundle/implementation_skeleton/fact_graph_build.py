from langgraph.graph import END, START, StateGraph
from taxonomy_resolver import resolve_leaf, LEAF_TO_SLOT

def validate_fact_graph(state: dict) -> dict:
    facts = state["fact_graph"]["facts"]
    for fact in facts:
        leaf = resolve_leaf(fact["fact_kind"])
        if fact["leaf_label"] != leaf or fact["conflict_slot"] != LEAF_TO_SLOT[leaf]:
            raise ValueError("Fact graph contains a non-Fixed-8 or inconsistent fact")
        if fact["reflection_validation"] != {
            "accepted": True,
            "reflection_agent_count": 1,
        }:
            raise ValueError("Every source fact requires reflection-agent validation")
    return {**state, "fact_graph_validated": True}

def build_fact_graph_validation_graph():
    graph = StateGraph(dict)
    graph.add_node("validate_fixed8_fact_graph", validate_fact_graph)
    graph.add_edge(START, "validate_fixed8_fact_graph")
    graph.add_edge("validate_fixed8_fact_graph", END)
    return graph
