from app import settings
from app.services.money_printer_turbo_factory import (
    create_money_printer_turbo_executor,
)


def test_factory_returns_none_without_ssh_configuration(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "MPT_SSH_HOST",
        "",
    )
    monkeypatch.setattr(
        settings,
        "MPT_SSH_USER",
        "",
    )
    monkeypatch.setattr(
        settings,
        "MPT_SSH_KEY",
        "",
    )

    executor = create_money_printer_turbo_executor()

    assert executor is None
