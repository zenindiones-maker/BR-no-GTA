"""Núcleo editorial profissional do VEDIT."""

from app.services.vedit.candidate_scoring import (
    CandidateScore,
    score_candidate,
)
from app.services.vedit.editorial_matching import (
    EditorialMatch,
    match_candidate,
)
from app.services.vedit.cut_engine import (
    CutDecision,
    build_cut,
)
from app.services.vedit.rhythm_engine import (
    RhythmDecision,
    build_rhythm,
)
from app.services.vedit.transition_director import (
    TransitionDecision,
    choose_transition,
)
from app.services.vedit.audio_director import (
    AudioDecision,
    build_audio_plan,
)
from app.services.vedit.caption_director import (
    CaptionDecision,
    build_caption_plan,
)
from app.services.vedit.graphics_director import (
    GraphicDecision,
    build_graphics_plan,
)
from app.services.vedit.timeline_builder import (
    TimelineDecision,
    build_timeline,
)
from app.services.vedit.qa_director import (
    QAIssue,
    QAResult,
    run_qa,
)

__all__ = [
    "CandidateScore",
    "score_candidate",
    "EditorialMatch",
    "match_candidate",
    "CutDecision",
    "build_cut",
    "RhythmDecision",
    "build_rhythm",
    "TransitionDecision",
    "choose_transition",
    "AudioDecision",
    "build_audio_plan",
    "CaptionDecision",
    "build_caption_plan",
    "GraphicDecision",
    "build_graphics_plan",
    "TimelineDecision",
    "build_timeline",
    "QAIssue",
    "QAResult",
    "run_qa",
]
