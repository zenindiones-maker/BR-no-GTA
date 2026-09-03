import pytest

from app.services.media_format_service import (
    LANDSCAPE_16_9,
    PORTRAIT_9_16,
    MediaFormatError,
    build_render_config,
    get_media_format,
    list_media_formats,
)


def test_landscape_16_9_format():
    media_format = get_media_format("16:9")

    assert media_format is LANDSCAPE_16_9
    assert media_format.width == 1920
    assert media_format.height == 1080
    assert media_format.resolution == "1920x1080"
    assert media_format.aspect_ratio == "16:9"
    assert media_format.orientation == "horizontal"
    assert media_format.is_horizontal is True
    assert media_format.is_vertical is False


def test_portrait_9_16_format():
    media_format = get_media_format("9:16")

    assert media_format is PORTRAIT_9_16
    assert media_format.width == 1080
    assert media_format.height == 1920
    assert media_format.resolution == "1080x1920"
    assert media_format.aspect_ratio == "9:16"
    assert media_format.orientation == "vertical"
    assert media_format.is_vertical is True
    assert media_format.is_horizontal is False


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("16:9", LANDSCAPE_16_9),
        ("landscape", LANDSCAPE_16_9),
        ("horizontal", LANDSCAPE_16_9),
        ("9:16", PORTRAIT_9_16),
        ("portrait", PORTRAIT_9_16),
        ("vertical", PORTRAIT_9_16),
    ],
)
def test_format_aliases(alias, expected):
    assert get_media_format(alias) is expected


def test_format_names_are_case_insensitive():
    assert get_media_format("  LANDSCAPE  ") is LANDSCAPE_16_9
    assert get_media_format("  Portrait  ") is PORTRAIT_9_16


def test_list_media_formats_contains_both_formats():
    formats = list_media_formats()

    assert LANDSCAPE_16_9 in formats
    assert PORTRAIT_9_16 in formats
    assert len(formats) == 2


@pytest.mark.parametrize(
    "invalid_name",
    [
        "",
        "   ",
        "square",
        "4:3",
        "1920x1080",
        None,
    ],
)
def test_invalid_format_is_rejected(invalid_name):
    with pytest.raises(MediaFormatError):
        get_media_format(invalid_name)


def test_build_landscape_render_config():
    config = build_render_config("16:9")

    assert config == {
        "resolution": "1920x1080",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "aspect_ratio": "16:9",
        "orientation": "horizontal",
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
    }


def test_build_portrait_render_config():
    config = build_render_config("9:16")

    assert config["resolution"] == "1080x1920"
    assert config["width"] == 1080
    assert config["height"] == 1920
    assert config["aspect_ratio"] == "9:16"
    assert config["orientation"] == "vertical"


def test_render_config_allows_explicit_overrides():
    config = build_render_config(
        "9:16",
        fps=60,
        container="mov",
        video_codec="h265",
        audio_codec="opus",
    )

    assert config["resolution"] == "1080x1920"
    assert config["fps"] == 60
    assert config["container"] == "mov"
    assert config["video_codec"] == "h265"
    assert config["audio_codec"] == "opus"


@pytest.mark.parametrize(
    "fps",
    [
        0,
        -1,
        0.5,
        "30",
        None,
    ],
)
def test_invalid_explicit_fps_is_rejected(fps):
    if fps is None:
        config = build_render_config("16:9", fps=fps)
        assert config["fps"] == 30
        return

    with pytest.raises(MediaFormatError):
        build_render_config("16:9", fps=fps)
