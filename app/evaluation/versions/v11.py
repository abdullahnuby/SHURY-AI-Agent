"""Deterministic V11 benchmark for analytics + self-observability."""
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
from app.knowledge.data_analysis import profile_dataset, answer_question, compare_datasets
from app.knowledge.memory import Memory
from app.observability.agent_analytics import analyze_runtime


def run_v11_benchmark() -> dict:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / 'a.csv'; b = root / 'b.csv'
        with a.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['name','value','group','date']); w.writerows([
                ['a',1,'x','2026-01-01'], ['b',2,'x','2026-01-02'], ['c',3,'y','2026-01-03'],
                ['d',100,'y','2026-01-04'], ['',5,'y','2026-01-05']])
        with b.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['name','value','group','date']); w.writerows([
                ['a',2,'x','2026-01-01'], ['b',4,'x','2026-01-02'], ['c',6,'z','2026-01-03']])
        p = profile_dataset(a)
        q = answer_question(a, 'ما متوسط value؟')
        o = answer_question(a, 'اكتشف الشذوذ في value')
        cmp = compare_datasets(a, b)
        m = Memory(root / 'm.db')
        m.add_note('benchmark')
        analytics = analyze_runtime(m)
        return {
            'passed': sum([
                p.rows == 5 and p.columns == 4,
                q['answer']['value'] == 22.2,
                o['answer']['outliers'] >= 1,
                'new_categories' in cmp['columns']['group'],
                analytics['effects'] == 0 and analytics['runs'] == 0 and analytics['negative_cusum'] == 0.0,
            ]),
            'total': 5,
            'details': {
                'profile': p.to_dict(), 'aggregate': q, 'outliers': o,
                'compare': cmp, 'analytics_empty': analytics,
            },
        }
