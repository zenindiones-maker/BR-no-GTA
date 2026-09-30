from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_SECRET_PATTERN=re.compile(r"(?:sk|test-openai-key)-[A-Za-z0-9_-]{4,}")


class OpenAIAgentsAPIError(RuntimeError):
    def __init__(
        self,
        message:str,
        *,
        code:str="openai_agents_api_error",
        status_code:int|None=None,
        retryable:bool=False,
    )->None:
        safe=_SECRET_PATTERN.sub("[REDACTED_OPENAI_API_KEY]",str(message or "OpenAI Agents API request failed."))
        if "authorization" in safe.lower() and "bearer" in safe.lower():
            safe="OpenAI Agents API authentication request failed."
        super().__init__(safe[:1200])
        self.code=code
        self.status_code=status_code
        self.retryable=bool(retryable)


OpenAIAgentsHTTPError=OpenAIAgentsAPIError


def _default_sender(
    *,
    method:str,
    url:str,
    headers:dict[str,str],
    body:dict[str,Any]|None,
    timeout_seconds:int,
)->tuple[int,dict[str,Any]]:
    raw=None if body is None else json.dumps(
        body,ensure_ascii=False,sort_keys=True,separators=(",",":")
    ).encode("utf-8")
    req=Request(url,data=raw,headers=headers,method=method.upper())
    try:
        with urlopen(req,timeout=timeout_seconds) as response:
            status=int(getattr(response,"status",200))
            payload=response.read()
    except HTTPError as exc:
        try:
            detail=exc.read().decode("utf-8",errors="replace")
        except Exception:
            detail=""
        raise OpenAIAgentsAPIError(
            f"OpenAI Agents HTTP {exc.code}: {detail}",
            code="http_error",
            status_code=int(exc.code),
            retryable=int(exc.code)>=500 or int(exc.code)==429,
        ) from exc
    except (URLError,TimeoutError,OSError) as exc:
        raise OpenAIAgentsAPIError(
            str(exc),
            code="transport_error",
            retryable=True,
        ) from exc
    if not payload:
        return status,{}
    try:
        parsed=json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise OpenAIAgentsAPIError("OpenAI Agents returned invalid JSON",code="invalid_json") from exc
    if not isinstance(parsed,dict):
        raise OpenAIAgentsAPIError("OpenAI Agents returned non-object JSON",code="invalid_response")
    return status,parsed


class OpenAIAgentsHTTPTransport:
    def __init__(
        self,
        *,
        api_key:str,
        sender:Callable[...,tuple[int,dict[str,Any]]]|None=None,
        request_json:Callable[...,dict[str,Any]]|None=None,
        timeout_seconds:int=30,
        base_url:str="https://api.openai.com/v1",
    )->None:
        key=str(api_key or "").strip()
        if not key:
            raise ValueError("OpenAI API key is required")
        self._api_key=key
        self.timeout_seconds=int(timeout_seconds)
        if not 1<=self.timeout_seconds<=300:
            raise ValueError("timeout_seconds must be in [1,300]")
        self.base_url=str(base_url or "").rstrip("/")
        if request_json is not None:
            def _sender(*,method,url,headers,body,timeout_seconds):
                payload=request_json(
                    method,
                    url,
                    headers=headers,
                    json_body=body,
                    timeout_seconds=timeout_seconds,
                )
                if not isinstance(payload,dict):
                    raise OpenAIAgentsAPIError("OpenAI Agents returned non-object payload")
                return int(payload.get("_http_status") or 200),payload
            self._sender=_sender
        else:
            self._sender=sender or _default_sender

    def __call__(
        self,
        *,
        method:str,
        path:str,
        body:dict[str,Any]|None=None,
        idempotency_key:str|None=None,
    )->dict[str,Any]:
        normalized="/"+str(path or "").lstrip("/")
        if not normalized.startswith("/agents/"):
            raise PermissionError("OpenAI Agents transport refuses non-Agents API endpoint")
        headers={
            "Authorization":f"Bearer {self._api_key}",
            "OpenAI-Beta":"agents=v1",
            "Content-Type":"application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"]=str(idempotency_key)
        try:
            status,payload=self._sender(
                method=str(method).upper(),
                url=self.base_url+normalized,
                headers=headers,
                body=body,
                timeout_seconds=self.timeout_seconds,
            )
        except OpenAIAgentsAPIError:
            raise
        except Exception as exc:
            safe=str(exc).replace(self._api_key,"[REDACTED_OPENAI_API_KEY]")
            safe=_SECRET_PATTERN.sub("[REDACTED_OPENAI_API_KEY]",safe)
            raise OpenAIAgentsAPIError(safe,code="transport_error") from exc
        if not isinstance(payload,dict):
            raise OpenAIAgentsAPIError("OpenAI Agents returned non-object payload")
        return {"_http_status":int(status),**payload}

    def request(
        self,
        method:str,
        path:str,
        *,
        body:dict[str,Any]|None=None,
        idempotency_key:str|None=None,
    )->dict[str,Any]:
        return self(
            method=method,
            path=path,
            body=body,
            idempotency_key=idempotency_key,
        )

    def create_session(self,body:dict[str,Any])->dict[str,Any]:
        return self(method="POST",path="/agents/sessions",body=body)

    def retrieve_session(self,session_id:str)->dict[str,Any]:
        return self(method="GET",path=f"/agents/sessions/{session_id}")

    def retrieve_turn(self,session_id:str,turn_id:str)->dict[str,Any]:
        return self(
            method="GET",
            path=f"/agents/sessions/{session_id}/turns/{turn_id}",
        )

    def submit_events(
        self,
        session_id:str,
        events:list[dict[str,Any]],
        *,
        idempotency_key:str|None=None,
    )->dict[str,Any]:
        body={"events":events}
        if idempotency_key:
            body["idempotency_key"]=idempotency_key
        return self(
            method="POST",
            path=f"/agents/sessions/{session_id}/events",
            body=body,
            idempotency_key=idempotency_key,
        )


__all__=[
    "OpenAIAgentsAPIError",
    "OpenAIAgentsHTTPError",
    "OpenAIAgentsHTTPTransport",
]
