from datetime import datetime
from app.runtime.registry import tool
from app.intelligence.keywords import TIME_KW, SAVE_KW, has


@tool(name="get_time", description="يرجع الوقت والتاريخ الحالي", stage=0,
      match=lambda g: has(g, TIME_KW) and not has(g, SAVE_KW),
      pipe_source=True, pipe_label=lambda a: "الوقت: ",
      capability="time", produces=("current_time_available",), cost=1.0, risk="low", idempotent=True, parallel_safe=True)
def get_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
