"""Domain models shared by the permissions service."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class User:
    """A user and the organizations they are a member of."""

    user_id: str
    organizations: frozenset[str]


@dataclass(frozen=True)
class Principal:
    """An authenticated caller acting within one organization.

    Two principals are equal when they represent the same actor, which lets
    per-actor records such as the audit trail follow a user across the
    organizations they switch between.
    """

    user_id: str
    organization_id: str = field(compare=False)


@dataclass(frozen=True)
class PermissionSet:
    """Permissions granted to a user within a single organization."""

    organization_id: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class AuditEvent:
    """A single recorded change made by an actor."""

    organization_id: str
    action: str
    recorded_at: float
