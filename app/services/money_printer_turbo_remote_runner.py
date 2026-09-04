from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {path}"
        )

    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise ValueError(
            f"O JSON precisa conter um objeto: {path}"
        )

    return data


def load_script(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Script não encontrado: {path}"
        )

    script = path.read_text(
        encoding="utf-8"
    ).strip()

    if not script:
        raise ValueError(
            "O script do MPT não pode estar vazio."
        )

    return script


def build_mpt_command(
    *,
    mpt_root: Path,
    task_id: str,
    video_subject: str,
    video_script: str,
) -> list[str]:
    return [
        "uv",
        "run",
        "python",
        "cli.py",
        "--task-id",
        task_id,
        "--video-subject",
        video_subject,
        "--video-script",
        video_script,
        "--stop-at",
        "end",
    ]


def run_mpt(
    *,
    mpt_root: Path,
    task_id: str,
    video_subject: str,
    video_script: str,
) -> subprocess.CompletedProcess[str]:
    command = build_mpt_command(
        mpt_root=mpt_root,
        task_id=task_id,
        video_subject=video_subject,
        video_script=video_script,
    )

    return subprocess.run(
        command,
        cwd=mpt_root,
        capture_output=True,
        text=True,
        check=True,
    )


def parse_mpt_json(stdout: str) -> Any:
    lines = [
        line.strip()
        for line in stdout.splitlines()
        if line.strip()
    ]

    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    raise ValueError(
        "O MoneyPrinterTurbo terminou sem retornar "
        "um objeto JSON válido."
    )


def _find_mp4(value: Any) -> str | None:
    if isinstance(value, str):
        candidate = value.strip()

        if candidate.lower().endswith(".mp4"):
            return candidate

        return None

    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {
                "video_file",
                "video_path",
                "output_path",
                "file_path",
                "path",
            }:
                found = _find_mp4(item)

                if found:
                    return found

            found = _find_mp4(item)

            if found:
                return found

    if isinstance(value, list):
        for item in value:
            found = _find_mp4(item)

            if found:
                return found

    return None


def find_video_file(result: Any) -> str:
    video_file = _find_mp4(result)

    if not video_file:
        raise ValueError(
            "Não foi possível localizar o arquivo MP4 "
            "na resposta do MoneyPrinterTurbo."
        )

    return video_file


def validate_video_file(
    *,
    video_file: Path,
    job_root: Path,
) -> None:
    if not video_file.is_absolute():
        raise ValueError(
            "O VIDEO_FILE retornado pelo MPT precisa "
            "ser um caminho absoluto."
        )

    try:
        video_file.relative_to(job_root)
    except ValueError as exc:
        raise ValueError(
            "O VIDEO_FILE retornado pelo MPT está "
            "fora do diretório do job."
        ) from exc

    if video_file.suffix.lower() != ".mp4":
        raise ValueError(
            "O VIDEO_FILE retornado pelo MPT não é MP4."
        )

    if not video_file.is_file():
        raise FileNotFoundError(
            f"Vídeo produzido pelo MPT não encontrado: "
            f"{video_file}"
        )

    if video_file.stat().st_size <= 0:
        raise ValueError(
            f"Vídeo produzido pelo MPT está vazio: "
            f"{video_file}"
        )


def copy_video_to_job_output(
    *,
    video_file: Path,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir / "video.mp4"
    )

    partial_path = (
        output_dir / "video.mp4.part"
    )

    if partial_path.exists():
        partial_path.unlink()

    shutil.copy2(
        video_file,
        partial_path,
    )

    if not partial_path.exists():
        raise FileNotFoundError(
            "O MP4 não foi copiado para o output do job."
        )

    if partial_path.stat().st_size <= 0:
        raise ValueError(
            "O MP4 copiado para o output do job está vazio."
        )

    partial_path.replace(output_path)

    return output_path


def emit_result(
    *,
    video_file: Path,
    task_dir: Path,
    log_file: Path,
    result_file: Path,
) -> None:
    print("MPT_RESULT")
    print(f"VIDEO_FILE={video_file}")
    print(f"TASK_DIR={task_dir}")
    print(f"LOG_FILE={log_file}")
    print(f"RESULT_FILE={result_file}")


def execute(
    *,
    input_dir: Path,
    mpt_root: Path,
    output_dir: Path,
    task_id: str,
) -> None:
    job_file = input_dir / "job.json"
    script_file = input_dir / "script.txt"

    job = load_json(job_file)
    script = load_script(script_file)

    subject = str(
        job.get("objective", "")
    ).strip()

    if not subject:
        raise ValueError(
            "O job.json precisa possuir objective."
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    completed = run_mpt(
        mpt_root=mpt_root,
        task_id=task_id,
        video_subject=subject,
        video_script=script,
    )

    result = parse_mpt_json(
        completed.stdout
    )

    result_file = (
        output_dir / "mpt-result.json"
    )

    result_file.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    video_file = Path(
        find_video_file(result)
    )

    job_root = (
        mpt_root
        / "storage"
        / "tasks"
        / task_id
    )

    validate_video_file(
        video_file=video_file,
        job_root=job_root,
    )

    task_dir = video_file.parent

    output_video = copy_video_to_job_output(
        video_file=video_file,
        output_dir=output_dir,
    )

    log_file = (
        output_dir
        / f"run-{task_id}.log"
    )

    log_file.write_text(
        completed.stderr,
        encoding="utf-8",
    )

    emit_result(
        video_file=output_video,
        task_dir=task_dir,
        log_file=log_file,
        result_file=result_file,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Runner remoto do MoneyPrinterTurbo "
            "para o BR-no-GTA."
        )
    )

    parser.add_argument(
        "--input-dir",
        required=True,
    )

    parser.add_argument(
        "--mpt-root",
        required=True,
    )

    parser.add_argument(
        "--output-dir",
        required=True,
    )

    parser.add_argument(
        "--task-id",
        required=True,
    )

    args = parser.parse_args()

    try:
        execute(
            input_dir=Path(args.input_dir),
            mpt_root=Path(args.mpt_root),
            output_dir=Path(args.output_dir),
            task_id=args.task_id,
        )

    except subprocess.CalledProcessError as exc:
        print(
            "MPT_ERROR",
            file=sys.stderr,
        )

        if exc.stderr:
            print(
                exc.stderr,
                file=sys.stderr,
            )

        return exc.returncode or 1

    except Exception as exc:
        print(
            f"MPT_ERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
