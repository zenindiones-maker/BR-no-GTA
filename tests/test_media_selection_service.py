from app.services import media_selection_service as service


def test_select_media_segments_preserves_source_identity(monkeypatch):
    captured = {}

    def fake_create_unit(**kwargs):
        captured["unit"] = kwargs
        return {"id": 42}

    def fake_create_segment(**kwargs):
        captured.setdefault("segments", []).append(kwargs)
        return {"id": len(captured["segments"]), **kwargs}

    monkeypatch.setattr(
        service,
        "create_and_persist_content_unit",
        fake_create_unit,
    )
    monkeypatch.setattr(
        service,
        "create_and_persist_content_segment",
        fake_create_segment,
    )

    result = service.select_media_segments(
        knowledge={
            "source_path": "/workspace/gta6/source.mp4",
            "scenes": [
                {
                    "start_seconds": 10,
                    "end_seconds": 16,
                }
            ],
        },
        content_item_id=1,
        script_id=2,
        idea_id=3,
        title="GTA 6",
        objective="Informar",
        hook="Novo trailer",
        narration="Texto de teste",
        target_duration_seconds=6,
    )

    assert result["segment_count"] == 1

    segment = result["segments"][0]

    assert segment["id"] == 1
    assert segment["content_unit_id"] == 42
    assert segment["file_path"] == "/workspace/gta6/source.mp4"
    assert segment["source_start_seconds"] == 10.0
    assert segment["source_end_seconds"] == 16.0
    assert segment["duration_seconds"] == 6.0
    assert segment["role"] == "content"
