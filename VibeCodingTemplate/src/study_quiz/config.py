"""CLI and environment configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Mapping

from .errors import ConfigError


SESSION_RE = re.compile(r"^[0-9]+$")


def parse_session(value: str) -> int:
    raw = value.strip()
    if not SESSION_RE.fullmatch(raw):
        raise ConfigError("session은 양의 정수여야 합니다.")
    session = int(raw)
    if session <= 0 or session > 9999:
        raise ConfigError("session은 1 이상 9999 이하이어야 합니다.")
    return session


def session_dir_name(session: int) -> str:
    return f"session{session:02d}"


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"필수 환경변수 {name}이(가) 없습니다.")
    return value


@dataclass(frozen=True)
class CommonConfig:
    session: int
    repo_root: Path
    max_retries: int = 2

    @property
    def session_dir(self) -> Path:
        return self.repo_root / session_dir_name(self.session)


@dataclass(frozen=True)
class SyncConfig(CommonConfig):
    notion_token: str = ""
    database_id: str = ""
    data_source_id: str = ""
    notion_api_base: str = "https://api.notion.com/v1"
    notion_version: str = "2025-09-03"
    name_property: str = "Name"
    session_property: str = "Session"
    status_property: str = "Status"
    published_value: str = "Published"
    session_value_template: str = "session{session:02d}"

    @classmethod
    def from_env(
        cls,
        session: int,
        repo_root: Path,
        env: Mapping[str, str] | None = None,
    ) -> "SyncConfig":
        values = os.environ if env is None else env
        template = values.get("NOTION_SESSION_VALUE_TEMPLATE", "session{session:02d}")
        try:
            template.format(session=session)
        except (KeyError, ValueError) as exc:
            raise ConfigError(
                "NOTION_SESSION_VALUE_TEMPLATE은 {session} 형식을 사용해야 합니다."
            ) from exc
        return cls(
            session=session,
            repo_root=repo_root,
            notion_token=_required(values, "NOTION_TOKEN"),
            database_id=_required(values, "NOTION_DATABASE_ID"),
            data_source_id=values.get("NOTION_DATA_SOURCE_ID", "").strip(),
            notion_api_base=values.get(
                "NOTION_API_BASE", "https://api.notion.com/v1"
            ).rstrip("/"),
            notion_version=values.get("NOTION_VERSION", "2025-09-03").strip(),
            name_property=values.get("NOTION_NAME_PROPERTY", "Name").strip(),
            session_property=values.get("NOTION_SESSION_PROPERTY", "Session").strip(),
            status_property=values.get("NOTION_STATUS_PROPERTY", "Status").strip(),
            published_value=values.get("NOTION_PUBLISHED_VALUE", "Published").strip(),
            session_value_template=template,
        )

    @property
    def session_value(self) -> str:
        return self.session_value_template.format(session=self.session)


@dataclass(frozen=True)
class QuizConfig(CommonConfig):
    openai_api_key: str = ""
    openai_model: str = ""
    openai_api_base: str = "https://api.openai.com/v1"

    @classmethod
    def from_env(
        cls,
        session: int,
        repo_root: Path,
        env: Mapping[str, str] | None = None,
    ) -> "QuizConfig":
        values = os.environ if env is None else env
        return cls(
            session=session,
            repo_root=repo_root,
            openai_api_key=_required(values, "OPENAI_API_KEY"),
            openai_model=_required(values, "OPENAI_MODEL"),
            openai_api_base=values.get(
                "OPENAI_API_BASE", "https://api.openai.com/v1"
            ).rstrip("/"),
        )
