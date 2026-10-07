from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from pathlib import Path
from typing import Literal

from app.runtime.security import safe_workspace_path, workspace_root
from app.intelligence.understanding import normalize

ResolutionStatus = Literal['resolved', 'ambiguous', 'missing', 'outside']


@dataclass(frozen=True)
class WorkspaceReference:
    status: ResolutionStatus
    value: str = ''
    candidates: tuple[str, ...] = ()
    raw: str = ''
    role: str = 'source'

    @property
    def resolved(self) -> bool:
        return self.status == 'resolved' and bool(self.value)


_ROLE_MARKERS = {
    'source': (
        'ملف', 'الملف', 'فولدر', 'الفولدر', 'مجلد', 'المجلد', 'folder', 'directory', 'file',
        'dataset', 'البيانات', 'ملف البيانات', 'the file', 'the folder', 'the directory',
    ),
    'destination': (
        'إلى', 'الى', 'في مجلد', 'فى مجلد', 'حطه في', 'حطّه في', 'حطها في', 'داخل مجلد',
        'داخل', 'to', 'into', 'in folder', 'inside folder', 'save in', 'write in', 'put in',
    ),
}

_STOP_WORDS = {
    'و', 'وقولي', 'وقلّي', 'وقول', 'ولي', 'بس', 'ثم', 'بعد', 'علشان', 'عشان', 'فيه', 'في',
    'الى', 'إلى', 'to', 'and', 'then', 'please', 'بقى', 'كده', 'كذا', 'the', 'a', 'an',
}


def _clean(value: str) -> str:
    return str(value or '').strip().strip(' \t\r\n,.;:!?؟()[]{}<>"\'`')


def _norm(value: str) -> str:
    return re.sub(r'[^\w\u0600-\u06ff]+', ' ', normalize(_clean(value))).strip().casefold()


def _token_forms(value: str) -> set[str]:
    """Generate conservative grammatical-prefix variants for a workspace name token."""
    normalized = _norm(value)
    forms = {normalized} if normalized else set()
    # Common Arabic proclitics can attach to a Latin/Arabic folder name (e.g. "للـarchive").
    prefixes = ('لل', 'بال', 'وال', 'فال', 'كال', 'ل', 'ب', 'و', 'ف', 'ك')
    for form in tuple(forms):
        for prefix in prefixes:
            if form.startswith(prefix) and len(form) > len(prefix) + 1:
                forms.add(form[len(prefix):])
    if normalized.startswith('ال') and len(normalized) > 3:
        forms.add(normalized[2:])
    return forms

def _looks_external(raw: str) -> bool:
    text = _clean(raw).replace('\\', '/')
    path = Path(text)
    windows_absolute = bool(re.match(r'^[A-Za-z]:/', text))
    return windows_absolute or path.is_absolute() or text == '..' or text.startswith('../') or text.startswith('./../') or '/..' in text


def _relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _inventory(root: Path, expected_kind: str = 'any') -> list[str]:
    values: list[str] = []
    if not root.exists():
        return values
    for item in root.rglob('*'):
        if expected_kind == 'file' and not item.is_file():
            continue
        if expected_kind == 'dir' and not item.is_dir():
            continue
        if item == root:
            continue
        values.append(_relative_name(item, root))
    return sorted(values, key=lambda x: (len(Path(x).parts), x.casefold(), x))


def _candidate_tokens(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r'["\']([^"\']+)["\']', text):
        candidates.append(_clean(match.group(1)))
    candidates.extend(
        _clean(m.group(0))
        for m in re.finditer(r'(?<![\w./\\-])[^\s,;!?؟()\[\]{}]+\.(?:csv|json|sqlite3?|db|txt|md|pdf|xlsx?|py|sql|log)\b', text, re.I)
    )
    # Explicit path-like tokens, including simple relative nested paths.
    candidates.extend(
        _clean(m.group(0))
        for m in re.finditer(r'(?<![\w])(?:[A-Za-z0-9_\- .]+[\\/])+(?:[A-Za-z0-9_\- .]+)', text)
    )
    return [x for x in candidates if x]


def _after_marker(text: str, role: str) -> list[str]:
    out: list[str] = []
    markers = _ROLE_MARKERS.get(role, _ROLE_MARKERS['source'])
    lowered = text.casefold()
    for marker in sorted(markers, key=len, reverse=True):
        pos = lowered.find(marker.casefold())
        while pos >= 0:
            tail = text[pos + len(marker):].lstrip(' \t:="\'')
            if not tail:
                break
            words = tail.split()
            current: list[str] = []
            for word in words:
                cleaned = _clean(word)
                if not cleaned or _norm(cleaned) in _STOP_WORDS:
                    break
                current.append(cleaned)
                joined = _clean(' '.join(current))
                # An unquoted marker reference generally ends at natural connectors; a
                # file extension is a strong end signal even when punctuation follows.
                if re.search(r'\.(?:csv|json|sqlite3?|db|txt|md|pdf|xlsx?|py|sql|log)$', cleaned, re.I):
                    out.append(joined)
                    break
                if len(current) >= 4:
                    out.append(joined)
                    break
            if current:
                out.append(_clean(' '.join(current)))
            pos = lowered.find(marker.casefold(), pos + len(marker))
    return out


