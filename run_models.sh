#!/bin/sh
# Run a model on the task N times in sandboxed workspaces, then grade and record results.
set -eu

usage() {
    cat >&2 <<'EOF'
usage: run_models.sh [-n ATTEMPTS] [-m MODEL] [-o RUNS_DIR] [-t TIMEOUT_SECONDS] [--no-append]
       run_models.sh -g RUNS_DIR [--no-append]

  -n  number of attempts (default 5)
  -m  model passed to `claude --model` (default: the CLI's default model)
  -o  where workspaces and transcripts are kept (default ~/.cache/tenant-leak-bench/runs/<timestamp>)
  -t  wall-clock limit per attempt (default 1800)
  -g  grade-only: re-audit and grade an existing RUNS_DIR without running the model
  --no-append  print the results row instead of writing it into README.md
EOF
    exit 2
}

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMAGE="${IMAGE:-tenant-leak-bench}"
ATTEMPTS=5 MODEL="" TIMEOUT=1800 APPEND="--append" GRADE_ONLY=0
RUNS="$HOME/.cache/tenant-leak-bench/runs/$(date +%Y%m%d-%H%M%S)"

while [ $# -gt 0 ]; do
    case "$1" in
        -n) ATTEMPTS=$2; shift ;;
        -m) MODEL=$2; shift ;;
        -o) RUNS=$2; shift ;;
        -t) TIMEOUT=$2; shift ;;
        -g) GRADE_ONLY=1; RUNS=$2; shift ;;
        --no-append) APPEND="" ;;
        *) usage ;;
    esac
    shift
done

die() { echo "preflight: $*" >&2; exit 1; }
SOLVER_FILES="app tests/visible task.md requirements.txt"
FORBIDDEN_IN_WORKSPACE="tests/hidden verify.py validate.sh solution.patch wrong_fixes valid_fixes README.md run_eval.sh run_models.sh .git"
# Claude Code keys ~/.claude/projects and /tmp/claude-<uid> folders by the cwd path, so
# each attempt's own memory/scratchpad paths are fine; only the repo's key is a leak.
REPO_KEY=$(printf '%s' "$ROOT" | sed 's#[^A-Za-z0-9]#-#g')
LEAK_PATTERN="$ROOT|$REPO_KEY|tests/hidden|solution\.patch|wrong_fixes|valid_fixes|verify\.py"

echo "== preflight: grader integrity"
git -C "$ROOT" diff --quiet HEAD -- tests/hidden verify.py || die "tests/hidden or verify.py differ from HEAD"
repo_hash=$(cd "$ROOT" && sha256sum verify.py tests/hidden/*.py | sha256sum | cut -c1-16)
image_hash=$(docker run --rm --network none "$IMAGE" sh -c 'sha256sum verify.py tests/hidden/*.py | sha256sum' | cut -c1-16) \
    || die "grader image '$IMAGE' not found; run: docker build -t $IMAGE ."
[ "$repo_hash" = "$image_hash" ] || die "grader image is stale (image $image_hash != repo $repo_hash); rebuild it"
echo "  grader image hidden tests + verify.py match HEAD ($repo_hash)"

if [ "$GRADE_ONLY" -eq 1 ]; then
    [ -d "$RUNS" ] || die "no such runs dir: $RUNS"
    ATTEMPTS=$(find "$RUNS" -maxdepth 1 -name 'attempt-*.jsonl' | wc -l)
    [ "$ATTEMPTS" -gt 0 ] || die "no attempt transcripts in $RUNS"
fi
mkdir -p "$RUNS"
RUNS=$(CDPATH= cd -- "$RUNS" && pwd)
case "$RUNS/" in "$ROOT"/*) die "runs dir must be outside the repo" ;; esac

PROMPT="You are working in a Python repository (the current directory). Resolve the issue described below.
Edit the code under app/ to fix it. You can run the existing tests with: python -m pytest -q tests/visible
When you are finished, reply with a short summary of the root cause and your fix.

$(cat "$ROOT/task.md")"

CLEAN=""
CONTAMINATED=0
for i in $(seq 1 "$ATTEMPTS"); do
    ws="$RUNS/attempt-$i"
    log="$RUNS/attempt-$i.jsonl"
    echo "== attempt $i/$ATTEMPTS -> $ws"
    if [ "$GRADE_ONLY" -eq 1 ]; then
        [ -f "$log" ] && [ -d "$ws/app" ] || die "missing $log or $ws/app"
    else
    mkdir -p "$ws"
    git -C "$ROOT" archive HEAD $SOLVER_FILES | tar -x -C "$ws"
    for item in $FORBIDDEN_IN_WORKSPACE; do
        [ ! -e "$ws/$item" ] || die "$ws contains $item"
    done
    echo "  workspace isolated: $(cd "$ws" && find . -type f | wc -l) files, no grader material"

    set -- "Read(/$ws/**)" "Glob(/$ws/**)" "Grep(/$ws/**)" "Edit(/$ws/**)" "Write(/$ws/**)" "TodoWrite"
    for py in python python3; do
        for flags in "" "-q " "-v " "-x "; do
            set -- "$@" "Bash($py -m pytest ${flags}tests/visible)"
        done
    done
    set +e
    (cd "$ws" && printf '%s' "$PROMPT" | timeout "$TIMEOUT" claude -p \
        ${MODEL:+--model "$MODEL"} \
        --output-format stream-json --verbose \
        --permission-mode dontAsk \
        --setting-sources project \
        --strict-mcp-config \
        --no-session-persistence \
        --disallowedTools WebFetch WebSearch Agent Task \
        --allowedTools "$@" \
        > "$log" 2> "$RUNS/attempt-$i.stderr")
    status=$?
    set -e
    echo "  claude exited with status $status"
    fi

    if grep -Eq "$LEAK_PATTERN" "$log"; then
        echo "  !! transcript references grader material; attempt excluded:" >&2
        grep -Eo "$LEAK_PATTERN" "$log" | sort | uniq -c >&2
        CONTAMINATED=$((CONTAMINATED + 1))
    else
        echo "  transcript audit clean"
        CLEAN="$CLEAN $ws"
    fi
done

[ -n "$CLEAN" ] || { echo "no clean attempts to grade" >&2; exit 1; }
resolved_model=$(python3 -c "
import json, sys
for line in open(sys.argv[1]):
    event = json.loads(line)
    if event.get('type') == 'system' and event.get('model'):
        print(event['model']); break
" "$RUNS/attempt-1.jsonl" 2>/dev/null || true)
model_label=${resolved_model:-${MODEL:-default}}

echo "== grading $(echo $CLEAN | wc -w) clean attempt(s) as '$model_label'"
# shellcheck disable=SC2086
"$ROOT/run_eval.sh" $APPEND $( [ "$CONTAMINATED" -eq 0 ] || echo --notes "$CONTAMINATED-excluded-for-contamination") "$model_label" $CLEAN
echo "workspaces and transcripts kept in $RUNS"
