from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class EditPlanError(ValueError):
    """Erro de validação de um EditPlan."""


@dataclass(frozen=True)
class EditClip:
    """Trecho audiovisual posicionado na timeline."""

    segment_id: int | None
    media_path: str
    track: str
    start_seconds: float
    source_start_seconds: float
    duration_seconds: float
    role: str = "content"
    fit: str = "cover"

    def __post_init__(self) -> None:
        if self.segment_id is not None and (
            not isinstance(self.segment_id, int)
            or isinstance(self.segment_id, bool)
            or self.segment_id <= 0
        ):
            raise EditPlanError(
                "segment_id deve ser um inteiro positivo ou None."
            )

        if not isinstance(self.media_path, str) or not self.media_path.strip():
            raise EditPlanError("media_path deve ser uma string não vazia.")

        if not isinstance(self.track, str) or not self.track.strip():
            raise EditPlanError("track deve ser uma string não vazia.")

        if self.start_seconds < 0:
            raise EditPlanError("start_seconds não pode ser negativo.")

        if self.source_start_seconds < 0:
            raise EditPlanError(
                "source_start_seconds não pode ser negativo."
            )

        if self.duration_seconds <= 0:
            raise EditPlanError(
                "duration_seconds deve ser maior que zero."
            )

        if not isinstance(self.role, str) or not self.role.strip():
            raise EditPlanError("role deve ser uma string não vazia.")

        if self.fit not in {"contain", "cover", "stretch", "none"}:
            raise EditPlanError(
                f"fit inválido: {self.fit!r}"
            )


@dataclass(frozen=True)
class EditTrack:
    """Trilha lógica da montagem."""

    name: str
    kind: str
    clips: tuple[EditClip, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise EditPlanError("Track name deve ser uma string não vazia.")

        if self.kind not in {"video", "audio", "text", "overlay"}:
            raise EditPlanError(
                f"Tipo de track inválido: {self.kind!r}"
            )


@dataclass(frozen=True)
class EditText:
    """Texto/legenda que deverá aparecer na montagem."""

    text: str
    start_seconds: float
    duration_seconds: float
    track: str = "T1"
    font_size: int = 64
    color: str = "white"
    align: str = "center"
    box: bool = False

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise EditPlanError("Texto não pode ser vazio.")

        if self.start_seconds < 0:
            raise EditPlanError(
                "Texto não pode começar antes de zero."
            )

        if self.duration_seconds <= 0:
            raise EditPlanError(
                "Duração do texto deve ser maior que zero."
            )

        if self.font_size <= 0:
            raise EditPlanError(
                "font_size deve ser maior que zero."
            )


@dataclass(frozen=True)
class EditAudio:
    """Direção de uma camada de áudio."""

    media_path: str
    track: str
    start_seconds: float = 0.0
    source_start_seconds: float = 0.0
    duration_seconds: float | None = None
    volume: float = 1.0
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.media_path.strip():
            raise EditPlanError(
                "media_path do áudio não pode ser vazio."
            )

        if not self.track.strip():
            raise EditPlanError(
                "track do áudio não pode ser vazia."
            )

        if self.start_seconds < 0:
            raise EditPlanError(
                "start_seconds do áudio não pode ser negativo."
            )

        if self.source_start_seconds < 0:
            raise EditPlanError(
                "source_start_seconds do áudio não pode ser negativo."
            )

        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise EditPlanError(
                "duration_seconds do áudio deve ser maior que zero."
            )

        if self.volume < 0:
            raise EditPlanError(
                "volume do áudio não pode ser negativo."
            )

        if self.fade_in_seconds < 0 or self.fade_out_seconds < 0:
            raise EditPlanError(
                "Fades de áudio não podem ser negativos."
            )


@dataclass(frozen=True)
class EditTransition:
    """Transição entre dois segmentos da montagem."""

    from_segment_id: int
    to_segment_id: int
    type: str = "dissolve"
    duration_seconds: float = 0.25

    def __post_init__(self) -> None:
        for field_name, value in (
            ("from_segment_id", self.from_segment_id),
            ("to_segment_id", self.to_segment_id),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise EditPlanError(
                    f"{field_name} deve ser um inteiro positivo."
                )

        if not self.type.strip():
            raise EditPlanError(
                "Tipo de transição não pode ser vazio."
            )

        if self.duration_seconds < 0:
            raise EditPlanError(
                "Duração da transição não pode ser negativa."
            )


@dataclass(frozen=True)
class EditEffect:
    """Efeito aplicado a um segmento da montagem."""

    segment_id: int
    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.segment_id, int)
            or isinstance(self.segment_id, bool)
            or self.segment_id <= 0
        ):
            raise EditPlanError(
                "segment_id deve ser um inteiro positivo."
            )

        if not self.name.strip():
            raise EditPlanError(
                "Nome do efeito não pode ser vazio."
            )


