from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from study_quiz.__main__ import run
from study_quiz.config import QuizConfig
from study_quiz.errors import ApiError, ValidationError
from study_quiz.models import Article
from study_quiz.quiz import (
    OpenAIQuizClient,
    generate_quiz,
    parse_quiz_response,
    render_quiz,
)

from helpers import FakeTransport


def valid_quiz(source: str = "article.md") -> dict[str, object]:
    return {
        "questions": [
            {
                "question": "핵심 내용은?",
                "choices": ["정답", "오답 1", "오답 2", "오답 3"],
                "answer": 1,
                "explanation": "글에 정답이라고 설명되어 있다.",
                "source": source,
            }
        ]
    }


class QuizTests(unittest.TestCase):
    def article(self) -> Article:
        return Article(Path("article.md"), "article.md", "# 글\n정답")

    def config(self, root: Path, retries: int = 2) -> QuizConfig:
        return QuizConfig(
            session=1,
            repo_root=root,
            max_retries=retries,
            openai_api_key="secret",
            openai_model="test-model",
        )

    def test_structured_payload_and_invalid_response_retry(self) -> None:
        responses = [
            {"output_text": '{"questions": []}'},
            {"output_text": json.dumps(valid_quiz(), ensure_ascii=False)},
        ]

        def handler(method, url, headers, payload):
            self.assertEqual(method, "POST")
            self.assertTrue(url.endswith("/responses"))
            self.assertEqual(headers["Authorization"], "Bearer secret")
            schema_format = payload["text"]["format"]
            self.assertEqual(schema_format["type"], "json_schema")
            self.assertTrue(schema_format["strict"])
            self.assertEqual(
                schema_format["schema"]["properties"]["questions"]["maxItems"], 20
            )
            self.assertNotIn("minLength", json.dumps(schema_format["schema"]))
            return responses.pop(0)

        transport = FakeTransport(handler)
        questions = OpenAIQuizClient(
            self.config(Path(".")), transport
        ).generate([self.article()])
        self.assertEqual(len(questions), 1)
        self.assertEqual(len(transport.calls), 2)

    def test_permanent_api_error_is_not_retried(self) -> None:
        def handler(method, url, headers, payload):
            raise ApiError("bad request", status=400)

        transport = FakeTransport(handler)
        with self.assertRaises(ApiError):
            OpenAIQuizClient(self.config(Path(".")), transport).generate(
                [self.article()]
            )
        self.assertEqual(len(transport.calls), 1)

    def test_response_validation_and_render(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(valid_quiz(), ensure_ascii=False),
                        }
                    ],
                }
            ]
        }
        questions = parse_quiz_response(response, [self.article()])
        quiz, answers = render_quiz(questions)
        self.assertIn("① 정답", quiz)
        self.assertNotIn("정답 1", quiz)
        self.assertIn("정답 1", answers)
        self.assertIn("[article.md](article.md)", answers)

        invalid = valid_quiz()
        invalid["questions"][0]["source"] = "missing.md"  # type: ignore[index]
        with self.assertRaisesRegex(ValidationError, "존재하지"):
            parse_quiz_response(
                {"output_text": json.dumps(invalid, ensure_ascii=False)},
                [self.article()],
            )

    def test_cli_generate_writes_both_files_and_preserves_other_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session01"
            session.mkdir()
            (session / "article.md").write_text("# 글\n정답", encoding="utf-8")
            other = root / "session02"
            other.mkdir()
            other_file = other / "keep.md"
            other_file.write_text("보존", encoding="utf-8")
            summary = root / "summary.md"

            transport = FakeTransport(
                lambda method, url, headers, payload: {
                    "output_text": json.dumps(valid_quiz(), ensure_ascii=False)
                }
            )
            result = run(
                ["--repo-root", str(root), "generate", "--session", "1"],
                env={
                    "OPENAI_API_KEY": "secret",
                    "OPENAI_MODEL": "test-model",
                    "GITHUB_STEP_SUMMARY": str(summary),
                },
                transport=transport,
            )
            self.assertEqual(result, 0)
            self.assertTrue((session / "quiz.md").is_file())
            self.assertTrue((session / "quiz_answers.md").is_file())
            self.assertEqual(other_file.read_text(encoding="utf-8"), "보존")
            self.assertIn("성공", summary.read_text(encoding="utf-8"))

    def test_invalid_ai_response_preserves_both_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session01"
            session.mkdir()
            (session / "article.md").write_text("근거 글", encoding="utf-8")
            quiz = session / "quiz.md"
            answers = session / "quiz_answers.md"
            quiz.write_text("기존 문제", encoding="utf-8")
            answers.write_text("기존 정답", encoding="utf-8")
            transport = FakeTransport(
                lambda method, url, headers, payload: {
                    "output_text": '{"questions": []}'
                }
            )
            config = self.config(root, retries=0)
            with self.assertRaises(ValidationError):
                generate_quiz(config, OpenAIQuizClient(config, transport))
            self.assertEqual(quiz.read_text(encoding="utf-8"), "기존 문제")
            self.assertEqual(answers.read_text(encoding="utf-8"), "기존 정답")

    def test_cli_missing_secret_changes_nothing_and_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "session01"
            session.mkdir()
            article = session / "article.md"
            article.write_text("원본", encoding="utf-8")
            summary = root / "summary.md"
            transport = FakeTransport(lambda *args: self.fail("API must not be called"))
            result = run(
                ["--repo-root", str(root), "generate", "--session", "1"],
                env={"GITHUB_STEP_SUMMARY": str(summary)},
                transport=transport,
            )
            self.assertEqual(result, 1)
            self.assertEqual(article.read_text(encoding="utf-8"), "원본")
            self.assertFalse((session / "quiz.md").exists())
            self.assertIn("실패", summary.read_text(encoding="utf-8"))
            self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
