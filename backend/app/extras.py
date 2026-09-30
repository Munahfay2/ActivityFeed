"""Polls, feedback, issues, check-in, Airtime rewards, Voice, analytics, extra USSD flows."""
import os, time, logging, collections
import xml.etree.ElementTree as ET
from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Session
from app.main import (Base, now, get_db, organizer, User, Event, Attendee, FeedItem, ScheduleItem, Notification,
                      AuditLog, clean, norm_phone, ser, audit, LIVE_AT, AT_USER, AT_KEY)

log = logging.getLogger("activity_feed")
router = APIRouter()
_pk = lambda: Column(Integer, primary_key=True)

class Poll(Base):
    __tablename__ = "polls"; id = _pk(); event_id = Column(Integer, ForeignKey("events.id"), index=True)
    question = Column(String); status = Column(String, default="OPEN"); created_at = Column(DateTime, default=now)
class PollOption(Base):
    __tablename__ = "poll_options"; id = _pk(); poll_id = Column(Integer, ForeignKey("polls.id"), index=True); text = Column(String)
class PollResponse(Base):
    __tablename__ = "poll_responses"; __table_args__ = (UniqueConstraint("poll_id", "attendee_id"),)
    id = _pk(); poll_id = Column(Integer, ForeignKey("polls.id")); option_id = Column(Integer)
    attendee_id = Column(Integer); source = Column(String); created_at = Column(DateTime, default=now)
class Feedback(Base):
    __tablename__ = "feedback"; __table_args__ = (UniqueConstraint("session_id", "attendee_id"),)
    id = _pk(); event_id = Column(Integer, index=True); session_id = Column(Integer); attendee_id = Column(Integer)
    rating = Column(Integer); comment = Column(Text, default=""); source = Column(String); created_at = Column(DateTime, default=now)
class Issue(Base):
    __tablename__ = "issues"; id = _pk(); event_id = Column(Integer, index=True); attendee_id = Column(Integer)
    category = Column(String); description = Column(Text, default=""); status = Column(String, default="OPEN")
    created_at = Column(DateTime, default=now); resolved_at = Column(DateTime)
class Reward(Base):
    __tablename__ = "rewards"; id = _pk(); event_id = Column(Integer, index=True); attendee_id = Column(Integer)
    amount = Column(Integer); status = Column(String); simulated = Column(Boolean, default=False); created_at = Column(DateTime, default=now)

# ---------- helpers ----------
def get_event(db, eid): return db.get(Event, eid) or (_ for _ in ()).throw(HTTPException(404, "Event not found"))
def att_by_phone(db, eid, phone):
    a = db.query(Attendee).filter_by(event_id=eid, phone=norm_phone(phone)).first()
    if not a: raise HTTPException(404, "Phone number is not registered for this event")
    return a
def cast_vote(db, poll, option_id, att, source):
    if poll.status != "OPEN": raise HTTPException(409, "Poll is closed")
    if not db.query(PollOption).filter_by(id=option_id, poll_id=poll.id).first(): raise HTTPException(422, "Invalid option")
    if db.query(PollResponse).filter_by(poll_id=poll.id, attendee_id=att.id).first(): raise HTTPException(409, "You have already voted")
    db.add(PollResponse(poll_id=poll.id, option_id=option_id, attendee_id=att.id, source=source))
def poll_results(db, p):
    counts = dict(db.query(PollResponse.option_id, func.count()).filter_by(poll_id=p.id).group_by(PollResponse.option_id).all())
    total = sum(counts.values())
    return {"id": p.id, "question": p.question, "status": p.status, "responses": total,
            "options": [{"id": o.id, "text": o.text, "votes": counts.get(o.id, 0),
                         "percent": round(100 * counts.get(o.id, 0) / total, 1) if total else 0}
                        for o in db.query(PollOption).filter_by(poll_id=p.id).order_by(PollOption.id)]}
def save_feedback(db, eid, sid, att, rating, comment, source):
    if not 1 <= rating <= 5: raise HTTPException(422, "Rating must be 1-5")
    if not db.query(ScheduleItem).filter_by(id=sid, event_id=eid).first(): raise HTTPException(404, "Session not found")
    if db.query(Feedback).filter_by(session_id=sid, attendee_id=att.id).first(): raise HTTPException(409, "Feedback already submitted")
    db.add(Feedback(event_id=eid, session_id=sid, attendee_id=att.id, rating=rating, comment=clean(comment, 500), source=source))

