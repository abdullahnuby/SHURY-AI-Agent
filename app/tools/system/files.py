"""Workspace file tools. لا تُكتشف تلقائيًا بواسطة الـRulePlanner؛ تُستخدم فقط عبر المسارات الصريحة المناسبة.
كل المسارات محبوسة جوه الـworkspace (AGENT_WORKSPACE أو ./workspace). الكتابة بموافقة.
"""
import os
from pathlib import Path

from app.runtime.registry import tool

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "workspace"
MAX_READ_BYTES = 1_000_000
MAX_READ_CHARS = 3_500   # لازم يتماشى مع MAX_OBS_CHARS في react.py
MAX_WRITE_CHARS = 200_000
MAX_LIST = 200


def workspace_root() -> Path:
    root = Path(os.environ.get("AGENT_WORKSPACE") or DEFAULT_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_path(rel: str) -> Path:
    root = workspace_root()
    raw = str(rel)
    # User-facing task paths often name the workspace root explicitly (e.g.
    # `workspace/report.md`). AGENT_WORKSPACE already points at that root, so normalize
    # one leading workspace component instead of creating workspace/workspace/*.
    if not Path(raw).is_absolute():
        normalized = raw.replace("\\", "/").lstrip("/")
        if normalized.casefold() == "workspace":
            raw = "."
        elif normalized.casefold().startswith("workspace/"):
            raw = normalized.split("/", 1)[1]
    p = (root / raw).resolve()   # resolve بيحل symlinks و".." والمسارات المطلقة
    if p != root and root not in p.parents:
        raise ValueError("المسار برة الـworkspace")
    return p


_safe = safe_path  # alias للتوافق

_common = dict(stage=0, match=lambda g: False, capability="workspace_files")
_read_common = {k: v for k, v in _common.items() if k != "capability"}


@tool(description="يعرض محتويات مجلد جوه الـworkspace (استخدم '.' للجذر)",
      params={"path": "مسار نسبي، '.' للجذر"}, cost=0.5, produces=("workspace_snapshot_observed",), verification_level="standard", organization_department="operations", organization_role="operations:file-specialist", **_common)
def list_files(path: str):
    p = safe_path(path)
    if not p.is_dir():
        raise ValueError("مش مجلد")
    rows = []
    for x in sorted(p.iterdir())[:MAX_LIST]:
        rows.append({"name": x.name, "type": "dir" if x.is_dir() else "file",
                     "bytes": x.stat().st_size if x.is_file() else None})
    return rows

@tool(description="يفحص الـworkspace بشكل recursive ويعيد snapshot بكل الملفات داخل المجلدات الفرعية، مع إمكانية استبعاد مسار تقرير محدد",
      params={"path": "مسار نسبي، './' للجذر", "exclude_path": "مسار ملف اختياري يستبعد من snapshot"},
      cost=1.0, produces=("workspace_recursive_snapshot_observed",), verification_level="strong", organization_department="operations", organization_role="operations:file-specialist", **_common)
def list_files_recursive(path: str = ".", exclude_path: str = ""):
    root = safe_path(path)
    if not root.is_dir():
        raise ValueError("مش مجلد")
    excluded = safe_path(exclude_path) if str(exclude_path).strip() else None
    rows: list[dict] = []
    for current, dirs, files in os.walk(root):
        dirs.sort(); files.sort()
        current_path = Path(current)
        for name in files:
            file_path = current_path / name
            if excluded is not None and file_path.resolve() == excluded.resolve():
                continue
            rel = file_path.relative_to(workspace_root()).as_posix()
            rows.append({
                "name": rel,
                "type": "file",
                "bytes": file_path.stat().st_size,
                "suffix": file_path.suffix.casefold(),
            })
            if len(rows) >= MAX_LIST * 100:
                raise ValueError("عدد الملفات recursive يتجاوز الحد الآمن")
    return rows


def _read_text(path: str) -> tuple[Path, str]:
    p = safe_path(path)
    if not p.is_file():
        raise ValueError("الملف مش موجود")
    if p.stat().st_size > MAX_READ_BYTES:
        raise ValueError("الملف أكبر من الحد المسموح")
    return p, p.read_text(encoding="utf-8", errors="replace")


def _chunk(p: Path, text: str, start: int) -> dict:
    end = min(len(text), start + MAX_READ_CHARS)
    # Workspace-relative paths are part of cross-tool contracts. Keep them
    # platform-independent so Windows ``\\`` does not disagree with tools
    # such as move_workspace_report that already emit POSIX separators.
    relative_path = p.relative_to(workspace_root()).as_posix()
    return {"path": relative_path, "total_chars": len(text), "line_count": len(text.splitlines()), "start": start,
            "end": end, "content": text[start:end],
            "next_start": end if end < len(text) else None}   # None = وصلت لآخر الملف


@tool(description="يقرا بداية ملف نصي (أول 3500 حرف). لو next_start مش null كمل بـread_file_part أو دور بـsearch_in_file",
      params={"path": "مسار الملف النسبي"}, cost=0.5, capability="file_read", organization_department="operations", organization_role="operations:file-specialist", **_read_common)
def read_file(path: str):
    p, text = _read_text(path)
    return _chunk(p, text, 0)


@tool(description="يقرا جزء من ملف نصي ابتداءً من موضع حرف معين (استخدم next_start من القراءة السابقة)",
      params={"path": "مسار الملف النسبي", "start": "رقم الحرف اللي تبدأ منه (عدد صحيح)"}, cost=0.5, **_common)
def read_file_part(path: str, start: int):
    p, text = _read_text(path)
    start = int(start)
    if start < 0 or start >= max(len(text), 1):
        raise ValueError(f"start خارج نطاق الملف (طوله {len(text)} حرف)")
    return _chunk(p, text, start)


@tool(description="يدور على نص داخل ملف ويرجع السطور المطابقة بأرقامها (grep). مفيد للملفات الكبيرة",
      params={"path": "مسار الملف النسبي", "query": "النص المطلوب"}, cost=0.5, **_common)
def search_in_file(path: str, query: str):
    if not str(query).strip():
        raise ValueError("query فاضي")
    _, text = _read_text(path)
    q, hits = str(query).casefold(), []
    for i, line in enumerate(text.splitlines(), 1):
        if q in line.casefold():
            hits.append({"line": i, "text": line[:300]})
            if len(hits) >= 20:
                break
    return {"query": query, "matches": hits, "capped": len(hits) >= 20}


@tool(description="يكتب/يستبدل ملف نصي في الـworkspace (بموافقة)",
      params={"path": "مسار الملف النسبي", "content": "المحتوى"},
      requires_approval=True, risk="medium", cost=1.5, **_common)
def write_file(path: str, content: str):
    if len(content) > MAX_WRITE_CHARS:
        raise ValueError("المحتوى أكبر من الحد المسموح")
    p = safe_path(path)
    if p == workspace_root() or p.is_dir():
        raise ValueError("المسار مجلد")
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"path": str(p.relative_to(workspace_root())), "bytes": len(content.encode("utf-8")),
            "overwrote": existed}


