from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from typing import Any

from app.services.edit_plan_service import (
    EditAudio,
    EditClip,
    EditEffect,
    EditPlan,
    EditQA,
    EditText,
    EditTrack,
    EditTransition,
)

from app.services.vedit import (
    build_audio_plan,
    build_caption_plan,
    build_cut,
    build_graphics_plan,
    build_rhythm,
    build_timeline,
    choose_transition,
    match_candidate,
    run_qa,
    score_candidate,
)


class VEditError(RuntimeError):
    """Erro operacional do VEDIT."""


@dataclass(frozen=True)
class VEditBrainContext:
    action: str
    reason: str
    priority: str
    confidence: float

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any] | None,
    ) -> "VEditBrainContext":
        value = value or {}

        return cls(
            action=str(value.get("action", "EXECUTION")),
            reason=str(
                value.get(
                    "reason",
                    "Execução audiovisual autorizada pelo GTA6 Brain.",
                )
            ),
            priority=str(value.get("priority", "MEDIUM")),
            confidence=float(value.get("confidence", 1.0)),
        )


@dataclass(frozen=True)
class VEditPolicy:
    max_scene_duration_seconds: float = 8.0
    default_transition_seconds: float = 0.18
    hook_duration_seconds: float = 4.0
    caption_font_size: int = 52

    enable_transitions: bool = True
    enable_captions: bool = True
    enable_title_card: bool = True
    require_real_media: bool = True

    # VEDIT editorial scoring.
    semantic_relevance_weight: float = 0.30
    editorial_relevance_weight: float = 0.25
    visual_quality_weight: float = 0.15
    motion_weight: float = 0.10
    audio_energy_weight: float = 0.05
    narrative_fit_weight: float = 0.15

    @classmethod
    def from_brain(
        cls,
        brain: VEditBrainContext,
    ) -> "VEditPolicy":
        if brain.priority == "CRITICAL":
            return cls(
                max_scene_duration_seconds=5.0,
                default_transition_seconds=0.12,
                hook_duration_seconds=3.0,
            )

        if brain.priority == "HIGH":
            return cls(
                max_scene_duration_seconds=6.0,
                default_transition_seconds=0.15,
                hook_duration_seconds=3.5,
            )

        return cls()


def _call_core(
    function: Any,
    kwargs: dict[str, Any],
) -> Any:
    """
    Chamada compatível com o núcleo VEDIT.

    Filtra somente argumentos suportados pela implementação instalada.
    Isso permite evoluir os Directors sem quebrar o contrato do facade.
    """
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(**kwargs)

    parameters = signature.parameters

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return function(**kwargs)

    accepted = {
        key: value
        for key, value in kwargs.items()
        if key in parameters
    }

    return function(**accepted)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)

    if hasattr(value, "to_dict"):
        result = value.to_dict()
        if isinstance(result, dict):
            return dict(result)

    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        result = asdict(value)
        if isinstance(result, dict):
            return dict(result)

    return {}


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, number))


