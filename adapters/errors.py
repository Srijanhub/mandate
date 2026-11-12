from __future__ import annotations

from mandate_core.domain.errors import MandateCoreError


class ExternalServiceError(MandateCoreError):
    """Raised when an upstream partner/sponsor HTTP service fails or rejects a request."""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502
