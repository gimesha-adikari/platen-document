from __future__ import annotations

from platen_document.engine.language_policy import (
    FusedLanguageDetector,
    LanguageDecisionStatus,
    LanguageProbe,
    OCRLanguageMode,
    OCRLanguagePolicy,
)


def test_explicit_language_policy_preserves_canonical_codes() -> None:
    policy = OCRLanguagePolicy.from_request("eng+sin")
    assert policy.mode is OCRLanguageMode.EXPLICIT
    assert policy.languages == ("eng", "sin")
    assert policy.engine_expression == "eng+sin"


def test_auto_policy_is_distinct_from_explicit_selection() -> None:
    policy = OCRLanguagePolicy.from_request("auto", mode="AUTO", languages=["eng", "sin"])
    assert policy.mode is OCRLanguageMode.AUTO
    assert policy.languages == ("eng", "sin")


def test_detector_keeps_safe_undetermined_state_when_evidence_is_empty() -> None:
    detector = FusedLanguageDetector(initial_probes=1, normal_max_probes=1, expanded_max_probes=1, min_confidence=95)
    result = detector.detect(("eng", "sin"), lambda languages: LanguageProbe(languages, "", -1.0))
    assert result.status is LanguageDecisionStatus.UNDETERMINED
