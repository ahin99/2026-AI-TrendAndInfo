from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "commit_session.sh"


class WorkflowTests(unittest.TestCase):
    def test_workflow_contracts(self) -> None:
        for name, command in (
            ("sync-notion.yml", "python -m study_quiz sync"),
            ("generate-quiz.yml", "python -m study_quiz generate"),
        ):
            text = (ROOT / ".github" / "workflows" / name).read_text(
                encoding="utf-8"
            )
            self.assertIn("workflow_dispatch:", text)
            self.assertIn("contents: write", text)
            self.assertIn("group: study-quiz-${{ github.ref }}", text)
            self.assertIn(command, text)
            self.assertLess(text.index(command), text.index("commit_session.sh"))

    def test_commit_helper_success_and_no_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.name", "Test")
            self.git(repo, "config", "user.email", "test@example.com")
            session = repo / "session01"
            session.mkdir()
            (session / "quiz.md").write_text("old quiz\n", encoding="utf-8")
            (session / "quiz_answers.md").write_text("old answer\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "initial")
            initial_count = self.commit_count(repo)
            env = dict(os.environ, SKIP_PUSH="1")

            subprocess.run(
                ["bash", str(SCRIPT), "quiz", "session01"],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(self.commit_count(repo), initial_count)

            (session / "quiz.md").write_text("new quiz\n", encoding="utf-8")
            (session / "quiz_answers.md").write_text("new answer\n", encoding="utf-8")
            subprocess.run(
                ["bash", str(SCRIPT), "quiz", "session01"],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(self.commit_count(repo), initial_count + 1)
            changed = self.git(repo, "show", "--pretty=", "--name-only", "HEAD")
            self.assertEqual(
                set(changed.splitlines()),
                {"session01/quiz.md", "session01/quiz_answers.md"},
            )

    def test_commit_helper_rejects_unsafe_path_without_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.name", "Test")
            self.git(repo, "config", "user.email", "test@example.com")
            (repo / "seed").write_text("seed", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "initial")
            before = self.commit_count(repo)
            result = subprocess.run(
                ["bash", str(SCRIPT), "sync", "../outside"],
                cwd=repo,
                env=dict(os.environ, SKIP_PUSH="1"),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.commit_count(repo), before)

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit_count(self, repo: Path) -> int:
        return int(self.git(repo, "rev-list", "--count", "HEAD"))


if __name__ == "__main__":
    unittest.main()

