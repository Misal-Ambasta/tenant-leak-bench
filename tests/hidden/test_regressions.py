from support import Api, build, run


def test_audit_history_follows_a_user_across_orgs() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        await api.replace(t.multi, t.org_a, {"read"})
        await api.replace(t.multi, t.org_b, {"read", "write"})
        await api.replace(t.peer_a, t.org_a, {"admin"})
        events = await api.audit(t.multi, t.org_b)
        assert [event["organization_id"] for event in events] == [t.org_a, t.org_b]

    run(env, scenario)


def test_non_member_cannot_update_permissions() -> None:
    env = build()
    t = env.tenancy

    async def scenario(api: Api) -> None:
        response = await api.put_raw(t.peer_a, t.org_b, {"admin"})
        assert response.status_code == 403
        assert (await api.get_raw(t.peer_a, t.org_a)).status_code == 200

    run(env, scenario)
