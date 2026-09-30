# Activity Feed
One event. One live feed. Every attendee connected, by web, USSD or SMS. Built on Africa's Talking (SMS, USSD, Voice, Airtime).

## Architecture
```
Organizer -> FastAPI -> DB -> Activity Feed
                         \-> Africa's Talking SMS/Voice/Airtime -> Attendee
Feature phone -> USSD -> Africa's Talking -> /api/webhooks/ussd -> DB -> Organizer dashboard
```
Stack: FastAPI, SQLAlchemy, SQLite (dev) / PostgreSQL (`DATABASE_URL`), JWT auth. Frontend: React + Vite + Tailwind in `frontend/` (`npm install && npm run dev`).

## Run locally
```
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && cp .env.example .env   # set JWT_SECRET
uvicorn app.main:app --reload --env-file .env             # docs at /docs
python -m pytest
```
## Environment variables
See `backend/.env.example`. Extra: `REWARD_MAX_KES` (default 50), `REWARD_MAX_PER_ATTENDEE` (default 1), `DEMO_ORGANIZER_PASSWORD`, `WEBHOOK_TOKEN`.

## Demo mode
`DEMO_MODE=true` (or missing credentials): SMS, Voice and Airtime are never sent. Records are flagged `simulated: true`. Seeded attendees are flagged `is_demo`.

## Africa's Talking setup (callbacks; append `?token=$WEBHOOK_TOKEN` if set)
| Product | Callback |
|---|---|
| USSD | `POST /api/webhooks/ussd` |
| SMS delivery reports | `POST /api/webhooks/sms/delivery` |
| Inbound SMS | `POST /api/webhooks/sms` |
| Voice | `POST /api/webhooks/voice` |
Use the sandbox username `sandbox` with sandbox API key, and a tunnel (e.g. ngrok) locally.
Airtime: `POST /api/events/{id}/rewards` (organizer only, capped). Voice: `POST /api/events/{id}/voice` (max 10 recipients).

## Deployment
Backend on Render/Railway/Fly.io with PostgreSQL; set env vars and point callbacks to `https://<domain>/api/webhooks/...`.
