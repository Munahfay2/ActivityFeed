import os
os.environ.update(DATABASE_URL="sqlite:///./test.db", DEMO_MODE="true", JWT_SECRET="t")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
def hdr():
    c.post("/api/auth/register", json={"name": "Org", "email": "o@x.com", "password": "password123"})
    t = c.post("/api/auth/login", json={"email": "o@x.com", "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}
def test_bad_login(): assert c.post("/api/auth/login", json={"email": "no@x.com", "password": "password123"}).status_code == 401
def test_unauthorized(): assert c.post("/api/events", json={}).status_code == 401
def test_flow():
    h = hdr()
    e = c.post("/api/events", headers=h, json={"name": "TestConf", "venue": "V", "date": "d", "start_time": "9", "end_time": "5"}).json()
    assert c.post(f"/api/events/{e['id']}/attendees", json={"name": "Ann", "phone": "0712345678"}).status_code == 201
    assert c.post(f"/api/events/{e['id']}/attendees", json={"name": "Ann", "phone": "0712345678"}).status_code == 409
    c.post(f"/api/events/{e['id']}/announcements", headers=h, json={"title": "Moved", "content": "Room C now", "channels": ["FEED", "SMS", "USSD"]})
    assert c.post("/api/webhooks/ussd", data={"phoneNumber": "+254712345678", "text": "2"}).text.startswith("CON LATEST UPDATES")
    assert "Room C" in c.post("/api/webhooks/ussd", data={"phoneNumber": "+254712345678", "text": "2"}).text
    assert c.post("/api/webhooks/ussd", data={"phoneNumber": "+254799999999", "text": "9"}).text.startswith("CON Invalid")

def test_ussd_event_selection_then_existing_menu_flow():
    h = hdr()
    e1 = c.post("/api/events", headers=h, json={"name": "First Event", "venue": "V1", "date": "d", "start_time": "9", "end_time": "5"}).json()
    e2 = c.post("/api/events", headers=h, json={"name": "Second Event", "venue": "V2", "date": "d", "start_time": "9", "end_time": "5"}).json()
    first = c.post("/api/webhooks/ussd", data={"phoneNumber": "+254712345679", "text": "", "sessionId": "session-evt"}).text
    assert "Select an event" in first and "First Event" in first and "Second Event" in first
    menu = c.post("/api/webhooks/ussd", data={"phoneNumber": "+254712345679", "text": "2", "sessionId": "session-evt"}).text
    assert "Welcome to Activity Feed" in menu and "First Event" in menu
    assert c.post("/api/webhooks/ussd", data={"phoneNumber": "+254712345679", "text": "1", "sessionId": "session-evt"}).text.startswith("CON Enter your name:")
    assert e1["id"] != e2["id"]


def test_demo_password_is_synced_from_env_on_startup():
    import app.main as main
    os.environ["DEMO_ORGANIZER_PASSWORD"] = "demo12345"
    db = main.SessionLocal()
    demo = db.query(main.User).filter_by(email="demo@activityfeed.africa").first()
    if demo is None:
        demo = main.User(name="Demo Organizer", email="demo@activityfeed.africa", password_hash=main.hash_pw("stale-password"))
        db.add(demo)
    else:
        demo.password_hash = main.hash_pw("stale-password")
    db.commit(); db.close()

    main.startup()

    db = main.SessionLocal()
    refreshed = db.query(main.User).filter_by(email="demo@activityfeed.africa").first()
    db.close()

    assert refreshed is not None
    assert main.check_pw("demo12345", refreshed.password_hash) is True
    assert c.post("/api/auth/login", json={"email": "demo@activityfeed.africa", "password": "demo12345"}).status_code == 200
