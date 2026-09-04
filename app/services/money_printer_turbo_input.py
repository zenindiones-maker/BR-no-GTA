from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MoneyPrinterTurboInputPackage:
    """
    Pacote de entrada preparado pelo BR para uma execução do
    MoneyPrinterTurbo.

    O pacote representa uma fronteira entre o domínio do BR e
    o ambiente de produção remoto.

    O MPT não recebe objetos internos do BR nem acesso ao banco.
    Ele recebe apenas arquivos serializados neste diretório.
    """

    directory: Path
    job_file: Path
    script_file: Path
    scenes_file: Path


def create_money_printer_turbo_input_package(
    render_job: dict[str, Any],
    output_dir: Path,
) -> MoneyPrinterTurboInputPackage:
    """
    Cria o pacote de entrada do MoneyPrinterTurbo a partir
    de um Render Job.

    Esta função não executa o MPT, não usa rede e não conhece
    SSH, rsync ou subprocess.

    O contrato produzido é:

        output_dir/
        ├── job.json
        ├── script.txt
        └── scenes.json
    """

    _validate_render_job(render_job)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    job_file = output_dir / "job.json"
    script_file = output_dir / "script.txt"
    scenes_file = output_dir / "scenes.json"

    script = _build_script(render_job)
    scenes = _build_scenes(render_job)
    job = _build_job_metadata(render_job)

    _write_json(job_file, job)
    _write_text(script_file, script)
    _write_json(scenes_file, scenes)

    return MoneyPrinterTurboInputPackage(
        directory=output_dir,
        job_file=job_file,
        script_file=script_file,
        scenes_file=scenes_file,
    )


def _validate_render_job(
    render_job: dict[str, Any],
) -> None:
    if not isinstance(render_job, dict) or not render_job:
        raise ValueError(
            "O render job informado é inválido."
        )

    required_fields = (
        "content_item_id",
        "script_id",
        "idea_id",
        "objective",
        "format",
        "estimated_duration_seconds",
        "scenes",
        "audio_requirements",
        "visual_requirements",
        "render",
    )

    for field in required_fields:
        if field not in render_job:
            raise ValueError(
                "O render job não possui o campo obrigatório: "
                f"{field}."
            )

    scenes = render_job["scenes"]

    if not isinstance(scenes, list) or not scenes:
        raise ValueError(
            "O render job precisa possuir cenas."
        )

    required_scene_fields = (
        "order",
        "narrative_block",
        "narration",
        "visual_type",
        "visual_description",
        "duration_seconds",
        "execution_requirements",
    )

    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError(
                "Cada cena do render job deve ser um objeto válido."
            )

        for field in required_scene_fields:
            if field not in scene:
                raise ValueError(
                    "A cena não possui o campo obrigatório: "
                    f"{field}."
                )


def _build_script(
    render_job: dict[str, Any],
) -> str:
    parts: list[str] = []

    for scene in render_job["scenes"]:
        narration = str(
            scene["narration"]
        ).strip()

        if narration:
            parts.append(narration)

    script = "\n\n".join(parts).strip()

    if not script:
        raise ValueError(
            "Render job não possui narração utilizável."
        )

    return script + "\n"


def _build_scenes(
    render_job: dict[str, Any],
) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []

    for scene in render_job["scenes"]:
        scenes.append(
            {
                "order": scene["order"],
                "narrative_block": scene["narrative_block"],
                "narration": scene["narration"],
                "visual_type": scene["visual_type"],
                "visual_description": scene[
                    "visual_description"
                ],
                "duration_seconds": scene[
                    "duration_seconds"
                ],
                "execution_requirements": list(
                    scene.get(
                        "execution_requirements"
                    ) or []
                ),
            }
        )

    return scenes


def _build_job_metadata(
    render_job: dict[str, Any],
) -> dict[str, Any]:
    """
    Produz somente metadados necessários para a execução.

    Não copia o Render Job inteiro deliberadamente.
    """

    return {
        "content_item_id": render_job["content_item_id"],
        "script_id": render_job["script_id"],
        "idea_id": render_job["idea_id"],
        "objective": render_job["objective"],
        "format": render_job["format"],
        "estimated_duration_seconds": (
            render_job[
                "estimated_duration_seconds"
            ]
        ),
        "audio_requirements": list(
            render_job.get(
                "audio_requirements"
            ) or []
        ),
        "visual_requirements": list(
            render_job.get(
                "visual_requirements"
            ) or []
        ),
        "render": dict(
            render_job["render"]
        ),
    }


def _write_json(
    path: Path,
    value: Any,
) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_text(
    path: Path,
    value: str,
) -> None:
    path.write_text(
        value,
        encoding="utf-8",
    )
