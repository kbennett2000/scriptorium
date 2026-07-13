#!/usr/bin/env bash
# run-cycle.sh — run one dev cycle. The MODEL edits files; the SCRIPT does all
# git/PR/issue plumbing after, so the report-back can never be skipped.
#
#   ./run-cycle.sh        # lowest open instructions-only issue
#   ./run-cycle.sh 4      # a specific issue
# Run from inside the project repo.

set -euo pipefail

# --- refuse to run on a dirty tree (leftover state causes bad cycles) ------
if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty. Clean it first: git checkout . && git clean -fd"
  exit 1
fi

# --- pick the issue --------------------------------------------------------
N="${1:-}"
if [ -z "$N" ]; then
  N=$(gh issue list --state open --label instructions --json number,labels \
       --jq '[.[] | select(.labels|length==1)] | sort_by(.number) | .[0].number // empty')
fi
[ -z "$N" ] && { echo "No open instructions-only issues."; exit 0; }
echo "== Cycle on issue #$N"

# --- fresh branch off the default branch -----------------------------------
DEFAULT=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
BRANCH="cycle/issue-$N"
git fetch -q origin
git checkout -q "$DEFAULT"
git pull -q
git checkout -qB "$BRANCH" "origin/$DEFAULT"

# --- the model does the WORK only (no git, no gh, no issue edits) -----------
TASK=$(gh issue view "$N" --json title,body,comments \
  --jq '.title + "\n\n" + .body + "\n\n---\n\n" + ([.comments[].body] | join("\n\n---\n\n"))')
PROMPT="Do the work for this task by editing files only.

Do NOT commit, push, open a PR, or touch the GitHub issue — the harness handles all of that. Just make the file changes. If you are genuinely blocked and cannot proceed, explain the blocker clearly and make no changes.

Task:
$TASK"

# stream live in a terminal; just capture under cron (no tty)
if [ -t 1 ]; then SINK=(tee /dev/tty); else SINK=(cat); fi
OUTPUT=$(claude -p "$PROMPT" \
  --allowedTools "Read,Edit,Write,Bash" \
  --max-turns 40 \
  --permission-mode acceptEdits 2>&1 | "${SINK[@]}")

# --- plumbing, done deterministically by the script ------------------------
if [ -n "$(git status --porcelain)" ]; then
  echo "== Files changed -> commit, PR, report"
  git add -A
  git commit -qm "Cycle: issue #$N"
  git push -q -u origin "$BRANCH"
  PR_URL=$(gh pr create --head "$BRANCH" --base "$DEFAULT" \
            --title "Cycle: issue #$N" --body "Resolves work for issue #$N." )
  gh issue comment "$N" --body "PR: $PR_URL"
  gh issue edit "$N" --add-label cycle-summary --remove-label instructions
  echo "Done. PR: $PR_URL"
else
  echo "== No file changes -> needs-input"
  gh issue comment "$N" --body "Cycle made no changes. Model output:

$OUTPUT"
  gh issue edit "$N" --add-label needs-input --remove-label instructions
  git checkout -q "$DEFAULT"
  git branch -qD "$BRANCH" 2>/dev/null || true
  echo "Done. Marked needs-input."
fi
