"""Minimal JSON HTTP transport and bounded retry handling."""

from __future__ import annotations

import json
import random
import time
from typing import Any, Callable, Mapping
from urllib import error, request

from .errors import ApiError


class JsonTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        raise NotImplementedError


class UrllibJsonTransport(JsonTransport):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = request.Request(
            url, data=body, headers=request_headers, method=method.upper()
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            message = _safe_http_error(exc)
            raise ApiError(
                f"외부 API 요청 실패(HTTP {exc.code}): {message}", status=exc.code
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ApiError("외부 API 연결 또는 timeout 오류가 발생했습니다.", status=503) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError("외부 API가 올바른 JSON을 반환하지 않았습니다.") from exc
        if not isinstance(parsed, dict):
            raise ApiError("외부 API JSON의 최상위 값이 객체가 아닙니다.")
        return parsed


def _safe_http_error(exc: error.HTTPError) -> str:
    try:
        raw = exc.read(8192).decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            message = parsed.get("message")
            if not isinstance(message, str):
                nested = parsed.get("error")
                if isinstance(nested, dict):
                    message = nested.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return "응답 본문에 안전한 오류 메시지가 없습니다."


def with_retry(
    operation: Callable[[], dict[str, Any]],
    *,
    max_retries: int,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> dict[str, Any]:
    attempt = 0
    while True:
        try:
            return operation()
        except ApiError as exc:
            if not exc.transient or attempt >= max_retries:
                raise
            delay = (2**attempt) + min(max(jitter(), 0.0), 1.0)
            sleep(delay)
            attempt += 1
