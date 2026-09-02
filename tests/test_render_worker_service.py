from __future__ import annotations

from unittest.mock import Mock

from app.services.render_worker_service import (
    process_next_render_job,
)


def test_worker_preserves_explicit_executor(monkeypatch):
    explicit_executor = object()
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job(
        executor=explicit_executor,
    )

    orchestration.assert_called_once_with(
        executor=explicit_executor,
    )


def test_worker_uses_mpt_factory_when_executor_is_not_provided(
    monkeypatch,
):
    mpt_executor = object()
    factory = Mock(return_value=mpt_executor)
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )
    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job()

    factory.assert_called_once_with()
    orchestration.assert_called_once_with(
        executor=mpt_executor,
    )


def test_worker_passes_none_when_mpt_is_not_configured(
    monkeypatch,
):
    factory = Mock(return_value=None)
    orchestration = Mock()

    monkeypatch.setattr(
        "app.services.render_worker_service.create_money_printer_turbo_executor",
        factory,
    )
    monkeypatch.setattr(
        "app.services.render_worker_service.execute_next_render_job",
        orchestration,
    )

    process_next_render_job()

    factory.assert_called_once_with()
    orchestration.assert_called_once_with(
        executor=None,
    )
