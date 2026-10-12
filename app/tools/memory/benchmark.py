from app.runtime.registry import tool
from app.evaluation.memory_benchmark import run_memory_benchmark


@tool(description="يشغل benchmark محلي لذاكرة الوكيل: recall/update/episodes/procedures/expiry/forgetting/provenance/export",
      stage=0, triggers=("memory benchmark", "benchmark memory", "اختبر الذاكرة", "benchmark الذاكرة"),
      capability="memory_benchmark", produces=("memory_benchmark_complete",), cost=0.2, risk="low", parallel_safe=True)
def memory_benchmark():
    return run_memory_benchmark()
