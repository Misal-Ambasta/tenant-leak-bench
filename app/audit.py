"""Audit trail of permission changes, grouped by acting user."""

from collections import defaultdict

from .clock import Clock
from .models import AuditEvent, Principal


class AuditLog:
    """Append-only record of the changes each actor has made."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._events: defaultdict[Principal, list[AuditEvent]] = defaultdict(list)

    def record(self, principal: Principal, action: str) -> None:
        event = AuditEvent(principal.organization_id, action, self._clock.now())
        self._events[principal].append(event)

    def history(self, principal: Principal) -> list[AuditEvent]:
        """Return every change made by this actor, across all organizations."""
        return list(self._events.get(principal, ()))
