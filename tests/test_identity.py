from app.identity import get_identity, identity_context


def test_shury_identity_contract():
    identity = get_identity()
    assert identity.name == "SHURY"
    assert identity.short_name == "شوري"
    assert identity.mission
    assert identity.principles
    assert identity.boundaries
    context = identity_context().lower()
    assert "identity" in context
    assert "shury" in context
    assert "mission" in context


def test_identity_does_not_grant_tool_permissions():
    context = identity_context().lower()
    assert "cannot" in context or "not permission" in context
    assert "bypass" in context
