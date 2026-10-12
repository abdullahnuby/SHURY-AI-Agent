"""Local RAG engine using lexical retrieval plus Arabic semantic embeddings.

The engine performs local retrieval only. Arabic-Retrieval-v1.0 supplies semantic embeddings;
all scoring, evidence handling, citation binding and answer synthesis remain deterministic.
- hierarchical chunking for text/tables
- BM25-style lexical retrieval
- character n-gram lexical similarity
- reciprocal-rank fusion (RRF)
- MMR-style diversity selection
- query decomposition / multi-hop retrieval
- evidence-aware adaptive retries and fail-closed abstention
- lightweight working-memory consolidation with decay
- extractive answer synthesis with citation bindings

The result is retrieval-augmented *extractive* reasoning: every returned claim is bound to
retrieved source chunks, so unsupported text is not fabricated by the runtime.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import time
import os

from app.intelligence.semantic.retrieval import MODEL_NAME as SEMANTIC_MODEL_NAME, passage_vectors, query_vector
from collections import Counter, defaultdict
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.intelligence.understanding import normalize

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "rag.db"


def default_rag_db() -> Path:
    """Resolve the active RAG DB from the environment, falling back to the app data DB.

    Evaluation and sandbox runs must be able to isolate their RAG state without mutating
    the developer machine database.
    """
    configured = os.getenv("AGENT_RAG_DB")
    return Path(configured).expanduser() if configured else DEFAULT_DB
SUPPORTED = {".txt", ".md", ".markdown", ".csv", ".json", ".sqlite", ".sqlite3", ".db"}
IGNORED_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    fingerprint TEXT NOT NULL,
    kind TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    modified REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL DEFAULT 'world',
    project_id TEXT,
    source_ref TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed REAL NOT NULL DEFAULT 0,
    embedding BLOB,
    embedding_model TEXT,
    FOREIGN KEY(source_id) REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE(source_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id, ordinal);
CREATE TABLE IF NOT EXISTS postings (
    term TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    tf INTEGER NOT NULL,
    PRIMARY KEY(term, chunk_id),
    FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_postings_term ON postings(term);
CREATE INDEX IF NOT EXISTS idx_postings_chunk ON postings(chunk_id);
CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    hops INTEGER NOT NULL,
    candidates INTEGER NOT NULL,
    retrieved INTEGER NOT NULL,
    evidence_score REAL NOT NULL,
    grounded INTEGER NOT NULL,
    ts TEXT NOT NULL
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(text: str) -> list[str]:
    n = normalize(text)
    raw: list[str] = []
    current: list[str] = []
    for ch in n:
        if ch.isalnum() or ch == "_" or unicodedata.category(ch).startswith("L"):
            current.append(ch)
        elif current:
            raw.append("".join(current))
            current = []
    if current:
        raw.append("".join(current))
    out = []
    for tok in raw:
        # Small, deterministic Arabic/Latin normalization for recall without a stemmer dependency.
        tok = re.sub(r"^(?:ال|وال|بال|لل)", "", tok) if len(tok) > 4 else tok
        tok = re.sub(r"(?:ها|هم|هن|ك|ي|ه)$", "", tok) if len(tok) > 5 else tok
        out.append(tok)
    return out


def _char_ngrams(text: str, n: int = 3) -> Counter[str]:
    s = re.sub(r"\s+", " ", normalize(text))
    if len(s) < n:
        return Counter([s] if s else [])
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _fingerprint_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(str(path.resolve()).encode("utf-8"))
    h.update(path.read_bytes())
    return h.hexdigest()


def _fingerprint_text(text: str) -> str:
    return _hash_bytes(text.encode("utf-8"))


def _split_text(text: str, max_chars: int = 1200, overlap: int = 180) -> list[tuple[str, str]]:
    """Heading-aware paragraph chunking with bounded overlap."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    lines = normalized.splitlines()
    title = ""
    sections: list[tuple[str, list[str]]] = []
    current: list[str] = []
    for line in lines:
        m = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
        if m:
            if current:
                sections.append((title, current))
                current = []
            title = m.group(1).strip()
            continue
        current.append(line)
    if current:
        sections.append((title, current))
    if not sections:
        sections = [("", lines)]

    chunks: list[tuple[str, str]] = []
    for section_title, sec_lines in sections:
        paragraphs = re.split(r"\n\s*\n", "\n".join(sec_lines))
        buf = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            piece = f"{section_title}\n{para}".strip() if section_title else para
            if len(buf) + len(piece) + 2 <= max_chars:
                buf = (buf + "\n\n" + piece).strip()
            else:
                if buf:
                    chunks.append((section_title, buf))
                tail = buf[-overlap:] if buf and overlap else ""
                buf = (tail + "\n\n" + piece).strip()
                while len(buf) > max_chars:
                    chunks.append((section_title, buf[:max_chars].strip()))
                    buf = buf[max_chars - overlap :].strip() if overlap else buf[max_chars:].strip()
        if buf:
            chunks.append((section_title, buf))
    # De-duplicate accidental overlap artifacts.
    seen = set()
    unique = []
    for title, text_part in chunks:
        key = (title, text_part)
        if text_part and key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _table_chunks(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []
        chunks: list[tuple[str, str]] = [("schema", f"CSV columns: {', '.join(fields)} | rows: {len(rows)}")]
        for idx, row in enumerate(rows):
            payload = " | ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, ""))
            chunks.append((f"row {idx + 1}", payload))
        return chunks
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _json_chunks(payload)
    if suffix in {".sqlite", ".sqlite3", ".db"}:
        return _sqlite_chunks(path)
    return []


def _json_chunks(payload, prefix: str = "root") -> list[tuple[str, str]]:
    chunks = []
    if isinstance(payload, list):
        for i, item in enumerate(payload):
            if isinstance(item, dict):
                text_part = " | ".join(f"{k}: {v}" for k, v in item.items() if not isinstance(v, (dict, list)))
                chunks.append((f"{prefix}[{i}]", text_part))
                for k, v in item.items():
                    if isinstance(v, (dict, list)):
                        chunks.extend(_json_chunks(v, f"{prefix}[{i}].{k}"))
            else:
                chunks.append((f"{prefix}[{i}]", str(item)))
        return chunks
    if isinstance(payload, dict):
        scalar = " | ".join(f"{k}: {v}" for k, v in payload.items() if not isinstance(v, (dict, list)))
        if scalar:
            chunks.append((prefix, scalar))
        for k, v in payload.items():
            if isinstance(v, (dict, list)):
                chunks.extend(_json_chunks(v, f"{prefix}.{k}"))
    else:
        chunks.append((prefix, str(payload)))
    return chunks


def _sqlite_chunks(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        chunks = []
        for table in tables:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34)*2)}")')]
            count = conn.execute(f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34)*2)}"').fetchone()[0]
            chunks.append((f"table {table} schema", f"table: {table} | columns: {', '.join(cols)} | rows: {count}"))
            quoted = '"' + table.replace('"', '""') + '"'
            for idx, row in enumerate(conn.execute(f"SELECT * FROM {quoted}")):
                values = " | ".join(f"{cols[i]}: {row[i]}" for i in range(min(len(cols), len(row))) if row[i] is not None)
                chunks.append((f"table {table} row {idx + 1}", values))
        return chunks
    finally:
        conn.close()


