import os
import xml.etree.ElementTree as ET
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
    h, eid, _ = setup()
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

def test_voice_uses_ussd_event_menu_and_registration_flow():
    from app import extras, main
    h, eid, _ = setup()
    session_id = "voice-menu-flow"
    session_key = f"voice:{session_id}"
    extras.VOICE_SESSIONS.pop(session_id, None)
    main.USSD_EVENT_SELECTION.pop(session_key, None)
    phone = "+254711009999"
    c.post(f"/api/events/{eid}/polls", headers=h,
           json={"question": "Which session?", "options": ["AI", "Security"]})
    attendees = c.get(f"/api/events/{eid}/attendees", headers=h).json()
    alert = c.post(f"/api/events/{eid}/voice", headers=h,
                   json={"message": "Emergency exit at north door", "attendee_ids": [attendees[0]["id"]]})
    assert alert.status_code == 201

    def call(digits=""):
        data = {"isActive": "1", "sessionId": session_id, "callerNumber": phone}
        if digits:
            data["dtmfDigits"] = digits
        return c.post("/api/webhooks/voice", data=data)

    event_prompt = call()
    assert event_prompt.status_code == 200
    event_prompt_text = "".join(ET.fromstring(event_prompt.content).itertext())
    assert "Emergency exit at north door" in event_prompt_text and "Select an event" in event_prompt_text

    menu = call("1")
    menu_prompt = "".join(ET.fromstring(menu.content).itertext())
    assert "Welcome to Activity Feed" in menu_prompt
    assert "1. Register" in menu_prompt and "7. Help" in menu_prompt

    updates = call("2")
    assert "LATEST UPDATES" in "".join(ET.fromstring(updates.content).itertext())
    back = call("0")
    assert "Welcome to Activity Feed" in "".join(ET.fromstring(back.content).itertext())

    assert "SCHEDULE" in "".join(ET.fromstring(call("3").content).itertext())
    assert "Welcome to Activity Feed" in "".join(ET.fromstring(call("0").content).itertext())
    assert "HELP" in "".join(ET.fromstring(call("7").content).itertext())
    assert "Welcome to Activity Feed" in "".join(ET.fromstring(call("0").content).itertext())

    confirm = call("1")
    assert "press 1" in "".join(ET.fromstring(confirm.content).itertext())
    registered = call("1")
    assert "phone number is registered" in "".join(ET.fromstring(registered.content).itertext())

    db = main.SessionLocal()
    attendee = db.query(main.Attendee).filter_by(event_id=eid, phone=phone).first()
    db.close()
    assert attendee is not None and attendee.registration_source == "VOICE"

    session_id = "voice-poll-flow"
    call(); call("1")
    assert "Which session?" in "".join(ET.fromstring(call("4").content).itertext())
    assert "vote is counted" in "".join(ET.fromstring(call("1").content).itertext())
    assert c.get(f"/api/events/{eid}/polls").json()[0]["responses"] == 1

    session_id = "voice-feedback-flow"
    call(); call("1"); call("5")
    assert "Rate AI" in "".join(ET.fromstring(call("1").content).itertext())
    assert "Thank you for your feedback" in "".join(ET.fromstring(call("5").content).itertext())

    session_id = "voice-issue-flow"
    call(); call("1")
    assert "REPORT AN ISSUE" in "".join(ET.fromstring(call("6").content).itertext())
    assert "Issue reported" in "".join(ET.fromstring(call("2").content).itertext())
