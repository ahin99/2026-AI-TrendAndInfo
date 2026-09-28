#!/usr/bin/env bash
set -euo pipefail

operation="${1:-}"
session_dir="${2:-}"

if [[ "$operation" != "sync" && "$operation" != "quiz" ]]; then
  echo "operation must be sync or quiz" >&2
  exit 2
fi
if [[ ! "$session_dir" =~ ^session[0-9]{2,4}$ ]]; then
  echo "invalid session directory" >&2
  exit 2
fi

if [[ "$operation" == "sync" ]]; then
  git add -- "$session_dir"
  commit_message="Sync Notion $session_dir"
else
  git add -- "$session_dir/quiz.md" "$session_dir/quiz_answers.md"
  commit_message="Generate quiz for $session_dir"
fi

if git diff --cached --quiet; then
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "No $operation changes." >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "$commit_message"
if [[ "${SKIP_PUSH:-0}" != "1" ]]; then
  git push
fi

