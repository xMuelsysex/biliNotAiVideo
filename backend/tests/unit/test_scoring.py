import math
from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.errors import InvalidDetectorOutput
from app.domain.scoring import aggregate_detector_outputs, label_for_score
from app.domain.types import (
    DeclarationState,
    DetectorKind,
    DetectorOutput,
    EvidenceItem,
    LabelKey,
    ScoreResult,
)


def detector(
    kind: DetectorKind,
    *,
    score: float,
    confidence: float = 1.0,
    material_factor: float = 1.0,
) -> DetectorOutput:
    return DetectorOutput(
        kind=kind,
        score=score,
        confidence=confidence,
        material_factor=material_factor,
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, LabelKey.NO_OBVIOUS_AI),
        (29, LabelKey.NO_OBVIOUS_AI),
        (30, LabelKey.LIGHT),
        (59, LabelKey.LIGHT),
        (60, LabelKey.MEDIUM),
        (79, LabelKey.MEDIUM),
        (80, LabelKey.HIGH),
        (100, LabelKey.HIGH),
    ],
)
def test_label_thresholds(score: int, expected: LabelKey) -> None:
    assert label_for_score(score) is expected


@pytest.mark.parametrize("score", [-1, 101])
def test_label_rejects_out_of_range_score(score: int) -> None:
    with pytest.raises(ValueError, match="score must be between 0 and 100"):
        label_for_score(score)


@pytest.mark.parametrize(
    ("outputs", "expected_score", "expected_confidence", "expected_status"),
    [
        (
            [
                detector(DetectorKind.TEXT, score=1.0),
                detector(DetectorKind.VISUAL, score=1.0),
                detector(DetectorKind.METADATA, score=1.0),
            ],
            100,
            1.0,
            "sufficient",
        ),
        (
            [
                detector(DetectorKind.TEXT, score=1.0),
                detector(DetectorKind.VISUAL, score=1.0),
            ],
            100,
            0.9,
            "sufficient",
        ),
        (
            [detector(DetectorKind.TEXT, score=1.0)],
            100,
            0.5,
            "sufficient",
        ),
        (
            [
                detector(DetectorKind.TEXT, score=0.2),
                detector(DetectorKind.VISUAL, score=0.8),
            ],
            47,
            0.9,
            "sufficient",
        ),
        ([], 0, 0.0, "insufficient"),
    ],
)
def test_aggregate_core_cases(
    outputs: list[DetectorOutput],
    expected_score: int,
    expected_confidence: float,
    expected_status: Literal["sufficient", "insufficient"],
) -> None:
    result = aggregate_detector_outputs(outputs)

    assert result.score == expected_score
    assert result.confidence == expected_confidence
    assert result.evidence_status == expected_status


def test_missing_sources_renormalize_score() -> None:
    result = aggregate_detector_outputs(
        [detector(DetectorKind.VISUAL, score=0.75)]
    )

    assert result.score == 75
    assert result.confidence == 0.4
    assert result.label is LabelKey.MEDIUM
    assert result.evidence_status == "sufficient"


def test_material_factor_reduces_confidence_only() -> None:
    result = aggregate_detector_outputs(
        [
            detector(
                DetectorKind.TEXT,
                score=0.8,
                confidence=1.0,
                material_factor=0.3,
            )
        ]
    )

    assert result.score == 80
    assert result.confidence == 0.15
    assert result.label is None
    assert result.evidence_status == "insufficient"


def test_zero_material_factor_is_unavailable_for_score() -> None:
    result = aggregate_detector_outputs(
        [
            detector(
                DetectorKind.TEXT,
                score=1.0,
                confidence=1.0,
                material_factor=0.0,
            ),
            detector(
                DetectorKind.VISUAL,
                score=0.5,
                confidence=1.0,
                material_factor=1.0,
            ),
        ]
    )

    assert result.score == 50
    assert result.confidence == 0.4
    assert result.label is LabelKey.LIGHT
    assert result.evidence_status == "sufficient"


