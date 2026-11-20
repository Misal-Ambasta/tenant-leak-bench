"""HTTP routes for reading and changing organization permissions."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .audit import AuditLog
from .auth import AuthorizationService
from .dependencies import current_principal
from .models import PermissionSet, Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class PermissionUpdate(BaseModel):
    permissions: set[str]


def _serialize(permission_set: PermissionSet) -> dict[str, Any]:
    return {
        "organization_id": permission_set.organization_id,
        "permissions": sorted(permission_set.permissions),
    }


def build_router(authorizer: AuthorizationService, audit_log: AuditLog) -> APIRouter:
    """Create the API router bound to the given services."""
    router = APIRouter(prefix="/orgs/{organization_id}")

    @router.get("/permissions")
    async def list_permissions(principal: CurrentPrincipal) -> dict[str, Any]:
        return _serialize(await authorizer.permissions_for(principal))

    @router.get("/permissions/{permission}")
    async def check_permission(principal: CurrentPrincipal, permission: str) -> dict[str, Any]:
        return {
            "organization_id": principal.organization_id,
            "permission": permission,
            "allowed": await authorizer.has_permission(principal, permission),
        }

    @router.put("/permissions")
    async def replace_permissions(
        principal: CurrentPrincipal, body: PermissionUpdate
    ) -> dict[str, Any]:
        updated = await authorizer.update_permissions(principal, body.permissions)
        audit_log.record(principal, f"set permissions: {', '.join(sorted(body.permissions))}")
        return _serialize(updated)

    @router.get("/audit/me")
    async def my_audit_history(principal: CurrentPrincipal) -> dict[str, Any]:
        await authorizer.require_membership(principal)
        return {
            "user_id": principal.user_id,
            "events": [
                {"organization_id": event.organization_id, "action": event.action}
                for event in audit_log.history(principal)
            ],
        }

    return router
