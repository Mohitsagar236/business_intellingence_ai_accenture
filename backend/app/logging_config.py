"""
Centralized logging setup (P1-2).

Every module gets its own logger via `logging.getLogger(__name__)`; `configure_logging()` is
called once, at process startup (app/main.py), to attach a single handler/formatter/level to
the "app" logger namespace — every module logger (app.pipeline.narrative, app.api.auth, ...)
is a child of it and inherits the config, so nothing configures logging independently.

Log lines are structured-but-readable — `event_name key=value key=value` — via `event()`
below, not raw Python object dumps:

    INFO    app.pipeline.orchestrator  detection_started metric=revenue window=2026-07-01:2026-07-31
    WARNING app.pipeline.narrative     llm_call_failed provider=anthropic error_type=Timeout

Never log: passwords, JWTs/API keys, full prompts or raw customer text, full LLM responses, or
entire uploaded records — every call site in this codebase that logs is expected to pass only
identifiers, counts, and short reasons, never bulk content.
"""
from __future__ import annotations

import logging

from app.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    app_logger = logging.getLogger("app")
    app_logger.setLevel(settings.log_level.upper())
    app_logger.addHandler(handler)
    _configured = True


def event(logger: logging.Logger, level: int, name: str, **fields: object) -> None:
    """`logger.log(level, ...)` formatted as `event_name key=value key=value ...`."""
    kv = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.log(level, f"{name} {kv}".rstrip())
