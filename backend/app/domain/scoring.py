from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType

from pydantic import ValidationError

from app.domain.errors import InvalidDetectorOutput
from app.domain.types import DetectorKind, DetectorOutput, LabelKey, ScoreResult

type RawDetectorOutput = DetectorOutput | Mapping[str, object]

BASE_WEIGHTS: Mapping[DetectorKind, Decimal] = MappingProxyType(
    {
        DetectorKind.TEXT: Decimal("0.5"),
        DetectorKind.VISUAL: Decimal("0.4"),
        DetectorKind.METADATA: Decimal("0.1"),
    }
)

_INTERNAL_QUANTUM = Decimal("0.0001")
_API_CONFIDENCE_QUANTUM = Decimal("0.01")
_SCORE_QUANTUM = Decimal("1")
_SCORE_SCALE = Decimal("100")
_CONFIDENCE_THRESHOLD = Decimal("0.4000")
_ZERO = Decimal("0")


def aggregate_detector_outputs(outputs: Iterable[RawDetectorOutput]) -> ScoreResult:
    detectors = _validate_unique_outputs(outputs)
    available = tuple(detector for detector in detectors if detector.material_factor > 0)

    if available:
        weighted_score = sum(
            (
                BASE_WEIGHTS[detector.kind] * _decimal(detector.score)
                for detector in available
            ),
            start=_ZERO,
        )
        score_weight = sum(
            (BASE_WEIGHTS[detector.kind] for detector in available),
            start=_ZERO,
        )
        normalized_score = _quantize_internal(weighted_score / score_weight)
    else:
        normalized_score = Decimal("0.0000")

    internal_confidence = _quantize_internal(
        sum(
            (
                BASE_WEIGHTS[detector.kind]
                * _decimal(detector.confidence)
                * _decimal(detector.material_factor)
                for detector in available
            ),
            start=_ZERO,
        )
    )

    public_score = int(
        (normalized_score * _SCORE_SCALE).quantize(
            _SCORE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    )
    public_confidence = float(
        internal_confidence.quantize(
            _API_CONFIDENCE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    )

    if internal_confidence < _CONFIDENCE_THRESHOLD:
        return ScoreResult(
            score=public_score,
            confidence=public_confidence,
            label=None,
            evidence_status="insufficient",
        )

    return ScoreResult(
        score=public_score,
        confidence=public_confidence,
        label=label_for_score(public_score),
        evidence_status="sufficient",
    )


def label_for_score(score: int) -> LabelKey:
    if not 0 <= score <= 100:
        raise ValueError(f"score must be between 0 and 100: {score}")
    if score < 30:
        return LabelKey.NO_OBVIOUS_AI
    if score < 60:
        return LabelKey.LIGHT
    if score < 80:
        return LabelKey.MEDIUM
    return LabelKey.HIGH


def _validate_unique_outputs(
    outputs: Iterable[RawDetectorOutput],
) -> tuple[DetectorOutput, ...]:
    validated: list[DetectorOutput] = []
    seen: set[DetectorKind] = set()

    for raw_input in outputs:
        detector = _validate_output(raw_input)
        if detector.kind in seen:
            raise InvalidDetectorOutput(
                raw_input,
                reason=f"duplicate detector kind: {detector.kind.value}",
            )
        seen.add(detector.kind)
        validated.append(detector)

    return tuple(validated)


def _validate_output(raw_input: RawDetectorOutput) -> DetectorOutput:
    if isinstance(raw_input, DetectorOutput):
        return raw_input

    try:
        return DetectorOutput.model_validate(raw_input)
    except ValidationError as error:
        raise InvalidDetectorOutput(
            raw_input,
            reason="invalid detector output",
            validation_errors=tuple(error.errors()),
        ) from error


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _quantize_internal(value: Decimal) -> Decimal:
    return value.quantize(_INTERNAL_QUANTUM, rounding=ROUND_HALF_UP)
