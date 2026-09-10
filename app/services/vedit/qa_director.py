from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QAIssue:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class QAResult:
    passed: bool
    ready_for_render: bool
    issues: tuple[QAIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "ready_for_render": self.ready_for_render,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def run_qa(
    *,
    clips: list[dict[str, Any]],
    duration_seconds: float,
    min_duration_seconds: float,
    max_duration_seconds: float,
    require_audio: bool = True,
    require_video: bool = True,
) -> QAResult:
    """QA editorial antes de liberar o EditPlan para render."""

    issues: list[QAIssue] = []

    if duration_seconds < min_duration_seconds:
        issues.append(
            QAIssue(
                "DURATION_TOO_SHORT",
                "ERROR",
                "Duração abaixo do mínimo editorial.",
            )
        )

    if duration_seconds > max_duration_seconds:
        issues.append(
            QAIssue(
                "DURATION_TOO_LONG",
                "ERROR",
                "Duração acima do máximo editorial.",
            )
        )

    if require_video and not clips:
        issues.append(
            QAIssue(
                "NO_VIDEO",
                "ERROR",
                "Nenhum clip de vídeo foi produzido.",
            )
        )

    for clip in clips:
        path = clip.get("media_path") or clip.get("file_path")

        if not isinstance(path, str) or not path.strip():
            issues.append(
                QAIssue(
                    "NO_MEDIA_PATH",
                    "ERROR",
                    "Clip não possui mídia real.",
                )
            )

        start = float(clip.get("source_start_seconds", 0.0))
        end = float(clip.get("source_end_seconds", 0.0))

        if end <= start:
            issues.append(
                QAIssue(
                    "SOURCE_RANGE_INVALID",
                    "ERROR",
                    "Range de origem inválido.",
                )
            )

    if require_audio:
        has_audio = any(
            str(clip.get("track", "")).startswith("A")
            for clip in clips
        )

        if not has_audio:
            issues.append(
                QAIssue(
                    "NO_AUDIO_LAYER",
                    "WARNING",
                    "Nenhuma camada de áudio foi associada ao EditPlan.",
                )
            )

    errors = any(issue.severity == "ERROR" for issue in issues)

    return QAResult(
        passed=not errors,
        ready_for_render=not errors,
        issues=tuple(issues),
    )
