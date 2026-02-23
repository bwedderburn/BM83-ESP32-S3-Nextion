#!/bin/bash
set -euo pipefail

# Discover potentially recoverable commits and optionally create rescue branches.
# Usage:
#   ./scripts/recover_git_candidates.sh
#   ./scripts/recover_git_candidates.sh --create-branches
#   ./scripts/recover_git_candidates.sh --pattern 'whitespace|format|cleanup' --limit 200
#
# --pattern VALUE  Extended regex (ERE) pattern matched against reflog messages.
# --limit  VALUE   Max number of reflog lines to scan (must be a positive integer).
# --branch-prefix VALUE  Prefix for created rescue branches (default: rescue/auto).

PATTERN='whitespace|space|format|cleanup|mpy|circuitpython|refactor|fix'
LIMIT=120
CREATE_BRANCHES=0
BRANCH_PREFIX='rescue/auto'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pattern)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --pattern requires a non-empty value." >&2; exit 1
      fi
      PATTERN="${2}"
      shift 2
      ;;
    --limit)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --limit requires a non-empty value." >&2; exit 1
      fi
      if ! [[ "${2}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Error: --limit must be a positive integer, got '${2}'." >&2; exit 1
      fi
      LIMIT="${2}"
      shift 2
      ;;
    --create-branches)
      CREATE_BRANCHES=1
      shift
      ;;
    --branch-prefix)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --branch-prefix requires a non-empty value." >&2; exit 1
      fi
      BRANCH_PREFIX="${2}"
      shift 2
      ;;
    -h|--help)
      sed -n '1,12p' "$0"
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
FSCK_OUT="$(git fsck --lost-found 2>/dev/null | grep -E 'dangling commit|dangling tag|dangling blob' || true)"
echo "${FSCK_OUT}"
# Extract commit SHAs from dangling objects so they can be rescued even when
# reflog entries have expired or the branch has been deleted.
mapfile -t DANGLING_SHAS < <(echo "${FSCK_OUT}" | awk '/dangling commit/{print $3}' || true)

echo
echo '== Candidate SHAs from reflog messages =='
mapfile -t REFLOG_SHAS < <(
  git reflog --all \
  | head -n "$LIMIT" \
  | grep -Ei "$PATTERN" \
  | awk '{print $1}' \
  | sort -u
)

# Combine dangling commit SHAs with reflog-sourced SHAs, deduplicating.
mapfile -t SHAS < <(
  { printf '%s\n' "${DANGLING_SHAS[@]+"${DANGLING_SHAS[@]}"}"; \
    printf '%s\n' "${REFLOG_SHAS[@]+"${REFLOG_SHAS[@]}"}"; } \
  | sort -u | grep -v '^$' || true
)

if [[ ${#SHAS[@]} -eq 0 ]]; then
  echo 'No matching SHAs found in reflog or dangling objects.'
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
    # Skip SHAs that no longer resolve to an object (e.g. stale reflog entries).
    if ! git rev-parse --quiet --verify "${sha}^{object}" >/dev/null 2>&1; then
      echo "skip (invalid SHA): ${sha}"
      continue
    fi

    short_sha="$(git rev-parse --short "$sha" 2>/dev/null || true)"
    short_sha="${short_sha:-$sha}"
    branch_name="${BRANCH_PREFIX}-${short_sha}"
    if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
      echo "skip (exists): ${branch_name}"
      continue
    fi

    if git branch "$branch_name" "$sha"; then
      echo "created: ${branch_name} -> ${sha}"
    else
      echo "failed to create branch: ${branch_name} -> ${sha}" >&2
    fi
  done
fi

echo
echo 'Done.'
