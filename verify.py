"""Grade a submission's ``app/`` against the pristine hidden test suite.

Prints ``{"passed": bool, "score": float, "details": [...]}`` to stdout.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

GRADER_ROOT = Path(__file__).resolve().parent
HIDDEN_TESTS = GRADER_ROOT / "tests" / "hidden"
TIMEOUT_SECONDS = 300
TAMPERING_PATTERN = re.compile(r"\b_?pytest\b|\bconftest\b|\bjunit", re.IGNORECASE)

GROUPS: dict[str, tuple[float, list[str]]] = {
    "cross_org_isolation": (
        0.30,
        [
            "test_list_returns_requested_org_after_other_org_is_cached",
            "test_isolation_holds_when_the_smaller_org_is_cached_first",
            "test_check_endpoint_uses_the_requested_org",
            "test_endpoints_do_not_leak_into_each_other_across_orgs",
        ],
    ),
    "user_isolation_and_authz": (
        0.10,
        [
            "test_users_in_the_same_org_have_independent_permissions",
            "test_non_members_are_forbidden_even_with_a_warm_cache",
            "test_non_member_cannot_update_permissions",
        ],
    ),
    "ttl_expiry": (
        0.15,
        [
            "test_cached_value_is_served_until_the_ttl_elapses",
            "test_each_org_entry_expires_on_its_own_schedule",
        ],
    ),
    "invalidation": (
        0.15,
        [
            "test_update_is_visible_immediately_in_that_org",
            "test_check_endpoint_reflects_an_update",
            "test_update_in_one_org_does_not_leak_into_another",
        ],
    ),
    "concurrent_isolation": (
        0.15,
        [
            "test_concurrent_requests_across_orgs_stay_isolated",
            "test_update_racing_with_reads_in_another_org",
        ],
    ),
    "cache_effectiveness": (
        0.10,
        [
            "test_repeated_reads_are_served_from_cache",
            "test_concurrent_misses_share_one_load_per_key",
        ],
    ),
    "audit_regression": (0.05, ["test_audit_history_follows_a_user_across_orgs"]),
}

PYTEST_INI = """[pytest]
pythonpath = .
testpaths = tests/hidden
addopts = -p no:cacheprovider
"""


def find_tampering(app_dir: Path) -> list[str]:
    """Return files in the submission that reference the test harness."""
    flagged = []
    for path in sorted(app_dir.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".pth", ".cfg", ".ini", ".toml"}:
            if TAMPERING_PATTERN.search(path.read_text(errors="replace")):
                flagged.append(str(path.relative_to(app_dir.parent)))
    return flagged


def run_hidden_suite(app_dir: Path) -> dict[str, bool]:
    """Run the pristine suite against a copy of ``app_dir``; map test name to pass."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "conftest.py")
    with tempfile.TemporaryDirectory(prefix="grade-") as tmp:
        workdir = Path(tmp)
        shutil.copytree(app_dir, workdir / "app", ignore=ignore)
        shutil.copytree(HIDDEN_TESTS, workdir / "tests" / "hidden", ignore=ignore)
        (workdir / "pytest.ini").write_text(PYTEST_INI)
        report = workdir / "report.xml"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": tmp,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        command = [
            sys.executable, "-I", "-m", "pytest",
            "-c", str(workdir / "pytest.ini"), "--rootdir", tmp,
            "-q", f"--junitxml={report}",
        ]
        try:
            completed = subprocess.run(
                command, cwd=tmp, env=env, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS,
            )
            sys.stderr.write(completed.stdout[-4000:] + completed.stderr[-2000:])
        except subprocess.TimeoutExpired:
            sys.stderr.write("hidden suite timed out\n")
            return {}
        if not report.exists():
            return {}
        return parse_junit(report)


def parse_junit(report: Path) -> dict[str, bool]:
    outcomes: dict[str, bool] = {}
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        failed = any(child.tag in {"failure", "error", "skipped"} for child in case)
        name = case.get("name", "")
        outcomes[name] = outcomes.get(name, True) and not failed
    return outcomes


def grade(outcomes: dict[str, bool], tampering: list[str]) -> dict[str, Any]:
    details = []
    score = 0.0
    for group, (weight, tests) in GROUPS.items():
        results = {test: (not tampering) and outcomes.get(test, False) for test in tests}
        group_passed = all(results.values())
        score += weight if group_passed else 0.0
        details.append({"group": group, "weight": weight, "passed": group_passed, "tests": results})
    if tampering:
        details.append({"group": "integrity", "passed": False, "flagged_files": tampering})
    score = round(score, 4)
    return {"passed": score == 1.0, "score": score, "details": details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--submission", type=Path, default=Path.cwd(),
        help="directory containing the submitted app/ package (default: cwd)",
    )
    args = parser.parse_args()
    app_dir = args.submission.resolve() / "app"
    if not app_dir.is_dir():
        result = grade({}, [f"missing {app_dir}"])
    else:
        tampering = find_tampering(app_dir)
        result = grade({} if tampering else run_hidden_suite(app_dir), tampering)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
