from pathlib import Path


def test_runtime_package_layout_is_responsibility_oriented():
    root = Path(__file__).resolve().parents[1]
    app = root / "app"
    top_level_py = sorted(p.name for p in app.iterdir() if p.is_file() and p.suffix == ".py")
    assert top_level_py == ["__init__.py", "api.py", "main.py"]
    assert not list(app.glob("v*_engine.py"))
    assert not list(app.glob("v*_benchmark.py"))
    for package in ("domain", "runtime", "planning", "knowledge", "intelligence", "skills", "integrations", "services", "tools", "evaluation", "interfaces"):
        assert (app / package / "__init__.py").exists()


def test_historical_docs_are_not_in_runtime_tree():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "history").is_dir()
    assert not list((root / "app").rglob("ARCHITECTURE_V*.md"))
    assert not list((root / "app").rglob("RESEARCH_NOTES_V*.md"))
