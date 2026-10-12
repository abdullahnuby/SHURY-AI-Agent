#!/usr/bin/env python3
"""SHURY — 10 مهام فعلية من شغل عبدالله (طيبة، السبعاية، Trust ES، المزرعة).

بتستخدم نفس الـharness بتاع shury_acceptance.py (لازم يكون جنبه في نفس المجلد).

الاستخدام:
  python shury_real_tasks.py --selftest
  python shury_real_tasks.py --freeze
  python shury_real_tasks.py --project <مسار_المشروع> --label c243 --seed 7 --out "$PWD\\real_c243_s7.json"
  python shury_real_tasks.py --project <مسار> --label c243 --seed 7 --data-dir "D:\\بياناتي" --out ...
  python shury_real_tasks.py --compare a.json b.json

--data-dir اختياري: لو فيه ملفات بنفس الأسماء والأعمدة (تحت)، المهام بتستخدم بياناتك الحقيقية
والإجابة الصح بتتحسب منها، بدل البيانات التجريبية. الأعمدة المطلوبة:
  tayba_sales.csv : date,product,qty,amount
  tayba_stock.csv : item,stock,reorder_level
  sebaeya_boq.csv : item,unit,qty,unit_price,amount
  palm_harvest.csv: block,trees,kg
(الأعمدة بالإنجليزي، والقيم بأي لغة. ملفات مش موجودة = بيانات تجريبية للمهمة دي.)

مهام "stretch" (R3 وR5 وR7) متوقع إنها صعبة على SHURY وهدفها تكشف حدوده، مش تتحسب فشل في الجودة.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shury_acceptance as S  # noqa: E402

DATA_DIR: Path | None = None
TASKS: list[dict] = []


def task(id, group, steps, setup, check, good, stretch=False, approve=True):
    TASKS.append(dict(id=id, group=group, split="REAL", steps=steps, setup=setup, check=check, good=good,
                      approve=approve, needs_network=False, stretch=stretch))


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(ws: Path, name: str, header: list[str], rows: list[list]) -> None:
    S.w(ws, name, ",".join(header) + "\n" + "\n".join(",".join(str(c) for c in r) for r in rows) + "\n")


def _real(name: str, ws: Path) -> list[dict] | None:
    """بيانات المستخدم الحقيقية لو موجودة، وبيتم نسخها للـworkspace."""
    if DATA_DIR and (DATA_DIR / name).exists():
        shutil.copy(DATA_DIR / name, ws / name)
        return _read_csv(ws / name)
    return None


def _num(x) -> float:
    return float(str(x).translate(S.AR_DIGITS).replace(",", "").strip() or 0)


# ───────────────────────── طيبة ─────────────────────────
PRODUCTS = {"شراب قطن أطفال": 35, "شراب رجالي كلاسيك": 50, "شراب رياضي": 60, "شراب كاحل": 40,
            "شراب شتوي صوف": 75, "شراب مخطط": 45, "شراب ضغط": 90}


def _tayba_rows(ws, rng):
    rows = _real("tayba_sales.csv", ws)
    if rows is not None:
        return rows
    gen = []
    for day in range(1, 31):
        for p in rng.sample(list(PRODUCTS), 3):
            q = rng.randint(2, 40)
            gen.append([f"2026-09-{day:02d}", p, q, q * PRODUCTS[p]])
    _write_csv(ws, "tayba_sales.csv", ["date", "product", "qty", "amount"], gen)
    return _read_csv(ws / "tayba_sales.csv")


def s_tayba_top(ws, rng):
    rows = _tayba_rows(ws, rng)
    tot: dict[str, float] = {}
    for r in rows:
        tot[r["product"]] = tot.get(r["product"], 0) + _num(r["amount"])
    top = max(tot, key=tot.get)
    return dict(top=top, value=tot[top])


task("R1_tayba_top_product", "tayba",
     ["إيه أكتر منتج مبيعًا بالقيمة في tayba_sales.csv وكام قيمته؟"],
     s_tayba_top,
     lambda c: (c["truth"]["top"] in c["resp"][-1] and S.has_number(c["resp"][-1], c["truth"]["value"]),
                "المنتج أو قيمته غلط"),
     lambda c: ([f"{c['truth']['top']}: {c['truth']['value']}"], None))


def s_tayba_total(ws, rng):
    rows = _tayba_rows(ws, rng)
    return dict(total=sum(_num(r["amount"]) for r in rows), qty=sum(_num(r["qty"]) for r in rows))


task("R2_tayba_total_sales", "tayba",
     ["إجمالي المبيعات في tayba_sales.csv كام؟"],
     s_tayba_total,
     lambda c: (S.has_number(c["resp"][-1], c["truth"]["total"])
                and not S.has_number(c["resp"][-1], c["truth"]["qty"]) , "الإجمالي غلط (يمكن جمع عمود الكمية بدل القيمة)"),
     lambda c: ([f"الإجمالي {c['truth']['total']}"], None))


def s_stock(ws, rng):
    rows = _real("tayba_stock.csv", ws)
    if rows is None:
        gen = []
        for p in PRODUCTS:
            lvl = rng.randint(20, 60)
            gen.append([p, rng.randint(0, 100), lvl])
        _write_csv(ws, "tayba_stock.csv", ["item", "stock", "reorder_level"], gen)
        rows = _read_csv(ws / "tayba_stock.csv")
    low = [r["item"] for r in rows if _num(r["stock"]) < _num(r["reorder_level"])]
    return dict(n=len(low), items=low)


task("R3_tayba_low_stock", "tayba",
     ["كام صنف رصيده في tayba_stock.csv أقل من حد الطلب (reorder_level)؟"],
     s_stock,
     lambda c: (S.has_number(c["resp"][-1], c["truth"]["n"]) or (c["truth"]["n"] == 0 and "مفيش" in c["resp"][-1]),
                "عدد الأصناف الأقل من حد الطلب غلط (مقارنة عمودين)"),
     lambda c: ([f"{c['truth']['n']} صنف"], None), stretch=True)

# ───────────────────────── السبعاية ─────────────────────────
BOQ_ITEMS = [("حفر عام", "م3", 1800, 85), ("خرسانة عادية", "م3", 120, 1450), ("خرسانة مسلحة قواعد", "م3", 95, 2850),
             ("حديد تسليح", "طن", 38, 31500), ("مباني طوب", "م2", 640, 310), ("بياض داخلي", "م2", 1250, 140),
             ("عزل مائي", "م2", 420, 260)]


def s_boq(ws, rng):
    rows = _real("sebaeya_boq.csv", ws)
    if rows is None:
        gen = []
        for item, unit, q, price in BOQ_ITEMS:
            q2 = max(1, int(q * rng.uniform(0.8, 1.2)))
            gen.append([item, unit, q2, price, q2 * price])
        _write_csv(ws, "sebaeya_boq.csv", ["item", "unit", "qty", "unit_price", "amount"], gen)
        rows = _read_csv(ws / "sebaeya_boq.csv")
    return dict(total=sum(_num(r["amount"]) for r in rows),
                wrong=[sum(_num(r["qty"]) for r in rows), sum(_num(r["unit_price"]) for r in rows)])


task("R4_sebaeya_boq_total", "sebaeya",
     ["اجمعلي إجمالي المقايسة من عمود amount في sebaeya_boq.csv"],
     s_boq,
     lambda c: (S.only_number(c["resp"][-1], c["truth"]["total"], c["truth"]["wrong"]),
                "إجمالي المقايسة غلط (الكمية أو سعر الوحدة اتجمعوا بدل amount)"),
     lambda c: ([f"إجمالي المقايسة {c['truth']['total']}"], None))


def s_concrete(ws, rng):
    a, b, h, n = rng.choice([2.0, 2.5, 3.0]), rng.choice([2.0, 2.5, 3.0]), rng.choice([0.5, 0.6, 0.8]), rng.randint(8, 24)
    return dict(a=a, b=b, h=h, n=n, v=round(a * b * h * n, 3), partial=round(a * b * h, 3))


task("R5_sebaeya_concrete_volume", "sebaeya",
     ["عندي {n} قاعدة خرسانة، أبعاد كل قاعدة {a} × {b} × {h} متر. كام متر مكعب خرسانة الإجمالي؟"],
     s_concrete,
     lambda c: (S.has_number(c["resp"][-1], c["truth"]["v"], 0.05),
                ("رد بحجم قاعدة واحدة (أهمل عدد القواعد)" if S.has_number(c["resp"][-1], c["truth"]["partial"], 0.05)
                 else "الحجم الإجمالي غلط")),
     lambda c: ([f"{c['truth']['v']} م3"], None), stretch=True)


def s_reports(ws, rng):
    n = rng.randint(5, 14)
    for i in range(n):
        S.w(ws, f"reports/daily_202609{i+1:02d}.md", f"تقرير يوم {i+1}\n")
    S.w(ws, "reports/site_photos.zip", "x"); S.w(ws, "reports/boq_notes.txt", "n")
    return dict(n=n)


task("R6_sebaeya_daily_reports_count", "sebaeya",
     ["كام ملف md في مجلد reports؟"],
     s_reports,
     lambda c: (S.has_number(c["resp"][-1], c["truth"]["n"]) and not S.has_number(c["resp"][-1], c["truth"]["n"] + 2),
                "عدد تقارير md غلط (يمكن عدّ كل الملفات)"),
     lambda c: ([f"{c['truth']['n']} ملف"], None))

# ───────────────────────── Trust ES / Mazaya ─────────────────────────


def s_fee(ws, rng):
    v, p = rng.choice([450000, 650000, 850000, 1200000]), rng.choice([3, 4, 5])
    return dict(v=v, p=p, fee=v * p / 100)


task("R7_trust_design_fee", "trust_es",
     ["أتعاب التصميم {p}% من قيمة المشروع {v} جنيه. كام الأتعاب؟"],
     s_fee,
     lambda c: (S.has_number(c["resp"][-1], c["truth"]["fee"], 0.5), "الأتعاب غلط"),
     lambda c: ([f"{c['truth']['fee']:.0f} جنيه"], None), stretch=True)


def s_contractor(ws, rng):
    return dict(name=rng.choice(["حسين", "سيد", "عادل"]), phone="010" + "".join(str(rng.randint(0, 9)) for _ in range(8)))


task("R8_trust_contractor_memory", "trust_es",
     ["سجل مقاول الدهانات: {name} {phone}", "مقاول الدهانات رقمه كام؟"],
     s_contractor,
     lambda c: (c["truth"]["phone"] in S.norm(c["resp"][-1]), "ما رجّعش رقم مقاول الدهانات اللي اتسجل"),
     lambda c: (["تمام", f"الرقم {c['truth']['phone']}"], None))

# ───────────────────────── المزرعة ─────────────────────────
BLOCKS = ["حوض أ", "حوض ب", "حوض ج", "حوض د", "حوض هـ"]


def s_palm(ws, rng):
    rows = _real("palm_harvest.csv", ws)
    if rows is None:
        gen = []
        for b in BLOCKS:
            trees = rng.randint(300, 1200)
            gen.append([b, trees, int(trees * rng.uniform(18, 42))])
        _write_csv(ws, "palm_harvest.csv", ["block", "trees", "kg"], gen)
        rows = _read_csv(ws / "palm_harvest.csv")
    best = max(rows, key=lambda r: _num(r["kg"]))
    return dict(block=best["block"], kg=_num(best["kg"]), trees=_num(best["trees"]))


task("R9_palm_best_block", "farm",
     ["أنهي حوض أنتج أكتر تمر في palm_harvest.csv وكام كيلو؟"],
     s_palm,
     lambda c: (c["truth"]["block"] in c["resp"][-1] and S.has_number(c["resp"][-1], c["truth"]["kg"]),
                "الحوض أو كمية الكيلو غلط (يمكن اتخد عدد الأشجار بدل الكيلو)"),
     lambda c: ([f"{c['truth']['block']}: {c['truth']['kg']}"], None))


def s_report(ws, rng):
    rows = _tayba_rows(ws, rng); (ws / "reports").mkdir(exist_ok=True)
    return dict(total=sum(_num(r["amount"]) for r in rows))


def chk_report(c):
    rep = c["ws"] / "reports" / "tayba_report.md"
    if not rep.exists():
        return False, "التقرير tayba_report.md مش في مجلد reports"
    return S.has_number(rep.read_text(encoding="utf-8"), c["truth"]["total"]), "التقرير موجود لكن إجمالي المبيعات مش جواه"


task("R10_tayba_report_to_folder", "tayba",
     ["حلل tayba_sales.csv واعمل تقرير باسم tayba_report.md فيه إجمالي المبيعات وحطه في مجلد reports"],
     s_report, chk_report,
     lambda c: (["تم"], lambda ws: (ws / "reports/tayba_report.md").write_text(f"الإجمالي {c['truth']['total']}", encoding="utf-8")))


# ───────────────────────── runner ─────────────────────────
def task_hash() -> str:
    import hashlib
    spec = [(t["id"], t["group"], t["steps"], t["stretch"]) for t in TASKS]
    return hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def cmd_selftest() -> int:
    bad = 0
    for t in TASKS:
        rng = random.Random(f"1:{t['id']}"); ws = Path(__import__("tempfile").mkdtemp()); truth = t["setup"](ws, rng) or {}
        ctx = dict(resp=[""], ws=ws, truth=truth, approvals=[])
        resps, mut = t["good"](ctx)
        if mut:
            mut(ws)
        ctx["resp"] = resps
        ok_good, why = t["check"](ctx)
        rng = random.Random(f"1:{t['id']}"); ws2 = Path(__import__("tempfile").mkdtemp()); truth2 = t["setup"](ws2, rng) or {}
        ok_bad, _ = t["check"](dict(resp=["معرفش"], ws=ws2, truth=truth2, approvals=[]))
        status = "OK " if ok_good and not ok_bad else "BAD"
        bad += status == "BAD"
        print(f"{status} {t['id']:32s} good={ok_good} wrong_answer_passes={ok_bad}" + ("" if ok_good else f"  ({why})"))
    print(f"\nTasks: {len(TASKS)} | hash {task_hash()} | {'SELFTEST PASS' if not bad else str(bad) + ' PROBLEMS'}")
    return 1 if bad else 0


def cmd_run(a) -> None:
    global DATA_DIR
    DATA_DIR = Path(a.data_dir).resolve() if a.data_dir else None
    agent = S.real_agent_factory(Path(a.project).resolve())
    rows = []
    for t in TASKS:
        r, ws = S.run_one(t, a.seed, agent)
        r["stretch"] = t["stretch"]
        rows.append(r); shutil.rmtree(ws, ignore_errors=True)
        tag = "PASS " if r["passed"] else "FAIL "
        print(tag + r["id"] + ("  [stretch]" if t["stretch"] else "") + ("" if r["passed"] else "  <- " + r["reason"]))
    core = [r for r in rows if not r["stretch"]]
    out = dict(label=a.label, seed=a.seed, tasks_hash=task_hash(), data_dir=str(DATA_DIR) if DATA_DIR else None,
               passed=sum(r["passed"] for r in rows), total=len(rows),
               core_passed=sum(r["passed"] for r in core), core_total=len(core), results=rows)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{a.label}: {out['passed']}/{out['total']}  (أساسي {out['core_passed']}/{out['core_total']}) -> {a.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project"); ap.add_argument("--label", default="real"); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="real_result.json"); ap.add_argument("--data-dir")
    ap.add_argument("--compare", nargs=2); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    if a.freeze:
        print(task_hash(), len(TASKS), "tasks")
    elif a.selftest:
        sys.exit(cmd_selftest())
    elif a.compare:
        S.cmd_compare(a)
    elif a.project:
        cmd_run(a)
    else:
        ap.print_help()
