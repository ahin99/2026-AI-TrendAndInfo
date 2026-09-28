"""Idempotent, conflict-aware session synchronization."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
from typing import Iterable

from .config import SyncConfig
from .errors import ConflictError, ValidationError
from .models import NotionPage, RunResult
from .notion import NotionClient


HASH_LINE_RE = re.compile(r'^sync_hash:\s*.*(?:\n|$)', re.MULTILINE)


def sync_session(config: SyncConfig, client: NotionClient) -> RunResult:
    pages = client.fetch_pages()
    if not pages:
        raise ValidationError(
            f"{config.session_dir.name}에 해당하는 게시된 노션 글이 없습니다."
        )
    changes = apply_pages(config.session_dir, pages)
    return RunResult(
        operation="notion-sync",
        session_dir=config.session_dir.name,
        changed=bool(changes),
        item_count=len(pages),
        details=tuple(changes),
    )


def apply_pages(session_dir: Path, pages: Iterable[NotionPage]) -> list[str]:
    page_list = list(pages)
    page_ids = [page.page_id for page in page_list]
    if len(page_ids) != len(set(page_ids)):
        raise ValidationError("노션 조회 결과에 중복된 page ID가 있습니다.")

    managed = scan_managed_files(session_dir)
    desired: list[tuple[Path | None, Path, str]] = []
    destinations: set[Path] = set()
    changes: list[str] = []
    for page in page_list:
        old_path = managed.get(page.page_id)
        filename = page_filename(page)
        new_path = session_dir / filename
        if new_path in destinations:
            raise ValidationError(f"여러 페이지가 같은 파일명 {filename!r}을 사용합니다.")
        destinations.add(new_path)
        rendered = render_managed_page(page)
        if old_path is not None:
            assert_unmodified(old_path)
        if new_path.exists() and new_path != old_path:
            raise ConflictError(f"대상 파일이 이미 존재합니다: {new_path.name}")
        desired.append((old_path, new_path, rendered))
        if old_path is None:
            changes.append(f"추가: {new_path.name}")
        elif old_path.name != new_path.name:
            changes.append(f"이름 변경: {old_path.name} -> {new_path.name}")
        elif old_path.read_text(encoding="utf-8") != rendered:
            changes.append(f"갱신: {new_path.name}")

    if not changes:
        return []
    apply_staged_files(session_dir, desired)
    return changes


def scan_managed_files(session_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not session_dir.exists():
        return result
    if not session_dir.is_dir():
        raise ValidationError(f"session 경로가 디렉터리가 아닙니다: {session_dir}")
    for path in sorted(session_dir.glob("*.md")):
        metadata = parse_front_matter(path.read_text(encoding="utf-8"))
        page_id = metadata.get("notion_page_id")
        if not page_id:
            continue
        if page_id in result:
            raise ValidationError(f"같은 notion_page_id를 가진 파일이 중복됩니다: {page_id}")
        result[page_id] = path
    return result


def assert_unmodified(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    metadata = parse_front_matter(content)
    stored_hash = metadata.get("sync_hash")
    if not stored_hash:
        raise ConflictError(f"관리 파일에 sync_hash가 없습니다: {path.name}")
    if not _constant_time_equal(stored_hash, content_hash(content)):
        raise ConflictError(f"사용자 수정 충돌: {path.name}")


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def page_filename(page: NotionPage) -> str:
    normalized = unicodedata.normalize("NFKC", page.title).strip().lower()
    normalized = re.sub(r"[\\/]+", "-", normalized)
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-_.]{2,}", "-", normalized).strip("-._")
    slug = normalized[:80].rstrip("-._") or "untitled"
    short_id = re.sub(r"[^0-9a-zA-Z]", "", page.page_id)[:8].lower()
    if not short_id:
        short_id = hashlib.sha256(page.page_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}--{short_id}.md"


def render_managed_page(page: NotionPage) -> str:
    without_hash = (
        "---\n"
        f"notion_page_id: {json.dumps(page.page_id, ensure_ascii=False)}\n"
        f"notion_url: {json.dumps(page.url, ensure_ascii=False)}\n"
        f"notion_last_edited_time: {json.dumps(page.last_edited_time, ensure_ascii=False)}\n"
        f"title: {json.dumps(page.title, ensure_ascii=False)}\n"
        "---\n\n"
        f"# {page.title}\n\n"
        f"{page.markdown.strip()}\n"
    )
    digest = hashlib.sha256(without_hash.encode("utf-8")).hexdigest()
    return without_hash.replace(
        f"title: {json.dumps(page.title, ensure_ascii=False)}\n",
        f"title: {json.dumps(page.title, ensure_ascii=False)}\n"
        f"sync_hash: {json.dumps(digest)}\n",
        1,
    )


def content_hash(content: str) -> str:
    without_hash, count = HASH_LINE_RE.subn("", content, count=1)
    if count != 1:
        return ""
    return hashlib.sha256(without_hash.encode("utf-8")).hexdigest()


def parse_front_matter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in content[4:end].splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        raw = raw.strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        if isinstance(value, str):
            result[key] = value
    return result


def apply_staged_files(
    session_dir: Path, desired: list[tuple[Path | None, Path, str]]
) -> None:
    root = session_dir.parent
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{session_dir.name}.stage-", dir=root))
    backup: Path | None = None
    try:
        if session_dir.exists():
            shutil.copytree(session_dir, stage, dirs_exist_ok=True)
        for old_path, new_path, content in desired:
            staged_new = stage / new_path.name
            if old_path is not None and old_path.name != new_path.name:
                staged_old = stage / old_path.name
                if staged_old.exists():
                    staged_old.unlink()
            with staged_new.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)

        if session_dir.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=f".{session_dir.name}.backup-", dir=root)
            )
            backup.rmdir()
            os.replace(session_dir, backup)
        try:
            os.replace(stage, session_dir)
        except BaseException:
            if backup is not None and backup.exists() and not session_dir.exists():
                os.replace(backup, session_dir)
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if backup is not None and backup.exists():
            if not session_dir.exists():
                os.replace(backup, session_dir)
            else:
                shutil.rmtree(backup, ignore_errors=True)
