"""Small immutable models shared by synchronization and generation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotionPage:
    page_id: str
    title: str
    url: str
    last_edited_time: str
    markdown: str


@dataclass(frozen=True)
class Article:
    path: Path
    relative_path: str
    content: str


@dataclass(frozen=True)
class QuizQuestion:
    question: str
    choices: tuple[str, str, str, str]
    answer: int
    explanation: str
    source: str


@dataclass(frozen=True)
class RunResult:
    operation: str
    session_dir: str
    changed: bool
    item_count: int
    details: tuple[str, ...] = ()

