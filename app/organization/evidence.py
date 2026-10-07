from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import math
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable
from urllib.parse import urlparse

DEFAULT_SOURCE_CATALOG = Path(__file__).with_name("sources.toml")
_LOCAL_KINDS = {"", "local", "memory", "first_party_contract", "synthetic_seed"}


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    publisher: str
    url: str
    license: str = "free-to-read"
    jurisdiction: str = "global"
    authoritative_for: str = ""
    checked: str = ""
    source_kinds: tuple[str, ...] = ("web",)
    domains: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ("cite",)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_kinds"] = list(self.source_kinds)
        payload["domains"] = list(self.domains)
        payload["allowed_actions"] = list(self.allowed_actions)
        return payload


@dataclass(frozen=True)
class SkillEvidencePolicy:
    skill_key: str
    external_required: bool = False
    registered_source_required: bool = False
    min_evidence: int = 0
    min_registered_sources: int = 0
    freshness: str = "none"
    allowed_source_kinds: tuple[str, ...] = ()
    high_stakes: bool = False
    require_content_hash: bool = True
    require_retrieved_at: bool = True
    require_claim_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_source_kinds"] = list(self.allowed_source_kinds)
        return payload


@dataclass(frozen=True)
class EvidenceReceipt:
    evidence_id: str
    source_id: str | None
    source_kind: str
    title: str
    url: str
    content_hash: str
    retrieved_at: str
    published_at: str | None = None
    source_checked: str | None = None
    authority: float = 0.0
    freshness: float = 0.0
    registered: bool = False
    license: str | None = None
    allowed_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_actions"] = list(self.allowed_actions)
        return payload


@dataclass(frozen=True)
class EvidenceAssessment:
    skill_key: str
    ok: bool
    reason: str
    receipts: tuple[EvidenceReceipt, ...] = ()
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    registered_source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_key": self.skill_key,
            "ok": self.ok,
            "reason": self.reason,
            "receipts": [r.to_dict() for r in self.receipts],
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "registered_source_ids": list(self.registered_source_ids),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    if not re.fullmatch(r"20\d\d-\d\d-\d\d", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def freshness_score(value: Any, *, mode: str = "normal", today: date | None = None) -> float:
    if mode == "none":
        return 1.0
    parsed = _parse_date(value)
    if parsed is None:
        return 0.25
    current = today or date.today()
    age = max(0, (current - parsed).days)
    half_life = 90.0 if mode == "current" else 365.0
    return max(0.0, min(1.0, math.exp(-age / half_life)))


def _authority_from_url(url: str) -> float:
    host = (urlparse(url).hostname or "").casefold()
    if host.endswith(".gov") or host.endswith(".edu") or host.endswith(".ac.uk"):
        return 1.0
    if host in {"arxiv.org", "github.com", "raw.githubusercontent.com"}:
        return 0.94
    if host.endswith(".org"):
        return 0.86
    if host.endswith(".com"):
        return 0.74
    return 0.66


def _domain_matches(host: str, pattern: str) -> bool:
    p = pattern.casefold().strip()
    h = host.casefold().strip()
    if not p:
        return False
    if p.startswith("*."):
        return h.endswith(p[1:])
    return h == p or h.endswith("." + p)


class SourceRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DEFAULT_SOURCE_CATALOG)
        with self.path.open("rb") as handle:
            raw = tomllib.load(handle)
        self.sources = tuple(self._source_from_spec(item) for item in (raw.get("source") or ()))
        self.policies = tuple(self._policy_from_spec(item) for item in (raw.get("skill_policy") or ()))
        self._validate()
        self._source_map = {x.source_id: x for x in self.sources}
        self._policy_map = {x.skill_key: x for x in self.policies}

    @staticmethod
    def _tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = [value]
        return tuple(str(x).strip() for x in value if str(x).strip())

    @classmethod
    def _source_from_spec(cls, spec: dict[str, Any]) -> SourceRecord:
        return SourceRecord(
            source_id=str(spec.get("id") or "").strip(),
            title=str(spec.get("title") or "").strip(),
            publisher=str(spec.get("publisher") or "").strip(),
            url=str(spec.get("url") or "").strip(),
            license=str(spec.get("license") or "free-to-read").strip(),
            jurisdiction=str(spec.get("jurisdiction") or "global").strip(),
            authoritative_for=str(spec.get("authoritative_for") or "").strip(),
            checked=str(spec.get("checked") or "").strip(),
            source_kinds=cls._tuple(spec.get("source_kinds")) or ("web",),
            domains=cls._tuple(spec.get("domains")),
            allowed_actions=cls._tuple(spec.get("allowed_actions")) or ("cite",),
        )

    @classmethod
    def _policy_from_spec(cls, spec: dict[str, Any]) -> SkillEvidencePolicy:
        return SkillEvidencePolicy(
            skill_key=str(spec.get("skill_key") or "").strip(),
            external_required=bool(spec.get("external_required", False)),
            registered_source_required=bool(spec.get("registered_source_required", False)),
            min_evidence=int(spec.get("min_evidence", 0) or 0),
            min_registered_sources=int(spec.get("min_registered_sources", 0) or 0),
            freshness=str(spec.get("freshness") or "none").strip(),
            allowed_source_kinds=cls._tuple(spec.get("allowed_source_kinds")),
            high_stakes=bool(spec.get("high_stakes", False)),
            require_content_hash=bool(spec.get("require_content_hash", True)),
            require_retrieved_at=bool(spec.get("require_retrieved_at", True)),
            require_claim_support=bool(spec.get("require_claim_support", False)),
        )

    def _validate(self) -> None:
        ids = [x.source_id for x in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        for item in self.sources:
            if not item.source_id or not item.title or not item.publisher:
                raise ValueError("source requires id, title and publisher")
            if not item.url.startswith("https://"):
                raise ValueError(f"source URL must be https: {item.source_id}")
            if not item.license:
                raise ValueError(f"source license missing: {item.source_id}")
        keys = [x.skill_key for x in self.policies]
        if len(keys) != len(set(keys)):
            raise ValueError("skill evidence policies must be unique")
        for item in self.policies:
            if not item.skill_key:
                raise ValueError("skill policy requires skill_key")
            if item.freshness not in {"none", "normal", "current"}:
                raise ValueError(f"invalid freshness mode: {item.skill_key}")
            if item.min_evidence < 0 or item.min_registered_sources < 0:
                raise ValueError(f"negative evidence threshold: {item.skill_key}")
            if item.registered_source_required and item.min_registered_sources < 1:
                raise ValueError(f"registered_source_required needs a minimum: {item.skill_key}")

    def get(self, source_id: str) -> SourceRecord:
        return self._source_map[str(source_id).strip()]

    def policy_for_skill(self, skill_key: str) -> SkillEvidencePolicy:
        key = str(skill_key or "").strip()
        return self._policy_map.get(key, SkillEvidencePolicy(skill_key=key))

    def list_sources(self) -> tuple[SourceRecord, ...]:
        return self.sources

    def resolve(self, *, url: str = "", source_id: str | None = None, source_kind: str = "") -> SourceRecord | None:
        if source_id:
            return self._source_map.get(str(source_id).strip())
        host = (urlparse(url).hostname or "").casefold()
        for record in self.sources:
            if url and url.rstrip("/") == record.url.rstrip("/"):
                return record
            if host and any(_domain_matches(host, domain) for domain in record.domains):
                if not source_kind or source_kind in record.source_kinds:
                    return record
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "source_of_truth": str(self.path),
            "source_count": len(self.sources),
            "policy_count": len(self.policies),
            "sources": [x.to_dict() for x in self.sources],
            "policies": [x.to_dict() for x in self.policies],
        }


