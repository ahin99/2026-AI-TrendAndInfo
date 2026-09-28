from __future__ import annotations

from pathlib import Path
import unittest

from study_quiz.config import QuizConfig, SyncConfig, parse_session, session_dir_name
from study_quiz.errors import ApiError, ConfigError
from study_quiz.http import with_retry


class ConfigTests(unittest.TestCase):
    def test_session_validation_and_path(self) -> None:
        self.assertEqual(parse_session("1"), 1)
        self.assertEqual(parse_session("001"), 1)
        self.assertEqual(session_dir_name(1), "session01")
        self.assertEqual(session_dir_name(120), "session120")
        for invalid in ("", "0", "-1", "1.5", "x", "10000"):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigError):
                parse_session(invalid)

    def test_required_environment_is_checked(self) -> None:
        with self.assertRaisesRegex(ConfigError, "NOTION_TOKEN"):
            SyncConfig.from_env(1, Path("."), {})
        with self.assertRaisesRegex(ConfigError, "OPENAI_API_KEY"):
            QuizConfig.from_env(1, Path("."), {})
        with self.assertRaisesRegex(ConfigError, "OPENAI_MODEL"):
            QuizConfig.from_env(1, Path("."), {"OPENAI_API_KEY": "secret"})

    def test_sync_defaults_and_template(self) -> None:
        config = SyncConfig.from_env(
            3,
            Path("."),
            {"NOTION_TOKEN": "secret", "NOTION_DATABASE_ID": "db"},
        )
        self.assertEqual(config.session_value, "session03")
        self.assertEqual(config.notion_version, "2025-09-03")
        with self.assertRaisesRegex(ConfigError, "TEMPLATE"):
            SyncConfig.from_env(
                1,
                Path("."),
                {
                    "NOTION_TOKEN": "secret",
                    "NOTION_DATABASE_ID": "db",
                    "NOTION_SESSION_VALUE_TEMPLATE": "{missing}",
                },
            )


class RetryTests(unittest.TestCase):
    def test_retries_transient_errors_twice(self) -> None:
        attempts = 0
        sleeps: list[float] = []

        def operation() -> dict[str, object]:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ApiError("temporary", status=503)
            return {"ok": True}

        result = with_retry(
            operation, max_retries=2, sleep=sleeps.append, jitter=lambda: 0.0
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_does_not_retry_permanent_error(self) -> None:
        attempts = 0

        def operation() -> dict[str, object]:
            nonlocal attempts
            attempts += 1
            raise ApiError("bad request", status=400)

        with self.assertRaises(ApiError):
            with_retry(operation, max_retries=2, sleep=lambda _: None)
        self.assertEqual(attempts, 1)


if __name__ == "__main__":
    unittest.main()

