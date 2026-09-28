from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from study_quiz.errors import ConflictError
from study_quiz.models import NotionPage
from study_quiz.config import SyncConfig
from study_quiz.errors import ValidationError
from study_quiz.sync import apply_pages, assert_unmodified, scan_managed_files, sync_session


def page(page_id: str, title: str, body: str = "본문") -> NotionPage:
    return NotionPage(
        page_id=page_id,
        title=title,
        url=f"https://notion.so/{page_id}",
        last_edited_time="2026-09-28T00:00:00Z",
        markdown=body + "\n",
    )


class SyncTests(unittest.TestCase):
    def test_empty_notion_session_fails_without_creating_directory(self) -> None:
        class EmptyClient:
            @staticmethod
            def fetch_pages():
                return []

        with tempfile.TemporaryDirectory() as directory:
            config = SyncConfig(
                session=1,
                repo_root=Path(directory),
                notion_token="secret",
                database_id="db",
            )
            with self.assertRaisesRegex(ValidationError, "게시된 노션 글이 없습니다"):
                sync_session(config, EmptyClient())  # type: ignore[arg-type]
            self.assertFalse(config.session_dir.exists())

    def test_new_update_rename_and_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session01"
            first = apply_pages(session, [page("page-11111111", "첫 글")])
            self.assertEqual(len(first), 1)
            managed = scan_managed_files(session)
            old_path = managed["page-11111111"]
            assert_unmodified(old_path)
            self.assertEqual(apply_pages(session, [page("page-11111111", "첫 글")]), [])

            changed = apply_pages(
                session, [page("page-11111111", "바뀐 제목", "새 본문")]
            )
            self.assertIn("이름 변경", changed[0])
            new_path = scan_managed_files(session)["page-11111111"]
            self.assertNotEqual(old_path.name, new_path.name)
            self.assertFalse(old_path.exists())
            self.assertIn("새 본문", new_path.read_text(encoding="utf-8"))

    def test_missing_notion_page_is_not_deleted_and_manual_file_survives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session01"
            apply_pages(session, [page("p1", "하나"), page("p2", "둘")])
            manual = session / "manual.md"
            manual.write_text("직접 작성", encoding="utf-8")
            apply_pages(session, [page("p1", "하나", "변경")])
            self.assertIn("p2", scan_managed_files(session))
            self.assertEqual(manual.read_text(encoding="utf-8"), "직접 작성")

    def test_user_edit_conflict_preserves_all_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session01"
            apply_pages(session, [page("p1", "하나"), page("p2", "둘")])
            managed = scan_managed_files(session)
            p1_before = managed["p1"].read_text(encoding="utf-8")
            with managed["p2"].open("a", encoding="utf-8") as handle:
                handle.write("사용자 수정\n")
            with self.assertRaisesRegex(ConflictError, "사용자 수정 충돌"):
                apply_pages(
                    session,
                    [page("p1", "하나", "새 내용"), page("p2", "둘", "새 내용")],
                )
            self.assertEqual(managed["p1"].read_text(encoding="utf-8"), p1_before)
            self.assertIn("사용자 수정", managed["p2"].read_text(encoding="utf-8"))

    def test_unmanaged_filename_collision_fails_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session01"
            session.mkdir()
            candidate = page("abcdef123456", "제목")
            from study_quiz.sync import page_filename

            collision = session / page_filename(candidate)
            collision.write_text("manual", encoding="utf-8")
            with self.assertRaisesRegex(ConflictError, "이미 존재"):
                apply_pages(session, [candidate])
            self.assertEqual(collision.read_text(encoding="utf-8"), "manual")


if __name__ == "__main__":
    unittest.main()
