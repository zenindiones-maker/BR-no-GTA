from __future__ import annotations

import json
import os
import time
from socket import timeout as SocketTimeout
from typing import Any
from urllib import error, request

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage

DEFAULT_NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_NIM_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_NVIDIA_NIM_TIMEOUT_SECONDS = 120.0
_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}

class NvidiaNIMProviderError(AIProviderError):
    def __init__(self, safe_message: str, *, code: str, status_code: int | None = None,
                 retryable: bool = False, failure_stage: str = "provider_request",
                 response_present: bool | None = None,
                 structured_output_present: bool | None = None,
                 parse_stage: str | None = None,
                 exception_class: str | None = None,
                 sanitized_reason: str | None = None) -> None:
        super().__init__(
            safe_message, code=code, status_code=status_code, retryable=retryable,
            failure_pattern=f"nvidia_nim_{sanitized_reason or code}",
            failure_stage=failure_stage, transport="nvidia_openai_chat_completions",
            response_present=response_present,
            structured_output_present=structured_output_present,
            parse_stage=parse_stage,
            exception_class=exception_class or type(self).__name__,
            sanitized_reason=sanitized_reason or code,
        )
        self.provider = "nvidia_nim"

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, **super().to_dict()}

class NvidiaNimProviderAdapter:
    """Single generic adapter. DeepSeek Harness owns model selection."""
    def __init__(self, *, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout_seconds: float | None = None,
                 max_retries: int = 1) -> None:
        self.model = model or os.getenv("NVIDIA_NIM_MODEL") or DEFAULT_NVIDIA_NIM_MODEL
        root = (base_url or os.getenv("NVIDIA_NIM_BASE_URL") or DEFAULT_NVIDIA_NIM_BASE_URL).rstrip("/")
        if root.endswith("/chat/completions"):
            self.base_url = root[:-len("/chat/completions")]
            self.endpoint_url = root
        else:
            self.base_url = root
            self.endpoint_url = root + "/chat/completions"
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY")
        configured = os.getenv("NVIDIA_NIM_TIMEOUT_SECONDS")
        self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else configured or DEFAULT_NVIDIA_NIM_TIMEOUT_SECONDS)
        self.max_retries = int(max_retries)
        if self.max_retries not in (0, 1):
            raise ValueError("NVIDIA NIM max_retries must be 0 or 1")
        self.last_retry_count = 0
        self.last_http_status: int | None = None
        self.last_performance_metrics: dict[str, Any] = {}

    def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise NvidiaNIMProviderError(
                "NVIDIA_API_KEY is required when NVIDIA NIM is selected",
                code="missing_api_key", failure_stage="authentication_preflight",
                response_present=False, structured_output_present=False,
                parse_stage="preflight", exception_class="MissingCredential",
                sanitized_reason="missing_api_key",
            )
        body=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode("utf-8")
        req=request.Request(self.endpoint_url,data=body,headers={
            "Accept":"application/json","Content-Type":"application/json",
            "Authorization":f"Bearer {self._api_key}"},method="POST")
        self.last_retry_count=0
        raw=b""
        started=time.perf_counter()
        for attempt in range(self.max_retries+1):
            try:
                with request.urlopen(req,timeout=self.timeout_seconds) as response:
                    self.last_http_status=int(getattr(response,"status",200) or 200)
                    raw=response.read()
                break
            except error.HTTPError as exc:
                self.last_http_status=int(exc.code)
                retryable=int(exc.code) in _RETRYABLE_HTTP_STATUS
                if retryable and attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise self._http_error(int(exc.code)) from None
            except (TimeoutError,SocketTimeout):
                if attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise NvidiaNIMProviderError(
                    "NVIDIA NIM request timed out",code="timeout",retryable=True,
                    failure_stage="transport_request",response_present=False,
                    structured_output_present=False,parse_stage="transport",
                    exception_class="TimeoutError",sanitized_reason="timeout") from None
            except (error.URLError,OSError) as exc:
                if attempt < self.max_retries:
                    self.last_retry_count += 1
                    continue
                raise NvidiaNIMProviderError(
                    "NVIDIA NIM transport failed",code="transport_error",retryable=True,
                    failure_stage="transport_request",response_present=False,
                    structured_output_present=False,parse_stage="transport",
                    exception_class=type(exc).__name__,sanitized_reason="transport_error") from None
        latency=max(0.0,time.perf_counter()-started)
        self.last_performance_metrics={
            "transport":"nvidia_openai_chat_completions",
            "latency_seconds":latency,"timeout_seconds":self.timeout_seconds,
            "retry_count":self.last_retry_count,"http_status":self.last_http_status}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError):
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned invalid JSON",code="invalid_json",
                failure_stage="response_decode",response_present=True,
                structured_output_present=False,parse_stage="json_decode",
                exception_class="JSONDecodeError",sanitized_reason="invalid_json") from None

    def generate(self,prompt:str)->AIResponse:
        if not prompt or not prompt.strip():
            raise NvidiaNIMProviderError(
                "Prompt must not be empty",code="invalid_prompt",
                failure_stage="request_validation",response_present=False,
                structured_output_present=False,parse_stage="preflight",
                exception_class="ValueError",sanitized_reason="invalid_prompt")
        data=self._request_json({"model":self.model,"messages":[{"role":"user","content":prompt}]})
        try:
            choice=data["choices"][0]; message=choice["message"]; text=message["content"]
        except (KeyError,IndexError,TypeError):
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned an invalid chat completion",code="invalid_completion",
                failure_stage="response_extract",response_present=True,
                structured_output_present=isinstance(data,dict),
                parse_stage="chat_completion_content",exception_class="InvalidCompletion",
                sanitized_reason="invalid_completion") from None
        if not isinstance(text,str) or not text.strip():
            raise NvidiaNIMProviderError(
                "NVIDIA NIM returned an empty response",code="empty_response",
                failure_stage="response_extract",response_present=True,
                structured_output_present=isinstance(data,dict),
                parse_stage="chat_completion_content",exception_class="EmptyProviderResponse",
                sanitized_reason="empty_response")
        reasoning=message.get("reasoning_content")
        if not isinstance(reasoning,str): reasoning=None
        return AIResponse(
            text=text.strip(),provider="nvidia_nim",model=data.get("model") or self.model,
            reasoning_content=reasoning,usage=self._normalize_usage(data.get("usage")),
            finish_reason=choice.get("finish_reason"))

    def probe_capabilities(self)->dict[str,Any]:
        data=self._request_json({
            "model":self.model,
            "messages":[{"role":"user","content":
                'If function calling is supported call br_probe once with {"result":"ok"}. Otherwise return exactly {"result":"ok"}.'}],
            "tools":[{"type":"function","function":{
                "name":"br_probe","description":"Deterministic capability probe.",
                "parameters":{"type":"object","properties":{"result":{"type":"string"}},
                              "required":["result"],"additionalProperties":False}}}],
            "tool_choice":"auto","temperature":0,"max_tokens":96})
        choices=data.get("choices") if isinstance(data,dict) else None
        message=choices[0].get("message") if isinstance(choices,list) and choices and isinstance(choices[0],dict) else {}
        tool_calls=message.get("tool_calls") if isinstance(message,dict) else None
        tool_supported=False; structured=False
        if isinstance(tool_calls,list):
            for item in tool_calls:
                fn=item.get("function") if isinstance(item,dict) else None
                if not isinstance(fn,dict) or fn.get("name")!="br_probe": continue
                tool_supported=True
                try: args=json.loads(str(fn.get("arguments") or ""))
                except json.JSONDecodeError: args={}
                structured=args.get("result")=="ok"
                if structured: break
        content=message.get("content") if isinstance(message,dict) else None
        if not structured and isinstance(content,str) and content.strip():
            try:
                parsed=json.loads(content.strip())
                structured=isinstance(parsed,dict) and parsed.get("result")=="ok"
            except json.JSONDecodeError: structured=False
        usage=self._normalize_usage(data.get("usage") if isinstance(data,dict) else None)
        valid=bool(tool_supported or (isinstance(content,str) and content.strip()))
        return {
            "MODEL_ID":self.model,"HTTP_STATUS":self.last_http_status,
            "RESPONSE_VALID":valid,
            "LATENCY_MS":round(float(self.last_performance_metrics.get("latency_seconds") or 0.0)*1000,2),
            "TOOL_USE_SUPPORTED":tool_supported,
            "STRUCTURED_OUTPUT_RESULT":"PASS" if structured else "FAIL",
            "RATE_LIMIT_OBSERVED":False,
            "TOKEN_USAGE_IF_AVAILABLE":{
                "prompt_tokens":usage.prompt_tokens if usage else None,
                "completion_tokens":usage.completion_tokens if usage else None,
                "total_tokens":usage.total_tokens if usage else None,
                "reasoning_tokens":usage.reasoning_tokens if usage else None},
            "BILLING_CLASS":"NVIDIA_FREE_ENDPOINT",
            "HEALTH":"AVAILABLE" if valid else "DEGRADED"}

    @staticmethod
    def _normalize_usage(raw:Any)->AIUsage|None:
        if not isinstance(raw,dict): return None
        details=raw.get("completion_tokens_details")
        reasoning=details.get("reasoning_tokens") if isinstance(details,dict) else None
        def oi(v): return v if isinstance(v,int) and not isinstance(v,bool) else None
        return AIUsage(prompt_tokens=oi(raw.get("prompt_tokens")),
                       completion_tokens=oi(raw.get("completion_tokens")),
                       total_tokens=oi(raw.get("total_tokens")),
                       reasoning_tokens=oi(reasoning))

    @staticmethod
    def _http_error(status:int)->NvidiaNIMProviderError:
        mapping={401:("authentication_failed","NVIDIA NIM authentication failed",False),
                 403:("forbidden","NVIDIA NIM request was forbidden",False),
                 410:("gone","NVIDIA NIM endpoint or model is no longer available",False),
                 422:("invalid_request","NVIDIA NIM rejected the request",False),
                 429:("rate_limited","NVIDIA NIM rate limit exceeded",True)}
        if status in mapping: code,msg,retry=mapping[status]
        elif 500<=status<=599: code,msg,retry="upstream_error","NVIDIA NIM upstream service failed",True
        else: code,msg,retry="http_error","NVIDIA NIM request failed",False
        return NvidiaNIMProviderError(
            msg,code=code,status_code=status,retryable=retry,
            failure_stage="transport_response",response_present=True,
            structured_output_present=None,parse_stage="http_status",
            exception_class="HTTPError",sanitized_reason=code)

    def safe_configuration(self)->dict[str,Any]:
        return {"provider":"nvidia_nim","base_url":self.base_url,
                "endpoint_url":self.endpoint_url,"model":self.model,
                "timeout_seconds":self.timeout_seconds,
                "api_key_configured":bool(self._api_key)}

# Compatibility alias; still one implementation.
NvidiaNIMProvider=NvidiaNimProviderAdapter
