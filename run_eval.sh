#!/bin/sh
# Grade one model's attempts and print (or append) a README results row.
set -eu

usage() {
    cat >&2 <<'EOF'
usage: run_eval.sh [--local] [--append] [--notes TEXT] MODEL WORKSPACE [WORKSPACE...]

  MODEL       model name for the results table, e.g. claude-opus-5-5
  WORKSPACE   a solver's finished workspace (only its app/ is graded)
  --local     grade with the local python instead of the Docker grader image
  --append    add the row to the "Model run results" table in README.md
  --notes     text for the Notes column (default: most common failed groups)

Environment: IMAGE (default tenant-leak-bench), PYTHON (default python3).
EOF
    exit 2
}

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
IMAGE="${IMAGE:-tenant-leak-bench}"
PYTHON="${PYTHON:-python3}"
LOCAL=0 APPEND=0 NOTES=""

while [ $# -gt 0 ]; do
    case "$1" in
        --local) LOCAL=1 ;;
        --append) APPEND=1 ;;
        --notes) [ $# -ge 2 ] || usage; NOTES=$2; shift ;;
        -h|--help) usage ;;
        --*) echo "unknown option: $1" >&2; usage ;;
        *) break ;;
    esac
    shift
done
[ $# -ge 2 ] || usage
MODEL=$1
shift

RESULTS=$(mktemp)
trap 'rm -f "$RESULTS"' EXIT

for workspace in "$@"; do
    [ -d "$workspace/app" ] || { echo "no app/ in $workspace" >&2; exit 1; }
    absolute=$(CDPATH= cd -- "$workspace" && pwd)
    if [ "$LOCAL" -eq 1 ]; then
        json=$("$PYTHON" "$ROOT/verify.py" --submission "$absolute" 2>/dev/null || true)
    else
        json=$(docker run --rm --network none -v "$absolute":/submission:ro \
            "$IMAGE" python verify.py --submission /submission 2>/dev/null || true)
    fi
    [ -n "$json" ] || { echo "grader produced no output for $workspace" >&2; exit 1; }
    printf '%s\n' "$json" >> "$RESULTS"
    printf '%s\n' "$json" | "$PYTHON" -c "
import json, sys
r = json.load(sys.stdin)
failed = [d['group'] for d in r['details'] if not d['passed']]
print(f\"{sys.argv[1]:<50} score={r['score']:<5} passed={r['passed']}  failed={', '.join(failed) or '-'}\")
" "$workspace" >&2
done

ROW=$("$PYTHON" - "$RESULTS" "$MODEL" "$NOTES" <<'EOF'
import collections
import datetime
import json
import sys

results_path, model, notes = sys.argv[1:4]
results = [json.loads(line) for line in open(results_path) if line.strip()]
scores = [r["score"] for r in results]
passes = sum(r["passed"] for r in results)
if not notes:
    failures = collections.Counter(
        d["group"] for r in results for d in r["details"] if not d["passed"]
    )
    notes = "; ".join(f"{group} ×{count}" for group, count in failures.most_common(3)) or "all passed"
cells = [
    datetime.date.today().isoformat(),
    model,
    str(len(results)),
    f"{sum(scores) / len(scores):.3f}",
    f"{passes}/{len(results)} ({passes / len(results):.0%})",
    notes.replace("|", "\\|"),
]
print("| " + " | ".join(cells) + " |")
EOF
)

if [ "$APPEND" -eq 1 ]; then
    "$PYTHON" - "$ROOT/README.md" "$ROW" <<'EOF'
import sys

readme_path, row = sys.argv[1:3]
lines = open(readme_path).read().split("\n")
start = lines.index("## Model run results")
table = [i for i in range(start, len(lines)) if lines[i].startswith("|")]
placeholder = [i for i in table if lines[i].replace("|", "").strip() == ""]
if placeholder:
    lines[placeholder[0]] = row
else:
    lines.insert(table[-1] + 1, row)
open(readme_path, "w").write("\n".join(lines))
EOF
    echo "appended to README.md:" >&2
fi
echo "$ROW"
