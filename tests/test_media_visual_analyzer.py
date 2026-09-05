from pathlib import Path
import sys

from app.services.media_analysis.visual_analyzer import analyze_visual


class FakeFrame:
    def __init__(self, value):
        self.value = value
        self.shape = (720, 1280, 3)

    def __sub__(self, other):
        return FakeFlow(self.value - other.value)


class FakeFlow:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, key):
        return self


class FakeMagnitude:
    def __init__(self, value):
        self.value = value

    def mean(self):
        return self.value


class FakeCapture:
    def __init__(self, frames):
        self.frames = frames
        self.index = 0

    def isOpened(self):
        return True

    def get(self, property_id):
        return 2.0

    def read(self):
        if self.index >= len(self.frames):
            return False, None

        frame = self.frames[self.index]
        self.index += 1
        return True, frame

    def release(self):
        return None


class FakeCv2:
    CAP_PROP_FPS = 5
    COLOR_BGR2GRAY = 6

    def __init__(self, frames):
        self.frames = frames
        self.saved = []

    def VideoCapture(self, _):
        return FakeCapture(self.frames)

    def cvtColor(self, frame, _):
        return frame

    def calcOpticalFlowFarneback(
        self,
        previous,
        current,
        *_args,
    ):
        return current - previous

    def cartToPolar(self, x, y):
        magnitude = FakeMagnitude(abs(x.value))
        angle = 0
        return magnitude, angle

    def imwrite(self, path, frame):
        Path(path).write_bytes(b"fake-jpeg")
        self.saved.append((path, frame))
        return True


def test_visual_analyzer_builds_samples_and_motion(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    fake_cv2 = FakeCv2(
        frames=[
            FakeFrame(0),
            FakeFrame(1),
            FakeFrame(3),
            FakeFrame(6),
        ]
    )

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        fake_cv2,
    )

    samples, motions = analyze_visual(
        source,
        output_dir=tmp_path / "samples",
        sample_interval_seconds=1.0,
    )

    assert len(samples) == 2
    assert len(motions) == 3

    assert samples[0].time_seconds == 0.0
    assert samples[1].time_seconds == 1.0

    assert samples[0].width is not None
    assert samples[0].height is not None

    assert motions[0].motion_score == 1.0
    assert motions[1].motion_score == 2.0
    assert motions[2].motion_score == 3.0

    assert Path(samples[0].path).is_file()
    assert Path(samples[1].path).is_file()


def test_visual_analyzer_rejects_invalid_interval(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-media")

    fake_cv2 = FakeCv2(frames=[])

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        fake_cv2,
    )

    try:
        analyze_visual(
            source,
            output_dir=tmp_path / "samples",
            sample_interval_seconds=0,
        )
    except Exception as exc:
        assert "maior que zero" in str(exc)
    else:
        raise AssertionError("Era esperado erro de intervalo inválido.")
