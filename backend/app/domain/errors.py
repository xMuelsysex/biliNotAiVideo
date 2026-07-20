class ScoringError(ValueError):
    """Base class for canonical scoring failures."""


class InvalidDetectorOutput(ScoringError):
    def __init__(
        self,
        raw_input: object,
        *,
        reason: str,
        validation_errors: tuple[object, ...] = (),
    ) -> None:
        self.raw_input = raw_input
        self.reason = reason
        self.validation_errors = validation_errors
        super().__init__(reason)
