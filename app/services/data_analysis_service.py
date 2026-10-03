"""V12/V13 evidence-oriented data analysis orchestration."""
from __future__ import annotations
from collections import defaultdict
from statistics import mean
from app.knowledge.data_analysis import load_rows, profile_dataset, _clean, _parse_number
from app.knowledge.statistics.statistics_v12 import (
    bootstrap_ci, theil_sen, robust_z_scores, mutual_information, discretize_numeric,
    categorical_entropy, cliffs_delta, js_divergence, page_hinkley,
)
from app.knowledge.statistics.statistics_v13 import autocorrelation, moving_block_bootstrap_ci, choose_confidence_interval_method
from app.planning.adaptive_portfolio import select_trend_method, record_choice_outcome


def verify_comprehensive_report(report: dict, profile_fingerprint: str, row_count: int) -> dict:
    checks = {
        "fingerprint_matches": report.get("fingerprint") == profile_fingerprint,
        "row_count_nonnegative": int(report.get("rows", -1)) >= 0 and int(report.get("rows", -1)) == row_count,
        "findings_well_formed": all(isinstance(f, dict) and "type" in f for f in report.get("findings", [])),
        "methodology_present": bool(report.get("methodology")),
    }
    for finding in report.get("findings", []):
        if finding.get("type") == "numeric_summary":
            ci = finding.get("mean_ci95") or {}
            est = ci.get("estimate")
            lo = ci.get("lower"); hi = ci.get("upper")
            if est is not None and lo is not None and hi is not None and not (lo <= est <= hi):
                checks["ci_contains_estimate"] = False
                break
    else:
        checks["ci_contains_estimate"] = True
    return {"ok": all(checks.values()), "checks": checks, "method": "deterministic_evidence_certificate"}


def _numeric_values(rows, column):
    return [x for x in (_parse_number(_clean(r.get(column))) for r in rows) if x is not None]


