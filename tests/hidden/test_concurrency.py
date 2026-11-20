import asyncio

from support import Api, build, release_when_loading, run


def test_concurrent_requests_across_orgs_stay_isolated() -> None:
    env = build()
    t = env.tenancy
    pairs = [(t.multi, t.org_a), (t.multi, t.org_b), (t.peer_a, t.org_a), (t.member_b, t.org_b)]

    async def scenario(api: Api) -> None:
        env.store.gate = asyncio.Event()
        lists = [asyncio.ensure_future(api.permissions(u, o)) for _ in range(4) for u, o in pairs]
        checks = [
            asyncio.ensure_future(api.allowed(u, o, "billing")) for _ in range(4) for u, o in pairs
        ]
        await release_when_loading(env.store, len(pairs))
        list_results = await asyncio.gather(*lists)
        check_results = await asyncio.gather(*checks)
        expected_pairs = pairs * 4
        assert list_results == [t.expected(u, o) for u, o in expected_pairs]
        assert check_results == ["billing" in t.grants[(u, o)] for u, o in expected_pairs]

    run(env, scenario)


def test_update_racing_with_reads_in_another_org() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        env.store.gate = asyncio.Event()
        reads_b = [asyncio.ensure_future(api.permissions(t.multi, t.org_b)) for _ in range(5)]
        update_a = asyncio.ensure_future(api.replace(t.multi, t.org_a, {"read", "owner"}))
        await release_when_loading(env.store, 2)
        assert await asyncio.gather(*reads_b) == [t.expected(t.multi, t.org_b)] * 5
        assert await update_a == ["owner", "read"]
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)

    run(env, scenario)


def test_repeated_reads_are_served_from_cache() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        for _ in range(10):
            assert await api.permissions(t.peer_a, t.org_a) == t.expected(t.peer_a, t.org_a)
            assert await api.allowed(t.member_b, t.org_b, "write") is True
        assert env.store.reads == 2

    run(env, scenario)


def test_concurrent_misses_share_one_load_per_key() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        env.store.gate = asyncio.Event()
        requests = [
            asyncio.ensure_future(api.permissions(user, org))
            for _ in range(10)
            for user, org in [(t.peer_a, t.org_a), (t.member_b, t.org_b)]
        ]
        await release_when_loading(env.store, 2)
        await asyncio.gather(*requests)
        assert env.store.reads == 2

    run(env, scenario)
