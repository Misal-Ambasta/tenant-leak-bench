# tenant-leak-bench

A self-contained coding task for training and evaluating coding agents. The
solver gets a small multi-tenant FastAPI permissions service (in-memory, no
external services) and an issue describing only the symptom. The goal is to
find and fix a cross-tenant cache leak without breaking caching, expiry,
invalidation, concurrency or auditing.

## Layout

| Path | Visible to solver | Purpose |
|---|---|---|
| `task.md` | yes | Issue-style prompt (symptom only) |
| `app/` | yes | The buggy service (10 modules) |
| `tests/visible/` | yes | Basic API tests, all pass on the base commit |
| `tests/hidden/` | no | Grading suite (17 tests, 7 behavior groups) |
| `verify.py` | no | Grades a submission's `app/` against a pristine hidden suite, prints JSON |
| `solution.patch` | no | Reference fix |
| `valid_fixes/` | no | Alternative correct fixes; proves the grader is implementation-agnostic |
| `wrong_fixes/` | no | Plausible but incorrect fixes; each must score below 1.0 |
| `validate.sh` | no | Proves the task is well-formed (see below) |
| `Dockerfile` | n/a | `solver` target (workspace only) and `grader` target (default) |

## The defect

`app.models.Principal` declares `organization_id` with `field(compare=False)`.
That is intentional: `AuditLog` keys events by principal, so a user's audit
history follows them across organizations. `AuthorizationService` also uses the
`Principal` as its `TtlCache` key, so `Principal(u, "org-a")` and
`Principal(u, "org-b")` hit the same cache entry and the same in-flight load.
Whichever organization the user loads first is served for every organization
until the TTL expires or an update invalidates it.

Finding it requires connecting four files: `dependencies.py` builds the
principal correctly from the path, `auth.py` passes it to the cache,
`cache.py` keys entries and in-flight loads by equality, and `models.py`
defines that equality.

**Reference fix** (`solution.patch`): key the permission cache on an explicit
`(organization_id, user_id)` tuple at every cache call site (read, check and
invalidate). `valid_fixes/01-tenant-scope-object.patch` reaches the same result
with a dedicated `TenantScope` value object.

### Distractors (suspicious-looking but correct)

1. **Generation guard in `TtlCache._load`.** A load that started before
   `invalidate()` is not written to the cache but is still returned to its
   caller. This looks like a stale-data bug. It is correct: the caller's
   request was in flight before the write, and refusing to cache it is what
   stops a pre-update value from surviving the invalidation.
2. **`require_membership` bypasses the cache** and runs on every request,
   separately from the cached permission lookup. That looks like the auth check
   and the data could drift apart, which resembles the reported leak. It is
   deliberate so that membership revocation takes effect immediately, and it
   is correct: membership is always checked against the requested
   organization.

`Principal`'s `compare=False` is also a trap: removing it makes the symptom go
away but breaks the audit history feature (`wrong_fixes/04`, caught by both a
visible and a hidden test).

## Rubric

`verify.py` prints `{"passed": bool, "score": 0-1, "details": [...]}`. A group
earns its weight only if all of its tests pass. `passed` is true only at 1.0.

| Group | Weight | What it checks |
|---|---|---|
| `cross_org_isolation` | 0.30 | Both read endpoints return the requested org's data, in either cache order |
| `user_isolation_and_authz` | 0.10 | Users in one org don't share entries; non-members get 403 with a warm cache |
| `ttl_expiry` | 0.15 | Cached until TTL, refreshed after; each org entry expires on its own schedule |
| `invalidation` | 0.15 | Updates are visible immediately on both endpoints and do not leak into other orgs |
| `concurrent_isolation` | 0.15 | Interleaved concurrent requests across users/orgs/endpoints stay isolated |
| `cache_effectiveness` | 0.10 | Repeat reads hit the cache; concurrent misses share one load per key |
| `audit_regression` | 0.05 | Audit history still follows a user across orgs |

The base commit scores **0.25**.

### Grader integrity