def _match_inventory(reference: str, root: Path, expected_kind: str) -> WorkspaceReference:
    raw = _clean(reference)
    if not raw:
        return WorkspaceReference('missing', raw='', role='source')
    if _looks_external(raw):
        return WorkspaceReference('outside', raw=raw)

    stripped = raw.replace('\\', '/')
    if stripped.casefold().startswith('workspace/'):
        stripped = stripped.split('/', 1)[1]
    exact_target = _norm(stripped)
    entries = _inventory(root, expected_kind)
    exact = [entry for entry in entries if _norm(entry) == exact_target or _norm(Path(entry).name) == exact_target]
    if len(exact) == 1:
        return WorkspaceReference('resolved', exact[0], raw=raw)
    if len(exact) > 1:
        return WorkspaceReference('ambiguous', candidates=tuple(exact[:8]), raw=raw)

    # Fuzzy matching is used only against complete names/relative paths. It never
    # accepts arbitrary substrings, and it must clear a conservative similarity bar.
    scored: list[tuple[float, str]] = []
    for entry in entries:
        for candidate_name in (entry, Path(entry).name):
            score = SequenceMatcher(None, exact_target, _norm(candidate_name)).ratio()
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].casefold(), x[1]))
    if scored and scored[0][0] >= 0.86:
        top = scored[0][0]
        matches = sorted({entry for score, entry in scored if score >= max(0.86, top - 0.03)})
        if len(matches) == 1:
            return WorkspaceReference('resolved', matches[0], raw=raw)
        if matches:
            return WorkspaceReference('ambiguous', candidates=tuple(matches[:8]), raw=raw)
    return WorkspaceReference('missing', raw=raw)


def resolve_workspace_reference(reference: str, *, expected_kind: str = 'any', role: str = 'source', root: Path | None = None) -> WorkspaceReference:
    result = _match_inventory(reference, root or workspace_root(), expected_kind)
    return WorkspaceReference(result.status, result.value, result.candidates, result.raw, role)


def extract_workspace_reference(text: str, *, expected_kind: str = 'any', role: str = 'source', root: Path | None = None) -> WorkspaceReference:
    root = root or workspace_root()
    source = str(text or '').strip()
    if not source:
        return WorkspaceReference('missing', raw='', role=role)
    if _looks_external(source):
        # Only classify as outside when an actual path-like escape appears, not when the
        # sentence merely contains punctuation or a natural-language slash.
        for token in re.findall(r'(?:[A-Za-z]:[\\/][^\s,;!?؟]+|/[^\s,;!?؟]+|\.\.?[\\/][^\s,;!?؟]+)', source):
            if _looks_external(token):
                return WorkspaceReference('outside', raw=_clean(token), role=role)

    raw_candidates = []
    raw_candidates.extend(_candidate_tokens(source))
    raw_candidates.extend(_after_marker(source, role))
    # Existing workspace names can be referenced without a marker, but only when the
    # complete name/path actually occurs as a token in the user's text. Never add arbitrary
    # inventory entries to the candidate set: that would make an unrelated filename look
    # like a user's reference.
    entries = _inventory(root, expected_kind)
    normalized_source = _norm(source)
    for entry in entries:
        name = Path(entry).name
        entry_forms = _token_forms(entry) | _token_forms(name)
        source_tokens = re.findall(r'[\w\u0600-\u06ff]+(?:[.][\w-]+)?', normalized_source)
        source_forms = set()
        for token in source_tokens:
            source_forms.update(_token_forms(token))
        if entry_forms.intersection(source_forms):
            raw_candidates.append(entry)

    seen: set[str] = set()
    resolutions: list[WorkspaceReference] = []
    for candidate in raw_candidates:
        candidate = _clean(candidate)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        resolution = _match_inventory(candidate, root, expected_kind)
        if resolution.status in {'resolved', 'ambiguous', 'outside'}:
            resolutions.append(WorkspaceReference(resolution.status, resolution.value, resolution.candidates, resolution.raw, role))

    ambiguous = next((r for r in resolutions if r.status == 'ambiguous'), None)
    if ambiguous:
        return ambiguous
    outside = next((r for r in resolutions if r.status == 'outside'), None)
    if outside:
        return outside
    resolved = next((r for r in resolutions if r.resolved), None)
    if resolved:
        return resolved
    return WorkspaceReference('missing', raw='', role=role)


def require_resolved_path(reference: WorkspaceReference) -> str:
    if not reference.resolved:
        raise ValueError(f'workspace reference is {reference.status}')
    path = safe_workspace_path(reference.value)
    if not path.exists():
        raise ValueError('workspace reference disappeared before execution')
    return reference.value


def single_workspace_dataset() -> str | None:
    """Return the only supported local dataset when the workspace makes it unambiguous."""
    from app.runtime.security import workspace_root
    supported = {'.csv', '.json', '.sqlite', '.sqlite3', '.db'}
    paths = [p for p in workspace_root().rglob('*') if p.is_file() and p.suffix.casefold() in supported]
    return paths[0].relative_to(workspace_root()).as_posix() if len(paths) == 1 else None



__all__ = ['WorkspaceReference', 'extract_workspace_reference', 'resolve_workspace_reference', 'require_resolved_path', 'single_workspace_dataset']