def _candidate_from_scene(
    scene: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """
    Normaliza uma cena do Production Plan para o contrato de candidato
    utilizado pelos Directors do VEDIT.
    """
    visual_type = str(
        scene.get("visual_type") or ""
    ).lower()

    role = str(
        scene.get("role")
        or scene.get("narrative_block")
        or ""
    ).strip()

    candidate = dict(scene)

    candidate.setdefault(
        "semantic_relevance",
        scene.get("information_value", 0.5),
    )
    candidate.setdefault(
        "editorial_relevance",
        scene.get("editorial_relevance", 0.5),
    )
    candidate.setdefault(
        "visual_quality",
        scene.get("visual_value", 0.5),
    )
    candidate.setdefault(
        "motion",
        scene.get("motion_score", 0.5),
    )
    candidate.setdefault(
        "audio_energy",
        scene.get("audio_energy", 0.5),
    )
    candidate.setdefault(
        "narrative_fit",
        scene.get("narrative_fit", 0.5),
    )

    # Contrato temporal do VEDIT Cut Engine.
    # Production Plan usa source_start/source_end; o candidato
    # precisa expor a mesma janela como start_seconds/end_seconds.
    source_start = scene.get(
        "source_start_seconds",
        scene.get("start_seconds", 0.0),
    )
    source_end = scene.get(
        "source_end_seconds",
        scene.get("end_seconds"),
    )

    if source_end is None:
        try:
            source_end = float(source_start) + float(
                scene.get("duration_seconds", 0.0) or 0.0
            )
        except (TypeError, ValueError):
            source_end = source_start

    candidate["start_seconds"] = float(source_start or 0.0)
    candidate["end_seconds"] = float(source_end or 0.0)
    candidate["role"] = role or "content"
    candidate["visual_type"] = visual_type
    candidate["candidate_index"] = index

    return candidate


def _infer_role(
    scene: dict[str, Any],
    *,
    index: int,
) -> str:
    explicit = str(
        scene.get("role") or ""
    ).strip()

    if explicit:
        return explicit.lower()

    block = str(
        scene.get("narrative_block") or ""
    ).lower()

    aliases = {
        "intro": "hook",
        "introduction": "hook",
        "hook": "hook",
        "context": "context",
        "development": "development",
        "impact": "impact",
        "conclusion": "conclusion",
        "cta": "cta",
    }

    if block in aliases:
        return aliases[block]

    visual_type = str(
        scene.get("visual_type") or ""
    ).lower()

    if index == 1:
        return "hook"

    if "gameplay" in visual_type:
        return "gameplay"

    if "graphic" in visual_type:
        return "graphic"

    if "title" in visual_type:
        return "title"

    return "b_roll"


def _infer_fit(
    scene: dict[str, Any],
    *,
    video_format: str,
) -> str:
    explicit_fit = scene.get("fit")

    if explicit_fit in {
        "contain",
        "cover",
        "stretch",
        "none",
    }:
        return explicit_fit

    return "cover"


def _extract_real_media_source(
    scene: dict[str, Any],
    *,
    require_real_media: bool,
) -> dict[str, Any]:
    media_path = str(
        scene.get("file_path")
        or scene.get("media_path")
        or ""
    ).strip()

    if require_real_media and not media_path:
        raise VEditError(
            "VEDIT exige mídia real. "
            "A cena não possui file_path/media_path."
        )

    if not media_path:
        raise VEditError(
            "Cena sem mídia audiovisual."
        )

    if require_real_media and not os.path.isfile(media_path):
        raise VEditError(
            "VEDIT encontrou uma referência de mídia, "
            f"mas o arquivo não existe: {media_path}"
        )

    source_start = float(
        scene.get("source_start_seconds") or 0.0
    )

    source_end_value = scene.get(
        "source_end_seconds"
    )

    if source_end_value is None:
        source_end = (
            source_start
            + float(scene["duration_seconds"])
        )
    else:
        source_end = float(source_end_value)

    if source_start < 0:
        raise VEditError(
            "source_start_seconds não pode ser negativo."
        )

    if source_end <= source_start:
        raise VEditError(
            "source_end_seconds deve ser maior que source_start_seconds."
        )

    segment_id = scene.get("segment_id")

    if segment_id is not None:
        segment_id = _positive_int(
            segment_id,
            "segment_id",
        )

    return {
        "segment_id": segment_id,
        "media_path": media_path,
        "source_start_seconds": source_start,
        "source_end_seconds": source_end,
    }


def _score_and_match(
    *,
    candidate: dict[str, Any],
    narrative_role: str,
    narrative_block: dict[str, Any] | None,
    objective: str,
    policy: VEditPolicy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    weights = {
        "semantic_relevance": policy.semantic_relevance_weight,
        "editorial_relevance": policy.editorial_relevance_weight,
        "visual_quality": policy.visual_quality_weight,
        "motion": policy.motion_weight,
        "audio_energy": policy.audio_energy_weight,
        "narrative_fit": policy.narrative_fit_weight,
    }

    score = _call_core(
        score_candidate,
        {
            "candidate": candidate,
            "narrative_role": narrative_role,
            "narrative_block": narrative_block,
            "weights": weights,
        },
    )

    match = _call_core(
        match_candidate,
        {
            "candidate": candidate,
            "narrative_role": narrative_role,
            "visual_type": candidate.get("visual_type"),
            "objective": objective,
        },
    )

    return (
        _as_dict(score),
        _as_dict(match),
    )


def _build_audio_layers(
    *,
    production_plan: dict[str, Any],
    duration_seconds: float,
) -> tuple[list[EditAudio], dict[str, Any]]:
    """
    Usa o Audio Director para definir a arquitetura A1/A2/A3/A4,
    mas só materializa arquivos que realmente existem.
    """
    requirements = list(
        production_plan.get(
            "audio_requirements"
        )
        or []
    )

    has_narration = bool(
        production_plan.get("narration")
        or any(
            isinstance(item, dict)
            and str(item.get("type") or "").lower()
            in {"voice", "voiceover", "narration"}
            for item in requirements
        )
    )

    has_music = any(
        isinstance(item, dict)
        and str(item.get("type") or "").lower()
        in {"music", "bgm", "trilha"}
        for item in requirements
    )

    has_sfx = any(
        isinstance(item, dict)
        and str(item.get("type") or "").lower()
        in {"sfx", "sound_effect", "effect"}
        for item in requirements
    )

    has_ambience = any(
        isinstance(item, dict)
        and str(item.get("type") or "").lower()
        in {"ambience", "ambience", "ambient"}
        for item in requirements
    )

    audio_director = _call_core(
        build_audio_plan,
        {
            "narration_present": has_narration,
            "music_present": has_music,
            "sfx_present": has_sfx,
            "ambience_present": has_ambience,
        },
    )

    audio_metadata: dict[str, Any] = {
        "director": "audio_director",
        "plan": _as_dict(audio_director),
        "tracks": {
            "A1": "VOICE",
            "A2": "MUSIC",
            "A3": "SFX",
            "A4": "AMBIENCE",
        },
    }

    result: list[EditAudio] = []

    for item in requirements:
        if not isinstance(item, dict):
            continue

        media_path = str(
            item.get("file_path")
            or item.get("media_path")
            or ""
        ).strip()

        if not media_path or not os.path.isfile(media_path):
            continue

        kind = str(
            item.get("type")
            or item.get("role")
            or "music"
        ).lower()

        track = "A2"

        if kind in {
            "voice",
            "voiceover",
            "narration",
            "dialogue",
        }:
            track = "A1"
        elif kind in {
            "sfx",
            "sound_effect",
            "effect",
        }:
            track = "A3"
        elif kind in {
            "ambience",
            "ambient",
        }:
            track = "A4"

        duration = item.get(
            "duration_seconds"
        )

        if duration is None:
            duration = duration_seconds

        result.append(
            EditAudio(
                media_path=media_path,
                track=track,
                start_seconds=float(
                    item.get("start_seconds") or 0.0
                ),
                source_start_seconds=float(
                    item.get(
                        "source_start_seconds"
                    )
                    or 0.0
                ),
                duration_seconds=float(duration),
                volume=float(
                    item.get("volume", 1.0)
                ),
                fade_in_seconds=float(
                    item.get(
                        "fade_in_seconds"
                    )
                    or 0.0
                ),
                fade_out_seconds=float(
                    item.get(
                        "fade_out_seconds"
                    )
                    or 0.0
                ),
            )
        )

    return result, audio_metadata


def create_edit_plan(
    *,
    production_plan: dict[str, Any],
    brain_decision: dict[str, Any] | None = None,
    policy: VEditPolicy | None = None,
) -> EditPlan:
    """
    Editor Orchestrator profissional do VEDIT.

    O Brain determina a estratégia.
    O Production Plan determina a narrativa.
    O VEDIT decide como transformar mídia real em montagem.

    Fluxo efetivo:

        Candidate Scoring
            ↓
        Editorial Matching
            ↓
        Cut Engine
            ↓
        Rhythm Engine
            ↓
        Audio Director
            ↓
        Caption Director
            ↓
        Graphics Director
            ↓
        Transition Director
            ↓
        Timeline Builder
            ↓
        EditPlan
            ↓
        QA Director

    Não baixa mídia.
    Não executa FFmpeg.
    Não renderiza.
    Não publica.
    """
    _validate_production_plan(
        production_plan
    )

    brain = VEditBrainContext.from_dict(
        brain_decision
    )

    policy = (
        policy
        or VEditPolicy.from_brain(brain)
    )

    content_item_id = _positive_int(
        production_plan["content_item_id"],
        "content_item_id",
    )

    script_id = _positive_int(
        production_plan["script_id"],
        "script_id",
    )

    title = str(
        production_plan.get("title")
        or f"Vídeo do Content Item {content_item_id}"
    ).strip()

    objective = str(
        production_plan["objective"]
    ).strip()

    video_format = str(
        production_plan["format"]
    ).strip()

    scenes = list(
        production_plan["scenes"]
    )

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    # Trace editorial auditável do VEDIT.
    # Cada candidato avaliado permanece rastreável no EditPlan.
    scoring_trace: list[dict[str, Any]] = []

    # ---------------------------------------------------------
    # 1. INTELLIGENCE + SCORING + EDITORIAL MATCHING
    # ---------------------------------------------------------
    for index, scene in enumerate(
        scenes,
        start=1,
    ):
        _validate_scene(
            scene,
            index=index,
        )

        candidate = _candidate_from_scene(
            scene,
            index,
        )

        role = _infer_role(
            scene,
            index=index,
        )

        narrative_block = scene.get(
            "narrative_block"
        )

        score, match = _score_and_match(
            candidate=candidate,
            narrative_role=role,
            narrative_block=(
                narrative_block
                if isinstance(
                    narrative_block,
                    dict,
                )
                else None
            ),
            objective=objective,
            policy=policy,
        )

        total_score = float(
            score.get(
                "total",
                score.get(
                    "score",
                    0.0,
                ),
            )
            or 0.0
        )

        match_score = float(
            match.get(
                "score",
                0.0,
            )
            or 0.0
        )

        editorial_score = (
            total_score * 0.70
            + match_score * 0.30
        )

        candidate["_vedit_score"] = {
            "candidate_score": total_score,
            "editorial_match": match_score,
            "combined": editorial_score,
            "score_detail": score,
            "match_detail": match,
        }

        candidate["_vedit_role"] = role

        scoring_trace.append(
            {
                "scene_index": index,
                "candidate_index": candidate.get(
                    "candidate_index",
                    index,
                ),
                "role": role,
                "visual_type": candidate.get(
                    "visual_type",
                ),
                "score": {
                    "candidate_score": total_score,
                    "editorial_match": match_score,
                    "combined": editorial_score,
                },
                "score_detail": score,
                "match_detail": match,
                "selected": True,
                "reason": (
                    "candidato válido avaliado pelo "
                    "Candidate Scoring + Editorial Matching"
                ),
            }
        )

        # Não elimina mídia válida por um score baixo.
        # O score ordena a prioridade editorial.
        selected.append(candidate)

    # ---------------------------------------------------------
    # 2. EDITORIAL ORDER
    # ---------------------------------------------------------
    selected.sort(
        key=lambda item: (
            0
            if item["_vedit_role"] == "hook"
            else 1,
            -float(
                item["_vedit_score"]["combined"]
            ),
            int(
                item.get(
                    "order",
                    item.get(
                        "candidate_index",
                        0,
                    ),
                )
            ),
        )
    )

    # Preserva hook no início e mantém coerência narrativa.
    hooks = [
        item
        for item in selected
        if item["_vedit_role"] == "hook"
    ]

    others = [
        item
        for item in selected
        if item["_vedit_role"] != "hook"
    ]

    selected = (
        hooks[:1]
        + others
    )

    target_duration = float(
        production_plan.get(
            "estimated_duration_seconds"
        )
        or 0.0
    )

    if target_duration <= 0:
        raise VEditError(
            "estimated_duration_seconds deve ser positivo."
        )

    # ---------------------------------------------------------
    # 3. CUT + RHYTHM + TIMELINE
    # ---------------------------------------------------------
    video_clips: list[EditClip] = []
    texts: list[EditText] = []
    transitions: list[EditTransition] = []
    effects: list[EditEffect] = []

    timeline_inputs: list[dict[str, Any]] = []

    current_time = 0.0
    previous_segment_id: int | None = None
    previous_role: str | None = None

    decisions: list[dict[str, Any]] = []

    for index, candidate in enumerate(
        selected,
        start=1,
    ):
        scene = candidate

        source = _extract_real_media_source(
            scene,
            require_real_media=policy.require_real_media,
        )

        narrative_role = str(
            candidate.get(
                "_vedit_role",
                "content",
            )
        )

        available_duration = (
            source["source_end_seconds"]
            - source["source_start_seconds"]
        )

        max_duration = min(
            available_duration,
            policy.max_scene_duration_seconds,
        )

        target_scene_duration = min(
            float(
                scene["duration_seconds"]
            ),
            max_duration,
        )

        if narrative_role == "hook":
            target_scene_duration = min(
                target_scene_duration,
                policy.hook_duration_seconds,
            )

        rhythm = _call_core(
            build_rhythm,
            {
                "narrative_role": narrative_role,
                "requested_duration_seconds": target_scene_duration,
                "format_name": video_format,
                "priority": brain.priority,
                "beat_available": bool(
                    scene.get("beat_times")
                    or scene.get("beat_available", False)
                ),
                "pause_seconds": float(
                    scene.get("pause_seconds", 0.0)
                    or 0.0
                ),
            },
        )

        rhythm_data = _as_dict(
            rhythm
        )

        rhythm_duration = rhythm_data.get(
            "duration_seconds"
        )

        if rhythm_duration is not None:
            try:
                target_scene_duration = min(
                    target_scene_duration,
                    float(rhythm_duration),
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

        target_scene_duration = max(
            0.05,
            min(
                target_scene_duration,
                available_duration,
            ),
        )

        cut = _call_core(
            build_cut,
            {
                "candidate": candidate,
                "target_duration_seconds": target_scene_duration,
                "max_duration_seconds": max_duration,
                "narrative_role": narrative_role,
            },
        )

        cut_data = _as_dict(
            cut
        )

        source_start = float(
            cut_data.get(
                "source_start_seconds",
                source["source_start_seconds"],
            )
        )

        duration = float(
            cut_data.get(
                "duration_seconds",
                target_scene_duration,
            )
        )

        duration = min(
            duration,
            available_duration,
            max_duration,
        )

        if duration <= 0:
            rejected.append(
                {
                    "scene_index": index,
                    "reason": "cut_duration_invalid",
                }
            )
            continue

        segment_id = source.get(
            "segment_id"
        )

        clip = EditClip(
            segment_id=segment_id,
            media_path=source["media_path"],
            track="V1",
            start_seconds=current_time,
            source_start_seconds=source_start,
            duration_seconds=duration,
            role=narrative_role,
            fit=_infer_fit(
                scene,
                video_format=video_format,
            ),
        )

        video_clips.append(
            clip
        )

        narration = str(
            scene.get("narration")
            or ""
        ).strip()

        if (
            narration
            and policy.enable_captions
        ):
            caption = _call_core(
                build_caption_plan,
                {
                    "text": narration,
                    "start_seconds": current_time,
                    "duration_seconds": duration,
                    "narrative_role": narrative_role,
                    "font_size": policy.caption_font_size,
                    "position": "safe_center",
                    "transcript_words": scene.get(
                        "transcript_words"
                    ),
                },
            )

            caption_data = _as_dict(
                caption
            )

            if caption_data:
                texts.append(
                    EditText(
                        text=str(
                            caption_data.get(
                                "text",
                                narration,
                            )
                        ),
                        start_seconds=float(
                            caption_data.get(
                                "start_seconds",
                                current_time,
                            )
                        ),
                        duration_seconds=min(
                            duration,
                            float(
                                caption_data.get(
                                    "duration_seconds",
                                    duration,
                                )
                            ),
                        ),
                        track="T1",
                        font_size=int(
                            caption_data.get(
                                "font_size",
                                policy.caption_font_size,
                            )
                        ),
                        color=str(
                            caption_data.get(
                                "color",
                                "white",
                            )
                        ),
                        align=str(
                            caption_data.get(
                                "position",
                                "center",
                            )
                        ),
                        box=True,
                    )
                )

        # Graphics Director.
        graphics = _call_core(
            build_graphics_plan,
            {
                "narrative_role": narrative_role,
                "start_seconds": current_time,
                "duration_seconds": duration,
                "title": title,
                "narration": narration,
                "visual_type": scene.get(
                    "visual_type"
                ),
                "objective": objective,
            },
        )

        # Graphics Director.
        #
        # build_graphics_plan() retorna uma coleção de
        # GraphicDecision. Cada decisão gráfica deve ser
        # materializada como um EditEffect associado ao
        # segmento correspondente.
        #
        # Não reduzimos o resultado para um único dict:
        # um segmento pode possuir múltiplas decisões gráficas.
        graphics_decisions = (
            graphics
            if isinstance(graphics, (tuple, list))
            else (graphics,)
        )

        for graphic in graphics_decisions:
            graphics_data = _as_dict(graphic)

            if not graphics_data:
                continue

            graphic_kind = str(
                graphics_data.get(
                    "kind",
                    "",
                )
            ).strip()

            if (
                graphic_kind
                and segment_id is not None
            ):
                effects.append(
                    EditEffect(
                        segment_id=segment_id,
                        name=(
                            "vedit_graphic:"
                            + graphic_kind
                        ),
                        params=graphics_data,
                    )
                )

        # Transition Director.
        if (
            policy.enable_transitions
            and previous_segment_id is not None
            and segment_id is not None
        ):
            transition = _call_core(
                choose_transition,
                {
                    "previous_scene": (
                        None
                        if previous_role is None
                        else {
                            "role": previous_role,
                        }
                    ),
                    "current_scene": scene,
                    "previous_role": previous_role,
                    "current_role": narrative_role,
                    "narrative_change": (
                        previous_role != narrative_role
                    ),
                    "enable_transitions": True,
                },
            )

            transition_data = _as_dict(
                transition
            )

            transition_type = str(
                transition_data.get(
                    "type",
                    "cut",
                )
            )

            transition_duration = float(
                transition_data.get(
                    "duration_seconds",
                    0.0,
                )
                or 0.0
            )

            transition_duration = min(
                transition_duration,
                duration / 2,
            )

            transitions.append(
                EditTransition(
                    from_segment_id=previous_segment_id,
                    to_segment_id=segment_id,
                    type=transition_type,
                    duration_seconds=transition_duration,
                )
            )

        timeline_inputs.append(
            {
                "start_seconds": current_time,
                "end_seconds": current_time + duration,
                "duration_seconds": duration,
                "track": "V1",
                "segment_id": segment_id,
                "role": narrative_role,
                "reason": (
                    "VEDIT: "
                    f"score={candidate['_vedit_score']['combined']:.4f}; "
                    f"cut={source_start:.3f}+{duration:.3f}; "
                    f"rhythm={rhythm_data.get('reason', '')}"
                ),
            }
        )

        decisions.append(
            {
                "scene_index": index,
                "role": narrative_role,
                "score": candidate[
                    "_vedit_score"
                ],
                "cut": cut_data,
                "rhythm": rhythm_data,
                "media_path": source["media_path"],
                "source_start_seconds": source_start,
                "duration_seconds": duration,
            }
        )

        previous_segment_id = segment_id
        previous_role = narrative_role
        current_time += duration

    if not video_clips:
        raise VEditError(
            "VEDIT não produziu nenhum clip."
        )

    duration_seconds = current_time

    # Timeline Director.
    timeline = _call_core(
        build_timeline,
        {
            "decisions": timeline_inputs,
        },
    )

    timeline_data = _as_dict(
        timeline
    )

    # Audio Director.
    audio, audio_metadata = _build_audio_layers(
        production_plan=production_plan,
        duration_seconds=duration_seconds,
    )

    tracks = [
        EditTrack(
            name="V1",
            kind="video",
            clips=tuple(video_clips),
        )
    ]

    if audio:
        tracks.append(
            EditTrack(
                name="A1",
                kind="audio",
                clips=(),
            )
        )

    if texts:
        tracks.append(
            EditTrack(
                name="T1",
                kind="text",
                clips=(),
            )
        )

    # QA Director.
    # O contrato do QA trabalha com dicts de clips e valida
    # explicitamente mídia, range de origem e camada de vídeo.
    qa_clips = [
        {
            "media_path": clip.media_path,
            "track": clip.track,
            "start_seconds": clip.start_seconds,
            "source_start_seconds": clip.source_start_seconds,
            "source_end_seconds": (
                clip.source_start_seconds
                + clip.duration_seconds
            ),
            "duration_seconds": clip.duration_seconds,
            "segment_id": clip.segment_id,
            "role": clip.role,
        }
        for clip in video_clips
    ]

    # A camada de áudio é validada pelo QA como parte do conjunto
    # de clips. Quando houver áudio real, representamos suas camadas
    # explicitamente para que require_audio=True seja verificável.
    for audio_clip in audio:
        qa_clips.append(
            {
                "media_path": audio_clip.media_path,
                "track": audio_clip.track,
                "start_seconds": audio_clip.start_seconds,
                "source_start_seconds": (
                    audio_clip.source_start_seconds
                ),
                "source_end_seconds": (
                    audio_clip.source_start_seconds
                    + (
                        audio_clip.duration_seconds
                        if audio_clip.duration_seconds is not None
                        else duration_seconds
                    )
                ),
                "duration_seconds": (
                    audio_clip.duration_seconds
                    if audio_clip.duration_seconds is not None
                    else duration_seconds
                ),
            }
        )

    qa_director = _call_core(
        run_qa,
        {
            "clips": qa_clips,
            "duration_seconds": duration_seconds,
            "min_duration_seconds": max(
                0.1,
                target_duration * 0.90,
            ),
            "max_duration_seconds": (
                target_duration * 1.10
            ),
            "require_audio": True,
            "require_video": True,
        },
    )

    qa_data = _as_dict(
        qa_director
    )

    if qa_data.get(
        "ready_for_render"
    ) is False:
        issues = qa_data.get(
            "issues",
            [],
        )

        errors = [
            item
            for item in issues
            if isinstance(item, dict)
            and str(
                item.get(
                    "severity",
                    "",
                )
            ).upper()
            == "ERROR"
        ]

        if errors:
            raise VEditError(
                "QA do VEDIT bloqueou o render: "
                + "; ".join(
                    str(
                        item.get(
                            "message",
                            item,
                        )
                    )
                    for item in errors
                )
            )

    qa = EditQA(
        min_duration_seconds=max(
            0.1,
            target_duration * 0.90,
        ),
        max_duration_seconds=(
            target_duration * 1.10
        ),
        require_audio=True,
        require_video=True,
        require_valid_container=True,
        require_no_missing_media=True,
    )

    metadata = {
        "controller": "gta6_brain",
        "orchestrator": "deepseek_harness",
        "editor": "vedit",
        "edit_plan_version": "1",

        "brain_action": brain.action,
        "brain_reason": brain.reason,
        "brain_priority": brain.priority,
        "brain_confidence": brain.confidence,

        "editing_policy": {
            "max_scene_duration_seconds": (
                policy.max_scene_duration_seconds
            ),
            "default_transition_seconds": (
                policy.default_transition_seconds
            ),
            "hook_duration_seconds": (
                policy.hook_duration_seconds
            ),
            "scoring_weights": {
                "semantic_relevance": (
                    policy.semantic_relevance_weight
                ),
                "editorial_relevance": (
                    policy.editorial_relevance_weight
                ),
                "visual_quality": (
                    policy.visual_quality_weight
                ),
                "motion": policy.motion_weight,
                "audio_energy": (
                    policy.audio_energy_weight
                ),
                "narrative_fit": (
                    policy.narrative_fit_weight
                ),
            },
        },

        "professional_editing": True,
        "vedit_engine": "professional_editor_orchestrator",

        # Scoring auditável produzido pelo VEDIT.
        "scoring": {
            "method": (
                "candidate_scoring_plus_editorial_matching"
            ),
            "weights": {
                "semantic_relevance": (
                    policy.semantic_relevance_weight
                ),
                "editorial_relevance": (
                    policy.editorial_relevance_weight
                ),
                "visual_quality": (
                    policy.visual_quality_weight
                ),
                "motion": policy.motion_weight,
                "audio_energy": (
                    policy.audio_energy_weight
                ),
                "narrative_fit": (
                    policy.narrative_fit_weight
                ),
            },
            "combination": {
                "candidate_score_weight": 0.70,
                "editorial_match_weight": 0.30,
            },
            "candidates": scoring_trace,
            "candidate_count": len(scoring_trace),
            "selected_count": len(selected),
            "rejected_count": len(rejected),
        },

        "scene_count": len(video_clips),
        "transition_count": len(transitions),
        "text_count": len(texts),
        "audio_layer_count": len(audio),

        "editorial_decisions": decisions,
        "rejected_candidates": rejected,

        "timeline": timeline_data,
        "audio_director": audio_metadata,
        "qa_director": qa_data,

        "ready_for_render": (
            qa_data.get(
                "ready_for_render",
                True,
            )
            is not False
        ),
    }

    return EditPlan(
        version="1",
        content_item_id=content_item_id,
        script_id=script_id,
        title=title,
        objective=objective,
        format=video_format,
        duration_seconds=duration_seconds,
        tracks=tuple(tracks),
        texts=tuple(texts),
        audio=tuple(audio),
        transitions=tuple(transitions),
        effects=tuple(effects),
        qa=qa,
        metadata=metadata,
    )


def apply_edit_plan_to_video_spec(
    *,
    video_spec: dict[str, Any],
    edit_plan: EditPlan,
) -> dict[str, Any]:
    """Transporta o EditPlan para o Video Spec."""
    if (
        not isinstance(video_spec, dict)
        or not video_spec
    ):
        raise VEditError(
            "Video Spec inválida."
        )

    result = dict(video_spec)

    result["edit_plan"] = (
        edit_plan.to_dict()
    )

    result["estimated_duration_seconds"] = (
        edit_plan.duration_seconds
    )

    result["status"] = "ready"

    return result


def build_brain_context(
    *,
    action: str,
    reason: str,
    priority: str,
    confidence: float,
) -> dict[str, Any]:
    return {
        "action": str(action),
        "reason": str(reason),
        "priority": str(priority),
        "confidence": float(confidence),
    }


def _validate_production_plan(
    production_plan: dict[str, Any],
) -> None:
    if (
        not isinstance(
            production_plan,
            dict,
        )
        or not production_plan
    ):
        raise VEditError(
            "Production Plan inválido."
        )

    required_fields = (
        "content_item_id",
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "scenes",
    )

    for field in required_fields:
        if field not in production_plan:
            raise VEditError(
                "Production Plan não possui o campo obrigatório: "
                f"{field}."
            )

    if (
        not isinstance(
            production_plan["scenes"],
            list,
        )
        or not production_plan["scenes"]
    ):
        raise VEditError(
            "Production Plan precisa possuir cenas."
        )


def _validate_scene(
    scene: dict[str, Any],
    *,
    index: int,
) -> None:
    if not isinstance(scene, dict):
        raise VEditError(
            f"Cena {index} inválida."
        )

    required = (
        "order",
        "narrative_block",
        "narration",
        "visual_type",
        "visual_description",
        "duration_seconds",
    )

    for field in required:
        if field not in scene:
            raise VEditError(
                f"Cena {index} não possui o campo: {field}."
            )


def _positive_int(
    value: Any,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise VEditError(
            f"{field_name} deve ser um inteiro positivo."
        )

    return value
