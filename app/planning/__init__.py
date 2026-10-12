"""Planning package with lazy model-based planner exports to avoid import cycles."""

__all__ = ["ModelBasedPlanner", "ModelPlanCandidate", "ModelPlanEvaluation"]


def __getattr__(name):
    if name in __all__:
        from .model_based_planner import ModelBasedPlanner, ModelPlanCandidate, ModelPlanEvaluation
        return {
            "ModelBasedPlanner": ModelBasedPlanner,
            "ModelPlanCandidate": ModelPlanCandidate,
            "ModelPlanEvaluation": ModelPlanEvaluation,
        }[name]
    raise AttributeError(name)