@dataclass(frozen=True)
class EditQA:
    """Critérios que o resultado final precisa satisfazer."""

    min_duration_seconds: float | None = None
    max_duration_seconds: float | None = None
    require_audio: bool = True
    require_video: bool = True
    require_valid_container: bool = True
    require_no_missing_media: bool = True

    def __post_init__(self) -> None:
        if (
            self.min_duration_seconds is not None
            and self.min_duration_seconds < 0
        ):
            raise EditPlanError(
                "min_duration_seconds não pode ser negativo."
            )

        if (
            self.max_duration_seconds is not None
            and self.max_duration_seconds <= 0
        ):
            raise EditPlanError(
                "max_duration_seconds deve ser maior que zero."
            )

        if (
            self.min_duration_seconds is not None
            and self.max_duration_seconds is not None
            and self.min_duration_seconds > self.max_duration_seconds
        ):
            raise EditPlanError(
                "min_duration_seconds não pode exceder max_duration_seconds."
            )


@dataclass(frozen=True)
class EditPlan:
    """Contrato independente do editor para uma montagem completa."""

    version: str
    content_item_id: int
    script_id: int
    title: str
    objective: str
    format: str
    duration_seconds: float
    tracks: tuple[EditTrack, ...]
    texts: tuple[EditText, ...] = ()
    audio: tuple[EditAudio, ...] = ()
    transitions: tuple[EditTransition, ...] = ()
    effects: tuple[EditEffect, ...] = ()
    qa: EditQA = field(default_factory=EditQA)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version != "1":
            raise EditPlanError(
                f"Versão de EditPlan não suportada: {self.version!r}"
            )

        if self.content_item_id <= 0:
            raise EditPlanError(
                "content_item_id deve ser positivo."
            )

        if self.script_id <= 0:
            raise EditPlanError(
                "script_id deve ser positivo."
            )

        if not self.title.strip():
            raise EditPlanError("title não pode ser vazio.")

        if not self.objective.strip():
            raise EditPlanError("objective não pode ser vazio.")

        if not self.format.strip():
            raise EditPlanError("format não pode ser vazio.")

        if self.duration_seconds <= 0:
            raise EditPlanError(
                "duration_seconds deve ser maior que zero."
            )

        if not self.tracks:
            raise EditPlanError(
                "EditPlan precisa possuir pelo menos uma track."
            )

        clips = [
            clip
            for track in self.tracks
            for clip in track.clips
        ]

        if not clips:
            raise EditPlanError(
                "EditPlan precisa possuir pelo menos um clip."
            )

        for clip in clips:
            if (
                clip.start_seconds + clip.duration_seconds
                > self.duration_seconds + 0.001
            ):
                raise EditPlanError(
                    "Clip ultrapassa a duração declarada do EditPlan."
                )

    def to_dict(self) -> dict[str, Any]:
        """Serializa o contrato para transporte entre serviços."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditPlan":
        """Reconstrói um EditPlan validado a partir de JSON/dict."""
        if not isinstance(data, dict):
            raise EditPlanError(
                "EditPlan deve ser um objeto."
            )

        tracks = tuple(
            EditTrack(
                name=track["name"],
                kind=track["kind"],
                clips=tuple(
                    EditClip(
                        segment_id=clip.get("segment_id"),
                        media_path=clip["media_path"],
                        track=clip["track"],
                        start_seconds=clip["start_seconds"],
                        source_start_seconds=clip["source_start_seconds"],
                        duration_seconds=clip["duration_seconds"],
                        role=clip.get("role", "content"),
                        fit=clip.get("fit", "cover"),
                    )
                    for clip in track.get("clips", [])
                ),
            )
            for track in data.get("tracks", [])
        )

        texts = tuple(
            EditText(**item)
            for item in data.get("texts", [])
        )

        audio = tuple(
            EditAudio(**item)
            for item in data.get("audio", [])
        )

        transitions = tuple(
            EditTransition(**item)
            for item in data.get("transitions", [])
        )

        effects = tuple(
            EditEffect(**item)
            for item in data.get("effects", [])
        )

        qa = EditQA(
            **data.get("qa", {})
        )

        return cls(
            version=data["version"],
            content_item_id=data["content_item_id"],
            script_id=data["script_id"],
            title=data["title"],
            objective=data["objective"],
            format=data["format"],
            duration_seconds=data["duration_seconds"],
            tracks=tracks,
            texts=texts,
            audio=audio,
            transitions=transitions,
            effects=effects,
            qa=qa,
            metadata=dict(data.get("metadata", {})),
        )
