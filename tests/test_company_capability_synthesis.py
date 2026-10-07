from types import SimpleNamespace

from app.brain.models import PlannedAction, SemanticFrame
from app.domain.task_ir import TaskIR, TaskNode
from app.organization import DEFAULT_COMPANY, ExecutiveCapabilitySynthesizer, OrganizationRoutingError
from app.runtime.registry import Tool, load_tools


def test_ceo_extracts_structured_capabilities_without_workflow_names():
    task_ir = TaskIR(
        original="do two capabilities",
        objective="do two capabilities",
        nodes=[
            TaskNode(id="t1", objective="perform data analysis", capability="data_analysis", confidence=0.91),
            TaskNode(id="t2", objective="read the output", capability="file_read", arguments={"path": "report.md"}, depends_on=("t1",), confidence=0.88),
        ],
    )
    plan = DEFAULT_COMPANY.registry.synthesize_capabilities(
        task_ir=task_ir, registry=load_tools()
    )
    assert plan.valid is True
    assert [x.capability for x in plan.requirements] == ["data_analysis", "file_read"]
    assert [x.department for x in plan.selected] == ["data", "operations"]
    assert [x.requirement_key for x in plan.selected] == ["t1", "t2"]


def test_capability_synthesis_accepts_future_tool_by_declared_contract():
    registry = dict(load_tools())
    registry["future_finance_tool"] = SimpleNamespace(
        name="future_finance_tool",
        capability="future_finance_capability",
        organization_department="finance",
        organization_role="finance:analyst",
        produces=("future_finance_artifact",),
        cost=2.0,
        risk="low",
        verification_level="strong",
        args_for=lambda goal: {},
    )
    from app.organization.models import AgentRole, Department
    # Temporary extended registry proves routing uses organization declarations instead of
    # a tool-name switch. Finance is intentionally not in the default five-department roster.
    roles = DEFAULT_COMPANY.roles + (AgentRole(
        "finance:analyst", "Finance Analyst", "finance", "executive:chief-executive", "builder",
        "Analyze financial data", capabilities=("future_finance_capability",),
        write_surfaces=("workspace/finance/**",), runtime_domains=("finance",),
    ),)
    departments = DEFAULT_COMPANY.departments + (Department(
        "finance", "Finance", "finance:analyst", "Financial analysis.",
        specialists=("finance:analyst",), reviewer="qa:reviewer",
        owned_capabilities=("future_finance_capability",), owned_effects=("future_finance_artifact",),
    ),)
    from app.organization.registry import OrganizationRegistry
    org = OrganizationRegistry(roles, departments)
    requirement = ExecutiveCapabilitySynthesizer().requirements_from(
        semantic=SemanticFrame(
            text="future finance task", language="en", speech_act="command", concepts=(),
            requested_operation="future_finance_capability", uncertainty=(),
        )
    )[0]
    candidates = ExecutiveCapabilitySynthesizer().candidates_for(requirement, registry=registry, organization=org)
    assert candidates and candidates[0].department == "finance"
    assert candidates[0].specialist == "finance:analyst"


def test_unknown_capability_fails_closed_as_unresolved():
    semantic = SemanticFrame(
        text="perform an unknown capability", language="en", speech_act="command", concepts=(),
        requested_operation="unknown_capability", uncertainty=(),
    )
    plan = DEFAULT_COMPANY.registry.synthesize_capabilities(
        semantic=semantic, registry=load_tools()
    )
    assert plan.valid is False
    assert plan.unresolved == ("goal:1:unknown_capability",)


def test_synthesized_plan_rewrites_task_ir_dependencies_to_runtime_steps():
    task_ir = TaskIR(
        original="analyze then read",
        objective="analyze then read",
        nodes=[
            TaskNode(id="t1", objective="analyze dataset", capability="data_analysis"),
            TaskNode(id="t2", objective="read file", capability="file_read", arguments={"path": "report.md"}, depends_on=("t1",)),
        ],
    )
    actions, capability_plan = DEFAULT_COMPANY.registry.synthesize_executable_plan(
        semantic=SemanticFrame(
            text="analyze then read", language="en", speech_act="command", concepts=(),
            requested_operation="data_analysis", uncertainty=(),
        ),
        task_ir=task_ir,
        tool_registry=load_tools(),
    )
    assert capability_plan.valid is True
    assert [x.step_id for x in actions] == ["s1", "s2"]
    assert actions[1].depends_on == ("s1",)
    assert [x.tool for x in actions] == ["profile_dataset", "read_file"] or [x.tool for x in actions] == ["analyze_dataset", "read_file"]


def test_semantic_frame_compiles_to_structured_task_ir_without_second_nlp_pass():
    from app.intelligence.task_compiler import compile_task_ir
    frame = SemanticFrame(
        text="analyze dataset", language="en", speech_act="command", concepts=(),
        requested_operation="data_analysis", slots=(("path", "sales.csv"),), uncertainty=(),
    )
    task_ir = compile_task_ir(frame)
    assert task_ir.nodes[0].capability == "data_analysis"
    assert task_ir.nodes[0].arguments["path"] == "sales.csv"


def test_company_coordination_exposes_capability_requirements():
    plan = [
        PlannedAction("s1", "data_analysis", "analyze_dataset"),
        PlannedAction("s2", "file_read", "read_file", depends_on=("s1",)),
    ]
    coordination = DEFAULT_COMPANY.coordinate("generic", plan, tool_registry=load_tools())
    assert coordination.required_capabilities
    assert {x["capability"] for x in coordination.required_capabilities} == {"data_analysis", "file_read"}
    assert not coordination.unresolved_capabilities


def test_canonical_brain_records_company_capability_synthesis_without_error():
    from app.brain import CognitiveKernel
    result = CognitiveKernel().think_structured({
        "goal": "analyze dataset", "operation": "data_analysis", "capability": "data_analysis",
        "target": "", "target_type": "", "slots": {"path": "workspace/sales.csv"},
        "constraints": [], "temporal_requirements": [], "required_evidence": [],
        "priority": 0.5, "language": "en",
    })
    assert not [e for e in result.state.trace if e.get("kind") == "company_capability_synthesis_error"]
    assert result.state.company_capability_plan.get("valid") is True
    assert result.state.company_capability_plan["selected"][0]["tool"] == "analyze_dataset"
