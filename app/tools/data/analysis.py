from pathlib import Path
import os
import json
import re
from typing import Any
from statistics import mean

from app.runtime.registry import tool
from app.runtime.security import safe_workspace_path
from app.knowledge.data_analysis import DeterministicDataAgent, DataAnalysisError, DatasetProfile, profile_dataset, rank_findings, load_rows, _clean, _parse_number
from app.tools.system.files import workspace_root, safe_path

_agent = DeterministicDataAgent()
_SUPPORTED_DATA = {".csv", ".json", ".sqlite", ".sqlite3", ".db"}
ACTIVE_DATASET_REF = "@active_dataset"


def _workspace_root() -> Path:
    raw = os.getenv("AGENT_WORKSPACE")
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def _resolve_active_dataset() -> str:
    root = _workspace_root()
    if not root.exists() or not root.is_dir():
        raise DataAnalysisError(f"مساحة العمل غير موجودة: {root}")
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.casefold() in _SUPPORTED_DATA
    )
    if not files:
        raise DataAnalysisError("لم أجد ملف بيانات مدعومًا في مساحة العمل")
    if len(files) > 1:
        names = ", ".join(str(p.relative_to(root)) for p in files[:8])
        extra = " ..." if len(files) > 8 else ""
        raise DataAnalysisError(f"وجدت أكثر من dataset في مساحة العمل؛ حدّد الملف صراحة: {names}{extra}")
    return str(files[0].relative_to(root))


def _resolve_data_reference(path: str) -> str:
    return _resolve_active_dataset() if path == ACTIVE_DATASET_REF else path


def _extract_path(goal: str) -> str:
    from app.tools.workspace_reference import extract_workspace_reference, require_resolved_path
    result = extract_workspace_reference(goal, expected_kind="file", role="source")
    if result.resolved:
        return result.value
    if result.status == "missing":
        # A generic semantic reference such as "the dataset" is represented by the
        # canonical active-dataset symbol. Resolution/ambiguity is enforced by the
        # data tool at execution time; arbitrary sentences are never used as paths.
        text = str(goal or "").casefold()
        generic_reference = re.search(
            r"(?:\bdataset\b|\bdata(?:set)?\b|\bthe\s+data\b|ملف\s+البيانات|البيانات)",
            text,
            re.I,
        )
        if generic_reference:
            return ACTIVE_DATASET_REF
    return require_resolved_path(result)


@tool(
    "تحليل ملف محلي وإرجاع evidence إحصائي قابل لإعادة الإنتاج",
    {"path": "str"},
    name="profile_dataset",
    triggers=("profile dataset", "dataset profile", "data profile", "profile the dataset", "schema", "بروفايل البيانات", "بروفايل للبيانات", "هيكل البيانات", "اعمل بروفايل"),
    match=lambda g: any(x in g.casefold() for x in ("profile dataset", "dataset profile", "data profile", "profile the dataset", "profile the data", "profile data", "schema", "بروفايل البيانات", "بروفايل للبيانات", "هيكل البيانات", "اعمل بروفايل")),
    build_args=lambda g: {"path": _extract_path(g)},
    capability="data_analysis",
    organization_department="data",
    organization_role="data:data-analyst",
    produces=("dataset_profiled",),
    cost=2.0,
    duration=0.5,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
)
def profile_dataset_tool(path: str):
    return _agent.profile(str(safe_workspace_path(_resolve_data_reference(path))))


def _report_path_from_goal(goal: str) -> str:
    import re
    match = re.search(r"(?:save|write|create|generate|احفظ|اكتب|أنشئ|انشئ|جهز|جهّز)\s+(?:the\s+)?(?:report|file|document|التقرير|الملف|المستند)?[^\n]*?((?:[A-Za-z]:[\\/] |/)?[^\s,;!?؟]+\.(?:md|txt))", goal, re.I | re.X)
    if match:
        return match.group(1).strip(" \t,.;!?؟")
    match = re.search(r"([^\s,;!?؟]+\.(?:md|txt))", goal, re.I)
    if match:
        return match.group(1).strip(" \t,.;!?؟")
    return "analysis_report.md"



