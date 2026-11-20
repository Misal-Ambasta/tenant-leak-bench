"""Application factory and demo seed data."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .audit import AuditLog
from .auth import AuthorizationService, PermissionDenied
from .cache import TtlCache
from .clock import Clock, SystemClock
from .models import User
from .routes import build_router
from .store import PermissionStore


def create_app(
    *,
    clock: Clock | None = None,
    store: PermissionStore | None = None,
    ttl_seconds: float = 30.0,
) -> FastAPI:
    """Build the service; callers may inject a clock and store."""
    clock = clock if clock is not None else SystemClock()
    store = store if store is not None else PermissionStore()
    authorizer = AuthorizationService(store, TtlCache(clock, ttl_seconds))
    audit_log = AuditLog(clock)

    app = FastAPI(title="Tenant Permissions")
    app.state.store = store
    app.include_router(build_router(authorizer, audit_log), prefix="/api")

    @app.exception_handler(PermissionDenied)
    async def forbidden(_: Request, __: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "not a member"})

    return app


def create_seeded_app(*, clock: Clock | None = None, ttl_seconds: float = 30.0) -> FastAPI:
    """Build the service with a small demo data set."""
    store = PermissionStore()
    store.add_user(User("alice", frozenset({"org-a", "org-b"})))
    store.add_user(User("bob", frozenset({"org-a"})))
    store.set_permissions("alice", "org-a", {"read", "billing"})
    store.set_permissions("alice", "org-b", {"read"})
    store.set_permissions("bob", "org-a", {"read", "admin"})
    return create_app(clock=clock, store=store, ttl_seconds=ttl_seconds)


app = create_seeded_app()