_hits = collections.defaultdict(list)
def rate_ok(phone, limit=30, window=60):
    t = time.time(); h = [x for x in _hits[phone] if t - x < window]; ok = len(h) < limit
    if ok: h.append(t)
    _hits[phone] = h; return ok

# ---------- polls ----------
class PollIn(BaseModel): question: str = Field(min_length=3, max_length=200); options: list[str] = Field(min_length=2, max_length=6)
class VoteIn(BaseModel): option_id: int; phone: str
@router.post("/api/events/{eid}/polls", status_code=201)
def create_poll(eid: int, b: PollIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    from app.main import publish
    e = get_event(db, eid); p = Poll(event_id=eid, question=clean(b.question)); db.add(p); db.flush()
    db.add_all([PollOption(poll_id=p.id, text=clean(o, 60)) for o in b.options])
    publish(db, e, u.id, "Live poll", p.question, "POLL", "NORMAL", ["FEED", "USSD"]); db.commit()
    return poll_results(db, p)
@router.get("/api/events/{eid}/polls")
def list_polls(eid: int, db: Session = Depends(get_db)):
    return [poll_results(db, p) for p in db.query(Poll).filter_by(event_id=eid).order_by(Poll.id.desc())]
@router.post("/api/polls/{pid}/vote", status_code=201)
def vote(pid: int, b: VoteIn, db: Session = Depends(get_db)):
    p = db.get(Poll, pid) or (_ for _ in ()).throw(HTTPException(404, "Poll not found"))
    cast_vote(db, p, b.option_id, att_by_phone(db, p.event_id, b.phone), "WEB"); db.commit(); return poll_results(db, p)
@router.post("/api/polls/{pid}/close")
def close_poll(pid: int, u: User = Depends(organizer), db: Session = Depends(get_db)):
    p = db.get(Poll, pid) or (_ for _ in ()).throw(HTTPException(404, "Poll not found")); p.status = "CLOSED"; db.commit(); return poll_results(db, p)

# ---------- feedback, issues, check-in ----------
class FeedbackIn(BaseModel): session_id: int; phone: str; rating: int; comment: str = ""
@router.post("/api/events/{eid}/feedback", status_code=201)
def post_feedback(eid: int, b: FeedbackIn, db: Session = Depends(get_db)):
    save_feedback(db, eid, b.session_id, att_by_phone(db, eid, b.phone), b.rating, b.comment, "WEB"); db.commit(); return {"ok": True}
@router.get("/api/events/{eid}/feedback/summary")
def feedback_summary(eid: int, u: User = Depends(organizer), db: Session = Depends(get_db)):
    out = []
    for s in db.query(ScheduleItem).filter_by(event_id=eid).order_by(ScheduleItem.start_time):
        dist = dict(db.query(Feedback.rating, func.count()).filter_by(session_id=s.id).group_by(Feedback.rating).all())
        n = sum(dist.values())
        out.append({"session_id": s.id, "title": s.title, "responses": n,
                    "average": round(sum(k * v for k, v in dist.items()) / n, 2) if n else None,
                    "distribution": {r: dist.get(r, 0) for r in range(5, 0, -1)}})
    return out
CATEGORIES = ["Venue", "Technical Problem", "Security", "Accessibility", "Lost Item", "Medical Assistance", "Other"]
class IssueIn(BaseModel): phone: str; category: str; description: str = Field("", max_length=500)
class IssuePatch(BaseModel): status: str = Field(pattern="^(OPEN|IN_PROGRESS|RESOLVED)$")
@router.post("/api/events/{eid}/issues", status_code=201)
def report_issue(eid: int, b: IssueIn, db: Session = Depends(get_db)):
    if b.category not in CATEGORIES: raise HTTPException(422, f"Category must be one of {CATEGORIES}")
    i = Issue(event_id=eid, attendee_id=att_by_phone(db, eid, b.phone).id, category=b.category, description=clean(b.description, 500))
    db.add(i); db.commit(); return ser(i)
@router.get("/api/events/{eid}/issues")
def list_issues(eid: int, status: str | None = None, u: User = Depends(organizer), db: Session = Depends(get_db)):
    q = db.query(Issue).filter_by(event_id=eid)
    return [ser(i) for i in (q.filter_by(status=status) if status else q).order_by(Issue.id.desc())]
@router.patch("/api/issues/{iid}")
def update_issue(iid: int, b: IssuePatch, u: User = Depends(organizer), db: Session = Depends(get_db)):
    i = db.get(Issue, iid) or (_ for _ in ()).throw(HTTPException(404, "Issue not found"))
    i.status = b.status; i.resolved_at = now() if b.status == "RESOLVED" else None
    audit(db, u.id, i.event_id, "ISSUE_STATUS", f"{iid}->{b.status}"); db.commit(); return ser(i)
class CheckIn(BaseModel): phone: str
@router.get("/api/events/{eid}/attendees")
def list_attendees(eid: int, u: User = Depends(organizer), db: Session = Depends(get_db)):
    return [ser(a) for a in db.query(Attendee).filter_by(event_id=eid).order_by(Attendee.id)]
@router.post("/api/events/{eid}/checkin")
def checkin(eid: int, b: CheckIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    a = att_by_phone(db, eid, b.phone); a.checked_in = True; db.commit(); return ser(a)

# ---------- Airtime rewards (organizer-selected, capped) ----------
MAX_KES = int(os.getenv("REWARD_MAX_KES", "50")); MAX_PER = int(os.getenv("REWARD_MAX_PER_ATTENDEE", "1"))
class RewardIn(BaseModel): attendee_id: int; amount: int = Field(ge=5)
@router.post("/api/events/{eid}/rewards", status_code=201)
def reward(eid: int, b: RewardIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    a = db.query(Attendee).filter_by(id=b.attendee_id, event_id=eid).first()
    if not a: raise HTTPException(404, "Attendee not found")
    if b.amount > MAX_KES: raise HTTPException(422, f"Amount exceeds the per-reward limit of KES {MAX_KES}")
    if db.query(Reward).filter_by(event_id=eid, attendee_id=a.id).count() >= MAX_PER:
        raise HTTPException(409, "Reward limit reached for this attendee")
    r = Reward(event_id=eid, attendee_id=a.id, amount=b.amount, simulated=not LIVE_AT, status="SENT")
    if LIVE_AT:
        try:
            import africastalking; africastalking.initialize(AT_USER, AT_KEY)
            res = africastalking.Airtime.send(phone_number=a.phone, amount=str(b.amount), currency_code="KES")
            r.status = "SENT" if int(res.get("numSent", 0)) > 0 else "FAILED"
        except Exception: log.exception("Airtime failed"); r.status = "FAILED"
    db.add(r); audit(db, u.id, eid, "REWARD", f"attendee={a.id} KES {b.amount} {r.status}"); db.commit()
    return {"participant": a.phone[:6] + "XXX" + a.phone[-3:], "amount": f"KES {b.amount}", "status": r.status, "simulated": r.simulated}

# ---------- Voice (max 10 selected recipients) ----------
class VoiceIn(BaseModel): message: str = Field(min_length=2, max_length=300); attendee_ids: list[int] = Field(min_length=1, max_length=10)
@router.post("/api/events/{eid}/voice", status_code=201)
def voice(eid: int, b: VoiceIn, u: User = Depends(organizer), db: Session = Depends(get_db)):
    get_event(db, eid)
    atts = db.query(Attendee).filter(Attendee.event_id == eid, Attendee.id.in_(b.attendee_ids)).all()
    if not atts: raise HTTPException(404, "No matching attendees")
    item = FeedItem(event_id=eid, type="EMERGENCY_ALERT", title="Urgent announcement", content=clean(b.message, 300),
                    priority="URGENT", channels="FEED,VOICE", created_by=u.id); db.add(item); db.flush()
    rows = [Notification(event_id=eid, feed_item_id=item.id, type="VOICE", channel="VOICE", message=item.content,
                         recipient=a.phone, simulated=not LIVE_AT, status="SENT") for a in atts]
    db.add_all(rows)
    if LIVE_AT:
        try:
            import africastalking; africastalking.initialize(AT_USER, AT_KEY)
            africastalking.Voice.call(callFrom=os.getenv("AT_VOICE_NUMBER"), callTo=[a.phone for a in atts])
        except Exception:
            log.exception("Voice failed")
            for r in rows: r.status = "FAILED"
    audit(db, u.id, eid, "VOICE_ALERT", f"recipients={len(rows)}"); db.commit()
    return {"recipients": len(rows), "simulated": not LIVE_AT, "status": rows[0].status}
VOICE_SESSIONS = {}

def voice_response(prompt, collect_digits=False):
    root = ET.Element("Response")
    if collect_digits:
        action = ET.SubElement(root, "GetDigits", {"numDigits": "1", "timeout": "10"})
        ET.SubElement(action, "Say").text = prompt
    else:
        ET.SubElement(root, "Say").text = prompt
    return Response(ET.tostring(root, encoding="unicode"), media_type="application/xml")

@router.post("/api/webhooks/voice")
def voice_webhook(isActive: str = Form("1"), sessionId: str = Form(""), callerNumber: str = Form(""),
                  dtmfDigits: str = Form(""), db: Session = Depends(get_db)):
    from app.main import USSD_EVENT_SELECTION, register_attendee, ussd_reply

    session_key = f"voice:{sessionId}"
    if isActive != "1":
        VOICE_SESSIONS.pop(sessionId, None)
        USSD_EVENT_SELECTION.pop(session_key, None)
        return Response("<Response/>", media_type="application/xml")

    phone = norm_phone(callerNumber)
    if not sessionId or not phone:
        return voice_response("Sorry, we could not identify this caller.")

    try:
        event = db.query(Event).filter_by(status="LIVE").order_by(Event.id.desc()).first()
        if not event:
            return voice_response("There are no active events right now.")

        is_new_session = sessionId not in VOICE_SESSIONS
        state = VOICE_SESSIONS.setdefault(sessionId, {
            "text": "", "awaiting_event": False, "pending_registration": False, "event_id": event.id,
        })
        selected_event_id = USSD_EVENT_SELECTION.get(session_key, state["event_id"])
        event = db.get(Event, selected_event_id) or event
        db.add(AuditLog(event_id=event.id, action="VOICE_HIT"))

        digits = dtmfDigits.strip()
        if state["pending_registration"]:
            if digits == "1":
                register_attendee(db, event, "Voice caller", phone, "VOICE")
                result = "END Your phone number is registered. A confirmation SMS is on its way."
            elif digits == "2":
                result = "END Registration cancelled."
            else:
                result = "CON To register this phone number, press 1. To cancel, press 2."
            state["pending_registration"] = result.startswith("CON")
        elif not digits:
            result = ussd_reply(db, event, phone, "", session_key)
            if is_new_session:
                alert = db.query(FeedItem).filter(FeedItem.channels.contains("VOICE")).order_by(FeedItem.id.desc()).first()
                if alert:
                    result = f"{result[:4]}Urgent announcement: {clean(alert.content, 300)}. {result[4:]}"
        elif state["awaiting_event"]:
            result = ussd_reply(db, event, phone, digits, session_key)
            state["awaiting_event"] = result.startswith("CON Select an event")
            state["text"] = ""
            state["event_id"] = USSD_EVENT_SELECTION.get(session_key, event.id)
        elif not state["text"] and digits == "1":
            attendee = db.query(Attendee).filter_by(event_id=event.id, phone=phone).first()
            if attendee:
                result = "END You are already registered for this event."
            else:
                state["pending_registration"] = True
                result = "CON To register this phone number, press 1. To cancel, press 2."
        else:
            state["text"] = f"{state['text']}*{digits}".strip("*")
            result = ussd_reply(db, event, phone, state["text"], session_key)
            if "Welcome to Activity Feed" in result:
                state["text"] = ""

        db.commit()
        if result.startswith("CON "):
            prompt = " ".join(result[4:].split())
            state["awaiting_event"] = state["awaiting_event"] or "Select an event" in prompt
            return voice_response(prompt, collect_digits=True)

        VOICE_SESSIONS.pop(sessionId, None)
        USSD_EVENT_SELECTION.pop(session_key, None)
        return voice_response(" ".join(result[4:].split()))
    except Exception:
        log.exception("Voice flow error")
        db.rollback()
        VOICE_SESSIONS.pop(sessionId, None)
        USSD_EVENT_SELECTION.pop(session_key, None)
        return voice_response("Sorry, we could not process your request. Please try again later.")
@router.post("/api/webhooks/sms")
def sms_inbound(from_: str = Form("", alias="from"), text: str = Form(""), db: Session = Depends(get_db)):
    log.info("Inbound SMS from %s (%d chars)", from_[-4:], len(text)); return {"ok": True}

# ---------- analytics ----------
@router.get("/api/events/{eid}/analytics")
def analytics(eid: int, u: User = Depends(organizer), db: Session = Depends(get_db)):
    reg = db.query(Attendee).filter_by(event_id=eid).count(); ci = db.query(Attendee).filter_by(event_id=eid, checked_in=True).count()
    sms = dict(db.query(Notification.status, func.count()).filter_by(event_id=eid, type="SMS").group_by(Notification.status).all())
    pr = dict(db.query(PollResponse.source, func.count()).join(Poll, Poll.id == PollResponse.poll_id).filter(Poll.event_id == eid).group_by(PollResponse.source).all())
    fb = dict(db.query(Feedback.source, func.count()).filter_by(event_id=eid).group_by(Feedback.source).all())
    ch = {k: pr.get(k, 0) + fb.get(k, 0) for k in ("WEB", "USSD")}
    return {"registered": reg, "checked_in": ci, "attendance_rate": round(100 * ci / reg, 1) if reg else 0,
            "sms": {k: sms.get(k, 0) for k in ("QUEUED", "SENT", "DELIVERED", "FAILED")},
            "voice_notifications": db.query(Notification).filter_by(event_id=eid, type="VOICE").count(),
            "ussd_interactions": db.query(AuditLog).filter_by(event_id=eid, action="USSD_HIT").count(),
            "feedback_responses": sum(fb.values()), "poll_responses": sum(pr.values()),
            "issues_reported": db.query(Issue).filter_by(event_id=eid).count(),
            "announcements": db.query(FeedItem).filter_by(event_id=eid).count(),
            "engagement_by_channel": ch, "rewards_sent": db.query(Reward).filter_by(event_id=eid, status="SENT").count(),
            "demo_mode": not LIVE_AT, "note": "All figures are computed from the database; seeded attendees are flagged is_demo."}

# ---------- extra USSD flows ----------
USSD_CATS = ["Technical", "Security", "Lost Item", "Accessibility", "Other"]
def _pick(seq, x):
    i = int(x)
    if not 1 <= i <= len(seq): raise ValueError
    return seq[i - 1]
def ussd_more(db, event, phone, parts):
    c, rest = parts[0], parts[1:]
    if c == "7": return "CON HELP\nAsk any organizer or visit the info desk.\n\n0. Back"
    a = db.query(Attendee).filter_by(event_id=event.id, phone=phone).first()
    if not a: return "END Please register first (option 1)."
    try:
        if c == "4":
            p = db.query(Poll).filter_by(event_id=event.id, status="OPEN").order_by(Poll.id.desc()).first()
            if not p: return "CON No active poll right now.\n\n0. Back"
            opts = db.query(PollOption).filter_by(poll_id=p.id).order_by(PollOption.id).all()
            if not rest: return f"CON {p.question[:70]}\n" + "\n".join(f"{i+1}. {o.text[:30]}" for i, o in enumerate(opts))
            cast_vote(db, p, _pick(opts, rest[0]).id, a, "USSD"); return "END Thanks, your vote is counted."
        if c == "5":
            ss = db.query(ScheduleItem).filter_by(event_id=event.id).order_by(ScheduleItem.start_time).all()
            if not rest: return "CON Rate which session?\n" + "\n".join(f"{i+1}. {s.title[:28]}" for i, s in enumerate(ss))
            s = _pick(ss, rest[0])
            if len(rest) == 1: return f"CON Rate {s.title[:30]}\n1 (poor) to 5 (excellent)"
            save_feedback(db, event.id, s.id, a, int(rest[1]), "", "USSD"); return "END Thank you for your feedback."
        if c == "6":
            if not rest: return "CON REPORT AN ISSUE\n" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(USSD_CATS))
            db.add(Issue(event_id=event.id, attendee_id=a.id, category=_pick(USSD_CATS, rest[0]), description="Reported via USSD"))
            return "END Issue reported. Organizers have been notified."
    except HTTPException as ex: return f"END {ex.detail}"
    except (ValueError, IndexError): return "END Invalid selection."
    return "END Invalid selection."
