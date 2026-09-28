from __future__ import annotations

from pathlib import Path
import unittest

from study_quiz.config import SyncConfig
from study_quiz.errors import ValidationError
from study_quiz.notion import NotionClient, render_blocks

from helpers import FakeTransport, rich_text


class NotionClientTests(unittest.TestCase):
    def config(self) -> SyncConfig:
        return SyncConfig(
            session=1,
            repo_root=Path("."),
            notion_token="secret",
            database_id="database-id",
        )

    def test_fetches_paginated_pages_and_blocks(self) -> None:
        query_calls = 0
        block_calls = 0

        def handler(method, url, headers, payload):
            nonlocal query_calls, block_calls
            self.assertEqual(headers["Authorization"], "Bearer secret")
            if method == "GET" and url.endswith("/databases/database-id"):
                return {"data_sources": [{"id": "source-id"}]}
            if method == "GET" and url.endswith("/data_sources/source-id"):
                return {
                    "properties": {
                        "Name": {"type": "title"},
                        "Session": {"type": "select"},
                        "Status": {"type": "status"},
                    }
                }
            if method == "POST" and url.endswith("/data_sources/source-id/query"):
                query_calls += 1
                self.assertEqual(
                    payload["filter"],
                    {
                        "and": [
                            {"select": {"equals": "session01"}, "property": "Session"},
                            {"status": {"equals": "Published"}, "property": "Status"},
                        ]
                    },
                )
                if query_calls == 1:
                    return {
                        "results": [self.page("p1", "첫 글")],
                        "has_more": True,
                        "next_cursor": "next",
                    }
                self.assertEqual(payload["start_cursor"], "next")
                return {"results": [self.page("p2", "둘째 글")], "has_more": False}
            if method == "GET" and "/blocks/p1/children" in url:
                block_calls += 1
                if "start_cursor" not in url:
                    return {
                        "results": [
                            {
                                "id": "b1",
                                "type": "paragraph",
                                "paragraph": {"rich_text": rich_text("본문")},
                                "has_children": False,
                            }
                        ],
                        "has_more": True,
                        "next_cursor": "block-next",
                    }
                return {
                    "results": [
                        {
                            "id": "b2",
                            "type": "image",
                            "image": {
                                "external": {"url": "https://example.com/image.png"},
                                "caption": rich_text("그림"),
                            },
                            "has_children": False,
                        }
                    ],
                    "has_more": False,
                }
            if method == "GET" and "/blocks/p2/children" in url:
                return {
                    "results": [
                        {
                            "id": "b3",
                            "type": "heading_2",
                            "heading_2": {"rich_text": rich_text("요약")},
                            "has_children": False,
                        }
                    ],
                    "has_more": False,
                }
            self.fail(f"unexpected request: {method} {url}")

        transport = FakeTransport(handler)
        pages = NotionClient(self.config(), transport).fetch_pages()
        self.assertEqual([page.page_id for page in pages], ["p1", "p2"])
        self.assertIn("본문", pages[0].markdown)
        self.assertIn("![그림](https://example.com/image.png)", pages[0].markdown)
        self.assertIn("## 요약", pages[1].markdown)
        self.assertEqual(query_calls, 2)
        self.assertEqual(block_calls, 2)

    def test_number_session_uses_input_number(self) -> None:
        seen_filter = None

        def handler(method, url, headers, payload):
            nonlocal seen_filter
            if url.endswith("/databases/database-id"):
                return {"data_sources": [{"id": "source-id"}]}
            if method == "GET" and url.endswith("/data_sources/source-id"):
                return {
                    "properties": {
                        "Name": {"type": "title"},
                        "Session": {"type": "number"},
                        "Status": {"type": "select"},
                    }
                }
            if method == "POST":
                seen_filter = payload["filter"]
                return {"results": [], "has_more": False}
            self.fail(f"unexpected request: {method} {url}")

        NotionClient(self.config(), FakeTransport(handler)).fetch_pages()
        self.assertEqual(
            seen_filter["and"][0],
            {"number": {"equals": 1}, "property": "Session"},
        )

    def test_incomplete_query_fails(self) -> None:
        def handler(method, url, headers, payload):
            if url.endswith("/databases/database-id"):
                return {"data_sources": [{"id": "source-id"}]}
            if method == "GET":
                return {
                    "properties": {
                        "Name": {"type": "title"},
                        "Session": {"type": "select"},
                        "Status": {"type": "status"},
                    }
                }
            return {
                "results": [],
                "has_more": False,
                "request_status": {"type": "incomplete"},
            }

        with self.assertRaisesRegex(ValidationError, "불완전"):
            NotionClient(self.config(), FakeTransport(handler)).fetch_pages()

    def test_unsupported_block_identifies_block(self) -> None:
        with self.assertRaisesRegex(ValidationError, "table.*block-1"):
            render_blocks([{"id": "block-1", "type": "table", "table": {}}])

    def test_internal_attachment_links_to_original_notion_page(self) -> None:
        result = render_blocks(
            [
                {
                    "id": "file-1",
                    "type": "file",
                    "file": {
                        "file": {"url": "https://temporary.example/download"},
                        "caption": rich_text("자료"),
                    },
                }
            ],
            notion_url="https://notion.so/original-page",
        )
        self.assertIn("[자료](https://notion.so/original-page)", result)
        self.assertNotIn("temporary.example", result)

    @staticmethod
    def page(page_id: str, title: str):
        return {
            "id": page_id,
            "url": f"https://notion.so/{page_id}",
            "last_edited_time": "2026-09-28T00:00:00.000Z",
            "properties": {"Name": {"title": rich_text(title)}},
        }


if __name__ == "__main__":
    unittest.main()
