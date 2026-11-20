"""Authorization: membership checks and cached permission lookups."""

from collections.abc import Awaitable, Callable, Iterable

from .cache import TtlCache
from .models import PermissionSet, Principal
from .store import PermissionStore


class PermissionDenied(Exception):
    """Raised when a principal is not a member of its requested organization."""


class AuthorizationService:
    """Resolves what a principal may do in the organization it is acting in."""

    def __init__(
        self, store: PermissionStore, cache: TtlCache[Principal, PermissionSet]
    ) -> None:
        self._store = store
        self._cache = cache

    async def require_membership(self, principal: Principal) -> None:
        """Reject principals that do not belong to their requested organization.

        Membership is read on every call, independently of the permission
        cache, so removing a member takes effect immediately.
        """
        user = await self._store.get_user(principal.user_id)
        if user is None or principal.organization_id not in user.organizations:
            raise PermissionDenied(principal.organization_id)

    async def permissions_for(self, principal: Principal) -> PermissionSet:
        await self.require_membership(principal)
        return await self._cache.get_or_load(principal, self._loader(principal))

    async def has_permission(self, principal: Principal, permission: str) -> bool:
        await self.require_membership(principal)
        granted = await self._cache.get_or_load(principal, self._loader(principal))
        return permission in granted.permissions

    async def update_permissions(
        self, principal: Principal, permissions: Iterable[str]
    ) -> PermissionSet:
        await self.require_membership(principal)
        self._store.set_permissions(principal.user_id, principal.organization_id, permissions)
        self._cache.invalidate(principal)
        return await self.permissions_for(principal)

    def _loader(self, principal: Principal) -> Callable[[], Awaitable[PermissionSet]]:
        async def load() -> PermissionSet:
            return await self._store.fetch_permissions(
                principal.user_id, principal.organization_id
            )

        return load