def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


def _select_requested_numeric_column(profile: DatasetProfile, question: str) -> str | None:
    numeric = [c for c in profile.column_profiles if c.inferred_type == "numeric"]
    if not numeric:
        return None
    q = question.casefold()
    if len(numeric) == 1:
        return numeric[0].name
    groups = (
        (12, ("sales", "sale", "mبيعات", "المبيعات", "revenue", "إيراد", "ايراد", "الإيراد")),
        (10, ("amount", "المبلغ", "قيمة", "القيمة", "value")),
    )
    ranked: list[tuple[int, str]] = []
    for col in numeric:
        name = col.name.casefold()
        score = 0
        for weight, terms in groups:
            if any(term in name for term in terms):
                score += weight
        if name in q:
            score += 20
        ranked.append((score, col.name))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][1] if ranked and ranked[0][0] > 0 else None



def _select_group_column(profile: DatasetProfile, question: str) -> str | None:
    """Select a categorical grouping column from the request without dataset-specific rules."""
    categorical = [c for c in profile.column_profiles if c.inferred_type in {"categorical", "boolean"}]
    if not categorical:
        return None
    q = question.casefold()
    scored: list[tuple[int, str]] = []
    semantic_hints = (
        (("region", "regions", "منطقة", "المناطق", "مناطق"), ("region", "area", "zone", "territory", "منطقة", "مناطق")),
        (("branch", "branches", "فرع", "الفروع", "فروع"), ("branch", "فرع", "الفروع")),
        (("channel", "channels", "قناة", "القنوات", "قنوات"), ("channel", "قناة", "القنوات")),
        (("segment", "segments", "شريحة", "الشرائح", "شرائح"), ("segment", "شريحة", "الشرائح")),
        (("category", "categories", "فئة", "الفئات", "فئات"), ("category", "type", "class", "فئة", "الفئات")),
    )
    for col in categorical:
        name = col.name.casefold()
        score = 0
        if name in q:
            score += 40
        for query_terms, name_terms in semantic_hints:
            if any(term in q for term in query_terms) and any(term in name for term in name_terms):
                score += 25
        if any(term in name for term in ("region", "area", "branch", "category", "group", "channel", "segment", "منطقة", "فرع", "فئة")):
            score += 6
        scored.append((score, col.name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    # A group column mentioned by name is unambiguous. Otherwise use the first
    # categorical field only when the language explicitly asks for grouping.
    return scored[0][1] if scored and scored[0][0] > 0 else categorical[0].name


def _requested_group_comparison(path: str | Path, profile: DatasetProfile, question: str) -> dict[str, Any]:
    """Compute requested group totals and deterministic leader/laggard decisions."""
    q = question.casefold()
    grouping_requested = any(k in q for k in ("حسب", "by ", "group by", "لكل منطقة", "بين المناطق", "بين الفروع", "مقارنة"))
    ranking_requested = any(k in q for k in ("أعلى إجمالي", "اعلى اجمالي", "أعلى", "اعلى", "الأعلى", "الاعلى", "أقل إجمالي", "اقل اجمالي", "أقل", "اقل", "الأقل", "الاقل", "highest", "lowest"))
    decision_requested = any(k in q for k in ("قرار", "decision", "recommend", "recommendation", "اقتراح", "مقترح", "عملي"))
    if not (grouping_requested and ranking_requested):
        return {}

    value_col = _select_requested_numeric_column(profile, question)
    group_col = _select_group_column(profile, question)
    if not value_col:
        return {"verified": False, "error": "no numeric value column could be identified for grouped comparison"}
    if not group_col:
        return {"verified": False, "error": "no categorical grouping column could be identified"}

    _, _, rows = load_rows(path)
    grouped: dict[str, list[tuple[int, float, dict[str, Any]]]] = {}
    for row_number, row in enumerate(rows, start=1):
        group = _clean(row.get(group_col))
        value = _parse_number(_clean(row.get(value_col)))
        if group is None or value is None:
            continue
        grouped.setdefault(str(group), []).append((row_number, value, dict(row)))

    if not grouped:
        return {"verified": False, "error": "no valid grouped numeric observations found"}

    groups = []
    for group, observations in sorted(grouped.items()):
        values = [item[1] for item in observations]
        groups.append({
            "group": group,
            "count": len(values),
            "total": sum(values),
            "average": mean(values),
            "minimum": min(values),
            "maximum": max(values),
        })

    highest = max(groups, key=lambda item: (item["total"], item["group"]))
    lowest = min(groups, key=lambda item: (item["total"], item["group"]))
    spread = highest["total"] - lowest["total"]
    decision = (
        f"Prioritize the highest-total group ({highest['group']}) for continued sales focus, "
        f"and review the lowest-total group ({lowest['group']}) before increasing resources there. "
        f"This decision is based only on the observed {value_col} totals; the gap is {spread:g}."
    ) if decision_requested else None

    result: dict[str, Any] = {
        "group_by": group_col,
        "value_column": value_col,
        "groups": groups,
        "highest_total_group": highest,
        "lowest_total_group": lowest,
        "total_spread": spread,
        "n_rows_used": sum(item["count"] for item in groups),
        "source_fingerprint": profile.fingerprint,
        "verified_against_source": True,
    }
    if decision is not None:
        result["decision"] = decision
    return result


def _group_comparison_lines(comparison: dict[str, Any]) -> list[str]:
    if not comparison or comparison.get("error"):
        return []
    lines = ["", "## Group Comparison", "", f"- Group by: `{comparison['group_by']}`", f"- Value column: `{comparison['value_column']}`", "", "| Group | Count | Total | Average | Minimum | Maximum |", "|---|---:|---:|---:|---:|---:|"]
    for item in comparison["groups"]:
        lines.append(
            f"| {item['group']} | {item['count']} | {_format_metric(item['total'])} | "
            f"{_format_metric(item['average'])} | {_format_metric(item['minimum'])} | {_format_metric(item['maximum'])} |"
        )
    hi = comparison["highest_total_group"]
    lo = comparison["lowest_total_group"]
    lines.extend([
        "",
        f"- Highest total: **{hi['group']}** = **{_format_metric(hi['total'])}**",
        f"- Lowest total: **{lo['group']}** = **{_format_metric(lo['total'])}**",
        f"- Total spread: **{_format_metric(comparison['total_spread'])}**",
    ])
    if comparison.get("decision"):
        lines.extend(["", "### Decision", "", comparison["decision"]])
    lines.extend(["", "## Group Comparison Certificate", "", "```json", json.dumps(comparison, ensure_ascii=False, sort_keys=True), "```"])
    return lines


def _verify_group_comparison(report_text: str, comparison: dict[str, Any]) -> dict[str, Any]:
    if not comparison:
        return {"ok": True, "checks": {"no_group_comparison": True}}
    if comparison.get("error"):
        return {"ok": False, "checks": {"request_resolved": False}, "error": comparison["error"]}
    checks = {
        "certificate_present": "## Group Comparison Certificate" in report_text,
        "source_fingerprint_present": comparison["source_fingerprint"] in report_text,
        "group_comparison_present": "## Group Comparison" in report_text,
    }
    try:
        payload = report_text.split("## Group Comparison Certificate", 1)[1].split("```json", 1)[1].split("```", 1)[0].strip()
        certificate = json.loads(payload)
    except Exception as exc:
        return {"ok": False, "checks": checks, "error": f"invalid group comparison certificate: {exc}"}
    checks["certificate_equals_recomputed_source"] = certificate == comparison
    checks["certificate_source_verified"] = certificate.get("verified_against_source") is True
    if comparison.get("decision"):
        checks["decision_present"] = comparison["decision"] in report_text
        checks["decision_mentions_highest"] = comparison["highest_total_group"]["group"] in comparison["decision"]
        checks["decision_mentions_lowest"] = comparison["lowest_total_group"]["group"] in comparison["decision"]
    return {"ok": all(checks.values()), "checks": checks}


def _requested_metrics(path: str | Path, profile: DatasetProfile, question: str) -> dict[str, Any]:
    q = question.casefold()
    wants = {
        "total": any(k in q for k in ("total", "sum", "مجموع", "إجمالي", "اجمالي", "الإجمالي")),
        "average": any(k in q for k in ("average", "mean", "متوسط", "المتوسط")),
        "maximum": any(k in q for k in ("maximum", "max", "highest", "أعلى", "اعلى", "أكبر", "اكبر")),
        "minimum": any(k in q for k in ("minimum", "min", "lowest", "أقل", "اقل", "أدنى", "ادنى", "أصغر", "اصغر")),
        "max_row": any(k in q for k in ("row with maximum", "row containing the maximum", "highest row", "الصف الذي يحتوي على أعلى", "الصف صاحب أعلى", "صف أعلى")),
    }
    if not any(wants.values()):
        return {}
    column = _select_requested_numeric_column(profile, question)
    if not column:
        return {"verified": False, "error": "no requested numeric column could be identified"}
    _, _, rows = load_rows(path)
    observed: list[tuple[int, float, dict[str, Any]]] = []
    for row_number, row in enumerate(rows, start=1):
        value = _parse_number(_clean(row.get(column)))
        if value is not None:
            observed.append((row_number, value, row))
    if not observed:
        return {"verified": False, "error": f"column {column!r} contains no numeric values"}
    values = [item[1] for item in observed]
    result: dict[str, Any] = {
        "selected_column": column,
        "n": len(values),
        "source_fingerprint": profile.fingerprint,
        "verified_against_source": True,
    }
    if wants["total"]:
        result["total"] = sum(values)
    if wants["average"]:
        result["average"] = mean(values)
    if wants["maximum"]:
        result["maximum"] = max(values)
    if wants["minimum"]:
        result["minimum"] = min(values)
    if wants["max_row"]:
        max_item = max(observed, key=lambda item: item[1])
        result["max_row"] = {
            "data_row": max_item[0],
            "value": max_item[1],
            "record": dict(max_item[2]),
        }
    return result


def _requested_metrics_lines(metrics: dict[str, Any]) -> list[str]:
    if not metrics or metrics.get("error"):
        return []
    lines = ["", "## Requested Metrics", "", f"- Selected numeric column: `{metrics['selected_column']}`"]
    labels = (("total", "Total"), ("average", "Average"), ("maximum", "Maximum"), ("minimum", "Minimum"))
    for key, label in labels:
        if key in metrics:
            lines.append(f"- {label}: **{_format_metric(metrics[key])}**")
    if "max_row" in metrics:
        row = metrics["max_row"]
        lines.append(
            f"- Row with maximum: data row **{row['data_row']}**, value **{_format_metric(row['value'])}**, "
            f"record=`{json.dumps(row['record'], ensure_ascii=False, sort_keys=True)}`"
        )
    lines.extend(["", "## Requested Metrics Certificate", "", "```json", json.dumps(metrics, ensure_ascii=False, sort_keys=True), "```"])
    return lines


def _verify_requested_metrics(report_text: str, metrics: dict[str, Any]) -> dict[str, Any]:
    if not metrics:
        return {"ok": True, "checks": {"no_requested_metrics": True}}
    if metrics.get("error"):
        return {"ok": False, "checks": {"request_resolved": False}, "error": metrics["error"]}
    checks = {
        "certificate_present": "## Requested Metrics Certificate" in report_text,
        "source_fingerprint_present": metrics["source_fingerprint"] in report_text,
    }
    try:
        payload = report_text.split("## Requested Metrics Certificate", 1)[1].split("```json", 1)[1].split("```", 1)[0].strip()
        certificate = json.loads(payload)
    except Exception as exc:
        return {"ok": False, "checks": checks, "error": f"invalid requested metrics certificate: {exc}"}
    checks["certificate_equals_recomputed_source"] = certificate == metrics
    checks["certificate_source_verified"] = certificate.get("verified_against_source") is True
    return {"ok": all(checks.values()), "checks": checks}


def _render_analysis_report(profile: DatasetProfile, findings: list[dict], *, question: str, requested_metrics: dict[str, Any] | None = None, group_comparison: dict[str, Any] | None = None) -> str:
    lines = [
        "# Data Analysis Report",
        "",
        f"- Source: `{profile.source}`",
        f"- Fingerprint: `{profile.fingerprint}`",
        f"- Rows: **{profile.rows}**",
        f"- Columns: **{profile.columns}**",
        f"- Duplicate rows: **{profile.duplicate_rows}**",
        f"- Quality score: **{profile.quality_score}**",
        "",
        "## Requested Scope",
        "",
        question.strip(),
        "",
        "## Schema and Column Statistics",
        "",
        "| Column | Type | Missing | Unique | Min | Max | Mean | Median | Stddev | Outliers |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in profile.column_profiles:
        lines.append(
            f"| {c.name} | {c.inferred_type} | {c.missing} ({c.missing_rate:.1%}) | {c.unique} | "
            f"{c.min if c.min is not None else ''} | {c.max if c.max is not None else ''} | "
            f"{c.mean if c.mean is not None else ''} | {c.median if c.median is not None else ''} | "
            f"{c.stddev if c.stddev is not None else ''} | {c.outliers} |"
        )
    lines.extend(["", "## Correlations", ""])
    if profile.correlations:
        for c in profile.correlations:
            lines.append(f"- `{c['x']}` vs `{c['y']}`: Pearson={c.get('pearson')}, Spearman={c.get('spearman')}, n={c.get('n')}")
    else:
        lines.append("No pairwise numeric correlations met the minimum sample requirement.")
    lines.extend(["", "## Key Findings", ""])
    if findings:
        for item in findings:
            lines.append(f"- **{item['type']}** — `{item['column']}` — severity {item['severity']}: {item['evidence']}")
    else:
        lines.append("No quality, outlier, trend, or strong-correlation findings were detected by the deterministic analysis rules.")
    lines.extend(["", "## Warnings", ""])
    if profile.warnings:
        lines.extend(f"- {w}" for w in profile.warnings)
    else:
        lines.append("No warnings were produced by the deterministic quality checks.")
    lines.extend(_requested_metrics_lines(requested_metrics or {}))
    lines.extend(_group_comparison_lines(group_comparison or {}))
    lines.extend(["", "## Verification", "", "The report was written by the deterministic data-analysis engine and re-read from disk before completion.", ""])
    return "\n".join(lines)


@tool(
    "ينشئ تقرير تحليل بيانات حقيقي داخل الـworkspace مع إعادة قراءة والتحقق من الملف الناتج",
    params={"path": "مسار dataset", "output_path": "مسار التقرير النسبي", "question": "نطاق التحليل المطلوب"},
    name="create_data_analysis_report",
    triggers=("analysis report", "comprehensive data analysis report", "create report", "save report", "تقرير تحليل", "تحليل شامل", "أنشئ تقرير", "احفظ تقرير"),
    match=lambda g: bool(__import__('re').search(r"(?:report|تقرير|احفظ.*\.(?:md|txt)|أنشئ.*\.(?:md|txt)|انشئ.*\.(?:md|txt))", g, __import__('re').I)),
    build_args=lambda g: {"path": _extract_path(g), "output_path": _report_path_from_goal(g), "question": g},
    capability="data_analysis_report",
    produces=("analysis_report_created",),
    requires_approval=True,
    risk="medium",
    cost=4.0,
    duration=2.0,
    parallel_safe=False,
    idempotent=True,
    verification_level="strong",
    intent_priority=12,
)
def create_data_analysis_report(path: str, output_path: str, question: str):
    source = _resolve_data_reference(path)
    profile_obj = profile_dataset(str(safe_workspace_path(source)))
    findings = rank_findings(profile_obj)
    requested = _requested_metrics(source, profile_obj, question)
    group_comparison = _requested_group_comparison(source, profile_obj, question)
    content = _render_analysis_report(profile_obj, findings, question=question, requested_metrics=requested, group_comparison=group_comparison)
    target = safe_workspace_path(output_path)
    root = safe_workspace_path(".")
    root = safe_workspace_path(".")
    if target == root or target.is_dir():
        raise DataAnalysisError("مسار التقرير يجب أن يكون ملفًا داخل الـworkspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    reread = target.read_text(encoding="utf-8")
    required = ("# Data Analysis Report", "## Schema and Column Statistics", "## Key Findings", "## Verification")
    base_verified = all(section in reread for section in required) and target.exists() and target.is_file()
    metric_verification = _verify_requested_metrics(reread, requested)
    group_verification = _verify_group_comparison(reread, group_comparison)
    merged_checks = dict(metric_verification.get("checks") or {})
    group_checks = dict(group_verification.get("checks") or {})
    for key, value in group_checks.items():
        merged_checks.setdefault(f"group_{key}", value)
    merged_checks["group_comparison"] = group_verification
    goal_verification = {
        "ok": bool(metric_verification.get("ok")) and bool(group_verification.get("ok")),
        "checks": merged_checks,
        "requested_metrics": metric_verification,
        "group_comparison": group_verification,
    }
    verified = base_verified and bool(goal_verification.get("ok"))
    return {"path": str(target.relative_to(root)), "bytes": len(reread.encode("utf-8")), "source": profile_obj.source, "fingerprint": profile_obj.fingerprint, "findings": findings, "verified": verified, "goal_verification": goal_verification, "requested_metrics": requested, "group_comparison": group_comparison, "summary": {"rows": profile_obj.rows, "columns": profile_obj.columns, "duplicate_rows": profile_obj.duplicate_rows, "quality_score": profile_obj.quality_score}}


@tool(
    "سؤال تحليلي محدد على ملف محلي بدون تنفيذ كود خارجي",
    {"path": "str", "question": "str"},
    name="analyze_dataset",
    triggers=("analyze", "analysis", "حلل", "متوسط", "average", "mean", "correlation", "ارتباط", "outlier", "anomal", "شذوذ"),
    match=lambda g: (
        not any(x in g.casefold() for x in ("comprehensive analysis", "تشخيص البيانات", "تحليل شامل", "حلل البيانات بالكامل"))
        and any(x in g.casefold() for x in ("analyze ", "analysis ", "average ", "mean ", "what is the average", "find the average", "حلل ", "متوسط ", "correlation", "ارتباط", "outlier", "anomal", "شذوذ", "القيم الشاذة"))
        and (any(ext in g.casefold() for ext in (".csv", ".json", ".sqlite", ".db")) or any(x in g.casefold() for x in ("dataset", "data file", "ملف البيانات")))
    ),
    build_args=lambda g: {"path": _extract_path(g), "question": g},
    capability="data_analysis",
    produces=("analysis_evidence",),
    cost=2.5,
    duration=0.7,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    intent_priority=9,
)
def analyze_dataset_tool(path: str, question: str):
    return _agent.ask(str(safe_workspace_path(_resolve_data_reference(path))), question)


@tool(
    "يجمع نتائج كل ملفات CSV الموجودة في snapshot recursive ويقارن إجمالي القيم في الأعمدة الرقمية بشكل حتمي",
    {"file_list": "snapshot recursive من workspace", "question": "الهدف التحليلي الأصلي"},
    name="analyze_csv_collection",
    capability="cross_department_data_move",
    organization_department="data",
    organization_role="data:data-analyst",
    produces=("csv_collection_analyzed",),
    cost=3.0,
    duration=1.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    pipe_param="file_list",
)
def analyze_csv_collection(file_list: list[dict], question: str = ""):
    import hashlib
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن تكون snapshot قائمة")
    rows=[]
    for item in file_list:
        if not isinstance(item, dict) or str(item.get("type")) != "file":
            continue
        rel=str(item.get("name") or "")
        if Path(rel).suffix.casefold() != ".csv":
            continue
        path=safe_workspace_path(rel)
        resolved, fields, records=load_rows(path)
        numeric=[]
        totals={}
        for field in fields:
            vals=[]
            for record in records:
                v=_parse_number(_clean(record.get(field)))
                if v is not None:
                    vals.append(float(v))
            if vals:
                numeric.append(field)
                totals[field]=sum(vals)
        rows.append({
            "path": rel, "rows": len(records), "columns": len(fields),
            "numeric_columns": numeric, "numeric_totals": totals,
            "numeric_total_sum": sum(totals.values()),
            "source_fingerprint": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if not rows:
        raise ValueError("لم أجد ملفات CSV قابلة للتحليل في snapshot")
    selected=max(rows, key=lambda x:(float(x["numeric_total_sum"]), x["path"]))
    return {"files": rows, "selected_path": selected["path"], "selected": selected,
            "count": len(rows), "source_snapshot": [dict(item) for item in file_list if isinstance(item, dict)],
            "verified": True}


def _preferred_numeric_field(fields: list[str], text: str) -> str | None:
    normalized = {str(f).casefold().strip(): str(f) for f in fields}
    for key in ("sales", "revenue"):
        if key in normalized:
            return normalized[key]
    source = str(text or "").casefold()
    for field in fields:
        if str(field).casefold() in source and any(word in source for word in ("sales", "revenue", "مبيعات", "إيراد")):
            return str(field)
    return None


@tool(
    "يقارن ملفات CSV recursively باختيار ملف المبيعات/الإيراد صاحب أعلى متوسط، ثم يعيد أرقام الاختيار وإجمالي/متوسط/أعلى/أقل قيمة مع بصمات المصدر",
    {"file_list": "snapshot recursive من workspace", "question": "الهدف التحليلي الأصلي"},
    name="analyze_csv_by_average",
    capability="cross_department_sales_report_move",
    organization_department="data",
    organization_role="data:data-analyst",
    produces=("csv_average_ranked",),
    cost=3.2,
    duration=1.0,
    parallel_safe=True,
    idempotent=True,
    verification_level="strong",
    pipe_param="file_list",
)
def analyze_csv_by_average(file_list: list[dict], question: str = ""):
    import hashlib
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن تكون snapshot قائمة")
    rows=[]
    for item in file_list:
        if not isinstance(item, dict) or str(item.get("type")) != "file":
            continue
        rel=str(item.get("name") or "")
        if Path(rel).suffix.casefold() != ".csv":
            continue
        path=safe_workspace_path(rel)
        _resolved, fields, records=load_rows(path)
        field=_preferred_numeric_field(fields, question)
        if not field:
            continue
        values=[]
        for record in records:
            value=_parse_number(_clean(record.get(field)))
            if value is not None:
                values.append(float(value))
        if not values:
            continue
        rows.append({
            "path": rel, "rows": len(records), "columns": len(fields),
            "selected_column": field, "total": sum(values), "average": sum(values)/len(values),
            "maximum": max(values), "minimum": min(values), "n_values": len(values),
            "source_fingerprint": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    if not rows:
        raise ValueError("لم أجد CSV به عمود sales أو revenue قابل للتحليل")
    selected=max(rows, key=lambda x:(float(x["average"]), x["path"]))
    return {
        "files": rows, "selected_path": selected["path"], "selected": selected,
        "selection_metric": "average", "count": len(rows),
        "source_snapshot": [dict(item) for item in file_list if isinstance(item, dict)],
        "verified": True,
    }

def _sales_report_markdown(analysis: dict, destination_dir: str) -> str:
    lines=["# Top Sales Analysis", "", "## Selection", f"Selection criterion: highest average of sales/revenue", f"Selected file: `{analysis.get('selected_path','')}`", f"Planned report destination: `{destination_dir.rstrip('/')}/{Path(str(analysis.get('selected_report_name') or 'top_sales_analysis.md')).name}`", ""]
    lines += ["## Files analyzed"]
    for item in analysis.get("files", []):
        lines.append(f"- `{item['path']}`: rows={item['rows']}, columns={item['columns']}, column=`{item['selected_column']}`, total={item['total']}, average={item['average']}, maximum={item['maximum']}, minimum={item['minimum']}")
        lines.append(f"  - source SHA-256: `{item['source_fingerprint']}`")
    selected=analysis.get('selected') or {}
    lines += ["", "## Winning File", f"- File: `{analysis.get('selected_path','')}`", f"- Column: `{selected.get('selected_column','')}`", f"- Total: **{selected.get('total')}**", f"- Average: **{selected.get('average')}**", f"- Maximum: **{selected.get('maximum')}**", f"- Minimum: **{selected.get('minimum')}**", "", "## Verification", "The report was generated from the recursive source snapshot; the selected file and all reported metrics are tied to its source fingerprint."]
    return "\n".join(lines)+"\n"


@tool(
    "ينشئ تقرير اختيار ملف المبيعات بناءً على أعلى متوسط ويعيد قراءته ويتحقق من جميع الأرقام من نتيجة التحليل",
    {"analysis_result": "نتيجة تحليل متوسط sales/revenue", "output_path": "مسار التقرير", "destination_dir": "المجلد المخطط لنقل التقرير"},
    name="create_sales_analysis_report",
    organization_department="data",
    organization_role="data:data-analyst",
    requires_approval=True,
    risk="medium",
    cost=1.4,
    capability="cross_department_sales_report_move",
    produces=("sales_analysis_report_created", "sales_analysis_report_verified"),
    verification_level="strong",
)
def create_sales_analysis_report(analysis_result: dict, output_path: str, destination_dir: str = "selected_reports"):
    if not isinstance(analysis_result, dict) or not analysis_result.get("selected"):
        raise ValueError("نتيجة التحليل مطلوبة")
    root=workspace_root(); target=safe_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload=dict(analysis_result)
    payload["selected_report_name"]=target.name
    target.write_text(_sales_report_markdown(payload, destination_dir), encoding="utf-8")
    reread=target.read_text(encoding="utf-8")
    selected=analysis_result.get("selected") or {}
    verified=bool(
        analysis_result.get("verified") and
        analysis_result.get("selected_path") and
        selected.get("selected_column") and
        str(analysis_result.get("selected_path")) in reread and
        str(selected.get("source_fingerprint")) in reread and
        str(selected.get("average")) in reread and
        str(selected.get("total")) in reread and
        str(selected.get("maximum")) in reread and
        str(selected.get("minimum")) in reread
    )
    if not verified:
        raise ValueError("فشل تحقق تقرير أعلى متوسط للمبيعات")
    return {"path": str(target.relative_to(root)).replace(chr(92), '/'), "verified": True, "report_reread_verified": True, "source_fingerprint": selected.get("source_fingerprint"), "selected_path": analysis_result.get("selected_path")}
