class MandateCoreError(Exception):
    """Base error for Mandate Core."""

    code: str = "CORE_ERROR"
    status_code: int = 400

    def __init__(self, message: str, *, code: str | None = None, details: object = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.details = details


class ValidationError(MandateCoreError):
    code = "VALIDATION_ERROR"
    status_code = 400


class NotFoundError(MandateCoreError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(MandateCoreError):
    code = "CONFLICT"
    status_code = 409


class IllegalTransitionError(MandateCoreError):
    code = "ILLEGAL_STATE_TRANSITION"
    status_code = 409


class PolicyBlockedError(MandateCoreError):
    code = "POLICY_BLOCKED"
    status_code = 403


class CommandParseError(MandateCoreError):
    code = "COMMAND_PARSE_ERROR"
    status_code = 400


class PaymentProviderError(MandateCoreError):
    code = "PAYMENT_PROVIDER_ERROR"
    status_code = 502


class LedgerTamperError(MandateCoreError):
    code = "LEDGER_TAMPERED"
    status_code = 500
