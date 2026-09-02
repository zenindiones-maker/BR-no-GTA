from __future__ import annotations

from app.services.money_printer_turbo_client import (
    MoneyPrinterTurboClient,
)
from app.services.money_printer_turbo_executor import (
    MoneyPrinterTurboExecutor,
)
from app.services.money_printer_turbo_factory import (
    create_money_printer_turbo_executor,
)


def test_factory_returns_none_when_mpt_is_not_configured(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_BASE_URL",
        "",
    )

    executor = create_money_printer_turbo_executor()

    assert executor is None


def test_factory_builds_mpt_executor_from_settings(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_BASE_URL",
        "http://127.0.0.1:8080",
    )
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_TIMEOUT",
        42.0,
    )
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_POLL_INTERVAL",
        7.0,
    )
    monkeypatch.setattr(
        "app.services.money_printer_turbo_factory.settings.MPT_MAX_POLLS",
        99,
    )

    executor = create_money_printer_turbo_executor()

    assert isinstance(executor, MoneyPrinterTurboExecutor)
    assert isinstance(executor.client, MoneyPrinterTurboClient)

    assert executor.client.base_url == (
        "http://127.0.0.1:8080"
    )
    assert executor.client.api_key == "test-key"
    assert executor.client.timeout == 42.0
    assert executor.poll_interval == 7.0
    assert executor.max_polls == 99
