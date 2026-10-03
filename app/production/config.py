from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ProductionConfig:
    environment: str = "development"
    require_auth: bool = False
    api_token: str = ""
    max_json_bytes: int = 2_000_000
    max_chat_chars: int = 20_000
    max_session_chars: int = 160
    max_idempotency_key_chars: int = 128
    rate_capacity: int = 60
    rate_refill_per_second: float = 1.0
    rate_trust_proxy: bool = False
    task_stale_seconds: float = 45.0
    approval_timeout_seconds: float = 180.0
    request_log_body: bool = False

    @classmethod
    def from_env(cls) -> "ProductionConfig":
        env = os.getenv("SHURY_ENV", "development").strip().casefold() or "development"
        token = os.getenv("SHURY_API_TOKEN", "").strip()
        require = _bool("SHURY_REQUIRE_API_AUTH", env in {"prod", "production"})
        if require and not token:
            raise RuntimeError("SHURY_API_TOKEN is required when API authentication is enabled")
        return cls(
            environment=env,
            require_auth=require,
            api_token=token,
            max_json_bytes=_int("SHURY_MAX_JSON_BYTES", 2_000_000, 16_384, 10_000_000),
            max_chat_chars=_int("SHURY_MAX_CHAT_CHARS", 20_000, 128, 100_000),
            max_session_chars=_int("SHURY_MAX_SESSION_CHARS", 160, 32, 512),
            max_idempotency_key_chars=_int("SHURY_MAX_IDEMPOTENCY_KEY_CHARS", 128, 16, 256),
            rate_capacity=_int("SHURY_RATE_CAPACITY", 60, 1, 10_000),
            rate_refill_per_second=_float("SHURY_RATE_REFILL_PER_SECOND", 1.0, 0.01, 1000.0),
            rate_trust_proxy=_bool("SHURY_TRUST_PROXY", False),
            task_stale_seconds=_float("AGENT_UI_TASK_STALE_SECONDS", 45.0, 5.0, 86_400.0),
            approval_timeout_seconds=_float("AGENT_UI_APPROVAL_TIMEOUT_SECONDS", 180.0, 5.0, 86_400.0),
            request_log_body=_bool("SHURY_REQUEST_LOG_BODY", False),
        )


_DEFAULT: ProductionConfig | None = None


def get_config() -> ProductionConfig:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ProductionConfig.from_env()
    return _DEFAULT


def reset_config_for_tests() -> None:
    global _DEFAULT
    _DEFAULT = None