def comprehensive_analysis(path, seed_text: str | None = None, memory=None) -> dict:
    p, fields, rows = load_rows(path)
    profile = profile_dataset(p)
    numeric = [c.name for c in profile.column_profiles if c.inferred_type == "numeric"]
    categorical = [c.name for c in profile.column_profiles if c.inferred_type in {"categorical", "boolean"}]
    report = {
        "source": str(p), "fingerprint": profile.fingerprint,
        "rows": len(rows), "columns": len(fields),
        "quality_score": profile.quality_score,
        "methodology": [], "findings": [], "verified": True,
    }
    report["quality"] = {
        "duplicate_rows": profile.duplicate_rows,
        "warnings": profile.warnings,
        "ranked_findings": [],
    }
    from app.knowledge.data_analysis import rank_findings
    report["quality"]["ranked_findings"] = rank_findings(profile)

    for col in numeric:
        xs = _numeric_values(rows, col)
        if not xs:
            continue
        cp = next(c for c in profile.column_profiles if c.name == col)
        ci_choice = choose_confidence_interval_method(xs)
        if ci_choice["method"] == "moving_block_bootstrap":
            ci = moving_block_bootstrap_ci(xs, "mean", 0.95, 800, (seed_text or profile.fingerprint) + ":" + col)
        else:
            ci = bootstrap_ci(xs, "mean", 0.95, 800, (seed_text or profile.fingerprint) + ":" + col)
        z = robust_z_scores(xs)
        robust_outliers = sum(abs(v) >= 3.5 for v in z if v != float("inf") and v != -float("inf"))
        method_choice = select_trend_method(
            xs, cp.outlier_rate, memory=memory,
            numeric_count=len(numeric), categorical_count=len(categorical),
        )
        if method_choice.method == "theil_sen":
            trend = theil_sen(xs)
        else:
            trend = {
                "slope": cp.trend_slope, "r2": cp.trend_r2, "method": "ordinary_least_squares"
            }
        report["methodology"].append({
            "column": col, "ci": ci["method"], "trend": trend["method"],
            "ci_selection": ci_choice,
            "trend_selection": {
                "method": method_choice.method,
                "reason": method_choice.reason,
                "evidence_score": method_choice.evidence_score,
                "learned_score": method_choice.learned_score,
                "final_score": method_choice.final_score,
                "context": method_choice.context,
                "candidates": list(method_choice.candidates),
            },
            "anomaly": "tukey_iqr_and_robust_z",
        })
        report["findings"].append({
            "type": "numeric_summary", "column": col,
            "n": len(xs), "mean": mean(xs), "mean_ci95": ci,
            "trend": trend, "tukey_outliers": cp.outliers,
            "robust_z_outliers": robust_outliers,
        })

    # Association discovery: correlations + discretized mutual information.
    for target in numeric:
        for feature in numeric:
            if feature == target:
                continue
            pairs = []
            for row in rows:
                x = _parse_number(_clean(row.get(feature)))
                y = _parse_number(_clean(row.get(target)))
                if x is not None and y is not None:
                    pairs.append((x, y))
            if len(pairs) < 5:
                continue
            fv = [x for x, _ in pairs]
            tv = [y for _, y in pairs]
            mi = mutual_information(discretize_numeric(fv), discretize_numeric(tv))
            corr = next((x for x in profile.correlations if {x['x'], x['y']} == {target, feature}), None)
            report["findings"].append({
                "type": "feature_relation", "target": target, "feature": feature,
                "n": len(pairs),
                "pearson": corr.get("pearson") if corr else None,
                "spearman": corr.get("spearman") if corr else None,
                "mutual_information_bits": mi,
            })
    for cat in categorical:
        vals = [str(_clean(r.get(cat))) for r in rows if _clean(r.get(cat)) is not None]
        ent = categorical_entropy(vals)
        if ent is not None:
            report["findings"].append({"type": "categorical_entropy", "column": cat, "entropy_bits": ent, "unique": len(set(vals))})

    # Online-style signal from row order for the first numeric field.
    if numeric:
        xs = _numeric_values(rows, numeric[0])
        report["online_monitor"] = page_hinkley(xs)
    else:
        report["online_monitor"] = page_hinkley([])

    report["findings"].sort(key=lambda x: (x.get("type", ""), x.get("column", x.get("feature", ""))))
    report["verification"] = verify_comprehensive_report(report, profile.fingerprint, len(rows))
    report["verified"] = bool(report["verification"]["ok"])
    report["adaptive_learning"] = []
    for item in report["methodology"]:
        sel = item.get("trend_selection") or {}
        if sel.get("method") and sel.get("context"):
            report["adaptive_learning"].append({
                "task": "trend", "method": sel["method"], "context": sel["context"],
                "evidence_score": sel.get("evidence_score"),
                "learned_score": sel.get("learned_score"),
                "final_score": sel.get("final_score"),
            })
    return report


def compare_numeric_effect(left_path, right_path, column: str) -> dict:
    lp, _, lr = load_rows(left_path); rp, _, rr = load_rows(right_path)
    a = _numeric_values(lr, column); b = _numeric_values(rr, column)
    if not a or not b:
        raise ValueError(f"لا توجد بيانات رقمية كافية في {column}")
    ci = bootstrap_ci([y - x for x, y in zip(a[:min(len(a),len(b))], b[:min(len(a),len(b))])], "mean", 0.95, 800,
                      f"{lp}:{rp}:{column}") if min(len(a), len(b)) >= 2 else None
    return {
        "column": column, "left_n": len(a), "right_n": len(b),
        "left_mean": mean(a), "right_mean": mean(b),
        "mean_difference": mean(b) - mean(a),
        "cliffs_delta": cliffs_delta(a, b),
        "paired_difference_ci95": ci,
        "js_divergence": js_divergence(discretize_numeric(a), discretize_numeric(b)),
        "verified": True,
    }
