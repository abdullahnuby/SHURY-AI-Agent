"""Deterministic local data-analysis engine.

No pandas, NumPy, neural generation, embeddings, or network calls.  The engine focuses on
reproducible evidence: schema inference, data-quality diagnostics, robust
statistics, correlations, trend estimation, outlier detection, group
aggregation, and dataset comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import sqlite3
import os
from collections import Counter, defaultdict
from statistics import mean, median, pstdev
from typing import Any, Iterable


TRUE_VALUES = {"true", "1", "yes", "y", "نعم", "صح"}
FALSE_VALUES = {"false", "0", "no", "n", "لا", "خطأ"}
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    inferred_type: str
    count: int
    missing: int
    missing_rate: float
    unique: int
    constant: bool
    min: Any = None
    max: Any = None
    mean: float | None = None
    median: float | None = None
    stddev: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    mad: float | None = None
    outliers: int = 0
    outlier_rate: float = 0.0
    top_values: list[dict] | None = None
    trend_slope: float | None = None
    trend_r2: float | None = None


@dataclass(frozen=True)
class DatasetProfile:
    source: str
    fingerprint: str
    rows: int
    columns: int
    duplicate_rows: int
    quality_score: float
    column_profiles: list[ColumnProfile]
    correlations: list[dict]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class DataAnalysisError(ValueError):
    pass


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    # Handle percentages without hiding the original text in raw rows.
    if text.endswith("%"):
        try:
            return float(text[:-1].strip()) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    low = value.strip().casefold()
    if low in TRUE_VALUES:
        return True
    if low in FALSE_VALUES:
        return False
    return None


def _parse_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _ranks(values: list[float]) -> list[float]:
    pairs = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(pairs):
        j = i + 1
        while j < len(pairs) and pairs[j][1] == pairs[i][1]:
            j += 1
        rank = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[pairs[k][0]] = rank
        i = j
    return ranks


def _linear_trend(values: list[float]) -> tuple[float | None, float | None]:
    n = len(values)
    if n < 2:
        return None, None
    xs = list(range(n))
    mx, my = mean(xs), mean(values)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / denom
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in values)
    if ss_tot == 0:
        r2 = 1.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
        r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, r2


def _outlier_stats(values: list[float]) -> tuple[float | None, float | None, int, int]:
    if len(values) < 4:
        return None, None, 0, 0
    q1 = _quantile(values, 0.25)
    q3 = _quantile(values, 0.75)
    if q1 is None or q3 is None:
        return q1, q3, 0, 0
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    count = sum(v < low or v > high for v in values)
    return q1, q3, count, len(values)


def _mad(values: list[float]) -> float | None:
    if not values:
        return None
    med = median(values)
    return median([abs(v - med) for v in values])


def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str | None]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise DataAnalysisError("CSV بدون أعمدة")
        fields = [str(x) for x in reader.fieldnames]
        rows = [{k: _clean(v) for k, v in row.items()} for row in reader]
    return fields, rows


def _read_json(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and isinstance(data.get("data"), list):
        rows = data["data"]
    else:
        raise DataAnalysisError("JSON يجب أن يكون array من records أو يحتوي على data array")
    if not all(isinstance(r, dict) for r in rows):
        raise DataAnalysisError("JSON rows يجب أن تكون objects")
    fields = sorted({str(k) for row in rows for k in row})
    return fields, [{k: row.get(k) for k in fields} for row in rows]


def _read_sqlite(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    conn = sqlite3.connect(str(path))
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if not tables:
            raise DataAnalysisError("SQLite بدون جداول")
        table = tables[0]
        safe = '"' + table.replace('"', '""') + '"'
        rows_raw = conn.execute(f"SELECT * FROM {safe}").fetchall()
        fields = [d[0] for d in conn.execute(f"SELECT * FROM {safe} LIMIT 0").description]
        return fields, [dict(zip(fields, row)) for row in rows_raw]
    finally:
        conn.close()


def _resolve_input_path(path: str | Path) -> Path:
    raw_text = str(path or "").strip()
    workspace = os.getenv("AGENT_WORKSPACE")
    base = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()

    # ``@active_dataset`` is a deterministic workspace reference. It is only resolved
    # when exactly one supported dataset exists; ambiguity must fail closed instead of
    # silently choosing the first file.
    if raw_text == "@active_dataset":
        candidates = sorted(
            p for p in base.iterdir()
            if p.is_file() and p.suffix.casefold() in {".csv", ".json", ".db", ".sqlite", ".sqlite3"}
            and not p.name.startswith(".")
        )
        if not candidates:
            raise DataAnalysisError("مفيش dataset واحد واضح في الـworkspace")
        if len(candidates) > 1:
            raise DataAnalysisError("أكثر من dataset موجود في الـworkspace؛ حدد الملف صراحة")
        return candidates[0].resolve()

    raw = Path(raw_text).expanduser()
    if not raw.is_absolute():
        candidate = (base / raw).resolve()
        if base != candidate and base not in candidate.parents:
            raise DataAnalysisError(f"المسار خارج الـworkspace: {path}")
        return candidate
    return raw.resolve()


def load_rows(path: str | Path) -> tuple[Path, list[str], list[dict[str, Any]]]:
    p = _resolve_input_path(path)
    if not p.exists() or not p.is_file():
        raise DataAnalysisError(f"الملف غير موجود: {p}")
    suffix = p.suffix.casefold()
    if suffix == ".csv":
        fields, rows = _read_csv(p)
    elif suffix == ".json":
        fields, rows = _read_json(p)
    elif suffix in {".db", ".sqlite", ".sqlite3"}:
        fields, rows = _read_sqlite(p)
    else:
        raise DataAnalysisError("الصيغة المدعومة: CSV, JSON, SQLite")
    return p, fields, rows


def _infer_type(values: list[Any]) -> str:
    nonmissing = [_clean(v) for v in values]
    nonmissing = [v for v in nonmissing if v is not None]
    if not nonmissing:
        return "unknown"
    bool_text = {"true", "false", "yes", "no", "y", "n", "نعم", "لا", "صح", "خطأ"}
    if nonmissing and all(v.casefold() in bool_text for v in nonmissing):
        return "boolean"
    nums = [_parse_number(v) for v in nonmissing]
    numeric_rate = sum(v is not None for v in nums) / len(nonmissing)
    dates = [_parse_date(v) for v in nonmissing]
    date_rate = sum(v is not None for v in dates) / len(nonmissing)
    if numeric_rate >= 0.95:
        return "numeric"
    if date_rate >= 0.9:
        return "datetime"
    unique = len(set(nonmissing))
    avg_len = sum(len(v) for v in nonmissing) / len(nonmissing)
    if unique <= min(20, max(5, int(len(nonmissing) * 0.1))):
        return "categorical"
    if avg_len > 35:
        return "text"
    return "categorical"


def _profile_column(name: str, values: list[Any]) -> ColumnProfile:
    cleaned = [_clean(v) for v in values]
    observed = [v for v in cleaned if v is not None]
    missing = len(cleaned) - len(observed)
    inferred = _infer_type(values)
    numeric = [x for x in (_parse_number(v) for v in observed) if x is not None]
    min_v = max_v = avg = med = sd = q1 = q3 = iqr = mad = None
    outliers = 0
    trend_slope = trend_r2 = None
    top = None
    if inferred == "numeric" and numeric:
        min_v, max_v = min(numeric), max(numeric)
        avg, med = mean(numeric), median(numeric)
        sd = pstdev(numeric) if len(numeric) > 1 else 0.0
        q1, q3 = _quantile(numeric, 0.25), _quantile(numeric, 0.75)
        iqr = (q3 - q1) if q1 is not None and q3 is not None else None
        mad = _mad(numeric)
        q1o, q3o, outliers, _ = _outlier_stats(numeric)
        trend_slope, trend_r2 = _linear_trend(numeric)
        q1, q3 = q1o, q3o
    elif inferred in {"categorical", "boolean"} and observed:
        counts = Counter(str(x) for x in observed)
        top = [{"value": k, "count": v, "share": v / len(observed)} for k, v in counts.most_common(10)]
    elif inferred == "datetime" and observed:
        dates = [_parse_date(v) for v in observed]
        nums = [d.timestamp() for d in dates if d is not None]
        if nums:
            min_v = datetime.fromtimestamp(min(nums)).isoformat()
            max_v = datetime.fromtimestamp(max(nums)).isoformat()
            trend_slope, trend_r2 = _linear_trend(nums)
    unique = len(set(str(v) for v in observed))
    return ColumnProfile(
        name=name,
        inferred_type=inferred,
        count=len(cleaned),
        missing=missing,
        missing_rate=missing / len(cleaned) if cleaned else 0.0,
        unique=unique,
        constant=unique <= 1 and bool(observed),
        min=min_v,
        max=max_v,
        mean=avg,
        median=med,
        stddev=sd,
        q1=q1,
        q3=q3,
        iqr=iqr,
        mad=mad,
        outliers=outliers,
        outlier_rate=outliers / len(numeric) if numeric else 0.0,
        top_values=top,
        trend_slope=trend_slope,
        trend_r2=trend_r2,
    )


def profile_dataset(path: str | Path) -> DatasetProfile:
    p, fields, rows = load_rows(path)
    tuples = [tuple(_clean(row.get(f)) for f in fields) for row in rows]
    dup = len(tuples) - len(set(tuples))
    cols = [_profile_column(f, [row.get(f) for row in rows]) for f in fields]
    numeric_cols = [c.name for c in cols if c.inferred_type == "numeric"]
    correlations = []
    for i, left in enumerate(numeric_cols):
        for right in numeric_cols[i + 1:]:
            pairs = []
            for row in rows:
                x, y = _parse_number(_clean(row.get(left))), _parse_number(_clean(row.get(right)))
                if x is not None and y is not None:
                    pairs.append((x, y))
            if len(pairs) >= 3:
                xs = [x for x, _ in pairs]; ys = [y for _, y in pairs]
                pearson = _pearson(xs, ys)
                spearman = _pearson(_ranks(xs), _ranks(ys))
                correlations.append({"x": left, "y": right, "n": len(pairs), "pearson": pearson, "spearman": spearman})
    warnings = []
    for c in cols:
        if c.missing_rate >= 0.2:
            warnings.append(f"{c.name}: missing rate {c.missing_rate:.1%}")
        if c.constant:
            warnings.append(f"{c.name}: constant column")
        if c.outlier_rate >= 0.1:
            warnings.append(f"{c.name}: high outlier rate {c.outlier_rate:.1%}")
    quality = 100.0
    quality -= min(30.0, (dup / len(rows) * 30.0) if rows else 0.0)
    quality -= min(40.0, sum(c.missing_rate for c in cols) / max(1, len(cols)) * 40.0)
    quality -= min(20.0, sum(c.constant for c in cols) * 5.0)
    quality = max(0.0, round(quality, 2))
    return DatasetProfile(str(p), _fingerprint(p), len(rows), len(fields), dup, quality, cols, correlations, warnings)



def _psi_numeric(base: list[float], current: list[float], bins: int = 10) -> float | None:
    if len(base) < 5 or len(current) < 5:
        return None
    # Degenerate baseline: any material movement away from the single value is drift.
    if max(base) == min(base):
        if max(current) == min(current):
            return 0.0 if current[0] == base[0] else 13.815510557964274
        return 13.815510557964274
    cuts = []
    for i in range(1, bins):
        q = _quantile(base, i / bins)
        if q is not None:
            cuts.append(q)
    edges = [-float("inf")] + cuts + [float("inf")]
    def counts(values):
        out = [0] * (len(edges) - 1)
        for v in values:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    out[i] += 1
                    break
        return out
    bc, cc = counts(base), counts(current)
    bsum, csum = len(base), len(current)
    psi = 0.0
    for b, c in zip(bc, cc):
        bp = max(b / bsum, 1e-6); cp = max(c / csum, 1e-6)
        psi += (cp - bp) * math.log(cp / bp)
    return psi


def _psi_categorical(base: list[str], current: list[str]) -> float | None:
    if len(base) < 5 or len(current) < 5:
        return None
    b, c = Counter(base), Counter(current)
    keys = sorted(set(b) | set(c))
    total_b, total_c = len(base), len(current)
    psi = 0.0
    for k in keys:
        bp = max(b.get(k, 0) / total_b, 1e-6); cp = max(c.get(k, 0) / total_c, 1e-6)
        psi += (cp - bp) * math.log(cp / bp)
    return psi

def rank_findings(profile: DatasetProfile) -> list[dict]:
    findings: list[dict] = []
    for c in profile.column_profiles:
        if c.missing_rate > 0:
            findings.append({"type": "missingness", "column": c.name, "severity": round(c.missing_rate * 100, 3),
                             "evidence": f"missing_rate={c.missing_rate:.3f}"})
        if c.outlier_rate > 0:
            findings.append({"type": "outliers", "column": c.name, "severity": round(c.outlier_rate * 100, 3),
                             "evidence": f"iqr_outlier_rate={c.outlier_rate:.3f}"})
        if c.constant:
            findings.append({"type": "constant", "column": c.name, "severity": 100.0, "evidence": "single_unique_value"})
        if c.trend_r2 is not None and c.trend_slope is not None and c.trend_r2 >= 0.6 and c.inferred_type == "numeric":
            findings.append({"type": "trend", "column": c.name, "severity": round(c.trend_r2 * 100, 3),
                             "evidence": f"slope={c.trend_slope:.6g};r2={c.trend_r2:.3f}"})
    for c in profile.correlations:
        strength = abs(c["pearson"]) if c.get("pearson") is not None else 0.0
        if strength >= 0.7:
            findings.append({"type": "correlation", "column": f"{c['x']}~{c['y']}", "severity": round(strength * 100, 3),
                             "evidence": f"pearson={c['pearson']:.3f};spearman={c['spearman']:.3f}"})
    findings.sort(key=lambda x: (-x["severity"], x["type"], x["column"]))
    return findings[:20]

def compare_datasets(left: str | Path, right: str | Path) -> dict:
    lp, lf, lr = load_rows(left)
    rp, rf, rr = load_rows(right)
    common = [c for c in lf if c in rf]
    report = {"left": str(lp), "right": str(rp), "common_columns": common, "rows_left": len(lr), "rows_right": len(rr), "columns": {}}
    for c in common:
        lt = _infer_type([r.get(c) for r in lr]); rt = _infer_type([r.get(c) for r in rr])
        entry = {"left_type": lt, "right_type": rt, "type_match": lt == rt}
        if lt == rt == "numeric":
            lx = [_parse_number(_clean(r.get(c))) for r in lr]; rx = [_parse_number(_clean(r.get(c))) for r in rr]
            lx = [x for x in lx if x is not None]; rx = [x for x in rx if x is not None]
            entry.update({"left_mean": mean(lx) if lx else None, "right_mean": mean(rx) if rx else None,
                          "left_median": median(lx) if lx else None, "right_median": median(rx) if rx else None})
            if lx and rx:
                pooled = max(abs(mean(lx)), abs(mean(rx)), 1e-9)
                entry["mean_relative_change"] = (mean(rx) - mean(lx)) / pooled
                entry["psi"] = _psi_numeric(lx, rx)
                entry["drift_alert"] = bool(entry["psi"] is not None and entry["psi"] >= 0.2)
        elif lt in {"categorical", "boolean"} and rt == lt:
            lc, rc = Counter(str(_clean(r.get(c))) for r in lr), Counter(str(_clean(r.get(c))) for r in rr)
            entry["new_categories"] = sorted(set(rc) - set(lc))[:20]
            entry["removed_categories"] = sorted(set(lc) - set(rc))[:20]
            entry["psi"] = _psi_categorical([str(_clean(r.get(c))) for r in lr], [str(_clean(r.get(c))) for r in rr])
            entry["drift_alert"] = bool(entry["psi"] is not None and entry["psi"] >= 0.2)
        report["columns"][c] = entry
    report["added_columns"] = [c for c in rf if c not in lf]
    report["removed_columns"] = [c for c in lf if c not in rf]
    return report


def answer_question(path: str | Path, question: str) -> dict:
    p, fields, rows = load_rows(path)
    q = str(question).casefold()
    profile = profile_dataset(p)
    numeric = [c for c in profile.column_profiles if c.inferred_type == "numeric"]
    cat = [c for c in profile.column_profiles if c.inferred_type in {"categorical", "boolean"}]
    result: dict[str, Any] = {"source": str(p), "fingerprint": profile.fingerprint, "question": question, "evidence": []}

    # Explicit quality intent.
    if any(k in q for k in ("جودة", "quality", "missing", "ناقص", "مفقود", "duplicate", "مكرر", "تكرار", "التكرارات")):
        result["answer"] = {"quality_score": profile.quality_score, "duplicate_rows": profile.duplicate_rows,
                             "warnings": profile.warnings, "columns": [asdict(c) for c in profile.column_profiles]}
        result["method"] = "deterministic_quality_profile"
        return result

    # Correlation between explicitly named columns.
    if any(k in q for k in ("correlation", "ارتباط", "علاقة")):
        named = [f for f in fields if f.casefold() in q]
        chosen = named[:2]
        if len(chosen) < 2 and len(numeric) >= 2:
            chosen = [numeric[0].name, numeric[1].name]
        if len(chosen) < 2:
            raise DataAnalysisError("أحتاج عمودين رقميين لحساب الارتباط")
        corr = next((x for x in profile.correlations if {x["x"], x["y"]} == set(chosen)), None)
        result["answer"] = corr
        result["method"] = "pearson_and_spearman"
        return result

    # V12: confidence interval for a numeric statistic.
    if any(k in q for k in ("فاصل ثقة", "confidence interval", "confidence", "ثقة المتوسط")):
        chosen = next((c for c in numeric if c.name.casefold() in q), numeric[0] if numeric else None)
        if chosen is None:
            raise DataAnalysisError("لا يوجد عمود رقمي لحساب فاصل الثقة")
        from app.knowledge.statistics.statistics_v12 import bootstrap_ci
        xs = [_parse_number(_clean(r.get(chosen.name))) for r in rows]
        xs = [x for x in xs if x is not None]
        ci = bootstrap_ci(xs, "mean", 0.95, 1000, profile.fingerprint + ":" + chosen.name)
        result["answer"] = {"column": chosen.name, "mean_ci95": ci}
        result["method"] = ci["method"]
        return result

    # V12: robust anomaly intent; compare Tukey and robust MAD-z evidence.
    if any(k in q for k in ("robust anomaly", "robust outlier", "شذوذ robust", "شذوذ قوي")):
        chosen = next((c for c in numeric if c.name.casefold() in q), numeric[0] if numeric else None)
        if chosen is None:
            raise DataAnalysisError("لا يوجد عمود رقمي لاكتشاف الشذوذ")
        from app.knowledge.statistics.statistics_v12 import robust_z_scores
        xs = [_parse_number(_clean(r.get(chosen.name))) for r in rows]
        xs = [x for x in xs if x is not None]
        zs = robust_z_scores(xs)
        rz = sum(abs(z) >= 3.5 for z in zs if math.isfinite(z))
        result["answer"] = {"column": chosen.name, "tukey_outliers": chosen.outliers, "robust_z_outliers": rz,
                             "robust_scale": "MAD * 1.4826"}
        result["method"] = "tukey_iqr_plus_robust_mad_z"
        return result

    # Outlier intent.
    if any(k in q for k in ("outlier", "شاذ", "شذوذ", "غريب")):
        chosen = next((c for c in numeric if c.name.casefold() in q), numeric[0] if numeric else None)
        if chosen is None:
            raise DataAnalysisError("لا يوجد عمود رقمي لاكتشاف الشذوذ")
        result["answer"] = {"column": chosen.name, "outliers": chosen.outliers, "outlier_rate": chosen.outlier_rate,
                             "q1": chosen.q1, "q3": chosen.q3, "iqr": chosen.iqr, "mad": chosen.mad}
        result["method"] = "tukey_iqr_with_mad"
        return result

    # Trend intent.
    if any(k in q for k in ("trend", "اتجاه", "تطور", "متغير مع الوقت", "ينمو", "ينخفض")):
        chosen = next((c for c in numeric if c.name.casefold() in q), numeric[0] if numeric else None)
        if chosen is None:
            raise DataAnalysisError("لا يوجد عمود رقمي لحساب الاتجاه")
        xs = [_parse_number(_clean(r.get(chosen.name))) for r in rows]
        xs = [x for x in xs if x is not None]
        from app.knowledge.statistics.statistics_v12 import choose_trend_method, theil_sen
        choice = choose_trend_method(xs, chosen.outlier_rate)
        if choice.method == "theil_sen":
            robust = theil_sen(xs)
            slope, r2 = robust["slope"], robust["r2"]
            method = "theil_sen_robust_trend"
        else:
            slope, r2 = chosen.trend_slope, chosen.trend_r2
            method = "ordinary_least_squares_trend"
        result["answer"] = {"column": chosen.name, "slope": slope, "r2": r2,
                             "interpretation": "increasing" if slope and slope > 0 else "decreasing" if slope and slope < 0 else "flat",
                             "selection_reason": choice.reason}
        result["method"] = method
        return result

    # Group aggregation: "متوسط value حسب group" / "average value by group".
    if (re.search(r"(?:^|\W)حسب(?:\W|$)", q, re.I) or re.search(r"\b(?:by|group\s+by)\b", q, re.I)) and numeric and cat:
        value_col = next((c.name for c in numeric if c.name.casefold() in q), numeric[0].name)
        group_col = next((c.name for c in cat if c.name.casefold() in q), cat[0].name)
        grouped = {}
        for row in rows:
            g = _clean(row.get(group_col)); v = _parse_number(_clean(row.get(value_col)))
            if g is None or v is None:
                continue
            bucket = grouped.setdefault(str(g), [])
            bucket.append(v)
        summary = [{"group": g, "count": len(vs), "mean": mean(vs), "median": median(vs), "sum": sum(vs)}
                   for g, vs in sorted(grouped.items())]
        result["answer"] = {"group_by": group_col, "value": value_col, "groups": summary}
        result["method"] = "deterministic_group_aggregation"
        return result

    # Aggregate intent: average/mean/median/min/max/sum/count.
    aggregate = None
    for key, op in (("sum", "sum"), ("اجمع", "sum"), ("مجموع", "sum"), ("إجمالي", "sum"), ("اجمالي", "sum"), ("الإجمالي", "sum"), ("متوسط", "mean"), ("average", "mean"),
                    ("mean", "mean"), ("median", "median"), ("وسيط", "median"),
                    ("minimum", "min"), ("min", "min"), ("اقل", "min"),
                    ("maximum", "max"), ("max", "max"), ("أعلى", "max"), ("count", "count"), ("عدد", "count")):
        if key in q:
            aggregate = op; break
    if aggregate:
        chosen = next((c for c in numeric if c.name.casefold() in q), numeric[0] if numeric else None)
        if aggregate == "count":
            result["answer"] = {"rows": len(rows)}
            result["method"] = "row_count"
            return result
        if chosen is None:
            raise DataAnalysisError("لم أجد عمودًا رقميًا للتحليل")
        xs = [_parse_number(_clean(r.get(chosen.name))) for r in rows]
        xs = [x for x in xs if x is not None]
        if not xs:
            raise DataAnalysisError(f"لا توجد قيم رقمية في {chosen.name}")
        fn = {"sum": sum, "mean": mean, "median": median, "min": min, "max": max}[aggregate]
        result["answer"] = {"column": chosen.name, "operation": aggregate, "value": fn(xs), "n": len(xs)}
        result["method"] = "deterministic_scalar_aggregation"
        return result

    # V12: deterministic factor/feature screening using aligned rows.
    if any(k in q for k in ("العوامل", "feature", "features", "predictors", "مرتبط بـ", "مرتبط ب", "عوامل مرتبطة")):
        target = next((c.name for c in numeric if c.name.casefold() in q), numeric[0].name if numeric else None)
        if target is None:
            raise DataAnalysisError("أحتاج متغيرًا رقميًا هدفًا")
        target_vals = []
        candidates = []
        for feature in fields:
            if feature == target:
                continue
            pairs_num = []
            for row in rows:
                tv = _parse_number(_clean(row.get(target)))
                fv = _parse_number(_clean(row.get(feature)))
                if tv is not None and fv is not None:
                    pairs_num.append((fv, tv))
            if len(pairs_num) >= 5:
                xs = [x for x, _ in pairs_num]; ys = [y for _, y in pairs_num]
                candidates.append({"feature": feature, "n": len(xs), "pearson": _pearson(xs, ys),
                                   "spearman": _pearson(_ranks(xs), _ranks(ys)),
                                   "mutual_information_bits": __import__('app.knowledge.statistics.statistics_v12', fromlist=['mutual_information']).mutual_information(
                                       __import__('app.knowledge.statistics.statistics_v12', fromlist=['discretize_numeric']).discretize_numeric(xs),
                                       __import__('app.knowledge.statistics.statistics_v12', fromlist=['discretize_numeric']).discretize_numeric(ys))})
                continue
            vals = []
            target_cat = []
            for row in rows:
                fv = _clean(row.get(feature)); tv = _parse_number(_clean(row.get(target)))
                if fv is not None and tv is not None:
                    vals.append(str(fv)); target_cat.append(str(tv))
            if len(vals) >= 5:
                from app.knowledge.statistics.statistics_v12 import discretize_numeric, mutual_information
                ys = [float(v) for v in target_cat]
                candidates.append({"feature": feature, "n": len(vals), "pearson": None, "spearman": None,
                                   "mutual_information_bits": mutual_information(vals, discretize_numeric(ys))})
        candidates.sort(key=lambda x: (-(x.get("mutual_information_bits") or 0.0), -(abs(x.get("spearman") or 0.0)), x["feature"]))
        result["answer"] = {"target": target, "features": candidates[:20]}
        result["method"] = "aligned_feature_screening_mutual_information"
        return result

    if any(k in q for k in ("profile", "schema", "وصف", "اعرض الأعمدة", "الاعمدة", "ملخص")):
        result["answer"] = profile.to_dict()
        result["method"] = "deterministic_dataset_profile"
        return result

    # Default is informative, not speculative: give a profile and ranked warnings.
    payload = profile.to_dict()
    payload["ranked_findings"] = rank_findings(profile)
    result["answer"] = payload
    result["method"] = "default_profile_fallback"
    return result


class DeterministicDataAgent:
    """Small capability-first data agent with evidence-oriented outputs."""

    def profile(self, path: str | Path) -> dict:
        p = profile_dataset(path)
        payload = p.to_dict()
        payload["ranked_findings"] = rank_findings(p)
        return payload

    def ask(self, path: str | Path, question: str) -> dict:
        result = answer_question(path, question)
        result["verified"] = bool(result.get("fingerprint"))
        return result

    def compare(self, left: str | Path, right: str | Path) -> dict:
        report = compare_datasets(left, right)
        report["verified"] = bool(report.get("common_columns") is not None)
        return report
