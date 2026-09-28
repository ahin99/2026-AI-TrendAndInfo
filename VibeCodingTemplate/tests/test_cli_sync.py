from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from study_quiz.__main__ import run
from study_quiz.sync import scan_managed_files

from helpers import FakeTransport, rich_text


class SyncCliIntegrationTests(unittest.TestCase):
    def test_cli_sync_to_file_is_idempotent_and_scoped(self) -> None:
        def handler(method, url, headers, payload):
            if method == "GET" and url.endswith("/data_sources/source-id"):
                return {
                    "properties": {
                        "Name": {"type": "title"},
                        "Session": {"type": "select"},
                        "Status": {"type": "status"},
                    }
                }
            if method == "POST" and url.endswith("/data_sources/source-id/query"):
                return {
                    "results": [
                        {
                            "id": "page-12345678",
                            "url": "https://notion.so/page-12345678",
                            "last_edited_time": "2026-09-28T00:00:00Z",
                            "properties": {"Name": {"title": rich_text("동기화 글")}},
                        }
                    ],
                    "has_more": False,
                }
            if method == "GET" and "/blocks/page-12345678/children" in url:
                return {
                    "results": [
                        {
                            "id": "block-1",
                            "type": "paragraph",
                            "paragraph": {"rich_text": rich_text("동기화 본문")},
                            "has_children": False,
                        }
                    ],
                    "has_more": False,
                }
            self.fail(f"unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / "session02"
            other.mkdir()
            untouched = other / "keep.md"
            untouched.write_text("보존", encoding="utf-8")
            env = {
                "NOTION_TOKEN": "secret",
                "NOTION_DATABASE_ID": "database-id",
                "NOTION_DATA_SOURCE_ID": "source-id",
            }
            transport = FakeTransport(handler)
            args = ["--repo-root", str(root), "sync", "--session", "1"]
            self.assertEqual(run(args, env=env, transport=transport), 0)
            managed = scan_managed_files(root / "session01")
            self.assertEqual(set(managed), {"page-12345678"})
            first_content = managed["page-12345678"].read_text(encoding="utf-8")
            self.assertIn("동기화 본문", first_content)

            self.assertEqual(run(args, env=env, transport=transport), 0)
            self.assertEqual(
                managed["page-12345678"].read_text(encoding="utf-8"), first_content
            )
            self.assertEqual(untouched.read_text(encoding="utf-8"), "보존")


if __name__ == "__main__":
    unittest.main()

