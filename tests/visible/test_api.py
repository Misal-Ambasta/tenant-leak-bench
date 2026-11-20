from fastapi.testclient import TestClient

from app.main import create_seeded_app

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}


def test_member_can_list_permissions() -> None:
    client = TestClient(create_seeded_app())
    response = client.get("/api/orgs/org-a/permissions", headers=ALICE)
    assert response.status_code == 200
    assert response.json() == {"organization_id": "org-a", "permissions": ["billing", "read"]}


def test_check_single_permission() -> None:
    client = TestClient(create_seeded_app())
    response = client.get("/api/orgs/org-a/permissions/admin", headers=BOB)
    assert response.json() == {"organization_id": "org-a", "permission": "admin", "allowed": True}


def test_non_member_is_forbidden() -> None:
    client = TestClient(create_seeded_app())
    assert client.get("/api/orgs/org-b/permissions", headers=BOB).status_code == 403


def test_missing_user_header_is_unauthorized() -> None:
    client = TestClient(create_seeded_app())
    assert client.get("/api/orgs/org-a/permissions").status_code == 401


def test_update_is_returned_and_readable() -> None:
    client = TestClient(create_seeded_app())
    update = client.put("/api/orgs/org-a/permissions", headers=BOB, json={"permissions": ["read"]})
    assert update.json() == {"organization_id": "org-a", "permissions": ["read"]}
    assert client.get("/api/orgs/org-a/permissions", headers=BOB).json()["permissions"] == ["read"]


def test_audit_history_follows_user_across_organizations() -> None:
    client = TestClient(create_seeded_app())
    client.put("/api/orgs/org-a/permissions", headers=ALICE, json={"permissions": ["read"]})
    client.put("/api/orgs/org-b/permissions", headers=ALICE, json={"permissions": ["read", "write"]})
    history = client.get("/api/orgs/org-a/audit/me", headers=ALICE).json()
    assert [event["organization_id"] for event in history["events"]] == ["org-a", "org-b"]
