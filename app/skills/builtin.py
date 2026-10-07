"""First-party executable Skill catalog used by the production SkillBank.

Built-in skills are capability contracts, not sentence rules. They bind semantic
capabilities to already-registered, policy/verification-governed tools.
"""
from __future__ import annotations

_COMMON_VERIFY = (
    {"type": "all_steps_verified"},
    {"type": "expected_effects_observed"},
)


def _skill(*, key: str, name: str, capability: str, tool: str, triggers=(), outputs=(), confidence: float = 0.85, verification=None):
    return {
        "key": key,
        "name": name,
        "triggers": tuple(triggers),
        "preconditions": (),
        "workflow": ({"step_id": "s1", "tool": tool, "capability": capability, "args_policy": "derive-from-live-goal"},),
        "termination": "complete only after tool execution and skill verification",
        "outputs": tuple(outputs),
        "evidence": ({"kind": "first_party_contract", "capability": capability, "tool": tool},),
        "verification": tuple(verification) if verification is not None else _COMMON_VERIFY,
        "confidence": confidence,
        "source": "builtin",
        "source_run_id": None,
        "status": "active",
    }


def _compound_skill(*, key: str, name: str, capability: str, workflow: tuple[dict, ...], outputs: tuple[str, ...], triggers=(), confidence: float=0.9):
    return {
        "key": key, "name": name, "triggers": tuple(triggers), "preconditions": (),
        "workflow": workflow,
        "termination": "complete only after all workflow steps execute and the final artifact is verified",
        "outputs": tuple(outputs),
        "evidence": tuple({"kind": "first_party_contract", "capability": capability, "tool": item.get("tool")} for item in workflow),
        "verification": (
            {"type": "all_steps_verified"},
            {"type": "expected_effects_observed"},
        ),
        "confidence": confidence, "source": "builtin", "source_run_id": None, "status": "active",
    }


