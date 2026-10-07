from __future__ import annotations

import ssl

from app.integrations.network import _TLS_CONTEXT


def test_network_tls_requires_certificate_and_hostname_verification():
    assert isinstance(_TLS_CONTEXT, ssl.SSLContext)
    assert _TLS_CONTEXT.verify_mode == ssl.CERT_REQUIRED
    assert _TLS_CONTEXT.check_hostname is True


def test_network_tls_has_trust_store():
    paths = _TLS_CONTEXT.get_ca_certs()
    assert paths, "TLS context has no trusted CA certificates"
