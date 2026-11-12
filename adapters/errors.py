from __future__ import annotations

import re

from mandate_core.domain.errors import MandateCoreError

_SECRET_PATTERNS = (
    re.compile(r"AQ\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"AC[0-9a-fA-F]{32}"),
    re.compile(r"(://[^:/\s]+:)[^@/\s]+(@)"),
    re.compile(r"((?:Bearer|Basic)\s+)[A-Za-z0-9._+/=-]+", flags=re.IGNORECASE),
    re.compile(
        r"((?:x-goog-api-key|x-api-key|api[_-]?key|client[_-]?secret|auth[_-]?token|authorization|password|secret)['\":=\s]+)[A-Za-z0-9._+/=-]+",
        flags=re.IGNORECASE,
    ),
)


def redact_secrets(text: str) -> str:
    """Scrub API keys, bearer tokens, and embedded database/URL credentials."""
    cleaned = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            cleaned = pat.sub(r"\1[REDACTED]\2", cleaned)
        elif pat.groups == 1:
            cleaned = pat.sub(r"\1[REDACTED]", cleaned)
        else:
            cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned


class ExternalServiceError(MandateCoreError):
    """Raised when an upstream partner/sponsor HTTP service fails or rejects a request."""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502
