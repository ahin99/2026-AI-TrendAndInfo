"""Application-specific errors with safe, user-facing messages."""

from __future__ import annotations


class StudyQuizError(Exception):
    """Base error that may be shown without a traceback."""


class ConfigError(StudyQuizError):
    """Invalid CLI or environment configuration."""


class ApiError(StudyQuizError):
    """An external API request failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def transient(self) -> bool:
        return self.status == 429 or (self.status is not None and self.status >= 500)


class ValidationError(StudyQuizError):
    """External or generated data did not satisfy the repository contract."""


class ConflictError(StudyQuizError):
    """A managed file contains user changes and cannot be overwritten."""
