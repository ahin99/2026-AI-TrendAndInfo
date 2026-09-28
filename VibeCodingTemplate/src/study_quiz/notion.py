"""Notion data-source querying and block-to-Markdown conversion."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote

from .config import SyncConfig
from .errors import ValidationError
from .http import JsonTransport, with_retry
from .models import NotionPage


class NotionClient:
    def __init__(self, config: SyncConfig, transport: JsonTransport) -> None:
        self.config = config
        self.transport = transport

    def fetch_pages(self) -> list[NotionPage]:
        data_source_id = self._resolve_data_source_id()
        schema = self._get(f"/data_sources/{quote(data_source_id, safe='')}")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValidationError("노션 데이터 소스에 properties 스키마가 없습니다.")
        query_filter = self._build_filter(properties)

        raw_pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"filter": query_filter, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            response = self._post(
                f"/data_sources/{quote(data_source_id, safe='')}/query", payload
            )
            if _query_incomplete(response):
                raise ValidationError(
                    "노션 데이터 소스 조회가 결과 제한으로 불완전하게 끝났습니다."
                )
            results = response.get("results")
            if not isinstance(results, list):
                raise ValidationError("노션 페이지 목록 응답에 results가 없습니다.")
            for item in results:
                if not isinstance(item, dict):
                    raise ValidationError("노션 페이지 목록에 객체가 아닌 항목이 있습니다.")
                raw_pages.append(item)
            if not response.get("has_more"):
                break
            cursor_value = response.get("next_cursor")
            if not isinstance(cursor_value, str) or not cursor_value:
                raise ValidationError("노션 pagination cursor가 올바르지 않습니다.")
            cursor = cursor_value

        pages: list[NotionPage] = []
        for raw_page in raw_pages:
            page_id = _required_string(raw_page, "id", "노션 페이지")
            title = self._page_title(raw_page)
            page_url = _required_string(raw_page, "url", f"노션 페이지 {page_id}")
            edited = _required_string(
                raw_page, "last_edited_time", f"노션 페이지 {page_id}"
            )
            blocks = self._all_block_children(page_id)
            markdown = render_blocks(blocks, notion_url=page_url).strip()
            if not markdown:
                raise ValidationError(f"노션 페이지 {page_id}의 텍스트 본문이 비어 있습니다.")
            pages.append(
                NotionPage(
                    page_id=page_id,
                    title=title,
                    url=page_url,
                    last_edited_time=edited,
                    markdown=markdown + "\n",
                )
            )
        return pages

    def _resolve_data_source_id(self) -> str:
        if self.config.data_source_id:
            return self.config.data_source_id
        database = self._get(
            f"/databases/{quote(self.config.database_id, safe='')}"
        )
        sources = database.get("data_sources")
        if not isinstance(sources, list) or not sources:
            raise ValidationError(
                "노션 database 응답에 data_sources가 없습니다. "
                "NOTION_DATA_SOURCE_ID를 직접 설정할 수 있습니다."
            )
        ids = [item.get("id") for item in sources if isinstance(item, dict)]
        valid_ids = [value for value in ids if isinstance(value, str) and value]
        if len(valid_ids) != 1:
            raise ValidationError(
                "노션 database에 데이터 소스가 여러 개입니다. "
                "NOTION_DATA_SOURCE_ID를 지정하세요."
            )
        return valid_ids[0]

    def _build_filter(self, properties: dict[str, Any]) -> dict[str, Any]:
        session_condition = _property_condition(
            properties,
            self.config.session_property,
            self.config.session_value,
            number_value=self.config.session,
        )
        status_condition = _property_condition(
            properties,
            self.config.status_property,
            self.config.published_value,
        )
        name_schema = properties.get(self.config.name_property)
        if not isinstance(name_schema, dict) or name_schema.get("type") != "title":
            raise ValidationError(
                f"노션 제목 속성 {self.config.name_property!r}이 title 형식이 아닙니다."
            )
        return {"and": [session_condition, status_condition]}

    def _page_title(self, page: dict[str, Any]) -> str:
        properties = page.get("properties")
        if not isinstance(properties, dict):
            raise ValidationError("노션 페이지에 properties가 없습니다.")
        title_property = properties.get(self.config.name_property)
        if not isinstance(title_property, dict):
            raise ValidationError(
                f"노션 페이지에 제목 속성 {self.config.name_property!r}이 없습니다."
            )
        title = rich_text_plain(title_property.get("title"))
        if not title.strip():
            raise ValidationError("노션 페이지 제목이 비어 있습니다.")
        return title.strip()

    def _all_block_children(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            suffix = "?page_size=100"
            if cursor:
                suffix += f"&start_cursor={quote(cursor, safe='')}"
            response = self._get(
                f"/blocks/{quote(block_id, safe='')}/children{suffix}"
            )
            results = response.get("results")
            if not isinstance(results, list):
                raise ValidationError(
                    f"노션 블록 {block_id}의 children 응답이 올바르지 않습니다."
                )
            for item in results:
                if not isinstance(item, dict):
                    raise ValidationError(
                        f"노션 블록 {block_id}에 잘못된 child가 있습니다."
                    )
                block = dict(item)
                if block.get("has_children"):
                    child_id = _required_string(block, "id", "노션 블록")
                    block["_children"] = self._all_block_children(child_id)
                blocks.append(block)
            if not response.get("has_more"):
                break
            cursor_value = response.get("next_cursor")
            if not isinstance(cursor_value, str) or not cursor_value:
                raise ValidationError("노션 블록 pagination cursor가 올바르지 않습니다.")
            cursor = cursor_value
        return blocks

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.notion_token}",
            "Notion-Version": self.config.notion_version,
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict[str, Any]:
        return with_retry(
            lambda: self.transport.request(
                "GET", self.config.notion_api_base + path, headers=self._headers()
            ),
            max_retries=self.config.max_retries,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return with_retry(
            lambda: self.transport.request(
                "POST",
                self.config.notion_api_base + path,
                headers=self._headers(),
                payload=payload,
            ),
            max_retries=self.config.max_retries,
        )


def _query_incomplete(response: dict[str, Any]) -> bool:
    status = response.get("request_status")
    return isinstance(status, dict) and status.get("type") == "incomplete"


def _property_condition(
    properties: dict[str, Any],
    name: str,
    text_value: str,
    *,
    number_value: int | None = None,
) -> dict[str, Any]:
    definition = properties.get(name)
    if not isinstance(definition, dict):
        raise ValidationError(f"노션 속성 {name!r}이 없습니다.")
    property_type = definition.get("type")
    if property_type == "number":
        if number_value is None:
            try:
                number_value = int(text_value)
            except ValueError as exc:
                raise ValidationError(
                    f"노션 number 속성 {name!r}에 사용할 값이 숫자가 아닙니다."
                ) from exc
        condition: dict[str, Any] = {"number": {"equals": number_value}}
    elif property_type in {"select", "status", "rich_text", "title"}:
        condition = {str(property_type): {"equals": text_value}}
    else:
        raise ValidationError(
            f"노션 속성 {name!r}의 형식 {property_type!r}은 지원하지 않습니다."
        )
    condition["property"] = name
    return condition


def _required_string(value: dict[str, Any], key: str, context: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValidationError(f"{context}에 문자열 {key!r} 값이 없습니다.")
    return result


def rich_text_plain(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "".join(
        item.get("plain_text", "")
        for item in value
        if isinstance(item, dict) and isinstance(item.get("plain_text", ""), str)
    )


def rich_text_markdown(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("plain_text", "")
        if not isinstance(text, str):
            continue
        text = text.replace("\\", "\\\\")
        annotations = item.get("annotations")
        if isinstance(annotations, dict):
            if annotations.get("code"):
                escaped_code = text.replace("`", "\\`")
                text = f"`{escaped_code}`"
            if annotations.get("bold"):
                text = f"**{text}**"
            if annotations.get("italic"):
                text = f"*{text}*"
            if annotations.get("strikethrough"):
                text = f"~~{text}~~"
        href = item.get("href")
        if isinstance(href, str) and href:
            text = f"[{text}]({href})"
        parts.append(text)
    return "".join(parts)


def render_blocks(
    blocks: Iterable[dict[str, Any]], indent: int = 0, notion_url: str = ""
) -> str:
    lines: list[str] = []
    ordered_number = 1
    previous_type = ""
    for block in blocks:
        block_type = block.get("type")
        if not isinstance(block_type, str):
            raise ValidationError("노션 블록 type이 없습니다.")
        data = block.get(block_type)
        if not isinstance(data, dict):
            data = {}
        text = rich_text_markdown(data.get("rich_text"))
        prefix = " " * indent
        if block_type == "paragraph":
            lines.append(prefix + text)
        elif block_type in {"heading_1", "heading_2", "heading_3"}:
            level = int(block_type[-1])
            lines.append(prefix + ("#" * level) + " " + text)
        elif block_type == "bulleted_list_item":
            lines.append(prefix + "- " + text)
        elif block_type == "numbered_list_item":
            if previous_type != "numbered_list_item":
                ordered_number = 1
            lines.append(prefix + f"{ordered_number}. " + text)
            ordered_number += 1
        elif block_type == "to_do":
            marker = "x" if data.get("checked") else " "
            lines.append(prefix + f"- [{marker}] " + text)
        elif block_type == "quote":
            lines.append(prefix + "> " + text)
        elif block_type == "callout":
            icon = data.get("icon")
            emoji = icon.get("emoji", "") if isinstance(icon, dict) else ""
            lines.append(prefix + "> " + (f"{emoji} " if emoji else "") + text)
        elif block_type == "code":
            language = data.get("language", "")
            language = language if isinstance(language, str) else ""
            lines.extend([prefix + f"```{language}", text, prefix + "```"])
        elif block_type == "divider":
            lines.append(prefix + "---")
        elif block_type == "toggle":
            lines.append(prefix + f"<details><summary>{text}</summary>")
        elif block_type == "equation":
            expression = data.get("expression")
            if not isinstance(expression, str):
                raise ValidationError("노션 equation 블록에 expression이 없습니다.")
            lines.append(prefix + f"$${expression}$$")
        elif block_type in {"image", "file", "pdf", "video", "audio"}:
            url = _file_url(data, notion_url)
            caption = rich_text_plain(data.get("caption")).strip()
            label = caption or ("이미지" if block_type == "image" else "첨부파일")
            if block_type == "image":
                lines.append(prefix + f"![{label}]({url})")
            else:
                lines.append(prefix + f"[{label}]({url})")
        elif block_type in {"bookmark", "embed", "link_preview"}:
            url = data.get("url")
            if not isinstance(url, str) or not url:
                raise ValidationError(f"노션 {block_type} 블록에 URL이 없습니다.")
            caption = rich_text_plain(data.get("caption")).strip() or url
            lines.append(prefix + f"[{caption}]({url})")
        elif block_type in {"column_list", "column", "synced_block"}:
            pass
        else:
            block_id = block.get("id", "unknown")
            raise ValidationError(
                f"지원하지 않는 노션 블록 {block_type!r} (block {block_id})"
            )

        children = block.get("_children")
        if isinstance(children, list) and children:
            child_indent = indent + 2 if block_type.endswith("list_item") else indent
            rendered = render_blocks(
                children, child_indent, notion_url=notion_url
            ).rstrip()
            if rendered:
                lines.append(rendered)
        if block_type == "toggle":
            lines.append(prefix + "</details>")
        lines.append("")
        previous_type = block_type
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _file_url(data: dict[str, Any], notion_url: str) -> str:
    external = data.get("external")
    if isinstance(external, dict):
        url = external.get("url")
        if isinstance(url, str) and url:
            return url
    internal = data.get("file")
    if isinstance(internal, dict) and notion_url:
        return notion_url
    raise ValidationError("노션 파일 블록에 원본 URL이 없습니다.")
