# Users occasionally see another organization's permissions

**Reported by:** Customer Support
**Severity:** High (tenant data exposure)

A customer who is a member of two organizations reported that after opening
the permissions page for organization B, they were shown the permissions they
hold in organization A, including `billing`, which they do not have in
organization B. We have not been able to reproduce it reliably, and other
customers have not reported it.

Please find the root cause and fix it.

## Constraints

- Keep the HTTP API (`/api/orgs/{organization_id}/...`) unchanged.
- Other services build the app through `app.main.create_app(clock=..., store=..., ttl_seconds=...)`
  and implement the `app.store.PermissionStore` interface. Both must remain
  backward compatible.
- Behavior that is unrelated to this report must keep working.

You can run the existing tests with `python -m pytest -q tests/visible`.
