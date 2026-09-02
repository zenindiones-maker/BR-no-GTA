import json

import pytest

from app.services.money_printer_turbo_client import (
    MoneyPrinterTurboClient,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        body=b"",
    ):
        self.status_code = status_code
        self._payload = payload
        self._body = body

    def read(self):
        if self._body:
            return self._body

        return json.dumps(
            self._payload,
            ensure_ascii=False,
        ).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "headers": dict(request.header_items()),
                "body": request.data,
                "timeout": timeout,
            }
        )

        if not self.responses:
            raise AssertionError(
                "Nenhuma resposta fake disponível."
            )

        return self.responses.pop(0)


def test_create_video_posts_to_mpt_videos_endpoint():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "task_id": "task-123",
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        timeout=15,
        transport=transport,
    )

    payload = {
        "video_subject": "GTA 6",
        "video_script": "Roteiro GTA 6.",
        "video_terms": ["GTA 6", "Vice City"],
    }

    result = client.create_video(payload)

    assert result == {
        "task_id": "task-123",
    }

    request = transport.requests[0]

    assert request["url"] == "http://mpt.local:8080/videos"
    assert request["method"] == "POST"
    assert request["timeout"] == 15

    assert json.loads(
        request["body"].decode("utf-8")
    ) == payload

    assert request["headers"]["Content-type"] == "application/json"


def test_get_task_calls_task_endpoint():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "task_id": "task-123",
                    "state": 4,
                    "progress": 50,
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        timeout=15,
        transport=transport,
    )

    result = client.get_task("task-123")

    assert result == {
        "task_id": "task-123",
        "state": 4,
        "progress": 50,
    }

    request = transport.requests[0]

    assert request["url"] == (
        "http://mpt.local:8080/tasks/task-123"
    )
    assert request["method"] == "GET"


def test_client_sends_api_key_when_configured():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "task_id": "task-123",
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        api_key="secret-key",
        timeout=15,
        transport=transport,
    )

    client.create_video(
        {
            "video_subject": "GTA 6",
        }
    )

    request = transport.requests[0]

    assert request["headers"]["Authorization"] == (
        "Bearer secret-key"
    )


def test_client_does_not_send_authorization_without_api_key():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "task_id": "task-123",
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        api_key="",
        timeout=15,
        transport=transport,
    )

    client.create_video(
        {
            "video_subject": "GTA 6",
        }
    )

    request = transport.requests[0]

    assert "Authorization" not in request["headers"]


def test_client_rejects_http_error():
    transport = FakeTransport(
        [
            FakeResponse(
                status_code=500,
                payload={
                    "detail": "Internal Server Error",
                },
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        timeout=15,
        transport=transport,
    )

    with pytest.raises(
        RuntimeError,
        match="500",
    ):
        client.create_video(
            {
                "video_subject": "GTA 6",
            }
        )


def test_client_rejects_invalid_json_response():
    transport = FakeTransport(
        [
            FakeResponse(
                status_code=200,
                body=b"not-json",
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        timeout=15,
        transport=transport,
    )

    with pytest.raises(
        RuntimeError,
        match="JSON",
    ):
        client.create_video(
            {
                "video_subject": "GTA 6",
            }
        )


def test_client_rejects_missing_task_id_response():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "message": "created",
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        timeout=15,
        transport=transport,
    )

    result = client.create_video(
        {
            "video_subject": "GTA 6",
        }
    )

    assert result == {
        "message": "created",
    }


def test_client_rejects_empty_base_url():
    with pytest.raises(
        ValueError,
        match="base_url",
    ):
        MoneyPrinterTurboClient(
            base_url="",
            transport=FakeTransport([]),
        )


def test_client_rejects_invalid_timeout():
    with pytest.raises(
        ValueError,
        match="timeout",
    ):
        MoneyPrinterTurboClient(
            base_url="http://mpt.local:8080",
            timeout=0,
            transport=FakeTransport([]),
        )


def test_client_rejects_invalid_task_id():
    transport = FakeTransport([])

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        transport=transport,
    )

    with pytest.raises(
        ValueError,
        match="task_id",
    ):
        client.get_task("")


def test_client_rejects_invalid_video_payload():
    transport = FakeTransport([])

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080",
        transport=transport,
    )

    with pytest.raises(
        ValueError,
        match="payload",
    ):
        client.create_video({})


def test_client_normalizes_trailing_base_url_slash():
    transport = FakeTransport(
        [
            FakeResponse(
                payload={
                    "task_id": "task-123",
                }
            )
        ]
    )

    client = MoneyPrinterTurboClient(
        base_url="http://mpt.local:8080/",
        transport=transport,
    )

    client.create_video(
        {
            "video_subject": "GTA 6",
        }
    )

    assert transport.requests[0]["url"] == (
        "http://mpt.local:8080/videos"
    )