def _hash_text(text: Any) -> str:
    if text is None:
        return ""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            return dict(value.to_dict())
        except Exception:
            return {}
    return {}


def build_receipts(evidence: Iterable[Any], registry: SourceRegistry, *, policy: SkillEvidencePolicy | None = None) -> tuple[EvidenceReceipt, ...]:
    receipts: list[EvidenceReceipt] = []
    for index, raw in enumerate(evidence or (), 1):
        item = _as_dict(raw)
        if not item:
            continue
        metadata = dict(item.get("metadata") or {})
        url = str(item.get("url") or metadata.get("url") or "").strip()
        source_kind = str(item.get("source_kind") or item.get("source") or metadata.get("source_kind") or "").strip()
        if not source_kind and url:
            host = (urlparse(url).hostname or "").casefold()
            if host == "arxiv.org" or host.endswith(".arxiv.org"):
                source_kind = "arxiv"
            elif host == "github.com" or host.endswith(".github.com") or host.endswith(".githubusercontent.com"):
                source_kind = "github"
            else:
                source_kind = "web"
        source_id = str(item.get("source_id") or metadata.get("source_id") or "").strip() or None
        record = registry.resolve(url=url, source_id=source_id, source_kind=source_kind)
        text = item.get("text") or item.get("abstract") or item.get("snippet") or ""
        content_hash = str(item.get("content_hash") or item.get("sha256") or metadata.get("content_hash") or "").strip() or _hash_text(text)
        retrieved_at = str(item.get("retrieved_at") or metadata.get("retrieved_at") or "").strip()
        published_at = str(item.get("published_at") or item.get("published") or metadata.get("published") or "").strip() or None
        receipts.append(EvidenceReceipt(
            evidence_id=str(item.get("evidence_id") or metadata.get("evidence_id") or f"evidence:{index}"),
            source_id=record.source_id if record else source_id,
            source_kind=source_kind or "unknown",
            title=str(item.get("title") or "").strip(),
            url=url,
            content_hash=content_hash,
            retrieved_at=retrieved_at,
            published_at=published_at,
            source_checked=record.checked if record else None,
            authority=_authority_from_url(url) if url else 0.0,
            freshness=freshness_score(published_at or (record.checked if record else None), mode=policy.freshness if policy else "normal"),
            registered=record is not None,
            license=record.license if record else None,
            allowed_actions=record.allowed_actions if record else (("cite",) if url else ()),
        ))
    return tuple(receipts)


