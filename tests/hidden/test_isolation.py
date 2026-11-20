from support import Api, build, run


def test_list_returns_requested_org_after_other_org_is_cached() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.permissions(t.multi, t.org_a) == t.expected(t.multi, t.org_a)
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)
        assert await api.permissions(t.multi, t.org_a) == t.expected(t.multi, t.org_a)

    run(env, scenario)


def test_isolation_holds_when_the_smaller_org_is_cached_first() -> None:
    env = build(seed=11)
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)
        assert await api.permissions(t.multi, t.org_a) == t.expected(t.multi, t.org_a)

    run(env, scenario)


def test_check_endpoint_uses_the_requested_org() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.allowed(t.multi, t.org_a, "billing") is True
        assert await api.allowed(t.multi, t.org_b, "billing") is False
        assert await api.allowed(t.multi, t.org_a, "export") is True

    run(env, scenario)


def test_endpoints_do_not_leak_into_each_other_across_orgs() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.permissions(t.multi, t.org_a) == t.expected(t.multi, t.org_a)
        assert await api.allowed(t.multi, t.org_b, "export") is False
        assert await api.allowed(t.multi, t.org_b, "read") is True
        assert await api.permissions(t.multi, t.org_b) == t.expected(t.multi, t.org_b)

    run(env, scenario)


def test_users_in_the_same_org_have_independent_permissions() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        assert await api.permissions(t.multi, t.org_a) == t.expected(t.multi, t.org_a)
        assert await api.permissions(t.peer_a, t.org_a) == t.expected(t.peer_a, t.org_a)
        assert await api.allowed(t.peer_a, t.org_a, "billing") is False
        assert await api.allowed(t.multi, t.org_a, "admin") is False

    run(env, scenario)


def test_non_members_are_forbidden_even_with_a_warm_cache() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        await api.permissions(t.multi, t.org_a)
        await api.permissions(t.member_b, t.org_b)
        assert (await api.get_raw(t.member_b, t.org_a)).status_code == 403
        assert (await api.get_raw(t.peer_a, t.org_b)).status_code == 403

    run(env, scenario)
