#!/bin/sh
# Proves: base fails, reference and alternative fixes pass, every wrong fix fails.
set -eu

PYTHON="${PYTHON:-python3}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILURES=0

prepare() {
    target="$WORK/$1"
    mkdir -p "$target/tests"
    cp -R "$ROOT/app" "$target/app"
    cp -R "$ROOT/tests/visible" "$target/tests/visible"
    if [ -n "${2:-}" ]; then
        patch --forward --batch --no-backup-if-mismatch -s -d "$target" -p1 < "$2"
    fi
    echo "$target"
}

grade() {
    "$PYTHON" "$ROOT/verify.py" --submission "$1" 2>"$1.log" || true
}

visible_pass() {
    (cd "$1" && "$PYTHON" -m pytest -q -p no:cacheprovider tests/visible >"$1.visible.log" 2>&1)
}

check() {
    label=$1 json=$2 expectation=$3
    if printf '%s' "$json" | "$PYTHON" -c "
import json, sys
r = json.load(sys.stdin)
failed = {d['group'] for d in r['details'] if not d['passed']}
ok = {'pass': r['passed'] and r['score'] == 1.0,
      'base': not r['passed'] and 'cross_org_isolation' in failed,
      'fail': not r['passed'] and r['score'] < 1.0}['$expectation']
print(f\"{'$label':<48} score={r['score']:<5} failed_groups={sorted(failed) or '-'}\")
sys.exit(0 if ok else 1)
"; then :; else
        echo "  !! $label did not meet expectation '$expectation'" >&2
        FAILURES=$((FAILURES + 1))
    fi
}

echo "== base"
base=$(prepare base)
visible_pass "$base" || { echo "  !! visible tests fail on base" >&2; FAILURES=$((FAILURES + 1)); }
check "base (visible tests pass)" "$(grade "$base")" base

echo "== reference and alternative fixes"
solution=$(prepare solution "$ROOT/solution.patch")
visible_pass "$solution" || { echo "  !! visible tests fail on solution" >&2; FAILURES=$((FAILURES + 1)); }
first=$(grade "$solution")
check "solution.patch" "$first" pass
for run in 2 3; do
    [ "$(grade "$solution")" = "$first" ] || { echo "  !! nondeterministic result on run $run" >&2; FAILURES=$((FAILURES + 1)); }
done
echo "  solution graded identically 3/3 times"
for fix in "$ROOT"/valid_fixes/*.patch; do
    name=$(basename "$fix" .patch)
    check "valid_fixes/$name" "$(grade "$(prepare "valid-$name" "$fix")")" pass
done

echo "== wrong fixes"
for fix in "$ROOT"/wrong_fixes/*.patch; do
    name=$(basename "$fix" .patch)
    check "wrong_fixes/$name" "$(grade "$(prepare "wrong-$name" "$fix")")" fail
done

echo "== tamper resistance"
FORCE_PASS='import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    outcome.get_result().outcome = "passed"
'
outside=$(prepare tamper-outside)
printf '%s' "$FORCE_PASS" > "$outside/conftest.py"
mkdir -p "$outside/tests/hidden" && : > "$outside/tests/hidden/test_isolation.py"
check "base + root conftest + emptied tests/hidden" "$(grade "$outside")" base
inside=$(prepare tamper-inside "$ROOT/solution.patch")
printf '%s' "$FORCE_PASS" > "$inside/app/conftest.py"
printf 'import _pytest.reports\n' > "$inside/app/_hooks.py"
check "solution + pytest hooks inside app/" "$(grade "$inside")" fail

if [ "$FAILURES" -ne 0 ]; then
    echo "validation: $FAILURES check(s) FAILED" >&2
    exit 1
fi
echo "validation: all checks passed"
