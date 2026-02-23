#!/usr/bin/env bash
set -euo pipefail

# Discover potentially recoverable commits and optionally create rescue branches.
# Usage:
#   ./scripts/recover_git_candidates.sh
#   ./scripts/recover_git_candidates.sh --create-branches
#   ./scripts/recover_git_candidates.sh --pattern 'whitespace|format|cleanup' --limit 200

PATTERN='whitespace|space|format|cleanup|mpy|circuitpython|refactor|fix'
LIMIT=120
CREATE_BRANCHES=0
BRANCH_PREFIX='rescue/auto'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pattern)
      PATTERN="${2:-}"
      shift 2
      ;;
    --limit)
      LIMIT="${2:-}"
      shift 2
      ;;
    --create-branches)
      CREATE_BRANCHES=1
      shift
      ;;
    --branch-prefix)
      BRANCH_PREFIX="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '1,25p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo 'Error: run from inside a git repository.' >&2
  exit 1
fi

echo '== Repo + branch =='
git status --short --branch

echo
echo '== Recent reflog entries (filtered) =='
# Keep this line tolerant even when grep finds no matches.
git reflog --date=iso --all | head -n "$LIMIT" | grep -Ei "$PATTERN" || true

echo
echo '== Reflog tip sample =='
git reflog --date=iso --all | head -n 25

echo
echo '== Dangling objects =='
# no --no-reflogs here; we want all candidates available locally.
git fsck --lost-found 2>/dev/null | grep -E 'dangling commit|dangling tag|dangling blob' || true

echo
echo '== Candidate SHAs from reflog messages =='
mapfile -t SHAS < <(
  git reflog --all \
  | head -n "$LIMIT" \
  | grep -Ei "$PATTERN" \
  | awk '{print $1}' \
  | sort -u
)

if [[ ${#SHAS[@]} -eq 0 ]]; then
  echo 'No matching SHAs found in reflog with current pattern.'
  echo "Try: $0 --pattern 'your-term|branch-name|ticket' --limit 500"
  exit 0
fi

printf '%s\n' "${SHAS[@]}"

echo
echo '== Candidate commit summaries =='
for sha in "${SHAS[@]}"; do
  git show -s --format='%h %ad %d %s' --date=iso "$sha" || true
done

if [[ "$CREATE_BRANCHES" -eq 1 ]]; then
  echo
  echo '== Creating rescue branches =='
  for sha in "${SHAS[@]}"; do
    short_sha="$(git rev-parse --short "$sha")"
    branch_name="${BRANCH_PREFIX}-${short_sha}"
    if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
      echo "skip (exists): ${branch_name}"
      continue
    fi

    git branch "$branch_name" "$sha"
    echo "created: ${branch_name} -> ${sha}"
  done
fi

echo
echo 'Done.'
