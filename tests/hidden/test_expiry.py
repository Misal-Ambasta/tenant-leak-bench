from support import Api, build, run


def test_cached_value_is_served_until_the_ttl_elapses() -> None:
    env = build(ttl=10.0)
    t = env.tenancy

    async def scenario(api: Api) -> None:
        original = t.expected(t.peer_a, t.org_a)
        assert await api.permissions(t.peer_a, t.org_a) == original
        env.store.set_permissions(t.peer_a, t.org_a, {"read", "audit"})
        env.clock.advance(env.ttl - 0.01)
        assert await api.permissions(t.peer_a, t.org_a) == original
        env.clock.advance(0.02)
        assert await api.permissions(t.peer_a, t.org_a) == ["audit", "read"]

    run(env, scenario)


def test_each_org_entry_expires_on_its_own_schedule() -> None:
    env = build(ttl=10.0)
    t = env.tenancy

    async def scenario(api: Api) -> None:
        await api.permissions(t.multi, t.org_a)
        env.clock.advance(6)
        await api.permissions(t.multi, t.org_b)
        env.store.set_permissions(t.multi, t.org_a, {"read", "a-changed"})
        env.store.set_permissions(t.multi, t.org_b, {"read", "b-changed"})
        env.clock.advance(4.5)
        assert await api.permissions(t.multi, t.org_a) == ["a-changed", "read"]
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)
        env.clock.advance(6)
        assert await api.permissions(t.multi, t.org_b) == ["b-changed", "read"]

    run(env, scenario)


def test_update_is_visible_immediately_in_that_org() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        await api.permissions(t.multi, t.org_a)
        assert await api.replace(t.multi, t.org_a, {"read", "deploy"}) == ["deploy", "read"]
        assert await api.permissions(t.multi, t.org_a) == ["deploy", "read"]
        assert await api.allowed(t.multi, t.org_a, "deploy") is True

    run(env, scenario)


def test_check_endpoint_reflects_an_update() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.allowed(t.multi, t.org_a, "export") is True
        await api.replace(t.multi, t.org_a, {"read"})
        assert await api.allowed(t.multi, t.org_a, "export") is False

    run(env, scenario)


def test_update_in_one_org_does_not_leak_into_another() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)
        await api.replace(t.multi, t.org_a, {"read", "owner"})
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)
        assert await api.allowed(t.multi, t.org_b, "owner") is False
        assert await api.permissions(t.multi, t.org_a) == ["owner", "read"]

    run(env, scenario)
