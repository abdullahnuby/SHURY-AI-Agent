import json
import sqlite3
from pathlib import Path

from app.knowledge.memory import Memory
from app.knowledge.memory_types import USER


def make_legacy_db(path: Path):
    conn = sqlite3.connect(path)
    conn.executescript('''
    CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        ts TEXT,
        importance INTEGER NOT NULL DEFAULT 3,
        tags TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        source TEXT NOT NULL DEFAULT 'user',
        confidence REAL NOT NULL DEFAULT 1.0
    );
    CREATE TABLE facts (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        ts TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        confidence REAL NOT NULL DEFAULT 1.0,
        source TEXT NOT NULL DEFAULT 'user',
        revision INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE fact_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        value TEXT,
        status TEXT NOT NULL,
        ts TEXT NOT NULL,
        source TEXT NOT NULL
    );
    CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT, status TEXT, plan TEXT, message TEXT, ts TEXT);
    INSERT INTO facts(key,value,ts,status,confidence,source,revision) VALUES
      ('city','Alexandria','2026-10-02T10:00:00','active',1.0,'user',2),
      ('name','?','2026-10-02T10:00:00','active',1.0,'user',1),
      ('work','Engineer','2026-10-02T10:00:00','deleted',0.8,'user',1);
    INSERT INTO fact_history(key,value,status,ts,source) VALUES
      ('city','Luxor','superseded','2026-09-01T10:00:00','user');
    INSERT INTO notes(text,ts,importance,tags,status,source,confidence) VALUES
      ('User prefers dark mode','2026-10-01T09:00:00',4,'["ui"]','active','user',0.95),
      ('','2026-10-01T09:00:00',3,'[]','active','user',1.0);
    ''')
    conn.commit(); conn.close()


def test_phase14_migrates_without_assigning_owner(tmp_path):
    db = tmp_path / 'legacy.db'
    make_legacy_db(db)
    mem = Memory(db, owner_id='local-default')
    # Legacy facts/notes are not auto-backfilled into live memory anymore.
    assert mem.get_fact('city', owner_id='local-default') is None
    report = mem.migrate_legacy_memory(backup_path=tmp_path / 'before.sqlite')
    assert report['status'] == 'completed'
    assert report['source_counts']['facts'] == 3
    assert report['source_counts']['notes'] == 2
    assert Path(report['backup_path']).exists()
    backup_con = sqlite3.connect(report['backup_path'])
    assert backup_con.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 3
    assert backup_con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 2
    backup_con.close()
    rows = sqlite3.connect(db).execute(
        "SELECT kind,key,value,scope,owner_id,status,source_ref,metadata FROM memory_items ORDER BY id"
    ).fetchall()
    migrated = [r for r in rows if (r[7] and ('legacy_fact_key' in r[7] or 'legacy_note_id' in r[7]))]
    assert any(r[1] == 'city' and r[3] == USER and r[4] is None and r[5] == 'unresolved' for r in migrated)
    assert any(r[2] == 'Luxor' and r[1] == 'city' and r[5] == 'unresolved' for r in migrated)
    assert any(r[1] == 'work' and r[5] == 'archived' for r in migrated)
    assert any(r[2] == 'User prefers dark mode' and r[5] == 'unresolved' for r in migrated)
    assert not mem.retrieve('Alexandria', owner_id='local-default', kinds={'fact'})


def test_phase14_is_idempotent_and_unknown_stays_unresolved(tmp_path):
    db = tmp_path / 'legacy.db'
    make_legacy_db(db)
    mem = Memory(db, owner_id='local-default')
    first = mem.migrate_legacy_memory()
    second = mem.migrate_legacy_memory()
    assert first['status'] == 'completed'
    assert second['status'] == 'completed'
    assert second['run_id'] == first['run_id']
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM memory_items WHERE owner_id IS NULL AND status='unresolved'").fetchone()[0]
    assert count >= 3
    status = con.execute("SELECT status FROM memory_migration_meta WHERE schema_name='personal-agent.memory-legacy-migration'").fetchone()[0]
    assert status == 'completed'
    con.close()


def test_phase14_quarantines_existing_global_personal_backfill(tmp_path):
    db = tmp_path / 'legacy.db'
    mem = Memory(db, owner_id='local-default')
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO memory_items(kind,key,value,normalized,scope,owner_id,source,confidence,importance,status,created_at,updated_at,revision,metadata) VALUES('fact','name','John','name john','global',NULL,'user',1.0,5,'active','2026-10-02T00:00:00','2026-10-02T00:00:00',1,?)",
                    (json.dumps({'legacy_fact':1}),))
        con.commit()
    report = mem.migrate_legacy_memory()
    row = sqlite3.connect(db).execute("SELECT scope,owner_id,status,metadata FROM memory_items WHERE key='name'").fetchone()
    assert row[0] == 'user' and row[1] is None and row[2] == 'unresolved'
    md = json.loads(row[3])
    assert md['phase14_quarantine'] is True
    assert report['unresolved_counts']['quarantined_fact'] == 1


def test_phase14_dry_run_does_not_modify_legacy_data(tmp_path):
    db = tmp_path / 'legacy.db'
    make_legacy_db(db)
    mem = Memory(db, owner_id='local-default')
    before = sqlite3.connect(db).execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
    report = mem.migrate_legacy_memory(dry_run=True)
    after = sqlite3.connect(db).execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
    assert report['status'] == 'dry_run'
    assert before == after
    assert not list(tmp_path.glob('*.sqlite'))
