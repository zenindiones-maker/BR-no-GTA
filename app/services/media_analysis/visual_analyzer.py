from __future__ import annotations

from pathlib import Path

from app.services.media_analysis.models import (
    MotionFeature,
    VisualSample,
)


class VisualAnalysisError(RuntimeError):
    """Erro na análise visual da mídia."""


def analyze_visual(
    source_path: str | Path,
    output_dir: str | Path | None = None,
    sample_interval_seconds: float = 2.0,
) -> tuple[tuple[VisualSample, ...], tuple[MotionFeature, ...]]:
    """
    Analisa visualmente uma mídia usando OpenCV.

    Produz:
    - amostras visuais periódicas;
    - métricas de movimento entre frames.

    Nenhuma decisão editorial é executada.
    """

    try:
        import cv2
    except ImportError as exc:
        raise VisualAnalysisError(
            "opencv-python-headless não está instalada no ambiente de análise."
        ) from exc

    path = Path(source_path)

    if not path.is_file():
        raise VisualAnalysisError(
            f"Mídia não encontrada: {path}"
        )

    if sample_interval_seconds <= 0:
        raise VisualAnalysisError(
            "sample_interval_seconds deve ser maior que zero."
        )

    destination = (
        Path(output_dir)
        if output_dir is not None
        else path.parent / ".media_analysis" / path.stem
    )
    destination.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(path))

    if not capture.isOpened():
        raise VisualAnalysisError(
            f"Não foi possível abrir a mídia com OpenCV: {path}"
        )

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)

    if fps <= 0:
        capture.release()
        raise VisualAnalysisError(
            "FPS inválido para análise visual."
        )

    frame_index = 0
    next_sample_seconds = 0.0
    previous_gray = None

    samples: list[VisualSample] = []
    motions: list[MotionFeature] = []

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            time_seconds = frame_index / fps

            gray = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2GRAY,
            )

            if previous_gray is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    previous_gray,
                    gray,
                    None,
                    0.5,
                    3,
                    15,
                    3,
                    5,
                    1.2,
                    0,
                )

                magnitude, _ = cv2.cartToPolar(
                    flow[..., 0],
                    flow[..., 1],
                )

                motion_score = float(magnitude.mean())

                motions.append(
                    MotionFeature(
                        start_seconds=max(
                            0.0,
                            time_seconds - (1.0 / fps),
                        ),
                        end_seconds=time_seconds,
                        motion_score=motion_score,
                    )
                )

            if time_seconds + 1e-9 >= next_sample_seconds:
                sample_path = (
                    destination
                    / f"sample_{len(samples):06d}.jpg"
                )

                written = cv2.imwrite(
                    str(sample_path),
                    frame,
                )

                if not written:
                    raise VisualAnalysisError(
                        f"Falha ao salvar amostra visual: {sample_path}"
                    )

                height, width = frame.shape[:2]

                samples.append(
                    VisualSample(
                        time_seconds=time_seconds,
                        path=str(sample_path),
                        width=int(width),
                        height=int(height),
                    )
                )

                next_sample_seconds += sample_interval_seconds

            previous_gray = gray
            frame_index += 1

    finally:
        capture.release()

    return tuple(samples), tuple(motions)
