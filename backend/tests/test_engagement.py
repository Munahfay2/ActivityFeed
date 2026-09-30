import os
os.environ.update(DATABASE_URL="sqlite:///./test.db", DEMO_MODE="true", JWT_SECRET="t")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
def setup():
    c.post("/api/auth/register", json={"name": "Org2", "email": "e2@x.com", "password": "password123"})
    t = c.post("/api/auth/login", json={"email": "e2@x.com", "password": "password123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {t}"}
    e = c.post("/api/events", headers=h, json={"name": "EngConf", "venue": "V", "date": "d", "start_time": "9", "end_time": "5"}).json()
    s = c.post(f"/api/events/{e['id']}/schedule", headers=h, json={"title": "AI", "venue": "Room A", "start_time": "10:00"}).json()
    for n, p in (("Ann", "0711000001"), ("Bea", "0711000002")):
        c.post(f"/api/events/{e['id']}/attendees", json={"name": n, "phone": p})
    return h, e["id"], s["id"]
def test_poll_and_duplicate_vote():
    h, eid, _ = setup()
    p = c.post(f"/api/events/{eid}/polls", headers=h, json={"question": "Best session?", "options": ["AI", "Cyber"]}).json()
    oid = p["options"][0]["id"]
    assert c.post(f"/api/polls/{p['id']}/vote", json={"option_id": oid, "phone": "0711000001"}).status_code == 201
    assert c.post(f"/api/polls/{p['id']}/vote", json={"option_id": oid, "phone": "0711000001"}).status_code == 409
    r = c.get(f"/api/events/{eid}/polls").json()[0]; assert r["responses"] == 1 and r["options"][0]["percent"] == 100
def test_ussd_vote_feedback_issue():
    h, eid, sid = setup()
    c.post(f"/api/events/{eid}/polls", headers=h, json={"question": "Which one?", "options": ["A", "B"]}).raise_for_status()
    u = lambda t: c.post("/api/webhooks/ussd", data={"phoneNumber": "+254711000002", "text": t}).text
    assert u("4").startswith("CON") and u("4*1").startswith("END Thanks") and "already" in u("4*1")
    assert u("5*1*5").startswith("END Thank you"); assert u("5*1*9").startswith("END Rating")
    assert u("6*2").startswith("END Issue reported"); assert u("4*9").startswith("END Invalid")
    fb = c.get(f"/api/events/{eid}/feedback/summary", headers=h).json()[0]; assert fb["average"] == 5
    assert c.get(f"/api/events/{eid}/issues", headers=h).json()[0]["category"] == "Security"
def test_reward_limits():
    h, eid, _ = setup(); aid = 1
    big = c.post(f"/api/events/{eid}/rewards", headers=h, json={"attendee_id": aid, "amount": 9999}); assert big.status_code in (404, 422)

def test_attendees_and_checkin():
    h, eid, _ = setup()
    rows = c.get(f"/api/events/{eid}/attendees", headers=h).json(); assert len(rows) == 2
    assert c.post(f"/api/events/{eid}/checkin", headers=h, json={"phone": "0711000001"}).json()["checked_in"] is True
    assert c.get(f"/api/events/{eid}/analytics", headers=h).json()["checked_in"] == 1
