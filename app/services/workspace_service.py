"""V14 public facade: heterogeneous workspace evidence + distribution drift."""
from __future__ import annotations

from app.integrations.workspace import catalog_workspace, deterministic_join, join_candidates, discover_workspace
from app.knowledge.data_analysis import load_rows, _parse_number, _clean
from app.knowledge.statistics.statistics_v14 import multivariate_drift


def workspace_analyze(path: str, max_join_pairs: int = 12) -> dict:
    catalog = catalog_workspace(path)
    tables = [s for s in catalog["sources"] if s["kind"] == "table"]
    join_graph = []
    for i, left in enumerate(tables):
        for right in tables[i + 1:]:
            try:
                candidates = join_candidates(left["path"], right["path"])
            except Exception as exc:
                candidates = [{"error": f"{type(exc).__name__}: {exc}"}]
            if candidates:
                join_graph.append({"left": left["path"], "right": right["path"], "candidates": candidates[:5]})
            if len(join_graph) >= max_join_pairs:
                break
        if len(join_graph) >= max_join_pairs:
            break
    quality = {
        "table_sources": len(tables),
        "document_sources": catalog["document_sources"],
        "parse_errors": len(catalog["errors"]),
        "join_candidates": sum(len(x["candidates"]) for x in join_graph if x.get("candidates")),
    }
    return {
        "workspace": catalog["root"],
        "fingerprint": __import__("hashlib").sha256("|".join(s["fingerprint"] for s in catalog["sources"]).encode()).hexdigest(),
        "catalog": catalog,
        "join_graph": join_graph,
        "quality": quality,
        "method": "deterministic_heterogeneous_workspace_catalog_and_join_graph",
        "verified": not bool(catalog["errors"]),
    }


def compare_sources(left: str, right: str) -> dict:
    lp, lf, lr = load_rows(left); rp, rf, rr = load_rows(right)
    common = [c for c in lf if c in rf]
    numeric = []
    for c in common:
        av = [_parse_number(_clean(r.get(c))) for r in lr]
        bv = [_parse_number(_clean(r.get(c))) for r in rr]
        av = [x for x in av if x is not None]; bv = [x for x in bv if x is not None]
        if len(av) >= 5 and len(bv) >= 5:
            numeric.append((c, av, bv))
    if not numeric:
        return {"left": str(lp), "right": str(rp), "numeric_drift": None, "method": "no_common_numeric_columns"}
    # compare the most stable aligned common subset: independent distributions, not paired rows.
    # Transform rows so dimensions share only complete numeric rows.
    base_rows, current_rows = [], []
    nbase, ncur = len(lr), len(rr)
    for i in range(nbase):
        row = []
        ok = True
        for name, _, _ in numeric:
            v = _parse_number(_clean(lr[i].get(name)))
            if v is None: ok = False; break
            row.append(v)
        if ok: base_rows.append(row)
    for i in range(ncur):
        row = []
        ok = True
        for name, _, _ in numeric:
            v = _parse_number(_clean(rr[i].get(name)))
            if v is None: ok = False; break
            row.append(v)
        if ok: current_rows.append(row)
    drift = multivariate_drift(base_rows, current_rows, [x[0] for x in numeric], seed_text=f"{lp}:{rp}")
    return {"left": str(lp), "right": str(rp), "common_numeric_columns": [x[0] for x in numeric],
            "baseline_rows": len(base_rows), "current_rows": len(current_rows),
            "numeric_drift": drift, "method": "multivariate_sliced_wasserstein_distribution_drift"}
