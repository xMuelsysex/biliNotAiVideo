class ScoringError(ValueError):
    """Base class for canonical scoring failures."""


class InvalidDetectorOutput(ScoringError):
    def __init__(
        self,
        *,
        reason: str,
        detector_kind: str | None = None,
        field_paths: tuple[str, ...] = (),
        error_codes: tuple[str, ...] = (),
    ) -> None:
        self.reason = reason
        self.detector_kind = detector_kind
        self.field_paths = field_paths
        self.error_codes = error_codes
        super().__init__(reason)
