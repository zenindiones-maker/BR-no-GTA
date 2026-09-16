from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.run_branding_canary import _validate_snapshots


def _snapshots() -> list[dict]:
    return [
        {
            "asset_id": 1,
            "asset_type": "intro",
            "telegram_file_id": "intro-file",
            "telegram_file_unique_id": "intro-unique",
            "remote_verified": True,
        },
        {
            "asset_id": 2,
            "asset_type": "watermark",
            "telegram_file_id": "watermark-file",
            "telegram_file_unique_id": "watermark-unique",
            "remote_verified": True,
        },
    ]


def test_canary_accepts_only_exact_remotely_verified_assets_1_and_2():
    with patch(
        "scripts.run_branding_canary._telegram_call",
        return_value={"file_path": "verified/asset.bin"},
    ) as telegram:
        result = _validate_snapshots("runtime-token", _snapshots())

    assert [(item["asset_id"], item["asset_type"]) for item in result] == [
        (1, "intro"),
        (2, "watermark"),
    ]
    assert telegram.call_count == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda items: items.pop(),
        lambda items: items[0].update(asset_id=18),
        lambda items: items[0].update(asset_type="watermark"),
        lambda items: items[1].update(remote_verified=False),
        lambda items: items[0].update(telegram_file_id=""),
    ],
)
def test_canary_fails_closed_for_wrong_asset_identity(mutation):
    snapshots = _snapshots()
    mutation(snapshots)
    with pytest.raises(RuntimeError):
        _validate_snapshots("runtime-token", snapshots)
