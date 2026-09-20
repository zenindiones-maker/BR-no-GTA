from __future__ import annotations

from dataclasses import dataclass
from typing import Any

HUMAN_APPROVED_SEGMENT_STRATEGY = "semantic-section-v1"


@dataclass(frozen=True)
class NarrationPolicyDecision:
    status: str
    reasons: tuple[str, ...]
    baseline_strategy: str
    candidate_strategy: str
    baseline_segments: int
    candidate_segments: int
    baseline_proper_noun_splits: int
    candidate_proper_noun_splits: int
    human_quality_proven: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "NARRATION_POLICY_PROMOTION": self.status,
            "reasons": list(self.reasons),
            "baseline_strategy": self.baseline_strategy,
            "candidate_strategy": self.candidate_strategy,
            "baseline_segments": self.baseline_segments,
            "candidate_segments": self.candidate_segments,
            "baseline_proper_noun_splits": self.baseline_proper_noun_splits,
            "candidate_proper_noun_splits": self.candidate_proper_noun_splits,
            "human_quality_proven": self.human_quality_proven,
        }


def evaluate_narration_policy_promotion(
    *,
    baseline_strategy: str,
    candidate_strategy: str,
    baseline_segments: int,
    candidate_segments: int,
    baseline_proper_noun_splits: int,
    candidate_proper_noun_splits: int,
    human_quality_proven: bool = False,
) -> NarrationPolicyDecision:
    reasons: list[str] = []

    if baseline_strategy != HUMAN_APPROVED_SEGMENT_STRATEGY:
        reasons.append("BASELINE_NOT_HUMAN_APPROVED_SEMANTIC_SECTION")

    if candidate_strategy != HUMAN_APPROVED_SEGMENT_STRATEGY and not human_quality_proven:
        reasons.append("CANDIDATE_REINTRODUCES_NON_SEMANTIC_SEGMENTATION")

    if candidate_segments > baseline_segments and not human_quality_proven:
        reasons.append("CANDIDATE_INCREASES_SPEECH_FRAGMENTATION")

    if candidate_proper_noun_splits > baseline_proper_noun_splits and not human_quality_proven:
        reasons.append("CANDIDATE_INCREASES_PROPER_NOUN_SPLITS")

    if candidate_proper_noun_splits > 0 and not human_quality_proven:
        reasons.append("CANDIDATE_SPLITS_PROPER_NOUNS_ACROSS_TTS_CALLS")

    status = "BLOCKED" if reasons else "PASS"
    return NarrationPolicyDecision(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        baseline_strategy=baseline_strategy,
        candidate_strategy=candidate_strategy,
        baseline_segments=int(baseline_segments),
        candidate_segments=int(candidate_segments),
        baseline_proper_noun_splits=int(baseline_proper_noun_splits),
        candidate_proper_noun_splits=int(candidate_proper_noun_splits),
        human_quality_proven=bool(human_quality_proven),
    )