def test_all_zero_material_factors_produce_insufficient_zero_result() -> None:
    result = aggregate_detector_outputs(
        [detector(DetectorKind.TEXT, score=1.0, material_factor=0.0)]
    )

    assert result == ScoreResult(
        score=0,
        confidence=0.0,
        label=None,
        evidence_status="insufficient",
    )


def test_internal_confidence_controls_sufficiency_before_api_rounding() -> None:
    result = aggregate_detector_outputs(
        [detector(DetectorKind.TEXT, score=0.8, confidence=0.79)]
    )

    assert result.confidence == 0.4
    assert result.evidence_status == "insufficient"
    assert result.label is None


def test_exact_confidence_threshold_is_sufficient() -> None:
    result = aggregate_detector_outputs(
        [detector(DetectorKind.TEXT, score=0.8, confidence=0.8)]
    )

    assert result.confidence == 0.4
    assert result.evidence_status == "sufficient"
    assert result.label is LabelKey.HIGH


@pytest.mark.parametrize(
    ("detector_score", "expected_score"),
    [(0.295, 30), (0.595, 60), (0.795, 80)],
)
def test_score_ties_round_half_up(
    detector_score: float,
    expected_score: int,
) -> None:
    result = aggregate_detector_outputs(
        [detector(DetectorKind.TEXT, score=detector_score)]
    )

    assert result.score == expected_score


def test_duplicate_detector_kinds_are_rejected() -> None:
    duplicate: dict[str, object] = {
        "kind": "text",
        "score": 0.9,
        "confidence": 1.0,
        "material_factor": 1.0,
    }

    with pytest.raises(InvalidDetectorOutput) as error:
        aggregate_detector_outputs(
            [detector(DetectorKind.TEXT, score=0.1), duplicate]
        )

    assert error.value.raw_input is duplicate
    assert error.value.reason == "duplicate detector kind: text"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score", math.nan),
        ("score", math.inf),
        ("score", -math.inf),
        ("score", -0.01),
        ("score", 1.01),
        ("confidence", math.nan),
        ("confidence", math.inf),
        ("confidence", -0.01),
        ("confidence", 1.01),
        ("material_factor", math.nan),
        ("material_factor", math.inf),
        ("material_factor", -0.01),
        ("material_factor", 1.01),
    ],
)
def test_invalid_numeric_input_raises_typed_error(
    field: str,
    value: float,
) -> None:
    raw: dict[str, object] = {
        "kind": "text",
        "score": 0.5,
        "confidence": 0.5,
        "material_factor": 1.0,
    }
    raw[field] = value

    with pytest.raises(InvalidDetectorOutput) as error:
        aggregate_detector_outputs([raw])

    assert error.value.raw_input is raw
    assert error.value.reason == "invalid detector output"
    assert error.value.validation_errors
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    "model",
    [
        EvidenceItem(description="AI generation disclosed"),
        detector(DetectorKind.TEXT, score=0.5, confidence=0.5),
        ScoreResult(
            score=50,
            confidence=0.5,
            label=LabelKey.LIGHT,
            evidence_status="sufficient",
        ),
    ],
)
def test_domain_models_are_immutable(model: BaseModel) -> None:
    field_name = next(iter(type(model).model_fields))

    with pytest.raises(ValidationError):
        setattr(model, field_name, None)


def test_detector_evidence_is_stored_as_an_immutable_tuple() -> None:
    evidence = EvidenceItem(description="AI production method disclosed")
    output = DetectorOutput(
        kind=DetectorKind.TEXT,
        score=0.5,
        confidence=0.5,
        material_factor=1.0,
        evidence=[evidence],
    )

    assert output.evidence == (evidence,)
    with pytest.raises(AttributeError):
        output.evidence.append(EvidenceItem(description="other"))


def test_declaration_states_have_stable_serialized_values() -> None:
    assert [state.value for state in DeclarationState] == [
        "declared_ai",
        "not_declared",
        "unknown",
    ]