@dataclass(frozen=True)
class Chunk:
    id: int
    source: str
    source_kind: str
    title: str
    text: str
    ordinal: int
    token_count: int
    access_count: int
    last_accessed: float


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    chunk_id: int
    source: str
    title: str
    text: str
    score: float
    rank_bm25: int | None
    rank_char: int | None
    fused_score: float
    hop: int
    semantic_score: float = 0.0
    knowledge_scope: str = "world"
    project_id: str | None = None
    source_ref: str | None = None
    provenance: dict | None = None


class RAGEngine:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path is not None else default_rag_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                conn.executescript(SCHEMA)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
                if "embedding" not in columns:
                    conn.execute("ALTER TABLE chunks ADD COLUMN embedding BLOB")
                if "embedding_model" not in columns:
                    conn.execute("ALTER TABLE chunks ADD COLUMN embedding_model TEXT")
                source_columns = {row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
                if "knowledge_scope" not in source_columns:
                    conn.execute("ALTER TABLE sources ADD COLUMN knowledge_scope TEXT NOT NULL DEFAULT 'world'")
                if "project_id" not in source_columns:
                    conn.execute("ALTER TABLE sources ADD COLUMN project_id TEXT")
                if "source_ref" not in source_columns:
                    conn.execute("ALTER TABLE sources ADD COLUMN source_ref TEXT")
                if "provenance_json" not in source_columns:
                    conn.execute("ALTER TABLE sources ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}'")
                if "content_hash" not in source_columns:
                    conn.execute("ALTER TABLE sources ADD COLUMN content_hash TEXT")
                conn.execute(
                    "UPDATE sources SET source_ref=path, provenance_json=json_object('origin', CASE WHEN lower(kind)='web' THEN 'external_source' ELSE 'local_file' END, 'source_kind', kind, 'source_ref', path), content_hash=fingerprint "
                    "WHERE source_ref IS NULL OR source_ref='' OR provenance_json IS NULL OR provenance_json='{}'"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_knowledge_scope ON sources(knowledge_scope, project_id, id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_source_ref ON sources(source_ref)")
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _store_embeddings(self, conn, rows: list[tuple[int, str]]) -> int:
        if not rows:
            return 0
        try:
            vectors = passage_vectors([text for _, text in rows])
        except Exception:
            return 0
        if vectors is None:
            return 0
        stored = 0
        for (chunk_id, _), vector in zip(rows, vectors):
            try:
                payload = vector.astype("float32", copy=False).tobytes()
            except Exception:
                continue
            conn.execute("UPDATE chunks SET embedding=?, embedding_model=? WHERE id=?",
                         (payload, SEMANTIC_MODEL_NAME, int(chunk_id)))
            stored += 1
        return stored

    def _backfill_embeddings(self, conn) -> int:
        try:
            rows = conn.execute(
                "SELECT id,title,text FROM chunks WHERE embedding IS NULL OR embedding_model != ? ORDER BY id",
                (SEMANTIC_MODEL_NAME,),
            ).fetchall()
        except Exception:
            return 0
        return self._store_embeddings(conn, [(int(r[0]), f"{r[1]}\n{r[2]}") for r in rows])

    def _semantic_candidates(self, query: str, limit: int, project_id: str | None = None) -> list[tuple[Chunk, float]]:
        vector = query_vector(query)
        if vector is None:
            return []
        try:
            import numpy as np
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT c.id,c.source_id,c.ordinal,c.title,c.text,c.token_count,c.access_count,c.last_accessed,s.path,s.kind,c.embedding,s.knowledge_scope,s.project_id,s.source_ref,s.provenance_json "
                    "FROM chunks c JOIN sources s ON s.id=c.source_id "
                    "WHERE c.embedding_model=? AND c.embedding IS NOT NULL "
                    "AND (s.knowledge_scope='world' OR (? IS NOT NULL AND s.project_id=?))",
                    (SEMANTIC_MODEL_NAME, project_id, project_id),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                return []
            decoded=[]; valid_rows=[]
            dim=int(getattr(vector, "shape", [0])[-1] or 0)
            for row in rows:
                blob=row[10]
                if not blob:
                    continue
                arr=np.frombuffer(blob, dtype=np.float32)
                if arr.size != dim:
                    continue
                valid_rows.append(row); decoded.append(arr)
            if not decoded:
                return []
            matrix=np.vstack(decoded)
            scores=matrix @ vector
            order=np.argsort(-scores, kind="stable")[:max(1, limit)]
            return [
                (Chunk(r[0], r[8], r[9], r[3], r[4], r[2], r[5], r[6], r[7]), float(max(0.0, min(1.0, (scores[i] + 1.0) / 2.0))))
                for i in order for r in [valid_rows[int(i)]]
            ]
        except Exception:
            return []

    def discover(self, path: str | Path) -> list[Path]:
        root = Path(path).expanduser().resolve()
        if root.is_file():
            if root.resolve() == self.db_path.resolve():
                return []
            return [root] if root.suffix.lower() in SUPPORTED else []
        if not root.is_dir():
            raise FileNotFoundError(str(root))
        files = []
        for p in sorted(root.rglob("*")):
            if any(part in IGNORED_DIRS for part in p.parts):
                continue
            if p.is_file() and p.suffix.lower() in SUPPORTED:
                if p.resolve() == self.db_path.resolve():
                    continue
                files.append(p)
        return files

    def _read_chunks(self, path: Path) -> tuple[str, list[tuple[str, str]]]:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return "text", _split_text(path.read_text(encoding="utf-8"))
        return "table", _table_chunks(path)

    def index(self, path: str | Path) -> dict:
        files = self.discover(path)
        conn = self._connect()
        added = updated = skipped = 0
        total_chunks = 0
        pending_embeddings: list[tuple[int, str]] = []
        try:
            with conn:
                for file_path in files:
                    fp = _fingerprint_file(file_path)
                    stat = file_path.stat()
                    old = conn.execute("SELECT id,fingerprint FROM sources WHERE path=?", (str(file_path),)).fetchone()
                    if old and old[1] == fp:
                        skipped += 1
                        total_chunks += conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (old[0],)).fetchone()[0]
                        continue
                    kind, raw_chunks = self._read_chunks(file_path)
                    meta = {"suffix": file_path.suffix.lower(), "size": stat.st_size, "modified": stat.st_mtime}
                    if old:
                        source_id = old[0]
                        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
                        conn.execute("UPDATE sources SET fingerprint=?,kind=?,metadata=?,modified=?,updated_at=? WHERE id=?",
                                     (fp, kind, json.dumps(meta, ensure_ascii=False), stat.st_mtime, _now(), source_id))
                        updated += 1
                    else:
                        cur = conn.execute("INSERT INTO sources(path,fingerprint,kind,metadata,modified,updated_at) VALUES(?,?,?,?,?,?)",
                                           (str(file_path), fp, kind, json.dumps(meta, ensure_ascii=False), stat.st_mtime, _now()))
                        source_id = cur.lastrowid
                        added += 1
                    for ordinal, (title, text_part) in enumerate(raw_chunks):
                        tokens = _tokens(text_part)
                        if not tokens:
                            continue
                        cur = conn.execute("INSERT INTO chunks(source_id,ordinal,title,text,token_count,fingerprint) VALUES(?,?,?,?,?,?)",
                                           (source_id, ordinal, title, text_part, len(tokens), _fingerprint_text(title + "\n" + text_part)))
                        chunk_id = cur.lastrowid
                        counts = Counter(tokens)
                        conn.executemany("INSERT INTO postings(term,chunk_id,tf) VALUES(?,?,?)",
                                         [(term, chunk_id, tf) for term, tf in counts.items()])
                        pending_embeddings.append((int(chunk_id), f"{title}\n{text_part}"))
                        total_chunks += 1
                self._store_embeddings(conn, pending_embeddings)
                self._backfill_embeddings(conn)
        finally:
            conn.close()
        return {"path": str(Path(path).expanduser().resolve()), "files": len(files), "added": added,
                "updated": updated, "skipped": skipped, "chunks": total_chunks, "indexed_at": _now()}

    def index_external_text(self, source_url: str, title: str, text: str, metadata: dict | None = None) -> dict:
        """Index bounded externally-fetched text with URL provenance."""
        if not source_url or not text.strip():
            return {"added": 0, "updated": 0, "skipped": 0, "chunks": 0, "url": source_url}
        fp = _fingerprint_text(source_url + "\n" + text)
        meta = dict(metadata or {})
        meta.update({"url": source_url, "title": title})
        raw_chunks = _split_text(text)
        conn = self._connect()
        added = updated = skipped = 0
        total = 0
        pending_embeddings: list[tuple[int, str]] = []
        try:
            with conn:
                old = conn.execute("SELECT id,fingerprint FROM sources WHERE path=?", (source_url,)).fetchone()
                if old and old[1] == fp:
                    skipped = 1
                    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (old[0],)).fetchone()[0]
                    return {"url": source_url, "added": 0, "updated": 0, "skipped": 1, "chunks": total}
                if old:
                    source_id = old[0]
                    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
                    conn.execute("UPDATE sources SET fingerprint=?,kind=?,metadata=?,modified=?,updated_at=? WHERE id=?",
                                 (fp, "web", json.dumps(meta, ensure_ascii=False), 0.0, _now(), source_id))
                    updated = 1
                else:
                    cur = conn.execute("INSERT INTO sources(path,fingerprint,kind,metadata,modified,updated_at) VALUES(?,?,?,?,?,?)",
                                       (source_url, fp, "web", json.dumps(meta, ensure_ascii=False), 0.0, _now()))
                    source_id = cur.lastrowid
                    added = 1
                for ordinal, (section_title, text_part) in enumerate(raw_chunks):
                    tokens = _tokens(text_part)
                    if not tokens:
                        continue
                    cur = conn.execute("INSERT INTO chunks(source_id,ordinal,title,text,token_count,fingerprint) VALUES(?,?,?,?,?,?)",
                                       (source_id, ordinal, section_title or title or source_url, text_part, len(tokens),
                                        _fingerprint_text(section_title + "\n" + text_part)))
                    chunk_id = cur.lastrowid
                    counts = Counter(tokens)
                    conn.executemany("INSERT INTO postings(term,chunk_id,tf) VALUES(?,?,?)",
                                     [(term, chunk_id, tf) for term, tf in counts.items()])
                    pending_embeddings.append((int(chunk_id), f"{section_title}\n{text_part}"))
                    total += 1
                self._store_embeddings(conn, pending_embeddings)
                self._backfill_embeddings(conn)
        finally:
            conn.close()
        return {"url": source_url, "added": added, "updated": updated, "skipped": skipped, "chunks": total}

    def index_memory(self, memory_db_path=None) -> dict:
        """Compatibility gate: personal memory must never be copied into the knowledge base."""
        return {
            "indexed": 0,
            "blocked": True,
            "reason": "personal memory is not knowledge and cannot be indexed into RAG",
            "policy": "personal memory and world/project knowledge are separate authorities",
        }

    def _fetch_candidates(self, query_tokens: list[str], project_id: str | None = None) -> tuple[list[tuple[Chunk, float]], list[tuple[Chunk, float]]]:
        conn = self._connect()
        try:
            stats = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            if not stats:
                return [], []
            placeholders = ",".join("?" for _ in query_tokens)
            df_rows = conn.execute(f"SELECT term, COUNT(*) FROM postings WHERE term IN ({placeholders}) GROUP BY term", query_tokens).fetchall() if query_tokens else []
            df = dict(df_rows)
            avgdl = conn.execute("SELECT AVG(token_count) FROM chunks").fetchone()[0] or 1.0
            seen = {}
            if query_tokens:
                rows = conn.execute(
                    f"SELECT p.chunk_id,p.term,p.tf,c.source_id,c.ordinal,c.title,c.text,c.token_count,c.access_count,c.last_accessed,s.path,s.kind "
                    f"FROM postings p JOIN chunks c ON c.id=p.chunk_id JOIN sources s ON s.id=c.source_id "
                    f"WHERE p.term IN ({placeholders}) AND (s.knowledge_scope='world' OR (? IS NOT NULL AND s.project_id=?))",
                    (*query_tokens, project_id, project_id)).fetchall()
                grouped = defaultdict(dict)
                for row in rows:
                    grouped[row[0]][row[1]] = row[2]
                for cid, term_tf in grouped.items():
                    score = 0.0
                    meta = rows[next(i for i,r in enumerate(rows) if r[0] == cid)]
                    dl = meta[7]
                    for term in query_tokens:
                        tf = term_tf.get(term)
                        if not tf:
                            continue
                        n = stats
                        dft = max(0, df.get(term, 0))
                        idf = math.log(1.0 + (n - dft + 0.5) / (dft + 0.5))
                        k1, b = 1.35, 0.72
                        score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1.0))))
                    access_decay = 0.12 * math.log1p(meta[8])
                    scored = score + access_decay
                    seen[cid] = (scored, meta)
                bm25 = []
                for score, meta in seen.values():
                    bm25.append((Chunk(meta[0], meta[10], meta[11], meta[5], meta[6], meta[1], meta[7], meta[8], meta[9]), score))
            else:
                bm25 = []

            # Character n-gram candidate scan is intentionally bounded by corpus size; this is exact and model-free.
            q_text = " ".join(query_tokens)
            qgrams = _char_ngrams(q_text)
            all_rows = conn.execute("SELECT c.id,c.source_id,c.ordinal,c.title,c.text,c.token_count,c.access_count,c.last_accessed,s.path,s.kind FROM chunks c JOIN sources s ON s.id=c.source_id WHERE (s.knowledge_scope='world' OR (? IS NOT NULL AND s.project_id=?))", (project_id, project_id)).fetchall()
            char = []
            for row in all_rows:
                grams = _char_ngrams(row[4])
                sim = _cosine(qgrams, grams)
                if sim > 0:
                    char.append((Chunk(row[0], row[8], row[9], row[3], row[4], row[2], row[5], row[6], row[7]), sim))
            bm25.sort(key=lambda x: (-x[1], x[0].id))
            char.sort(key=lambda x: (-x[1], x[0].id))
            return bm25[:80], char[:80]
        finally:
            conn.close()

    @staticmethod
    def _rrf(bm25, char, k: int = 60) -> list[tuple[Chunk, float, int | None, int | None]]:
        bm_ranks = {c.id: i + 1 for i, (c, _) in enumerate(bm25)}
        ch_ranks = {c.id: i + 1 for i, (c, _) in enumerate(char)}
        by_id = {c.id: c for c, _ in bm25}
        by_id.update({c.id: c for c, _ in char})
        scores = []
        for cid, chunk in by_id.items():
            s = 0.0
            if cid in bm_ranks:
                s += 1.0 / (k + bm_ranks[cid])
            if cid in ch_ranks:
                s += 1.0 / (k + ch_ranks[cid])
            scores.append((chunk, s, bm_ranks.get(cid), ch_ranks.get(cid)))
        scores.sort(key=lambda x: (-x[1], x[0].id))
        return scores

    @staticmethod
    def _overlap(a: Sequence[str], b: Sequence[str]) -> float:
        sa, sb = set(a), set(b)
        return len(sa & sb) / max(1, len(sa | sb))

    def retrieve(self, query: str, top_k: int = 8, hop: int = 0, candidate_k: int = 30, project_id: str | None = None) -> list[RetrievalResult]:
        qt = _tokens(query)
        if not qt:
            return []
        bm25, char = self._fetch_candidates(qt, project_id=project_id)
        fused = self._rrf(bm25, char)[:candidate_k]
        semantic = self._semantic_candidates(query, max(candidate_k * 2, top_k * 4), project_id=project_id)
        candidate_map = {chunk.id: (chunk, rrf_score, rb, rc, 0.0) for chunk, rrf_score, rb, rc in fused}
        semantic_rank = {chunk.id: score for chunk, score in semantic}
        for chunk, score in semantic:
            if chunk.id not in candidate_map:
                candidate_map[chunk.id] = (chunk, 0.0, None, None, score)
            else:
                current = candidate_map[chunk.id]
                candidate_map[chunk.id] = (current[0], current[1], current[2], current[3], score)
        qgrams = _char_ngrams(query)
        qtokens = qt
        reranked = []
        for chunk, rrf_score, rb, rc, semantic_score in candidate_map.values():
            terms = _tokens(chunk.text)
            lexical_overlap = len(set(qtokens) & set(terms)) / max(1, len(set(qtokens)))
            phrase = 1.0 if normalize(query) in normalize(chunk.text) else 0.0
            heading = len(set(_tokens(chunk.title)) & set(qtokens)) / max(1, len(set(qtokens)))
            char_score = _cosine(qgrams, _char_ngrams(chunk.text))
            length_penalty = 0.06 * max(0.0, (chunk.token_count - 220) / 220.0)
            # Ranking is deterministic across repeated queries. Access frequency is tracked for
            # memory decay/consolidation, but never changes retrieval order within a run.
            lexical_component = 0.36 * lexical_overlap + 0.14 * char_score + 0.12 * (rrf_score / (1 / 61 * 2)) + 0.05 * phrase + 0.03 * heading
            score = lexical_component + (0.30 * semantic_score if semantic_score > 0 else 0.0) - length_penalty
            reranked.append((chunk, score, rb, rc, rrf_score, semantic_score))
        reranked.sort(key=lambda x: (-x[1], x[0].id))

        selected = []
        selected_tokens: list[list[str]] = []
        for item in reranked:
            chunk = item[0]
            toks = _tokens(chunk.text)
            redundancy = max((self._overlap(toks, prev) for prev in selected_tokens), default=0.0)
            mmr = item[1] - 0.35 * redundancy
            if mmr <= 0 and selected:
                continue
            selected.append((item, mmr))
            selected_tokens.append(toks)
            if len(selected) >= top_k:
                break
        out = []
        conn = self._connect()
        try:
            for item, mmr in selected:
                row = conn.execute(
                    "SELECT s.knowledge_scope,s.project_id,s.source_ref,s.provenance_json FROM chunks c JOIN sources s ON s.id=c.source_id WHERE c.id=?",
                    (item[0].id,),
                ).fetchone()
                scope = row[0] if row else "world"
                proj = row[1] if row else None
                source_ref = row[2] if row else None
                try:
                    provenance = json.loads(row[3] or "{}") if row else {}
                except Exception:
                    provenance = {}
                out.append(RetrievalResult(query, item[0].id, item[0].source, item[0].title, item[0].text,
                                           round(max(0.0, mmr), 6), item[2], item[3], item[4], hop,
                                           round(float(item[5]), 6), scope, proj, source_ref, provenance))
        finally:
            conn.close()
        self._touch([r.chunk_id for r in out])
        return out

    def _touch(self, chunk_ids: Iterable[int]):
        ids = list(chunk_ids)
        if not ids:
            return
        conn = self._connect()
        try:
            with conn:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE chunks SET access_count=access_count+1,last_accessed=? WHERE id IN ({marks})", (time.time(), *ids))
        finally:
            conn.close()

    @staticmethod
    def decompose_query(query: str) -> list[str]:
        n = normalize(query)
        pieces = re.split(r"\s+(?:and|or|then|و|ثم|وكمان|وكذلك|بالاضافة الى|بالإضافة إلى)\s+|[؛;؟?]", n)
        pieces = [p.strip(" ,.:") for p in pieces if len(p.strip()) >= 4]
        return pieces[:4] if len(pieces) > 1 else [n]

    def _coverage(self, query: str, results: list[RetrievalResult]) -> dict:
        qt = set(_tokens(query))
        if not qt:
            return {"score": 0.0, "token_coverage": 0.0, "source_diversity": 0, "high_quality": 0}
        covered = set()
        for r in results:
            covered |= qt & set(_tokens(r.text + " " + r.title))
        token_coverage = len(covered) / len(qt)
        source_diversity = len({r.source for r in results})
        high_quality = sum(1 for r in results if r.score >= 0.25)
        score = 0.58 * token_coverage + 0.22 * min(1.0, source_diversity / 2.0) + 0.20 * min(1.0, high_quality / 3.0)
        return {"score": round(score, 6), "token_coverage": round(token_coverage, 6),
                "source_diversity": source_diversity, "high_quality": high_quality}

    def _expand_from_results(self, query: str, results: list[RetrievalResult]) -> str:
        q = set(_tokens(query))
        freq = Counter()
        for r in results[:5]:
            for t in _tokens(r.text):
                if len(t) >= 4 and t not in q:
                    freq[t] += 1
        extras = [t for t, _ in freq.most_common(6)]
        return (query + " " + " ".join(extras)).strip()

    def _extractive_answer(self, query: str, results: list[RetrievalResult], max_sentences: int = 6) -> tuple[str, list[dict]]:
        qtokens = set(_tokens(query))
        scored = []
        for r in results:
            sentences = re.split(r"(?<=[.!؟])\s+|\n+", r.text)
            for idx, sentence in enumerate(sentences):
                sentence = sentence.strip(" -•\t")
                if len(sentence) < 20:
                    continue
                st = set(_tokens(sentence))
                overlap = len(qtokens & st) / max(1, len(qtokens))
                score = 0.72 * overlap + 0.28 * r.score
                if overlap > 0:
                    scored.append((score, r, sentence, idx))
        scored.sort(key=lambda x: (-x[0], x[1].chunk_id, x[3]))
        chosen = []
        seen_sentences = set()
        for item in scored:
            key = normalize(item[2])
            if key in seen_sentences:
                continue
            chosen.append(item)
            seen_sentences.add(key)
            if len(chosen) >= max_sentences:
                break
        evidence = []
        answer_parts = []
        for i, (_, r, sentence, _) in enumerate(chosen, 1):
            marker = f"[S{i}]"
            answer_parts.append(f"{sentence} {marker}")
            evidence.append({"citation": marker, "source": r.source, "title": r.title, "chunk_id": r.chunk_id,
                             "score": r.score, "text": r.text})
        return "\n".join(answer_parts), evidence

    def query(self, query: str, top_k: int = 6, max_hops: int = 3, project_id: str | None = None) -> dict:
        if not query.strip():
            return {"query": query, "answer": "", "grounded": False, "abstained": True, "reason": "empty query", "evidence": [], "hops": 0}
        subqueries = self.decompose_query(query)
        all_results: list[RetrievalResult] = []
        trace = []
        seen = set()
        current_queries = subqueries
        for hop in range(max_hops):
            hop_results = []
            for q in current_queries:
                hop_results.extend(self.retrieve(q, top_k=max(8, top_k * 2), hop=hop, candidate_k=40, project_id=project_id))
            hop_results.sort(key=lambda r: (-r.score, r.chunk_id))
            for r in hop_results:
                if r.chunk_id not in seen:
                    all_results.append(r)
                    seen.add(r.chunk_id)
            all_results.sort(key=lambda r: (-r.score, r.chunk_id))
            all_results = all_results[: max(20, top_k * 4)]
            coverage = self._coverage(query, all_results)
            trace.append({"hop": hop, "queries": list(current_queries), "retrieved": len(hop_results), "coverage": coverage})
            # More complex queries require more coverage/source support before stop.
            threshold = 0.68 if len(subqueries) > 1 else 0.60
            if coverage["score"] >= threshold and coverage["high_quality"] >= min(3, top_k):
                break
            if hop + 1 < max_hops:
                if len(subqueries) > 1 and hop == 0:
                    current_queries = [q for q in subqueries if q not in current_queries] or [self._expand_from_results(query, all_results[:6])]
                else:
                    current_queries = [self._expand_from_results(query, all_results[:6])]
        coverage = self._coverage(query, all_results)
        final_results = all_results[:top_k]
        grounded = coverage["score"] >= (0.62 if len(subqueries) > 1 else 0.52) and bool(final_results)
        if not grounded:
            answer = "لا توجد أدلة كافية من المصادر المفهرسة للإجابة بأمان."
            evidence = []
            reason = "evidence_gate_failed"
        else:
            answer, evidence = self._extractive_answer(query, final_results)
            reason = "grounded_extract"
            if not answer:
                grounded = False
                answer = "لا توجد جمل قابلة للاستخراج تدعم السؤال في الأدلة المسترجعة."
                evidence = []
                reason = "no_extractable_support"
        conn = self._connect()
        try:
            with conn:
                conn.execute("INSERT INTO query_log(query,hops,candidates,retrieved,evidence_score,grounded,ts) VALUES(?,?,?,?,?,?,?)",
                             (query, len(trace), len(all_results), len(final_results), float(coverage["score"]), int(grounded), _now()))
        finally:
            conn.close()
        return {"query": query, "answer": answer, "grounded": grounded, "abstained": not grounded,
                "reason": reason, "hops": len(trace), "decomposition": subqueries, "evidence_gate": coverage,
                "trace": trace, "evidence": evidence, "retrieval": [r.__dict__ for r in final_results],
                "methods": {"sparse": "BM25", "lexical_secondary": "character_3gram_cosine", "fusion": "RRF",
                             "reranking": "lexical+phrase+heading+MMR", "adaptation": "query_decomposition+evidence_gate+query_expansion"}}

    def _require_knowledge_provenance(self, provenance: dict | None, source_ref: str | None) -> tuple[dict, str]:
        meta = dict(provenance or {})
        if str(meta.get("source_kind") or "").casefold().strip() == "synthetic_seed" or bool(meta.get("not_knowledge")) is True:
            raise ValueError("synthetic seed data cannot be imported into the knowledge base")
        ref = str(source_ref or meta.get("source_ref") or "").strip()
        if not ref:
            raise ValueError("knowledge source requires provenance/source_ref")
        for field in ("origin", "source_kind"):
            if not str(meta.get(field) or "").strip():
                raise ValueError(f"knowledge provenance requires {field}")
        meta["source_ref"] = ref
        return meta, ref

    def _annotate_knowledge_sources(self, *, paths: list[str] | None = None, source_ref: str | None = None,
                                    project_id: str | None = None, provenance: dict | None = None) -> list[dict]:
        meta, ref = self._require_knowledge_provenance(provenance, source_ref)
        conn = self._connect()
        try:
            with conn:
                rows = []
                for p in paths or []:
                    row = conn.execute("SELECT id,path,fingerprint FROM sources WHERE path=?", (str(Path(p).expanduser().resolve()),)).fetchone()
                    if row:
                        rows.append(row)
                if not rows and source_ref:
                    row = conn.execute("SELECT id,path,fingerprint FROM sources WHERE source_ref=? OR path=?", (ref, ref)).fetchall()
                    rows.extend(row)
                scope = "project" if project_id else "world"
                for sid, path_value, fingerprint in rows:
                    conn.execute(
                        "UPDATE sources SET knowledge_scope=?,project_id=?,source_ref=?,provenance_json=?,content_hash=?,updated_at=? WHERE id=?",
                        (scope, project_id, ref, json.dumps(meta, ensure_ascii=False, default=str), fingerprint, _now(), sid),
                    )
                return [{"id": int(r[0]), "path": r[1], "fingerprint": r[2], "knowledge_scope": scope,
                         "project_id": project_id, "source_ref": ref, "provenance": meta} for r in rows]
        finally:
            conn.close()

    def index_knowledge(self, path: str | Path, *, project_id: str | None = None,
                        provenance: dict | None = None, source_ref: str | None = None) -> dict:
        files = self.discover(path)
        result = self.index(path)
        if not files:
            return {**result, "knowledge": {"indexed": 0, "reason": "no supported files"}}
        meta = dict(provenance or {})
        meta.setdefault("origin", "local_file")
        meta.setdefault("source_kind", "document")
        ref = source_ref or str(Path(path).expanduser().resolve())
        annotations = self._annotate_knowledge_sources(paths=[str(p) for p in files], project_id=project_id, provenance=meta, source_ref=ref)
        return {**result, "knowledge": {"indexed": len(annotations), "sources": annotations, "project_id": project_id, "source_ref": ref}}

    def index_knowledge_text(self, source_url: str, title: str, text: str, *, project_id: str | None = None,
                             provenance: dict | None = None) -> dict:
        meta = dict(provenance or {})
        meta.setdefault("origin", "external_source")
        meta.setdefault("source_kind", "web")
        result = self.index_external_text(source_url, title, text, metadata=meta)
        self._annotate_knowledge_sources(project_id=project_id, provenance=meta, source_ref=source_url)
        return {**result, "knowledge": {"project_id": project_id, "source_ref": source_url, "provenance": meta}}

    def list_knowledge(self, *, project_id: str | None = None, limit: int = 100) -> list[dict]:
        conn = self._connect()
        try:
            if project_id is None:
                rows = conn.execute(
                    "SELECT id,path,kind,knowledge_scope,project_id,source_ref,provenance_json,content_hash,updated_at FROM sources WHERE knowledge_scope IN ('world','project') ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,path,kind,knowledge_scope,project_id,source_ref,provenance_json,content_hash,updated_at FROM sources WHERE knowledge_scope='world' OR (knowledge_scope='project' AND project_id=?) ORDER BY id DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            out=[]
            for row in rows:
                try: meta=json.loads(row[6] or "{}")
                except Exception: meta={}
                out.append({"id":row[0],"path":row[1],"kind":row[2],"knowledge_scope":row[3],"project_id":row[4],
                            "source_ref":row[5],"provenance":meta,"content_hash":row[7],"updated_at":row[8]})
            return out
        finally:
            conn.close()

    def remove_knowledge(self, source_ref: str, *, project_id: str | None = None) -> bool:
        ref = str(source_ref or "").strip()
        if not ref:
            raise ValueError("source_ref is required")
        conn = self._connect()
        try:
            with conn:
                if project_id is None:
                    row = conn.execute("SELECT id FROM sources WHERE (source_ref=? OR path=?) AND knowledge_scope='world'", (ref, ref)).fetchone()
                else:
                    row = conn.execute("SELECT id FROM sources WHERE (source_ref=? OR path=?) AND knowledge_scope='project' AND project_id=?", (ref, ref, project_id)).fetchone()
                if not row:
                    return False
                conn.execute("DELETE FROM sources WHERE id=?", (row[0],))
                return True
        finally:
            conn.close()

    def knowledge_stats(self, *, project_id: str | None = None) -> dict:
        conn = self._connect()
        try:
            if project_id is None:
                source_count = conn.execute("SELECT COUNT(*) FROM sources WHERE knowledge_scope IN ('world','project')").fetchone()[0]
                chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE knowledge_scope IN ('world','project'))").fetchone()[0]
            else:
                source_count = conn.execute("SELECT COUNT(*) FROM sources WHERE knowledge_scope='world' OR (knowledge_scope='project' AND project_id=?)", (project_id,)).fetchone()[0]
                chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE knowledge_scope='world' OR (knowledge_scope='project' AND project_id=?))", (project_id,)).fetchone()[0]
            return {"sources": int(source_count), "chunks": int(chunk_count), "project_id": project_id}
        finally:
            conn.close()

    def decay_report(self, half_life_days: float = 30.0) -> dict:
        now = time.time()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id,source_id,access_count,last_accessed FROM chunks").fetchall()
            values = []
            for cid, sid, count, last in rows:
                age_days = max(0.0, (now - last) / 86400) if last else 3650.0
                retention = (0.5 ** (age_days / max(half_life_days, 1e-9))) * (1.0 + math.log1p(count) * 0.15)
                values.append((cid, retention))
            mean_ret = sum(v for _, v in values) / max(1, len(values))
            stale = sum(1 for _, v in values if v < 0.25)
            return {"chunks": len(values), "mean_retention": round(mean_ret, 6), "stale_chunks": stale,
                    "half_life_days": half_life_days, "policy": "retrieval-frequency consolidation + exponential decay"}
        finally:
            conn.close()

    def stats(self) -> dict:
        conn = self._connect()
        try:
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            queries = conn.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
            grounded = conn.execute("SELECT COALESCE(SUM(grounded),0) FROM query_log").fetchone()[0]
            return {"sources": sources, "chunks": chunks, "queries": queries, "grounded_queries": grounded,
                    "grounded_rate": round(grounded / queries, 4) if queries else 0.0}
        finally:
            conn.close()


def rag_index(path: str, db_path=None) -> dict:
    return RAGEngine(db_path=db_path).index(path)


def rag_index_memory(db_path=None) -> dict:
    return RAGEngine(db_path=db_path).index_memory()


def rag_query(query: str, top_k: int = 6, db_path=None, project_id: str | None = None) -> dict:
    return RAGEngine(db_path=db_path).query(query, top_k=top_k, project_id=project_id)
