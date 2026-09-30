"""Activity Feed - P0 backend: auth, events, registration, feed, announcements,
schedule changes, Africa's Talking SMS + USSD, delivery tracking, dashboard."""
import os, hashlib, hmac, secrets, logging, datetime as dt
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Form, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

load_dotenv()
from sqlalchemy import (create_engine, Column, Integer, String, Boolean, DateTime,
                        ForeignKey, Text, func)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

log = logging.getLogger("activity_feed")
DEMO = os.getenv("DEMO_MODE", "true").lower() == "true"
AT_USER, AT_KEY = os.getenv("AT_USERNAME", ""), os.getenv("AT_API_KEY", "")
SENDER = os.getenv("AT_SMS_SENDER_ID") or None
SECRET = os.getenv("JWT_SECRET") or secrets.token_hex(32)  # random per process if unset
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
# Real calls only when DEMO_MODE=false AND credentials exist; otherwise simulated + labelled.
LIVE_AT = (not DEMO) and bool(AT_USER and AT_KEY)

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./activity_feed.db"),
                       connect_args={"check_same_thread": False} if "sqlite" in os.getenv("DATABASE_URL", "sqlite") else {})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
now = lambda: dt.datetime.now(dt.timezone.utc)

# ---------- models ----------
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True); name = Column(String); email = Column(String, unique=True)
    phone = Column(String); password_hash = Column(String); role = Column(String, default="ORGANIZER")
    created_at = Column(DateTime, default=now)
class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True); name = Column(String); description = Column(Text, default="")
    venue = Column(String); location = Column(String, default=""); date = Column(String); start_time = Column(String)
    end_time = Column(String); status = Column(String, default="LIVE"); created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=now)
class Attendee(Base):
    __tablename__ = "attendees"
    id = Column(Integer, primary_key=True); event_id = Column(Integer, ForeignKey("events.id"), index=True)
    name = Column(String); phone = Column(String, index=True); email = Column(String, default="")
    organization = Column(String, default=""); registration_source = Column(String)  # WEB | USSD
    checked_in = Column(Boolean, default=False); is_demo = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
class FeedItem(Base):
    __tablename__ = "feed_items"
    id = Column(Integer, primary_key=True); event_id = Column(Integer, ForeignKey("events.id"), index=True)
    type = Column(String); title = Column(String); content = Column(Text); priority = Column(String, default="NORMAL")
    channels = Column(String, default="FEED"); created_by = Column(Integer); created_at = Column(DateTime, default=now)
class ScheduleItem(Base):
    __tablename__ = "schedule_items"
    id = Column(Integer, primary_key=True); event_id = Column(Integer, ForeignKey("events.id"), index=True)
    title = Column(String); speaker = Column(String, default=""); venue = Column(String)
    start_time = Column(String); end_time = Column(String, default=""); description = Column(Text, default="")
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True); event_id = Column(Integer, index=True); feed_item_id = Column(Integer)
    type = Column(String, default="SMS"); channel = Column(String, default="SMS"); message = Column(Text)
    recipient = Column(String); status = Column(String, default="QUEUED")  # QUEUED|SENT|DELIVERED|FAILED
    simulated = Column(Boolean, default=False); provider_message_id = Column(String, index=True)
    created_at = Column(DateTime, default=now)
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True); user_id = Column(Integer); event_id = Column(Integer)
    action = Column(String); meta = Column(Text, default=""); created_at = Column(DateTime, default=now)

# ---------- security ----------
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"
def check_pw(pw, stored):
    salt, _ = stored.split("$"); return hmac.compare_digest(hash_pw(pw, salt), stored)
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
def current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    try:
        data = jwt.decode((authorization or "").removeprefix("Bearer "), SECRET, algorithms=["HS256"])
        u = db.get(User, int(data["sub"]))
    except Exception: u = None
    if not u: raise HTTPException(401, "Not authenticated")
    return u
def organizer(u: User = Depends(current_user)):
    if u.role not in ("ORGANIZER", "ADMIN"): raise HTTPException(403, "Organizer access required")
    return u
def clean(s, n=200): return "".join(c for c in (s or "") if c.isprintable() and c not in "*#<>").strip()[:n]
def norm_phone(p):
    p = "".join(c for c in (p or "") if c.isdigit() or c == "+")
    if p.startswith("0"): p = "+254" + p[1:]
    elif p and not p.startswith("+"): p = "+" + p
    return p if 10 <= len(p) <= 15 else ""
