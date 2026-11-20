"""In-memory persistence for users and permission grants."""

from collections.abc import Iterable

from .models import PermissionSet, User


class PermissionStore:
    """Stores users and their per-organization permission grants.

    Reads are asynchronous to match the interface of the database-backed
    store used in production.
    """

    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._grants: dict[tuple[str, str], frozenset[str]] = {}

    def add_user(self, user: User) -> None:
        self._users[user.user_id] = user

    def set_permissions(
        self, user_id: str, organization_id: str, permissions: Iterable[str]
    ) -> None:
        self._grants[(user_id, organization_id)] = frozenset(permissions)

    async def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def fetch_permissions(self, user_id: str, organization_id: str) -> PermissionSet:
        """Return the grant for ``user_id`` in ``organization_id``.

        A missing grant yields an empty set; membership is enforced by callers.
        """
        granted = self._grants.get((user_id, organization_id), frozenset())
        return PermissionSet(organization_id=organization_id, permissions=granted)
