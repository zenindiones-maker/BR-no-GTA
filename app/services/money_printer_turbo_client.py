from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol



class HTTPTransport(Protocol):
    """Contrato de transporte HTTP injetável para testes."""

    def open(
        self,
        request: urllib.request.Request,
        timeout: float,
    ) -> Any:
        ...


class _UrllibTransport:
    """Transporte HTTP real baseado na biblioteca padrão."""

    @staticmethod
    def open(
        request: urllib.request.Request,
        timeout: float,
    ) -> Any:
        return urllib.request.urlopen(
            request,
            timeout=timeout,
        )


class MoneyPrinterTurboClient:
    """
    Cliente HTTP mínimo para comunicação com o MoneyPrinterTurbo.

    Responsabilidades:
    - enviar POST /videos;
    - consultar GET /tasks/{task_id};
    - autenticar quando API key estiver configurada;
    - converter respostas JSON;
    - normalizar erros HTTP/rede.

    Não conhece Render Job, fila, banco ou regras editoriais.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 30.0,
        transport: HTTPTransport | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError(
                "base_url deve ser uma string não vazia."
            )

        if timeout <= 0:
            raise ValueError(
                "timeout deve ser maior que zero."
            )

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip() if api_key else ""
        self.timeout = timeout
        self._transport = transport or _UrllibTransport()

    def create_video(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Cria uma task de produção no MoneyPrinterTurbo.

        Endpoint:
            POST /videos
        """

        self._validate_payload(payload)

        return self._request_json(
            method="POST",
            path="/videos",
            payload=payload,
        )

    def get_task(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        """
        Consulta o estado de uma task do MoneyPrinterTurbo.

        Endpoint:
            GET /tasks/{task_id}
        """

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(
                "task_id deve ser uma string não vazia."
            )

        task_id = task_id.strip()

        return self._request_json(
            method="GET",
            path=f"/tasks/{urllib.parse.quote(task_id, safe='')}",
        )

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"

        headers = {
            "Accept": "application/json",
        }

        data = None

        if payload is not None:
            data = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")

            headers["Content-Type"] = "application/json"

        if self.api_key:
            headers["Authorization"] = (
                f"Bearer {self.api_key}"
            )

        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )

        try:
            with self._transport.open(
                request,
                timeout=self.timeout,
            ) as response:
                status_code = getattr(response, "status", None)

                if status_code is None:
                    status_code = response.status_code

                body = response.read()

        except urllib.error.HTTPError as exc:
            body = exc.read()

            detail = self._extract_error_detail(body)

            raise RuntimeError(
                "MoneyPrinterTurbo retornou HTTP "
                f"{exc.code}: {detail}"
            ) from exc

        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Não foi possível conectar ao "
                f"MoneyPrinterTurbo: {exc.reason}"
            ) from exc

        except TimeoutError as exc:
            raise RuntimeError(
                "Tempo limite excedido ao comunicar "
                "com o MoneyPrinterTurbo."
            ) from exc

        except OSError as exc:
            raise RuntimeError(
                "Erro de rede ao comunicar com o "
                f"MoneyPrinterTurbo: {exc}"
            ) from exc

        if status_code < 200 or status_code >= 300:
            detail = self._extract_error_detail(body)

            raise RuntimeError(
                "MoneyPrinterTurbo retornou HTTP "
                f"{status_code}: {detail}"
            )

        try:
            result = json.loads(
                body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "MoneyPrinterTurbo retornou uma resposta "
                "que não é JSON válido."
            ) from exc

        if not isinstance(result, dict):
            raise RuntimeError(
                "MoneyPrinterTurbo retornou JSON em "
                "formato inválido."
            )

        return result

    @staticmethod
    def _extract_error_detail(
        body: bytes,
    ) -> str:
        if not body:
            return "sem detalhes."

        try:
            payload = json.loads(
                body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return body.decode(
                "utf-8",
                errors="replace",
            ).strip() or "sem detalhes."

        if isinstance(payload, dict):
            for field in (
                "detail",
                "error",
                "message",
            ):
                value = payload.get(field)

                if value:
                    return str(value)

        return str(payload)

    @staticmethod
    def _validate_payload(
        payload: dict[str, Any],
    ) -> None:
        if not isinstance(payload, dict) or not payload:
            raise ValueError(
                "payload deve ser um dicionário não vazio."
            )