def audit(db, uid, eid, action, meta=""): db.add(AuditLog(user_id=uid, event_id=eid, action=action, meta=meta))

# ---------- Africa's Talking ----------
def _at_sms():
    import africastalking
    africastalking.initialize(AT_USER, AT_KEY); return africastalking.SMS
def send_sms(db: Session, event_id: int, message: str, phones: list[str], feed_item_id=None) -> dict:
    """Creates one Notification per recipient. Never raises: failures are recorded."""
    rows = [Notification(event_id=event_id, feed_item_id=feed_item_id, message=message, recipient=p,
                         simulated=not LIVE_AT) for p in phones]
    db.add_all(rows); db.flush()
    if not LIVE_AT:  # DEMO: clearly simulated, never claimed as delivered
        for r in rows: r.status, r.provider_message_id = "SENT", f"demo-{secrets.token_hex(6)}"
        return {"simulated": True, "queued": len(rows)}
    try:
        resp = _at_sms().send(message, phones, SENDER)
        by_num = {x["number"]: x for x in resp["SMSMessageData"]["Recipients"]}
        for r in rows:
            x = by_num.get(r.recipient)
            ok = x and x.get("statusCode") in (100, 101, 102)
            r.status, r.provider_message_id = ("SENT" if ok else "FAILED"), (x or {}).get("messageId")
        return {"simulated": False, "queued": len(rows)}
    except Exception as e:  # SMS failure must not break publishing
        log.exception("SMS send failed: %s", e)
        for r in rows: r.status = "FAILED"
        return {"simulated": False, "error": "SMS could not be sent. The update is still on the Activity Feed."}

# ---------- app ----------
app = FastAPI(title="Activity Feed API")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])

class Reg(BaseModel):
    name: str = Field(min_length=2, max_length=80); email: EmailStr; password: str = Field(min_length=8)
    phone: str = ""
class Login(BaseModel): email: EmailStr; password: str
@app.post("/api/auth/register", status_code=201)
def register(b: Reg, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=b.email).first(): raise HTTPException(409, "Email already registered")
    u = User(name=clean(b.name, 80), email=b.email, phone=norm_phone(b.phone), password_hash=hash_pw(b.password))
    db.add(u); db.commit(); return {"id": u.id}
