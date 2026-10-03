def choose_strategy(task_type: str, intents: list[dict], ambiguous: bool, baseline_steps: list[dict]) -> str:
    if ambiguous:
        return "clarify"
    names = {str(i.get("name")) for i in intents[:5]}
    if names & {"web_research", "scientific_research", "open_world_learning", "github_discovery", "github_learning"}:
        return "research_first"
    if task_type in {"memory", "computation"} and baseline_steps:
        return "deterministic"
    if baseline_steps:
        return "hybrid"
    return "reactive"

def risk_level(intents: list[dict], baseline_steps: list[dict]) -> str:
    if any(x.get("risk") == "high" for x in baseline_steps):
        return "high"
    if any(x.get("requires_approval") for x in baseline_steps):
        return "medium"
    if any(i.get("name") in {"development_validation", "development_inspection", "development_learning"} for i in intents):
        return "medium"
    return "low"