class CompanyEvidencePolicy:
    def __init__(self, registry: SourceRegistry | None = None):
        self.registry = registry or SourceRegistry()

    def assess(self, skill_key: str, evidence: Iterable[Any], *, claims: Iterable[Any] = ()) -> EvidenceAssessment:
        policy = self.registry.policy_for_skill(skill_key)
        receipts = build_receipts(evidence, self.registry, policy=policy)
        missing: list[str] = []
        warnings: list[str] = []

        if len(receipts) < policy.min_evidence:
            missing.append(f"min_evidence:{policy.min_evidence}")

        external = [r for r in receipts if r.source_kind not in _LOCAL_KINDS]
        if policy.external_required and not external:
            missing.append("external_evidence_required")

        registered_ids = sorted({r.source_id for r in receipts if r.registered and r.source_id})
        if policy.registered_source_required and len(registered_ids) < policy.min_registered_sources:
            missing.append(f"registered_sources:{policy.min_registered_sources}")

        if policy.allowed_source_kinds:
            bad = sorted({r.source_kind for r in external if r.source_kind not in policy.allowed_source_kinds})
            if bad:
                missing.append("disallowed_source_kind:" + ",".join(bad))

        if policy.require_content_hash:
            missing.extend(f"missing_content_hash:{r.evidence_id}" for r in receipts if not r.content_hash)
        if policy.require_retrieved_at:
            missing.extend(f"missing_retrieved_at:{r.evidence_id}" for r in external if not r.retrieved_at)

        if policy.freshness != "none":
            weak = [r.evidence_id for r in receipts if r.freshness < (0.35 if policy.freshness == "normal" else 0.50)]
            if weak:
                warnings.append("stale_evidence:" + ",".join(weak))
                if policy.high_stakes:
                    missing.append("freshness_requirement_not_met")

        if policy.registered_source_required:
            unregistered_external = [r.evidence_id for r in external if not r.registered]
            if unregistered_external:
                missing.append("unregistered_external_source:" + ",".join(unregistered_external))

        if policy.require_claim_support and not tuple(claims or ()):
            missing.append("claim_support_required")

        ok = not missing
        return EvidenceAssessment(
            skill_key=skill_key,
            ok=ok,
            reason="evidence_policy_satisfied" if ok else "evidence_policy_failed",
            receipts=receipts,
            missing=tuple(dict.fromkeys(missing)),
            warnings=tuple(dict.fromkeys(warnings)),
            registered_source_ids=tuple(registered_ids),
        )

    def collect_from_outputs(self, outputs: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence_rows: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        seen_evidence: set[tuple[str, str, str]] = set()
        seen_claims: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                claim_list = value.get("claims")
                if isinstance(claim_list, list):
                    for claim in claim_list:
                        if isinstance(claim, dict):
                            claim_id = str(claim.get("claim_id") or claim.get("text") or "").strip()
                            if claim_id and claim_id not in seen_claims:
                                seen_claims.add(claim_id)
                                claims.append(dict(claim))
                url = str(value.get("url") or "").strip()
                source_kind = str(value.get("source_kind") or value.get("source") or "").strip()
                text = value.get("text") or value.get("abstract") or value.get("snippet")
                if url and (text is not None or value.get("title") or value.get("sha256") or value.get("content_hash")):
                    key = (url, str(value.get("sha256") or value.get("content_hash") or ""), str(value.get("title") or ""))
                    if key not in seen_evidence:
                        seen_evidence.add(key)
                        row = dict(value)
                        if source_kind:
                            row["source_kind"] = source_kind
                        evidence_rows.append(row)
                for child in value.values():
                    visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    visit(child)

        visit(outputs)
        return evidence_rows, claims

    def assess_outputs(self, skill_key: str, outputs: Any) -> EvidenceAssessment:
        evidence, claims = self.collect_from_outputs(outputs)
        return self.assess(skill_key, evidence, claims=claims)

    def snapshot(self) -> dict[str, Any]:
        return self.registry.snapshot()
