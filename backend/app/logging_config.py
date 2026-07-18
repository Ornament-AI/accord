"""Structured logging with structlog."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

import structlog

# Keys (case-insensitive) whose values must never appear in structured logs.
# Matching uses underscore/hyphen token boundaries so ``employee_pan`` redacts
# but ordinary words like ``expand`` do not (``pan`` is not a token there).
_SENSITIVE_KEY_SPECS = (
    "pan",
    "pran",
    "account_number",
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
)
_SENSITIVE_TOKEN_SEQS = tuple(spec.split("_") for spec in _SENSITIVE_KEY_SPECS)
_KEY_SPLIT = re.compile(r"[_-]+")


def _key_is_sensitive(key: str) -> bool:
    """True when ``key`` matches a sensitive name on token boundaries."""
    tokens = [t for t in _KEY_SPLIT.split(key.lower()) if t]
    if not tokens:
        return False
    for seq in _SENSITIVE_TOKEN_SEQS:
        seq_len = len(seq)
        if seq_len == 1:
            if seq[0] in tokens:
                return True
            continue
        for idx in range(len(tokens) - seq_len + 1):
            if tokens[idx : idx + seq_len] == list(seq):
                return True
    return False


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if _key_is_sensitive(str(k)) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_sensitive(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor: recursively redact sensitive keys in ``event_dict``."""
    return _redact_value(event_dict)


def configure_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
            redact_sensitive,
            structlog.processors.JSONRenderer(serializer=json.dumps),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