BUILTIN_SKILLS = (
    _compound_skill(
        key="builtin:project-audit", name="Full software project audit", capability="project_audit",
        workflow=(
            {"step_id": "s1", "tool": "inspect_project", "capability": "development_inspection", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "git_status", "capability": "development_git", "depends_on": ("s1",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s3", "tool": "audit_project_tests", "capability": "project_test_audit", "depends_on": ("s2",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s4", "tool": "create_project_audit_report", "capability": "project_audit", "depends_on": ("s3",), "args": {"test_audit": "{{s3}}"}, "args_policy": "derive-from-live-goal"},
        ),
        outputs=("project_inspected", "git_status_observed", "project_tests_observed", "project_audit_report_created"),
        triggers=("project audit", "audit the project", "افحص المشروع بالكامل", "راجع المشروع بالكامل", "تدقيق المشروع"),
        confidence=0.98,
    ),
    _skill(key="builtin:calculate", name="Deterministic calculation", capability="calculate", tool="calculator",
           triggers=("calculate", "math", "احسب", "حساب"), outputs=("calculation_completed",)),
    _skill(key="builtin:time", name="Current time and date", capability="query_time", tool="get_time",
           triggers=("time", "date", "الوقت", "التاريخ"), outputs=("current_time_available",)),
    _skill(key="builtin:remember", name="Remember user fact", capability="remember", tool="remember_fact",
           triggers=("remember", "save fact", "افتكر", "احفظ معلومة"), outputs=("fact_saved",)),
    _skill(key="builtin:forget", name="Forget user fact", capability="forget_memory", tool="forget_fact",
           triggers=("forget", "delete memory", "انسى", "انس"), outputs=("fact_deleted",)),
    _skill(key="builtin:identity-recall", name="Recall user identity", capability="query_identity", tool="recall_fact",
           triggers=("my name", "who am i", "اسمي", "مين انا"), outputs=("fact_recalled",)),
    _skill(key="builtin:memory-search", name="Search user memory", capability="query_memory", tool="search_memory",
           triggers=("search memory", "my memory", "ابحث في الذاكرة", "ذاكرتي"), outputs=("memory_recalled",)),
    _compound_skill(
        key="builtin:workspace-file-organization", name="Organize workspace files into type folders and verify the move", capability="workspace_file_organization",
        workflow=(
            {"step_id": "s1", "tool": "list_files", "capability": "workspace_files", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "organize_workspace_files", "capability": "workspace_file_organization", "depends_on": ("s1",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s3", "tool": "read_file", "capability": "workspace_files", "depends_on": ("s2",), "args_policy": "derive-from-live-goal", "args": {"path": "file_organization_report.md"}},
        ),
        outputs=("workspace_snapshot_observed", "workspace_files_organized", "workspace_organization_verified"),
        triggers=("organize workspace files", "sort workspace files", "arrange files by type", "move files into folders", "رتب ملفات مساحة العمل", "نظم الملفات", "رتب الملفات حسب النوع"),
        confidence=0.99,
    ),
    _compound_skill(
        key="builtin:workspace-duplicate-cleanup", name="Detect duplicate file content and safely archive extra copies", capability="workspace_duplicate_cleanup",
        workflow=(
            {"step_id": "s1", "tool": "list_files_recursive", "capability": "workspace_recursive_files", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "deduplicate_workspace_files", "capability": "workspace_duplicate_cleanup", "depends_on": ("s1",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s3", "tool": "read_file", "capability": "workspace_files", "depends_on": ("s2",), "args": {"path": "duplicate_cleanup_report.md"}, "args_policy": "derive-from-live-goal"},
        ),
        outputs=("workspace_duplicates_detected", "workspace_duplicates_archived", "workspace_duplicate_cleanup_verified"),
        triggers=("find duplicate files", "duplicate content", "deduplicate workspace", "duplicate cleanup", "sha256 duplicates", "ابحث عن الملفات المتطابقة", "نفس المحتوى", "النسخ المتطابقة", "أرشيف التكرارات"),
        confidence=0.99,
    ),
    _compound_skill(
        key="builtin:workspace-recursive-inventory", name="Inventory the workspace tree and verify folder statistics and largest files", capability="workspace_recursive_inventory",
        workflow=(
            {"step_id": "s1", "tool": "list_files_recursive", "capability": "workspace_recursive_inventory", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "create_workspace_tree_inventory", "capability": "workspace_recursive_inventory", "depends_on": ("s1",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s3", "tool": "read_file", "capability": "workspace_files", "depends_on": ("s2",), "args": {"path": "workspace_inventory.md"}, "args_policy": "derive-from-live-goal"},
        ),
        outputs=("workspace_recursive_snapshot_observed", "workspace_tree_inventory_created", "workspace_tree_inventory_verified"),
        triggers=("recursive workspace inventory", "workspace tree inventory", "largest files", "inventory subfolders", "جرد مساحة العمل بالكامل", "المجلدات الفرعية", "أكبر 5 ملفات"),
        confidence=0.99,
    ),
    _compound_skill(
        key="builtin:workspace-inventory", name="Inventory workspace files into a verified report", capability="workspace_inventory",
        workflow=(
            {"step_id": "s1", "tool": "list_files", "capability": "workspace_files", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "create_file_inventory", "capability": "workspace_inventory", "depends_on": ("s1",), "args_policy": "derive-from-live-goal"},
            {"step_id": "s3", "tool": "read_file", "capability": "workspace_files", "depends_on": ("s2",), "args": {"path": "file_inventory.md"}, "args_policy": "derive-from-live-goal"},
        ),
        outputs=("workspace_snapshot_observed", "workspace_inventory_created", "workspace_inventory_verified"),
        triggers=("workspace inventory", "inventory files", "list all files in the workspace", "file inventory", "جرد الملفات", "حصر الملفات", "احصر الملفات"),
        confidence=0.98,
    ),
    _skill(key="builtin:file-read", name="Read workspace file", capability="file_read", tool="read_file",
           triggers=("read file", "open file", "اقرأ الملف", "افتح الملف"), outputs=()),
    _skill(key="builtin:data-analysis", name="Analyze dataset", capability="data_analysis", tool="analyze_dataset",
           triggers=("analyze dataset", "data analysis", "حلل البيانات", "حلل الملف"), outputs=("analysis_evidence",)),
    _skill(key="builtin:data-analysis-report", name="Analyze dataset and create verified report", capability="data_analysis_report", tool="create_data_analysis_report",
           triggers=("analysis report", "create report", "save report", "comprehensive data analysis report", "تقرير تحليل", "أنشئ تقرير", "احفظ تقرير"), outputs=("analysis_report_created",), confidence=0.95,
           verification=_COMMON_VERIFY + ({"type": "goal_verified"},)),
    _skill(key="builtin:project-inspection", name="Inspect software project", capability="development_inspection", tool="inspect_project",
           triggers=("inspect project", "analyze project", "افحص المشروع", "حلل المشروع"), outputs=("project_inspected",)),
    _skill(key="builtin:project-validation", name="Validate software project", capability="development_validation", tool="check_project",
           triggers=("test project", "build project", "check project", "اختبر المشروع", "ابني المشروع"), outputs=("project_checked",), confidence=0.8),
    _skill(key="builtin:web-research", name="Bounded web research", capability="research", tool="web_research",
           triggers=("research", "search web", "ابحث", "اعمل بحث"), outputs=("web_evidence", "knowledge_indexed"), confidence=0.8),
    _compound_skill(
        key="builtin:research-report", name="Research and compare external evidence into a verified report", capability="research_report",
        workflow=(
            {"step_id": "s1", "tool": "internet_research", "capability": "internet_deep_research", "args_policy": "derive-from-live-goal"},
            {"step_id": "s2", "tool": "create_research_report", "capability": "research_report", "depends_on": ("s1",), "args_policy": "derive-from-live-goal", "args": {"research_result": "{{s1}}"}},
        ),
        outputs=("research_evidence", "research_report_created", "research_report_verified"),
        triggers=("research report", "compare recent papers", "أحدث الأبحاث وقارن", "تقرير أبحاث"),
        confidence=0.98,
    ),
)
