API = "/api/v1"


def test_profile_round_trip(client):
    me = client.get(f"{API}/me").json()
    assert me["email"] == "admin@aquarient.test" and me["role"] == "admin" and me["name"] == "Test Admin"
    r = client.patch(f"{API}/me", json={"name": "Chandra", "title": "RevOps"}).json()
    assert r["name"] == "Chandra" and r["title"] == "RevOps"
    assert client.patch(f"{API}/me", json={"name": "  "}).status_code == 422


def test_settings_round_trip(client):
    s = client.get(f"{API}/me/settings").json()
    assert s["defaultLandingPage"] == "dashboard" and s["notifications"]["criticalFindings"] is True
    s["dateFormat"] = "iso"
    s["notifications"]["weeklyDigest"] = True
    assert client.put(f"{API}/me/settings", json=s).json()["dateFormat"] == "iso"
    assert client.get(f"{API}/me/settings").json()["notifications"]["weeklyDigest"] is True
    assert client.put(f"{API}/me/settings", json={**s, "dateFormat": "nope"}).status_code == 422


def test_health_lists_executable_areas(client):
    assert client.get(f"{API}/health").json()["executableAreaIds"] == [f"area-{n}" for n in range(1, 22)]
    r = client.get(f"{API}/assessments", params={"status": "completed", "pageSize": 24, "sort": "-completedAt"}).json()
    assert r == {"items": [], "total": 0, "page": 1, "pageSize": 24}


def test_assistant_status_and_notifications(client):
    assert client.get(f"{API}/assistant/status").json() == {"mode": "guide", "model": None}
    assert client.get(f"{API}/me/notifications").json() == []