def _inventory_output_path(goal: str) -> str:
    import re
    matches = list(re.finditer(r'[^\s,;!?؟]+\.(?:md|txt)\b', str(goal or ''), re.I))
    return matches[-1].group(0).strip(" \t,.;!?؟") if matches else "file_inventory.md"


def _inventory_to_markdown(rows: list[dict]) -> str:
    lines = [
        "# Workspace File Inventory",
        "",
        f"Total entries: **{len(rows)}**",
        "",
        "| Name | Type | Size (bytes) |",
        "|---|---|---:|",
    ]
    for row in rows:
        size = "" if row.get("bytes") is None else str(row.get("bytes"))
        lines.append(f"| {row.get('name','')} | {row.get('type','')} | {size} |")
    lines.extend(["", "## Verification", "", "The inventory was generated from one observed workspace snapshot and re-read from disk after creation.", ""])
    return "\n".join(lines)


@tool(
    "ينشئ جردًا حقيقيًا لملفات الـworkspace من snapshot مرصود ثم يعيد قراءة التقرير والتحقق من مطابقته",
    params={"file_list": "snapshot list من list_files", "output_path": "مسار تقرير الجرد"},
    name="create_file_inventory",
    cost=1.5,
    requires_approval=True,
    risk="medium",
    capability="workspace_inventory",
    produces=("workspace_inventory_created", "workspace_inventory_verified"),
    verification_level="strong",
    pipe_param="file_list",
    build_args=lambda g: {"output_path": _inventory_output_path(g)},
)
def create_file_inventory(file_list: list[dict], output_path: str):
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن يكون snapshot قائمة ملفات")
    target = safe_path(output_path)
    root = workspace_root()
    if target == root or target.is_dir():
        raise ValueError("مسار التقرير يجب أن يكون ملفًا داخل الـworkspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    content = _inventory_to_markdown(file_list)
    target.write_text(content, encoding="utf-8")
    reread = target.read_text(encoding="utf-8")
    body_lines = [line for line in reread.splitlines() if line.startswith("|") and not line.startswith("|---") and " Name " not in line]
    # Header + data rows: count data rows after excluding header.
    data_rows = len(body_lines)
    verified = (
        target.is_file()
        and "# Workspace File Inventory" in reread
        and "## Verification" in reread
        and data_rows == len(file_list)
    )
    if not verified:
        raise ValueError(f"فشل تحقق جرد workspace: snapshot={len(file_list)} report_rows={data_rows}")
    return {
        "path": str(target.relative_to(root)),
        "file_count": len(file_list),
        "verified": True,
        "snapshot": file_list,
    }


def _tree_folder_stats(rows: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for row in rows:
        rel = str(row.get("name") or "")
        parts = Path(rel).parts
        size = int(row.get("bytes") or 0)
        file_type = Path(rel).suffix.casefold() or "[no extension]"
        parent_parts = parts[:-1]
        # Every ancestor gets recursive file count/bytes/type set.
        for i in range(len(parent_parts) + 1):
            folder = Path(*parent_parts[:i]).as_posix() if i else "."
            item = stats.setdefault(folder, {"file_count": 0, "bytes": 0, "types": set()})
            item["file_count"] += 1
            item["bytes"] += size
            item["types"].add(file_type)
    return stats


def _workspace_tree_inventory_markdown(report: dict) -> str:
    lines = [
        "# Workspace Recursive Inventory", "",
        f"Snapshot files: **{report['file_count']}**",
        f"Snapshot bytes: **{report['total_bytes']}**",
        f"Excluded report: `{report['excluded_report']}`", "",
        "## Folder Statistics", "",
        "| Folder | Files (recursive) | Bytes (recursive) | Types |",
        "|---|---:|---:|---|",
    ]
    for folder in sorted(report["folder_stats"]):
        item = report["folder_stats"][folder]
        types = ", ".join(item["types"])
        lines.append(f"| {folder} | {item['file_count']} | {item['bytes']} | {types} |")
    lines.extend(["", "## Largest 5 Files", "", "| Rank | Path | Bytes | Type |", "|---:|---|---:|---|"])
    for rank, row in enumerate(report["largest_5"], 1):
        lines.append(f"| {rank} | {row['name']} | {row['bytes']} | {row['suffix'] or '[no extension]'} |")
    lines.extend(["", "## Verification", "",
                   f"Snapshot fingerprint: **{report['snapshot_fingerprint']}**",
                   f"Current filesystem matches snapshot: **{str(report['filesystem_match']).lower()}**",
                   f"Folder statistics match: **{str(report['folder_stats_match']).lower()}**",
                   f"Largest 5 match: **{str(report['largest_5_match']).lower()}**",
                   f"Report excluded from source statistics: **{str(report['report_excluded']).lower()}**", "",
                   "The report was created after the source snapshot and is excluded from the source statistics.", ""])
    return "\n".join(lines)


@tool(description="ينشئ جردًا recursive للـworkspace مع إحصاءات كل مجلد وأكبر الملفات، ثم يعيد قراءته ويتحقق منه مقابل filesystem الفعلي",
      params={"file_list": "snapshot recursive من list_files_recursive", "output_path": "مسار التقرير"},
      name="create_workspace_tree_inventory", cost=2.0, requires_approval=True, risk="medium",
      capability="workspace_recursive_inventory", produces=("workspace_tree_inventory_created", "workspace_tree_inventory_verified"),
      verification_level="strong", pipe_param="file_list",
      build_args=lambda g: {"output_path": _inventory_output_path(g)})
def create_workspace_tree_inventory(file_list: list[dict], output_path: str):
    import hashlib, json
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن يكون snapshot recursive")
    root = workspace_root()
    target = safe_path(output_path)
    excluded_rel = target.relative_to(root).as_posix()
    rows = [r for r in file_list if isinstance(r, dict) and r.get("type") == "file" and str(r.get("name") or "") != excluded_rel]
    snapshot_payload = [{"name": r["name"], "bytes": int(r.get("bytes") or 0), "suffix": str(r.get("suffix") or Path(r["name"]).suffix.casefold())} for r in rows]
    snapshot_fingerprint = hashlib.sha256(json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    before_hashes = {str(r["name"]): hashlib.sha256(safe_path(str(r["name"])).read_bytes()).hexdigest() for r in rows}
    def derive(current_rows):
        folder_stats = _tree_folder_stats(current_rows)
        largest = sorted(current_rows, key=lambda r: (-int(r.get("bytes") or 0), str(r.get("name") or "")))[:5]
        return {
            "file_count": len(current_rows),
            "total_bytes": sum(int(r.get("bytes") or 0) for r in current_rows),
            "folder_stats": folder_stats,
            "largest_5": largest,
        }
    expected = derive(rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {
        **expected, "excluded_report": excluded_rel, "snapshot_fingerprint": snapshot_fingerprint,
        "filesystem_match": False, "folder_stats_match": False, "largest_5_match": False, "report_excluded": True,
    }
    # Verify that no source content changed and no observed file disappeared/appeared, excluding the report itself.
    current = []
    for current_path in root.rglob("*"):
        if not current_path.is_file() or current_path.resolve() == target.resolve():
            continue
        rel = current_path.relative_to(root).as_posix()
        current.append({"name": rel, "type": "file", "bytes": current_path.stat().st_size, "suffix": current_path.suffix.casefold()})
    current = sorted(current, key=lambda r: str(r["name"]))
    expected_sorted = sorted(snapshot_payload, key=lambda r: str(r["name"]))
    current_sorted = sorted([{"name": r["name"], "bytes": int(r["bytes"]), "suffix": str(r.get("suffix") or Path(r["name"]).suffix.casefold())} for r in current], key=lambda r: str(r["name"]))
    fs_match = expected_sorted == current_sorted and all(hashlib.sha256(safe_path(name).read_bytes()).hexdigest() == digest for name, digest in before_hashes.items())
    actual = derive(current)
    folder_match = actual["folder_stats"] == expected["folder_stats"]
    largest_match = actual["largest_5"] == expected["largest_5"]
    report["filesystem_match"] = fs_match
    report["folder_stats_match"] = folder_match
    report["largest_5_match"] = largest_match
    content = _workspace_tree_inventory_markdown(report)
    target.write_text(content, encoding="utf-8")
    reread = target.read_text(encoding="utf-8")
    verified = all((target.is_file(), "# Workspace Recursive Inventory" in reread, "## Folder Statistics" in reread, "## Largest 5 Files" in reread, "## Verification" in reread, fs_match, folder_match, largest_match, report["report_excluded"]))
    if not verified:
        raise ValueError("فشل تحقق الجرد recursive مقابل filesystem الفعلي")
    report["path"] = str(target.relative_to(root))
    report["verified"] = True
    report["report_reread_verified"] = True
    return report



def _duplicate_cleanup_markdown(report: dict) -> str:
    lines = [
        "# Workspace Duplicate Cleanup Report", "",
        f"Original files: **{report['original_file_count']}**",
        f"Files moved: **{report['moved_file_count']}**",
        f"Active source files after operation: **{report['final_file_count']}**",
        f"Files archived: **{report['archived_file_count']}**",
        f"Managed files preserved after operation: **{report['workspace_managed_file_count_after']}**",
        f"Unique content groups before: **{report['unique_content_count_before']}**",
        f"Unique content groups after: **{report['unique_content_count_after']}**",
        f"Archive: `{report['archive']}`",
        "",
        "## Duplicate Groups", "",
        "| SHA-256 | Copies | Kept | Moved |", "|---|---:|---|---|",
    ]
    for group in report['duplicate_groups']:
        moved = ", ".join(x['destination'] for x in group['moved']) or "—"
        lines.append(f"| `{group['sha256']}` | {group['count']} | {group['kept']} | {moved} |")
    lines.extend([
        "", "## Verification", "",
        f"Moved files exist in archive: **{str(report['all_moved_exist']).lower()}**",
        f"Moved fingerprints preserved: **{str(report['all_moved_fingerprints_match']).lower()}**",
        f"Unique content count preserved: **{str(report['unique_content_count_preserved']).lower()}**",
        f"Kept copies remain present: **{str(report['kept_copies_present']).lower()}**",
        f"No file was deleted; cleanup used move-only operations: **{str(report['no_files_deleted']).lower()}**",
        f"No existing file replaced: **{str(report['no_files_replaced']).lower()}**",
        f"Source snapshot fingerprint: `{report['source_snapshot_fingerprint']}`",
        "", "The cleanup keeps one canonical copy in its original location and moves only duplicate copies into the archive without deleting files.", "",
    ])
    return "\n".join(lines)


@tool(
    "يكشف الملفات المتطابقة حسب SHA-256 من snapshot recursive ثم يحتفظ بنسخة واحدة وينقل النسخ الزائدة إلى archive آمن مع التحقق من سلامة المحتوى وعدم فقد أي ملف",
    params={"file_list": "snapshot recursive فعلي للملفات", "output_path": "مسار تقرير التنظيف", "archive_path": "مسار مجلد أرشيف النسخ الزائدة"},
    name="deduplicate_workspace_files",
    requires_approval=True,
    risk="high",
    cost=4.0,
    idempotent=False,
    capability="workspace_duplicate_cleanup",
    produces=("workspace_duplicates_detected", "workspace_duplicates_archived", "workspace_duplicate_cleanup_verified"),
    verification_level="strong",
    pipe_param="file_list",
)
def deduplicate_workspace_files(file_list: list[dict], output_path: str = "duplicate_cleanup_report.md", archive_path: str = "duplicates_archive"):
    import hashlib, json, shutil
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن يكون snapshot قائمة ملفات")
    root = workspace_root()
    report_target = safe_path(output_path)
    archive = safe_path(archive_path)
    if report_target == root or report_target.is_dir():
        raise ValueError("مسار التقرير يجب أن يكون ملفًا داخل الـworkspace")
    if archive == root or archive.is_file():
        raise ValueError("مسار الأرشيف يجب أن يكون مجلدًا داخل الـworkspace")

    def _live_snapshot() -> list[dict]:
        live: list[dict] = []
        for current, dirs, files in os.walk(root):
            dirs.sort(); files.sort()
            current_path = Path(current)
            for name in files:
                path = current_path / name
                if path.resolve() == report_target.resolve():
                    continue
                try:
                    rel = path.relative_to(root).as_posix()
                except ValueError:
                    continue
                if archive.resolve() == path.resolve() or archive.resolve() in path.resolve().parents:
                    continue
                data = path.read_bytes()
                live.append({
                    "name": rel,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
        live.sort(key=lambda r: r["name"])
        return live

    # Treat the caller's snapshot as observed evidence, but never as the source of truth.
    # Rebuild a live snapshot so duplicate detection cannot silently miss files because
    # of stale, shallow, or incorrectly rooted metadata.
    observed = []
    for r in file_list:
        if not isinstance(r, dict) or r.get("type") != "file":
            continue
        name = str(r.get("name") or "").strip().replace("\\", "/")
        if not name:
            continue
        source = safe_path(name)
        if report_target.resolve() == source.resolve() or archive.resolve() in source.resolve().parents:
            continue
        observed.append({"name": name, "bytes": int(r.get("bytes") or 0)})
    observed.sort(key=lambda r: r["name"])
    rows = _live_snapshot()
    observed_index = {(r["name"], int(r["bytes"])) for r in observed}
    live_index = {(r["name"], int(r["bytes"])) for r in rows}
    snapshot_matches_live = observed_index == live_index
    if not snapshot_matches_live:
        missing = sorted(live_index - observed_index)[:10]
        stale = sorted(observed_index - live_index)[:10]
        raise ValueError(f"الـsnapshot لا يطابق حالة filesystem الحالية؛ missing={missing}; stale={stale}")
    unique_before = {r["sha256"] for r in rows}
    source_snapshot_fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    groups = {}
    for row in rows:
        groups.setdefault(row["sha256"], []).append(row)
    duplicate_groups = []
    moves = []
    archive.mkdir(parents=True, exist_ok=True)
    used_dests = set()
    for digest, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        kept = members[0]["name"]
        group_moves = []
        for row in members[1:]:
            source = safe_path(row["name"])
            dest = _unique_destination(archive / Path(row["name"]).name)
            # Avoid collisions from multiple same-basename duplicates in one run.
            while dest.as_posix() in used_dests or dest.exists():
                dest = _unique_destination(dest.with_name(f"{dest.stem}__copy{len(used_dests)+2}{dest.suffix}"))
            used_dests.add(dest.as_posix())
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            shutil.move(str(source), str(dest))
            after = hashlib.sha256(dest.read_bytes()).hexdigest()
            item = {"source": row["name"], "destination": str(dest.relative_to(root)).replace("\\", "/"), "sha256_before": before, "sha256_after": after, "fingerprint_match": before == after}
            group_moves.append(item); moves.append(item)
        duplicate_groups.append({"sha256": digest, "count": len(members), "kept": kept, "moved": group_moves})

    current_files = []
    # Verify the same managed source scope used by the pre-operation snapshot:
    # exclude the generated report and the archive destination itself. Existing
    # archive contents are retained but are not re-counted as source files on
    # repeated runs.
    for current in root.rglob("*"):
        if not current.is_file():
            continue
        resolved = current.resolve()
        if resolved == report_target.resolve():
            continue
        if resolved == archive.resolve() or archive.resolve() in resolved.parents:
            continue
        rel = current.relative_to(root).as_posix()
        current_files.append((rel, hashlib.sha256(current.read_bytes()).hexdigest()))
    current_files.sort()
    final_file_count = len(current_files)
    unique_after = {digest for _, digest in current_files}

    all_moved_exist = all(safe_path(item["destination"]).is_file() for item in moves)
    all_moved_fingerprints_match = bool(moves) and all(item["fingerprint_match"] for item in moves) if moves else True
    unique_content_count_preserved = len(unique_before) == len(unique_after)
    kept_copies_present = all(safe_path(g["kept"]).is_file() and hashlib.sha256(safe_path(g["kept"]).read_bytes()).hexdigest() == g["sha256"] for g in duplicate_groups)
    # The active source scope shrinks by exactly the number of moved duplicates;
    # the moved files still exist in the archive, so this is not a deletion.
    no_files_deleted = (
        all(not safe_path(item["source"]).exists() for item in moves)
        and (final_file_count + len(moves) == len(rows))
    )
    no_files_replaced = all(not (item["source"] == item["destination"]) for item in moves)
    expected_archived = len(moves)
    verified = (
        all_moved_exist and all_moved_fingerprints_match and unique_content_count_preserved
        and kept_copies_present and no_files_deleted and no_files_replaced
        and final_file_count + len(moves) == len(rows)
        and expected_archived == sum(max(0, len(v) - 1) for v in groups.values())
    )
    if not verified:
        raise ValueError("فشل تحقق تنظيف النسخ المتطابقة")

    report = {
        "path": str(report_target.relative_to(root)).replace("\\", "/"),
        "archive": str(archive.relative_to(root)).replace("\\", "/"),
        "original_file_count": len(rows),
        "moved_file_count": len(moves),
        "final_file_count": final_file_count,
        "archived_file_count": len(moves),
        "workspace_managed_file_count_after": final_file_count + len(moves),
        "unique_content_count_before": len(unique_before),
        "unique_content_count_after": len(unique_after),
        "unique_content_count_preserved": unique_content_count_preserved,
        "duplicate_groups": duplicate_groups,
        "duplicate_group_count": len(duplicate_groups),
        "all_moved_exist": all_moved_exist,
        "all_moved_fingerprints_match": all_moved_fingerprints_match,
        "kept_copies_present": kept_copies_present,
        "no_files_deleted": no_files_deleted,
        "no_files_replaced": no_files_replaced,
        "source_snapshot_fingerprint": source_snapshot_fingerprint,
        "snapshot_matches_live": snapshot_matches_live,
        "verified": True,
        "report_reread_verified": False,
    }
    report_target.parent.mkdir(parents=True, exist_ok=True)
    report_target.write_text(_duplicate_cleanup_markdown(report), encoding="utf-8")
    reread = report_target.read_text(encoding="utf-8")
    report["report_reread_verified"] = all(marker in reread for marker in ("# Workspace Duplicate Cleanup Report", "## Duplicate Groups", "## Verification"))
    if not report["report_reread_verified"]:
        raise ValueError("تعذر إعادة قراءة تقرير تنظيف النسخ المتطابقة")
    return report


_CATEGORY_EXTENSIONS = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tif", ".tiff"},
    "documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
    "data": {".csv", ".xlsx", ".xls", ".json", ".xml", ".parquet", ".sqlite", ".sqlite3", ".db"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"},
    "archives": {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2"},
    "code": {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".java", ".cs", ".cpp", ".c", ".h", ".hpp", ".sql", ".sh", ".ps1"},
}


def _file_category(name: str) -> str:
    suffix = Path(str(name)).suffix.casefold()
    for category, extensions in _CATEGORY_EXTENSIONS.items():
        if suffix in extensions:
            return category
    return "other"


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 10_000):
        candidate = path.with_name(f"{stem}__{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"تعذر إيجاد اسم آمن بدون استبدال: {path.name}")


def _organization_markdown(report: dict) -> str:
    lines = [
        "# Workspace File Organization",
        "",
        f"Original files: **{report['original_file_count']}**",
        f"Moved files: **{report['moved_file_count']}**",
        f"Categories created: **{report['categories_created']}**",
        "",
        "## Classification",
        "",
        "| Original | Category | Destination |",
        "|---|---|---|",
    ]
    for row in report['moves']:
        lines.append(f"| {row['source']} | {row['category']} | {row['destination']} |")
    lines.extend(["", "## Verification", "",
                   f"Source snapshot files: **{report['original_file_count']}**",
                   f"Successfully moved: **{report['moved_file_count']}**",
                   f"Verified destinations: **{report['verified_destination_count']}**",
                   f"Fingerprint preserved for every moved file: **{str(report['all_fingerprints_match']).lower()}**",
                   f"No source files left at the original location: **{str(report['sources_cleared']).lower()}**",
                   "", "The organization was derived from the observed file snapshot; unknown extensions are placed in `other`.", ""])
    return "\n".join(lines)


@tool(
    "ينظم ملفات الـworkspace حسب نوعها من snapshot فعلي، بدون استبدال ملفات، ثم يتحقق من النقل وسلامة كل ملف ويكتب تقريرًا",
    params={"file_list": "snapshot من list_files", "output_path": "مسار تقرير التنظيم"},
    name="organize_workspace_files",
    requires_approval=True,
    risk="high",
    cost=3.0,
    idempotent=False,
    capability="workspace_file_organization",
    produces=("workspace_files_organized", "workspace_organization_verified"),
    verification_level="strong",
    pipe_param="file_list",
)
def organize_workspace_files(file_list: list[dict], output_path: str = "file_organization_report.md"):
    if not isinstance(file_list, list):
        raise ValueError("file_list يجب أن يكون snapshot قائمة ملفات")
    root = workspace_root()
    report_target = safe_path(output_path)
    if report_target == root or report_target.is_dir():
        raise ValueError("مسار التقرير يجب أن يكون ملفًا داخل الـworkspace")

    # Work only from the observed snapshot. Do not discover new files after execution begins.
    file_rows = [r for r in file_list if isinstance(r, dict) and r.get("type") == "file"]
    moves=[]
    for row in file_rows:
        name=str(row.get("name") or "").strip()
        if not name:
            continue
        source=safe_path(name)
        if not source.is_file():
            raise ValueError(f"الملف المرصود لم يعد موجودًا: {name}")
        category=_file_category(name)
        directory=root/category
        directory.mkdir(parents=True, exist_ok=True)
        dest=_unique_destination(directory/source.name)
        moves.append({"source": name, "category": category, "destination": str(dest.relative_to(root))})

    imported_hashes=[]
    for row in moves:
        source=safe_path(row['source'])
        dest=safe_path(row['destination'])
        import hashlib, shutil
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.move(str(source), str(dest))
        after=hashlib.sha256(dest.read_bytes()).hexdigest()
        row["sha256_before"]=before
        row["sha256_after"]=after
        row["fingerprint_match"]=before==after
        imported_hashes.append(row["fingerprint_match"])

    verified_dest=0
    for row in moves:
        if safe_path(row['destination']).is_file() and row['fingerprint_match']:
            verified_dest += 1
    sources_cleared=all(not safe_path(row['source']).exists() for row in moves)
    all_match=bool(moves) and all(imported_hashes) if moves else True
    expected_files=len(file_rows)
    observed_dest_files=sum(1 for category in {row["category"] for row in moves}
                            if (root/category).is_dir()
                            for x in (root/category).iterdir() if x.is_file()) if expected_files else 0
    # Count only moved file destinations for exact source/destination conservation.
    destination_set={row['destination'] for row in moves}
    destination_count=sum(1 for rel in destination_set if safe_path(rel).is_file())
    verified=(
        destination_count == expected_files
        and verified_dest == expected_files
        and sources_cleared
        and all_match
    )
    if not verified:
        raise ValueError(f"فشل تحقق تنظيم الملفات: source={expected_files} destination={destination_count} verified={verified_dest}")

    report={
        "original_file_count": expected_files,
        "moved_file_count": len(moves),
        "categories_created": len({row['category'] for row in moves}),
        "verified_destination_count": verified_dest,
        "all_fingerprints_match": all_match,
        "sources_cleared": sources_cleared,
        "moves": moves,
        "verified": True,
    }
    report_target.parent.mkdir(parents=True, exist_ok=True)
    report_target.write_text(_organization_markdown(report), encoding='utf-8')
    reread=report_target.read_text(encoding='utf-8')
    if "# Workspace File Organization" not in reread or "## Verification" not in reread:
        raise ValueError("تقرير تنظيم الملفات لم يُكتب بشكل صحيح")
    report["path"]=str(report_target.relative_to(root))
    report["report_reread_verified"]=True
    return report


@tool(
    "ينقل ملفًا واحدًا اختارته مهمة من قسم آخر إلى مجلد معالجة آمن بدون استبدال، مع SHA-256 قبل وبعد",
    {"analysis_result": "ناتج التحليل الذي يحتوي selected_path", "destination_dir": "مجلد الوجهة"},
    name="move_workspace_file",
    organization_department="operations",
    organization_role="operations:file-specialist",
    requires_approval=True,
    risk="high",
    cost=2.0,
    idempotent=False,
    capability="cross_department_data_move",
    produces=("workspace_file_moved",),
    verification_level="strong",
    pipe_param="analysis_result",
)
def move_workspace_file(analysis_result: dict, destination_dir: str):
    import hashlib, shutil
    if not isinstance(analysis_result, dict) or not analysis_result.get("selected_path"):
        raise ValueError("analysis_result لا يحتوي ملفًا مختارًا")
    root=workspace_root()
    source_rel=str(analysis_result["selected_path"])
    source=safe_path(source_rel)
    if not source.is_file():
        raise ValueError(f"الملف المختار غير موجود: {source_rel}")
    dest_dir=safe_path(destination_dir)
    if dest_dir == root or dest_dir.is_file():
        raise ValueError("destination_dir يجب أن يكون مجلدًا داخل workspace")
    dest_dir.mkdir(parents=True, exist_ok=True)
    snapshot = analysis_result.get("source_snapshot") or []
    before_other = {}
    for item in snapshot:
        rel = str(item.get("name") or "") if isinstance(item, dict) else ""
        if not rel or rel == source_rel:
            continue
        path = safe_path(rel)
        if path.is_file():
            before_other[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    dest=_unique_destination(dest_dir/source.name)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.move(str(source), str(dest))
    after=hashlib.sha256(dest.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("فشل تحقق fingerprint بعد النقل")
    after_other = {}
    for rel, before_hash in before_other.items():
        path = safe_path(rel)
        if not path.is_file():
            raise ValueError(f"ملف غير محدد اختفى أثناء النقل: {rel}")
        after_other[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    unchanged_files_verified = before_other == after_other
    if not unchanged_files_verified:
        raise ValueError("فشل تحقق سلامة الملفات الأخرى أثناء النقل")
    return {"source": source_rel, "destination": str(dest.relative_to(root)).replace(chr(92), '/'),
            "sha256_before": before, "sha256_after": after, "fingerprint_match": True,
            "destination_exists": dest.is_file(), "unchanged_files_count": len(before_other),
            "unchanged_files_verified": unchanged_files_verified,
            "unchanged_files_before": before_other, "unchanged_files_after": after_other,
            "verified": True}


@tool(
    "ينقل تقريرًا محليًا إلى مجلد داخل workspace دون استبدال ويتحقق من بصمة المحتوى قبل وبعد النقل",
    {"source_path": "مسار التقرير", "destination_dir": "المجلد الهدف"},
    name="move_workspace_report",
    organization_department="operations",
    organization_role="operations:file-specialist",
    requires_approval=True,
    risk="medium",
    cost=1.0,
    capability="cross_department_sales_report_move",
    produces=("report_moved", "report_move_verified"),
    verification_level="strong",
)
def move_workspace_report(source_path: str, destination_dir: str):
    import hashlib, shutil
    root=workspace_root(); source=safe_path(source_path)
    if not source.is_file():
        raise ValueError(f"التقرير غير موجود: {source_path}")
    dest_dir=safe_path(destination_dir)
    if dest_dir == root or dest_dir.is_file():
        raise ValueError("destination_dir يجب أن يكون مجلدًا داخل workspace")
    dest_dir.mkdir(parents=True, exist_ok=True)
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    dest=_unique_destination(dest_dir/source.name)
    shutil.move(str(source), str(dest))
    after=hashlib.sha256(dest.read_bytes()).hexdigest()
    if before != after:
        raise ValueError("فشل تحقق بصمة التقرير بعد النقل")
    return {"source": str(source.relative_to(root)).replace(chr(92), '/'), "destination": str(dest.relative_to(root)).replace(chr(92), '/'), "sha256_before": before, "sha256_after": after, "fingerprint_match": True, "destination_exists": dest.is_file(), "source_removed": not source.exists(), "verified": True}

def _company_report_markdown(analysis: dict, move: dict) -> str:
    lines=["# Company Data Workflow Report", "", "## Analysis"]
    for item in analysis.get("files", []):
        lines.append(f"- `{item['path']}`: rows={item['rows']}, columns={item['columns']}, numeric_total_sum={item['numeric_total_sum']}")
        for col,total in sorted(item.get("numeric_totals", {}).items()):
            lines.append(f"  - `{col}` total = {total}")
    selected=analysis.get("selected") or {}
    lines += ["", f"Selected file: `{analysis.get('selected_path','')}`", f"Selected numeric total: **{selected.get('numeric_total_sum')}**", "", "## Movement", f"Original path: `{move.get('source','')}`", f"New path: `{move.get('destination','')}`", f"SHA-256 before: `{move.get('sha256_before','')}`", f"SHA-256 after: `{move.get('sha256_after','')}`", f"SHA-256 preserved: **{str(bool(move.get('fingerprint_match'))).lower()}**", f"Other source files checked: **{move.get('unchanged_files_count', 0)}**", f"Other source files unchanged: **{str(bool(move.get('unchanged_files_verified'))).lower()}**", "", "## Verification", "The report was generated from the Data Department result and the Operations movement result."]
    return "\n".join(lines)+"\n"

@tool(
    "ينشئ تقريرًا لعملية Data→Operations متعددة الأقسام من نتائج التحليل والنقل المتحقق منها",
    {"analysis_result": "نتائج تحليل CSV", "move_result": "نتيجة نقل الملف", "output_path": "مسار التقرير"},
    name="create_company_data_report",
    organization_department="data",
    organization_role="data:data-analyst",
    requires_approval=True,
    risk="medium",
    cost=1.5,
    capability="cross_department_data_move",
    produces=("company_data_report_created", "company_data_report_verified"),
    verification_level="strong",
)
def create_company_data_report(analysis_result: dict, move_result: dict, output_path: str):
    if not isinstance(analysis_result, dict) or not isinstance(move_result, dict):
        raise ValueError("نتائج التحليل والنقل مطلوبة")
    root=workspace_root(); target=safe_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_company_report_markdown(analysis_result, move_result), encoding="utf-8")
    reread=target.read_text(encoding="utf-8")
    selected=str(analysis_result.get("selected_path") or "")
    destination=str(move_result.get("destination") or "")
    verified=bool(selected and destination and selected in reread and destination in reread and
                  str(move_result.get("sha256_before")) in reread and str(move_result.get("sha256_after")) in reread and
                  move_result.get("fingerprint_match") and move_result.get("unchanged_files_verified"))
    if not verified:
        raise ValueError("فشل تحقق company data report")
    return {"path": str(target.relative_to(root)).replace(chr(92), '/'), "verified": True, "report_reread_verified": True}
