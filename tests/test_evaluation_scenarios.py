from pathlib import Path
import json
from app.evaluation.scenarios import load_scenarios

def test_default_scenario_pack_loads():
    scenarios=load_scenarios(Path('docs/evaluation/default_scenarios.json'))
    ids={s.id for s in scenarios}
    assert {'core.calculate','compound.calculate_save','security.prompt_injection','workspace.frame_condition'} <= ids
    safety=next(s for s in scenarios if s.id=='security.prompt_injection')
    assert safety.workspace_files['poison.txt']
