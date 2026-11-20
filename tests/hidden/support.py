"""Shared fixtures for the hidden grading suite."""

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from app.main import create_app
from app.models import PermissionSet, User
from app.store import PermissionStore


class ManualClock:
    def __init__(self) -> None:
        self.value = 5_000.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class InstrumentedStore(PermissionStore):
    """Counts permission reads and can hold them until a gate opens."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.gate: asyncio.Event | None = None

    async def get_user(self, user_id: str) -> User | None:
        await asyncio.sleep(0)
        return await super().get_user(user_id)

    async def fetch_permissions(self, user_id: str, organization_id: str) -> PermissionSet:
        self.reads += 1
        if self.gate is not None:
            await self.gate.wait()
        return await super().fetch_permissions(user_id, organization_id)


@dataclass(frozen=True)
class Tenancy:
    org_a: str
    org_b: str
    multi: str
    peer_a: str
    member_b: str
    grants: dict[tuple[str, str], frozenset[str]]

    def expected(self, user: str, org: str) -> list[str]:
        return sorted(self.grants[(user, org)])


def make_tenancy(seed: int) -> Tenancy:
    rng = random.Random(seed)

    def ident(prefix: str) -> str:
        return f"{prefix}-{rng.getrandbits(40):010x}"

    org_a, org_b = ident("org"), ident("org")
    multi, peer_a, member_b = ident("usr"), ident("usr"), ident("usr")
    grants = {
        (multi, org_a): frozenset({"read", "billing", "export"}),
        (multi, org_b): frozenset({"read"}),
        (peer_a, org_a): frozenset({"read", "admin"}),
        (member_b, org_b): frozenset({"read", "write"}),
    }
    return Tenancy(org_a, org_b, multi, peer_a, member_b, grants)


@dataclass
class Env:
    clock: ManualClock
    store: InstrumentedStore
    tenancy: Tenancy
    ttl: float
    app: Any


def build(ttl: float = 30.0, seed: int = 7) -> Env:
    tenancy = make_tenancy(seed)
    store = InstrumentedStore()
    memberships: dict[str, set[str]] = {}
    for (user, org), permissions in tenancy.grants.items():
        memberships.setdefault(user, set()).add(org)
        store.set_permissions(user, org, permissions)
    for user, orgs in memberships.items():
        store.add_user(User(user, frozenset(orgs)))
    clock = ManualClock()
    app = create_app(clock=clock, store=store, ttl_seconds=ttl)
    return Env(clock, store, tenancy, ttl, app)


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_raw(self, user: str, org: str) -> httpx.Response:
        return await self._client.get(f"/api/orgs/{org}/permissions", headers={"X-User-Id": user})

    async def permissions(self, user: str, org: str) -> list[str]:
        response = await self.get_raw(user, org)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["organization_id"] == org
        return body["permissions"]

    async def allowed(self, user: str, org: str, permission: str) -> bool:
        response = await self._client.get(
            f"/api/orgs/{org}/permissions/{permission}", headers={"X-User-Id": user}
        )
        assert response.status_code == 200, response.text
        return response.json()["allowed"]

    async def put_raw(self, user: str, org: str, permissions: set[str]) -> httpx.Response:
        return await self._client.put(
            f"/api/orgs/{org}/permissions",
            headers={"X-User-Id": user},
            json={"permissions": sorted(permissions)},
        )

    async def replace(self, user: str, org: str, permissions: set[str]) -> list[str]:
        response = await self.put_raw(user, org, permissions)
        assert response.status_code == 200, response.text
        return response.json()["permissions"]

    async def audit(self, user: str, org: str) -> list[dict[str, str]]:
        response = await self._client.get(f"/api/orgs/{org}/audit/me", headers={"X-User-Id": user})
        assert response.status_code == 200, response.text
        return response.json()["events"]


@asynccontextmanager
async def api(env: Env) -> AsyncIterator[Api]:
    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://tenant.test") as client:
        yield Api(client)


def run(env: Env, scenario: Callable[[Api], Awaitable[None]]) -> None:
    async def main() -> None:
        async with api(env) as client:
            await scenario(client)

    asyncio.run(main())


async def release_when_loading(store: InstrumentedStore, expected_reads: int) -> None:
    """Open the store gate once requests are parked, using a bounded yield budget."""
    assert store.gate is not None
    for _ in range(20_000):
        if store.reads >= expected_reads:
            break
        await asyncio.sleep(0)
    for _ in range(500):
        await asyncio.sleep(0)
    store.gate.set()
