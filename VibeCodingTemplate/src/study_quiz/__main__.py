"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Mapping, Sequence

from .config import QuizConfig, SyncConfig, parse_session
from .errors import StudyQuizError
from .http import JsonTransport, UrllibJsonTransport
from .notion import NotionClient
from .quiz import OpenAIQuizClient, generate_quiz
from .summary import write_failure, write_success
from .sync import sync_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="study-quiz",
        description="노션 스터디 글을 동기화하고 session 퀴즈를 생성합니다.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="session 디렉터리를 둘 저장소 경로(기본값: 현재 경로)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("sync", "노션 글을 지정 session에 동기화"),
        ("generate", "지정 session 글로 퀴즈 생성"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--session", required=True, type=parse_session)
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: JsonTransport | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    values = os.environ if env is None else env
    api_transport = transport or UrllibJsonTransport()
    repo_root = args.repo_root.resolve()
    operation = "notion-sync" if args.command == "sync" else "quiz-generation"
    try:
        if args.command == "sync":
            config = SyncConfig.from_env(args.session, repo_root, values)
            result = sync_session(config, NotionClient(config, api_transport))
        else:
            config = QuizConfig.from_env(args.session, repo_root, values)
            result = generate_quiz(config, OpenAIQuizClient(config, api_transport))
    except StudyQuizError as exc:
        write_failure(operation, str(exc), values)
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    print(write_success(result, values))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

