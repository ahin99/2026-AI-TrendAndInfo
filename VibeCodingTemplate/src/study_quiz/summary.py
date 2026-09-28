"""Console and GitHub Actions summary reporting."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .models import RunResult


def write_success(result: RunResult, env: Mapping[str, str] | None = None) -> str:
    action = "변경됨" if result.changed else "변경 없음"
    message = (
        f"{result.operation} 완료: {result.session_dir}, "
        f"항목 {result.item_count}개, {action}"
    )
    lines = [f"## {result.operation} 성공", "", f"- Session: `{result.session_dir}`", f"- 결과: {action}", f"- 항목 수: {result.item_count}"]
    if result.details:
        lines.extend(["", "### 세부 정보", ""])
        lines.extend(f"- {detail}" for detail in result.details)
    _append_summary("\n".join(lines) + "\n", env)
    return message


def write_failure(operation: str, message: str, env: Mapping[str, str] | None = None) -> None:
    safe_message = message.strip()[:1000]
    _append_summary(
        f"## {operation} 실패\n\n- 원인: {safe_message}\n",
        env,
    )


def _append_summary(content: str, env: Mapping[str, str] | None) -> None:
    values = os.environ if env is None else env
    summary_path = values.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(content)

