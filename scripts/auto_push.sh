#!/usr/bin/env bash
set -euo pipefail

# Non-interactive GitHub push helper
# - Uses existing gh auth if available
# - Otherwise attempts token-based login via GH_TOKEN
# - Pushes current branch (default: main) to origin

BRANCH=${1:-main}
REMOTE=${2:-origin}

if ! command -v gh >/dev/null 2>&1; then
  echo "[auto_push] gh (GitHub CLI) is not installed. Install from https://cli.github.com/" >&2
  exit 1
fi

# Ensure git repo
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "[auto_push] Not a git repository." >&2
  exit 1
fi

# Ensure remote exists
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  if [[ -n "${GIT_REMOTE_URL:-}" ]]; then
    echo "[auto_push] Adding remote $REMOTE -> $GIT_REMOTE_URL"
    git remote add "$REMOTE" "$GIT_REMOTE_URL"
  else
    echo "[auto_push] Remote '$REMOTE' not set. Set GIT_REMOTE_URL env var or add manually." >&2
    exit 1
  fi
fi

# Auth check
if ! gh auth status >/dev/null 2>&1; then
  if [[ -n "${GH_TOKEN:-}" ]]; then
    echo "[auto_push] Logging into GitHub via GH_TOKEN (non-interactive)"
    # shellcheck disable=SC2312
    echo -n "$GH_TOKEN" | gh auth login --hostname github.com --with-token >/dev/null
  else
    echo "[auto_push] gh is not authenticated and GH_TOKEN is not set."
    echo "           Set an access token in GH_TOKEN or run: gh auth login --web" >&2
    exit 1
  fi
fi

# Push
echo "[auto_push] Pushing to $REMOTE $BRANCH"
git push -u "$REMOTE" "$BRANCH"