@app.post("/api/auth/login")
def login(b: Login, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(email=b.email).first()
    if not u or not check_pw(b.password, u.password_hash): raise HTTPException(401, "Invalid credentials")
    tok = jwt.encode({"sub": str(u.id), "role": u.role, "exp": now() + dt.timedelta(hours=12)}, SECRET, "HS256")
    return {"access_token": tok, "role": u.role}

class EventIn(BaseModel):
    name: str = Field(min_length=3, max_length=120); description: str = ""; venue: str; location: str = ""
    date: str; start_time: str; end_time: str
def ser(o): return {c.name: getattr(o, c.name) for c in o.__table__.columns}
@app.post("/api/events", status_code=201)
def create_event(b: EventIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    e = Event(**{k: clean(v, 500) for k, v in b.model_dump().items()}, created_by=u.id)
    db.add(e); db.flush(); audit(db, u.id, e.id, "EVENT_CREATED"); db.commit()
    return {**ser(e), "registration_path": f"/api/events/{e.id}/attendees", "ussd_code": os.getenv("AT_USSD_SERVICE_CODE", "not configured")}
@app.get("/api/events")
def list_events(db: Session = Depends(get_db)): return [ser(e) for e in db.query(Event).order_by(Event.id.desc())]

class AttendeeIn(BaseModel):
    name: str = Field(min_length=2, max_length=80); phone: str; email: str = ""; organization: str = ""
def register_attendee(db, event, name, phone, source, email="", org=""):
    phone = norm_phone(phone)
    if not phone: raise HTTPException(422, "Invalid phone number")
    if db.query(Attendee).filter_by(event_id=event.id, phone=phone).first():
        raise HTTPException(409, "This phone number is already registered")
    a = Attendee(event_id=event.id, name=clean(name, 80), phone=phone, email=clean(email), organization=clean(org),
                 registration_source=source)
    db.add(a); db.flush()
    send_sms(db, event.id, f"Welcome to {event.name}.\nYou are registered.\n{event.date}, {event.start_time} at {event.venue}.\nPowered by Activity Feed.", [phone])
    return a
@app.post("/api/events/{eid}/attendees", status_code=201)
def web_register(eid: int, b: AttendeeIn, db: Session = Depends(get_db)):
    e = db.get(Event, eid) or (_ for _ in ()).throw(HTTPException(404, "Event not found"))
    a = register_attendee(db, e, b.name, b.phone, "WEB", b.email, b.organization); db.commit(); return ser(a)

class Announce(BaseModel):
    title: str = Field(min_length=2, max_length=120); content: str = Field(min_length=2, max_length=1000)
    type: str = "ANNOUNCEMENT"; priority: str = Field("NORMAL", pattern="^(NORMAL|IMPORTANT|URGENT)$")
    channels: list[str] = ["FEED"]  # FEED, SMS, USSD (VOICE: P2, not implemented)
def publish(db, event, u_id, title, content, type_, priority, channels, sms_text=None):
    ch = {c for c in channels if c in ("FEED", "SMS", "USSD")} | {"FEED"}
    item = FeedItem(event_id=event.id, type=type_, title=clean(title, 120), content=clean(content, 1000),
                    priority=priority, channels=",".join(sorted(ch)), created_by=u_id)
    db.add(item); db.flush(); result = None
    if "SMS" in ch:
        phones = [a.phone for a in db.query(Attendee).filter_by(event_id=event.id)]
        result = send_sms(db, event.id, sms_text or f"EVENT UPDATE:\n{item.content}\n\nActivity Feed.", phones, item.id)
    audit(db, u_id, event.id, "PUBLISHED", f"feed_item={item.id} channels={item.channels}")
    return item, result
@app.post("/api/events/{eid}/announcements", status_code=201)
def announce(eid: int, b: Announce, u: User = Depends(organizer), db: Session = Depends(get_db)):
    e = db.get(Event, eid) or (_ for _ in ()).throw(HTTPException(404, "Event not found"))
    item, sms = publish(db, e, u.id, b.title, b.content, b.type, b.priority, b.channels); db.commit()
    return {"item": ser(item), "sms": sms, "demo_mode": not LIVE_AT}
@app.get("/api/events/{eid}/feed")
def feed(eid: int, type: str | None = None, limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    q = db.query(FeedItem).filter_by(event_id=eid)
    if type: q = q.filter_by(type=type)
    return [ser(i) for i in q.order_by(FeedItem.id.desc()).limit(limit)]

class SessionIn(BaseModel): title: str; speaker: str = ""; venue: str; start_time: str; end_time: str = ""; description: str = ""
class SessionPatch(BaseModel): venue: str = Field(min_length=1); notify_sms: bool = False
@app.post("/api/events/{eid}/schedule", status_code=201)
def add_session(eid: int, b: SessionIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    s = ScheduleItem(event_id=eid, **{k: clean(v, 500) for k, v in b.model_dump().items()}); db.add(s); db.commit(); return ser(s)
@app.get("/api/events/{eid}/schedule")
def schedule(eid: int, db: Session = Depends(get_db)):
    return [ser(s) for s in db.query(ScheduleItem).filter_by(event_id=eid).order_by(ScheduleItem.start_time)]
@app.patch("/api/schedule/{sid}")
def change_venue(sid: int, b: SessionPatch, u: User = Depends(organizer), db: Session = Depends(get_db)):
    s = db.get(ScheduleItem, sid) or (_ for _ in ()).throw(HTTPException(404, "Session not found"))
    old, s.venue = s.venue, clean(b.venue, 80); e = db.get(Event, s.event_id)
    msg = f"{s.title} has moved from {old} to {s.venue}."
    item, sms = publish(db, e, u.id, s.title, msg, "VENUE_CHANGE", "IMPORTANT",
                        ["FEED", "USSD"] + (["SMS"] if b.notify_sms else []),
                        f"EVENT UPDATE:\nYour {s.title} session has moved from {old} to {s.venue}.\n\nActivity Feed.")
    audit(db, u.id, e.id, "VENUE_CHANGED", f"session={s.id} {old}->{s.venue}"); db.commit()
    return {"session": ser(s), "feed_item": ser(item), "sms": sms}

@app.get("/api/events/{eid}/notifications")
def notifications(eid: int, db: Session = Depends(get_db), u: User = Depends(organizer)):
    rows = db.query(Notification.feed_item_id, Notification.message, Notification.status, Notification.simulated,
                    func.count()).filter_by(event_id=eid).group_by(Notification.feed_item_id, Notification.message,
                    Notification.status, Notification.simulated).all()
    out = {}
    for fid, msg, st, sim, n in rows:
        d = out.setdefault((fid, msg), {"message": msg, "recipients": 0, "simulated": sim, "QUEUED": 0, "SENT": 0, "DELIVERED": 0, "FAILED": 0})
        d[st] += n; d["recipients"] += n
    return list(out.values())
@app.get("/api/events/{eid}/dashboard")
def dashboard(eid: int, db: Session = Depends(get_db), u: User = Depends(organizer)):
    A = db.query(Attendee).filter_by(event_id=eid); reg = A.count(); ci = A.filter_by(checked_in=True).count()
    st = dict(db.query(Notification.status, func.count()).filter_by(event_id=eid).group_by(Notification.status).all())
    return {"registered": reg, "checked_in": ci, "attendance_rate": round(100 * ci / reg, 1) if reg else 0,
            "by_source": dict(A.with_entities(Attendee.registration_source, func.count()).group_by(Attendee.registration_source).all()),
            "sms": {k: st.get(k, 0) for k in ("QUEUED", "SENT", "DELIVERED", "FAILED")},
            "announcements": db.query(FeedItem).filter_by(event_id=eid).count(),
            "demo_mode": not LIVE_AT, "note": "SMS counts marked simulated in demo mode; seeded attendees are flagged is_demo."}

# ---------- webhooks ----------
def _guard(token):
    if WEBHOOK_TOKEN and not hmac.compare_digest(token or "", WEBHOOK_TOKEN): raise HTTPException(403, "Bad token")
_MAP = {"success": "DELIVERED", "sent": "SENT", "buffered": "SENT", "submitted": "SENT", "queued": "QUEUED"}
@app.post("/api/webhooks/sms/delivery")
def sms_delivery(id: str = Form(""), status: str = Form(""), phoneNumber: str = Form(""), token: str = Query(""),
                 db: Session = Depends(get_db)):
    _guard(token)
    n = db.query(Notification).filter_by(provider_message_id=id).first() if id else None
    if not n: log.warning("delivery callback for unknown id %r", id); return {"ok": True, "matched": False}
    new = _MAP.get(status.lower(), "FAILED")
    if n.status != "DELIVERED": n.status = new  # idempotent: duplicates never downgrade
    db.commit(); return {"ok": True, "matched": True}

USSD_EVENT_SELECTION = {}

def _event_choice_menu(events):
    lines = ["CON Select an event"]
    for i, ev in enumerate(events[:10], 1):
        lines.append(f"{i}. {ev.name[:30]}")
    return "\n".join(lines)

def ussd_reply(db, event, phone, text, sessionId=""):
    events = db.query(Event).order_by(Event.id.desc()).all()
    if sessionId and sessionId in USSD_EVENT_SELECTION:
        selected = db.get(Event, USSD_EVENT_SELECTION[sessionId])
        if selected:
            event = selected
    elif sessionId and len(events) > 1:
        if not text:
            return _event_choice_menu(events)
        try:
            choice = int(text.strip())
        except ValueError:
            return _event_choice_menu(events)
        if 1 <= choice <= len(events):
            selected = events[choice - 1]
            USSD_EVENT_SELECTION[sessionId] = selected.id
            event = selected
            text = ""
        else:
            return _event_choice_menu(events)
    parts = text.split("*") if text else []
    for i in range(len(parts) - 1, -1, -1):  # "0" = back to main menu
        if parts[i] == "0": parts = parts[i + 1:]; break
    main = ("CON Welcome to Activity Feed\n" f"{event.name}\n1. Register\n2. Latest Updates\n3. Today's Schedule\n4. Live Poll\n5. Feedback\n6. Report Issue\n7. Help")
    if not parts: return main
    c = parts[0]
    if c == "1":
        if db.query(Attendee).filter_by(event_id=event.id, phone=phone).first(): return "END You are already registered."
        if len(parts) == 1: return "CON Enter your name:"
        name = clean(parts[1], 80)
        if len(name) < 2: return "END Invalid name. Please try again."
        if len(parts) == 2: return f"CON Confirm registration as {name}?\n1. Yes\n2. No"
        if parts[2] == "1":
            register_attendee(db, event, name, phone, "USSD"); return "END Registered! A confirmation SMS is on its way."
        return "END Registration cancelled."
    if c == "2":
        items = db.query(FeedItem).filter_by(event_id=event.id).filter(FeedItem.channels.contains("USSD")).order_by(FeedItem.id.desc()).limit(3).all()
        body = "\n".join(f"{i+1}. {x.content[:60]}" for i, x in enumerate(items)) or "No updates yet."
        return f"CON LATEST UPDATES\n{body}\n\n0. Back"
    if c == "3":
        rows = db.query(ScheduleItem).filter_by(event_id=event.id).order_by(ScheduleItem.start_time).all()
        body = "\n".join(f"{s.start_time} {s.title[:22]} ({s.venue})" for s in rows) or "No sessions yet."
        return f"CON SCHEDULE\n{body}\n\n0. Back"
    if c in ("4", "5", "6", "7"):
        from app.extras import ussd_more
        return ussd_more(db, event, phone, parts)
    return "CON Invalid option.\n\n" + main[4:]
@app.post("/api/webhooks/ussd")
def ussd(phoneNumber: str = Form(""), text: str = Form(""), sessionId: str = Form(""), token: str = Query(""),
         db: Session = Depends(get_db)):
    from fastapi.responses import PlainTextResponse
    _guard(token)
    try:
        e = db.query(Event).filter_by(status="LIVE").order_by(Event.id.desc()).first()
        phone = norm_phone(phoneNumber)
        if not e or not phone: return PlainTextResponse("END Service temporarily unavailable. Please use the web interface.")
        from app.extras import rate_ok
        if not rate_ok(phone): return PlainTextResponse("END Too many requests. Please wait a minute.")
        db.add(AuditLog(event_id=e.id, action="USSD_HIT"))
        r = ussd_reply(db, e, phone, text[:200], sessionId or ""); db.commit(); return PlainTextResponse(r)
    except Exception:
        log.exception("USSD error"); db.rollback()
        return PlainTextResponse("END Service temporarily unavailable. Please use the web interface.")

# ---------- startup / demo seed ----------
@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    if not DEMO: return
    db = SessionLocal()
    pw = os.getenv("DEMO_ORGANIZER_PASSWORD") or "demo12345"
    demo_user = db.query(User).filter_by(email="demo@activityfeed.africa").first()
    if not demo_user:
        demo_user = User(name="Demo Organizer", email="demo@activityfeed.africa", password_hash=hash_pw(pw))
        db.add(demo_user)
    else:
        demo_user.password_hash = hash_pw(pw)
        demo_user.name = demo_user.name or "Demo Organizer"
    db.flush()
    log.warning("Seeded demo. Login: demo@activityfeed.africa / %s", pw)
    if db.query(Event).count() == 0:
        e = Event(name="Women in Tech Summit 2026", venue="Nairobi Innovation Hub", location="Nairobi", date="2026-09-30",
                  start_time="09:00", end_time="17:00", created_by=demo_user.id); db.add(e); db.flush()
        for t, tm, v in [("Opening Ceremony", "09:00", "Main Hall"), ("AI & Future of Work", "10:00", "Room A"),
                         ("Building for Africa", "11:30", "Room B"), ("Women in Technology Panel", "14:00", "Main Hall"),
                         ("Closing & Networking", "16:00", "Main Hall")]:
            db.add(ScheduleItem(event_id=e.id, title=t, start_time=tm, venue=v))
        for i, n in enumerate(["Amina Demo", "Wanjiru Demo", "Zawadi Demo"]):
            db.add(Attendee(event_id=e.id, name=n, phone=f"+2547000000{i:02d}", organization="DEMO (seeded)",
                            registration_source="WEB", is_demo=True))
        db.commit(); log.warning("Seeded demo. Login: demo@activityfeed.africa / %s", pw)
    else:
        db.commit()
    db.close()


# extra routes (imported last to avoid circular import problems)
from app import extras  # noqa: E402
app.include_router(extras.router)

Base.metadata.create_all(engine)  # tables exist even if startup hooks do not run
