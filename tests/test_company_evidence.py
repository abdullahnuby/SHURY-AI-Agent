from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.organization.evidence import CompanyEvidencePolicy, SourceRegistry, freshness_score


@pytest.fixture()
def registry(tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text(
        '''
[[source]]
id = "official"
title = "Official source"
publisher = "Gov"
url = "https://example.gov/"
license = "public-domain-usgov"
jurisdiction = "US"
authoritative_for = "official rule"
checked = "2026-10-05"
source_kinds = ["web"]
domains = ["example.gov"]
allowed_actions = ["cite", "summarize"]

[[skill_policy]]
skill_key = "skill:research"
external_required = true
registered_source_required = true
min_evidence = 1
min_registered_sources = 1
freshness = "current"
allowed_source_kinds = ["web"]
high_stakes = true
require_content_hash = true
require_retrieved_at = true
require_claim_support = true
''', encoding="utf-8")
    return SourceRegistry(path)


def test_registry_validates_and_resolves_domain(registry):
    assert registry.get("official").publisher == "Gov"
    found = registry.resolve(url="https://docs.example.gov/rules/1", source_kind="web")
    assert found is not None
    assert found.source_id == "official"


def test_registry_rejects_non_https(tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text('''[[source]]\nid="x"\ntitle="X"\npublisher="P"\nurl="http://x.test"\n''', encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        SourceRegistry(path)


def test_freshness_none_is_perfect():
    assert freshness_score(None, mode="none") == 1.0


def test_current_freshness_decays():
    today = date(2026, 10, 5)
    fresh = freshness_score("2026-10-05", mode="current", today=today)
    old = freshness_score("2025-01-01", mode="current", today=today)
    assert fresh > old


def test_assessment_accepts_registered_external_evidence(registry):
    assessment = CompanyEvidencePolicy(registry).assess(
        "skill:research",
        [{
            "evidence_id": "e1",
            "source_kind": "web",
            "title": "Official source",
            "url": "https://example.gov/rule",
            "text": "Rule text summary.",
            "published": "2026-10-04",
            "metadata": {"retrieved_at": "2026-10-05T00:00:00Z"},
        }],
        claims=[{"text": "Rule text summary", "support_ids": ["e1"]}],
    )
    assert assessment.ok
    assert assessment.registered_source_ids == ("official",)


def test_high_stakes_rejects_unregistered_external(registry):
    assessment = CompanyEvidencePolicy(registry).assess(
        "skill:research",
        [{
            "evidence_id": "e1",
            "source_kind": "web",
            "title": "Unknown",
            "url": "https://unknown.example/news",
            "text": "Some text.",
            "metadata": {"retrieved_at": "2026-10-05T00:00:00Z"},
        }],
        claims=[{"text": "Some text", "support_ids": ["e1"]}],
    )
    assert not assessment.ok
    assert any(x.startswith("unregistered_external_source") for x in assessment.missing)


def test_current_high_stakes_rejects_missing_claim_support(registry):
    assessment = CompanyEvidencePolicy(registry).assess(
        "skill:research",
        [{
            "evidence_id": "e1",
            "source_kind": "web",
            "title": "Official source",
            "url": "https://example.gov/rule",
            "text": "Some text.",
            "published": "2026-10-05",
            "metadata": {"retrieved_at": "2026-10-05T00:00:00Z"},
        }],
    )
    assert not assessment.ok
    assert "claim_support_required" in assessment.missing


def test_existing_non_external_policy_does_not_require_external():
    policy = CompanyEvidencePolicy().assess(
        "builtin:data-analysis",
        [{"evidence_id": "local1", "source_kind": "local", "title": "sales.csv", "text": "rows=4"}],
    )
    assert policy.ok


def test_collect_from_research_output_carries_provider_provenance():
    policy = CompanyEvidencePolicy()
    outputs = {
        "s1": {
            "web": {"sources": [{
                "title": "NIST", "url": "https://www.nist.gov/itl/ai-risk-management-framework",
                "sha256": "abc123", "retrieved_at": "2026-10-05T12:00:00Z", "text": "AI risk guidance."
            }]},
            "arxiv": {"papers": [{
                "title": "Agent Evidence", "url": "https://arxiv.org/abs/2605.06635",
                "published": "2026-05-07", "retrieved_at": "2026-10-05T12:00:00Z", "abstract": "Evidence provenance."
            }]}
        }
    }
    assessment = policy.assess_outputs("builtin:web-research", outputs)
    assert assessment.ok
    assert len(assessment.receipts) == 2
    assert all(r.content_hash and r.retrieved_at for r in assessment.receipts)
    assert "nist-ai-rmf" in assessment.registered_source_ids


def test_skill_binding_exposes_evidence_policy():
    from app.organization.skills import OrganizationSkillIndex
    from app.organization import DEFAULT_COMPANY
    from app.skills.registry import SkillBank
    binding = OrganizationSkillIndex(DEFAULT_COMPANY.registry._catalog(), SkillBank()).skill("builtin:research-report")
    assert binding.evidence_policy["external_required"] is True
    assert binding.evidence_policy["min_evidence"] >= 1


def test_url_inference_assigns_provider_kind():
    policy = CompanyEvidencePolicy()
    outputs = {
        "arxiv": {"papers": [{
            "title": "Paper", "url": "https://arxiv.org/abs/2605.06635",
            "sha256": "abc", "retrieved_at": "2026-10-05T12:00:00Z", "abstract": "Evidence."
        }]}
    }
    assessment = policy.assess_outputs("builtin:web-research", outputs)
    assert assessment.ok
    assert assessment.receipts[0].source_kind == "arxiv"
