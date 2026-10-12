from __future__ import annotations

from pathlib import Path

from app.brain.learning import BrainExperienceStore, LearningStore
from app.learning.brain_store import BrainKnowledgeStore
from app.learning.store import LearningStore as CanonicalLearningStore
from app.intelligence.semantic.retrieval import MODEL_NAME


def test_single_learning_store_schema_and_compatibility_facade(tmp_path: Path):
    assert BrainExperienceStore is LearningStore is CanonicalLearningStore
    facade = BrainKnowledgeStore(tmp_path / "learning.db")
    assert isinstance(facade.store, CanonicalLearningStore)
    assert facade.path.resolve() == Path(tmp_path / "learning.db").resolve()
    source = Path("app/learning/brain_store.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()
    assert "CREATE TABLE" not in Path("app/brain/learning.py").read_text(encoding="utf-8").upper()


def test_canonical_brain_has_no_generative_runtime_dependency():
    offenders: list[str] = []
    for path in Path("app/brain").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        forbidden = ("get_provider()", ".complete_structured(", ".complete(")
        if any(token in text for token in forbidden):
            offenders.append(str(path))
    assert offenders == [], offenders


def test_arabic_retrieval_is_the_configured_semantic_model():
    assert MODEL_NAME == "omarelshehy/Arabic-Retrieval-v1.0"


def test_source_tree_contains_no_legacy_generators():
    assert not Path("app/integrations/llm.py").exists()
    assert not Path("app/runtime/react.py").exists()
    assert not Path("app/intelligence/semantic/llm.py").exists()