- Hidden tests are not in the solver image. `verify.py` copies only the
  submission's `app/` into a fresh temp directory next to a pristine copy of
  `tests/hidden/`. Submitted `conftest.py` files are dropped, and edits to any
  local tests are irrelevant.
- pytest runs with `python -I`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, no cache
  provider, a grader-written `pytest.ini`, and a scrubbed environment.
  Results come from JUnit XML, not from parsing stdout.
- A submission whose `app/` references `pytest`, `_pytest`, `conftest` or
  `junit` scores 0 (an `integrity` detail is added).
- Hidden tests generate their own users and orgs with a seeded RNG, so
  hardcoding the demo data (`alice`, `org-a`) does not help.
- All tests are deterministic: time comes from an injected manual clock, and
  concurrency uses an `asyncio.Event` gate with a bounded number of event-loop
  yields. Nothing sleeps on wall-clock time. `validate.sh` grades the solution
  three times and requires identical output.

## Why it is hard

- The symptom points at the routes and the auth check, which are correct. The
  org ID flows through the request intact all the way into `Principal`.
- The cache key *looks* complete: a `Principal` visibly contains the org ID.
  The bug only shows once you know how dataclass `field(compare=False)` affects
  `__eq__` and `__hash__`.
- The obvious one-line fix (drop `compare=False`) breaks another feature.
- There are three cache call sites (read, check, invalidate), plus a
  single-flight in-flight map keyed the same way. Partial fixes leave a leak
  on the check endpoint or after updates.
- The visible tests never use one user in two orgs, so they pass on the buggy
  code.

## Expected model failure modes

| Failure mode | Example | Typical score |
|---|---|---|
| Patch the reported user or demo data | `wrong_fixes/01-hardcode-seeded-users.patch` | 0.25 |
| Disable or bypass the cache | `wrong_fixes/02-disable-cache.patch` | 0.75 |
| Fix only the list endpoint (and its invalidation) | `wrong_fixes/03-fix-list-endpoint-only.patch` | 0.40 |
| Make `Principal` equality include the org | `wrong_fixes/04-principal-equality-includes-org.patch` | 0.95 |
| Store the "current org" on the shared service | `wrong_fixes/05-request-state-on-shared-service.patch` | 0.75 |
| Rewrite the cache and lose single-flight or TTL semantics | — | ≤ 0.85 |
| Edit or delete tests | — | no effect |

## How to run

Everything runs in Docker with no network access at test time.

```bash
# Build the grader image (default target) and prove the task is well-formed
docker build -t tenant-leak-bench .
docker run --rm --network none tenant-leak-bench

# Build the solver workspace image (no hidden tests, patches or README)
docker build --target solver -t tenant-leak-bench:solver .

# Grade a solver's finished workspace (only its app/ is used)
docker run --rm --network none -v /path/to/workspace:/submission:ro \
    tenant-leak-bench python verify.py --submission /submission
```

`validate.sh` checks:

1. The visible tests pass on the base commit, and the base fails hidden tests
   including `cross_org_isolation`.
2. Base plus `solution.patch` scores 1.0 three times with identical output,
   and its visible tests pass.
3. Every patch in `valid_fixes/` scores 1.0.
4. Every patch in `wrong_fixes/` scores below 1.0.
5. Tampering doesn't work: a root `conftest.py` that forces passes, with
   `tests/hidden` emptied, still scores as the base; pytest hooks placed
   inside `app/` score 0.

Locally without Docker (Python 3.11, `pip install -r requirements.txt`):
`PYTHON=python3.11 ./validate.sh`.

## Model run results

Fill this table with `run_eval.sh`. Give it one finished solver workspace per
attempt. It grades each workspace in the grader image with networking off and
prints a row; `--append` writes the row here.

```bash
./run_eval.sh --append claude-opus-5-5 runs/opus/attempt-*/
./run_eval.sh --local --notes "no tool use" some-model ws1 ws2   # grade without Docker
```

Without `--notes`, the Notes column lists the three groups that failed most often.

| Date | Model | Attempts | Mean score | Pass rate | Notes |
|---|---|---|---|---|---|
| | | | | | |
