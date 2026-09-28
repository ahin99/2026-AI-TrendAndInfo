from __future__ import annotations

from typing import Any, Callable, Mapping

from study_quiz.http import JsonTransport


class FakeTransport(JsonTransport):
    def __init__(
        self,
        handler: Callable[[str, str, Mapping[str, str], Mapping[str, Any] | None], dict[str, Any]],
    ) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        del timeout
        copied_payload = dict(payload) if payload is not None else None
        copied_headers = dict(headers or {})
        self.calls.append((method, url, copied_headers, copied_payload))
        return self.handler(method, url, copied_headers, copied_payload)


def rich_text(text: str) -> list[dict[str, Any]]:
    return [
        {
            "plain_text": text,
            "href": None,
            "annotations": {
                "bold": False,
                "italic": False,
                "strikethrough": False,
                "code": False,
            },
        }
    ]

