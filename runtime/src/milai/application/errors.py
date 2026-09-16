class ApplicationError(RuntimeError):
    """Base class for safe application-layer errors."""


class IdempotencyConflict(ApplicationError):
    pass


class TenantMismatch(ApplicationError):
    pass


class EvidenceNotFound(ApplicationError):
    pass


class EvidencePayloadTooLarge(ApplicationError):
    pass


class EvidenceDataModeBlocked(ApplicationError):
    pass


class EvidenceContentUnavailable(ApplicationError):
    pass


class BlobPurgeRace(ApplicationError):
    pass


class RetrievalRouteDisabled(ApplicationError):
    pass


class CausalConsistencyError(ApplicationError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ContextOperationError(ApplicationError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CanonicalOperationError(ApplicationError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
