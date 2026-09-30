from __future__ import annotations

import pytest

from scripts import telegram_harness_gateway_v2 as gateway
from scripts.telegram_harness_gateway import TelegramApiError, TelegramRateLimitError


def test_startup_probe_retries_transient_network_failure_then_succeeds():
    calls=[]
    sleeps=[]
    class Api:
        def call(self, method, payload=None, *, timeout=20):
            calls.append((method,timeout))
            if len(calls)==1:
                raise TimeoutError("temporary timeout")
            if method=="getMe":
                return {"username":"bot","can_join_groups":True,"can_read_all_group_messages":True}
            return {"url":""}

    me, webhook = gateway._probe_telegram_startup(
        Api(),
        max_attempts=3,
        per_call_timeout=5,
        sleep_fn=lambda seconds:sleeps.append(seconds),
    )
    assert me["username"]=="bot"
    assert webhook["url"]==""
    assert calls == [("getMe",5),("getMe",5),("getWebhookInfo",5)]
    assert sleeps == [1.0]


def test_startup_probe_retries_wrapped_network_error():
    calls=[]
    class Api:
        def call(self, method, payload=None, *, timeout=20):
            calls.append(method)
            if len(calls)==1:
                raise TelegramApiError("Telegram network error: no address associated with hostname")
            if method=="getMe":
                return {"username":"bot"}
            return {"url":""}
    me,_=gateway._probe_telegram_startup(
        Api(),max_attempts=2,per_call_timeout=3,sleep_fn=lambda _s:None
    )
    assert me["username"]=="bot"
    assert calls==["getMe","getMe","getWebhookInfo"]


def test_startup_probe_does_not_retry_permanent_telegram_error():
    calls=[]
    class Api:
        def call(self, method, payload=None, *, timeout=20):
            calls.append(method)
            raise TelegramApiError("Telegram HTTP 401: Unauthorized")
    with pytest.raises(TelegramApiError,match="401"):
        gateway._probe_telegram_startup(
            Api(),max_attempts=4,per_call_timeout=5,sleep_fn=lambda _s:None
        )
    assert calls==["getMe"]


def test_startup_probe_respects_rate_limit_retry_after_bounded():
    calls=[]
    sleeps=[]
    class Api:
        def call(self, method, payload=None, *, timeout=20):
            calls.append(method)
            if len(calls)==1:
                raise TelegramRateLimitError("rate",retry_after_seconds=2)
            if method=="getMe":
                return {"username":"bot"}
            return {"url":""}
    gateway._probe_telegram_startup(
        Api(),max_attempts=2,per_call_timeout=5,sleep_fn=lambda s:sleeps.append(s)
    )
    assert sleeps==[2.0]
