"""Unit and integration tests for structured-log sensitive-field redaction."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import structlog

from app.logging_config import configure_logging, redact_sensitive

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"
_PAN_LITERAL = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
_LOGGER_CALL = re.compile(
    r"(?:logger|log)\.(?:debug|info|warning|error|exception|critical)\s*\(",
)


def test_redact_sensitive_nested_dict_and_list():
    event = {
        "event": "employee_updated",
        "employee_id": "emp-1",
        "expand": "keep-me",
        "profile": {
            "pan": "ABCDE1234F",
            "employee_pan": "VWXYZ5678A",
            "name": "Ada",
        },
        "accounts": [
            {"account_number": "1234567890", "bank": "SBI"},
            {"pran": "123456789012", "ok": True},
        ],
        "password": "secret-value",
        "authorization": "Bearer tok",
        "cookie": "accord_session=abc",
        "api_token": "t-1",
        "client_secret": "s-1",
    }
    redacted = redact_sensitive(None, "info", event)

    assert redacted["expand"] == "keep-me"
    assert redacted["employee_id"] == "emp-1"
    assert redacted["profile"]["pan"] == "[REDACTED]"
    assert redacted["profile"]["employee_pan"] == "[REDACTED]"
    assert redacted["profile"]["name"] == "Ada"
    assert redacted["accounts"][0]["account_number"] == "[REDACTED]"
    assert redacted["accounts"][0]["bank"] == "SBI"
    assert redacted["accounts"][1]["pran"] == "[REDACTED]"
    assert redacted["accounts"][1]["ok"] is True
    assert redacted["password"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["cookie"] == "[REDACTED]"
    assert redacted["api_token"] == "[REDACTED]"
    assert redacted["client_secret"] == "[REDACTED]"


def test_app_source_has_no_pan_literals_in_logger_calls():
    """Pragmatic grep: logger calls must not embed PAN-shaped string literals."""
    offenders: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in _LOGGER_CALL.finditer(source):
            # Scan the call argument region (bounded window).
            window = source[match.start() : match.start() + 400]
            if _PAN_LITERAL.search(window):
                offenders.append(f"{path.relative_to(_APP_ROOT.parent)}: {window[:120]!r}")
    assert offenders == []


def test_structlog_integration_redacts_sensitive_keys(caplog):
    configure_logging("INFO")
    log = structlog.get_logger("redaction-integration")
    with caplog.at_level(logging.INFO):
        log.info("auth_debug", password="super-secret", user_id="u-1", expand="visible")

    messages = [record.getMessage() for record in caplog.records]
    joined = "\n".join(messages)
    assert "[REDACTED]" in joined
    assert "super-secret" not in joined

    payload = None
    for message in reversed(messages):
        text = message.strip()
        if text.startswith("{"):
            payload = json.loads(text)
            break
    assert payload is not None
    assert payload.get("password") == "[REDACTED]"
    assert payload.get("user_id") == "u-1"
    assert payload.get("expand") == "visible"
