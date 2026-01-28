# Jeeves — Influencer Outreach Agent (MVP)

Jeeves is a backend service that acts as an **AI-assisted influencer outreach agent** for e-commerce brands.  
It manages influencers, campaigns, outreach threads, message drafting, approvals, sending, and automated follow-ups — with humans in the loop.

This MVP is designed to be:
- API-first
- Safe (no auto-sending without approval)
- Observable (structured JSON logs)
- Extensible (real LLM + email providers later)

---

## Core Concepts

### Influencer
A creator on a social platform (Instagram, TikTok, YouTube, etc.).

### Campaign
Defines the outreach rules:
- offer type (gifted / paid / affiliate)
- brand context
- outreach constraints

### Outreach Thread
Represents the conversation between your brand and an influencer for a specific campaign.

A thread moves through stages:
- `new` → needs initial draft
- `needs_approval` → draft ready for review
- `waiting` → message sent, awaiting reply
- `replied` → influencer responded

### Message
An individual communication:
- `direction`: outbound / inbound
- `status`: draft / approved / sent / received
- channel: email or DM (email only in MVP)

---

## Current Functionality

### ✅ CRUD APIs
- Influencers
- Campaigns
- Outreach threads

### ✅ Message Lifecycle
1. Draft generated (mock AI)
2. Human approval required
3. Message sent (stubbed sender)
4. Thread scheduling updated
5. Follow-ups generated automatically if needed

### ✅ AI Drafting (Stubbed)
- Drafts are generated using a **mock LLM** by default
- No OpenAI API key required for development
- Switchable to real OpenAI later via env vars

### ✅ Background Jobs (Celery)
1. **Job #1 — Initial Draft Generator**
   - Finds threads in `new`
   - Generates first outreach draft
   - Moves thread to `needs_approval`

2. **Job #2 — Follow-Up Generator**
   - Finds threads in `waiting`
   - Skips if any inbound reply exists
   - Generates follow-up draft after N days
   - Moves thread back to `needs_approval`

3. **Job #3 — Scheduling Updates**
   - When a message is sent:
     - sets `last_contact_at`
     - sets `next_followup_at`

### ✅ Testing Utilities
- Endpoint to simulate inbound replies (for testing follow-ups)

### ✅ Observability
- Structured JSON logging
- Shared logger for API + Celery
- Request IDs and Celery task IDs included

---

## Project Structure

```text
jeeves/
  backend/
    alembic/
    routers/
      influencers.py
      campaigns.py
      threads.py
      messages.py
    celery_app.py
    tasks.py
    llm.py
    db.py
    models.py
    schemas.py
    logging_config.py
    main.py
````

---

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/jeeves

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Logging
LOG_LEVEL=INFO
SERVICE_NAME=jeeves

# LLM
LLM_MODE=mock   # default (no API key required)
# LLM_MODE=openai
# OPENAI_API_KEY=sk-...

# Testing utilities
ALLOW_TEST_ENDPOINTS=true
```

---

## Running the App

### 1️⃣ Start dependencies

```bash
brew install redis postgresql
brew services start redis
brew services start postgresql
```

### 2️⃣ Activate virtualenv

```bash
cd jeeves/backend
source .venv/bin/activate
```

### 3️⃣ Run API

```bash
uvicorn main:app --reload
```

### 4️⃣ Run Celery worker

```bash
celery -A celery_app.celery_app worker --loglevel=INFO
```

### 5️⃣ Run Celery beat (scheduler)

```bash
celery -A celery_app.celery_app beat --loglevel=INFO
```

---

## Key API Endpoints

### Threads

```http
GET  /threads
GET  /threads/{thread_id}
GET  /threads/{thread_id}/messages
POST /threads/{thread_id}/simulate_inbound   # testing only
```

### Messages

```http
POST /messages/draft/{thread_id}
POST /messages/{message_id}/approve
POST /messages/{message_id}/send
GET  /messages
GET  /messages/{message_id}
```

---

## Message Workflow

```text
new thread
   ↓
Celery Job #1 generates draft
   ↓
needs_approval
   ↓
POST /approve
   ↓
POST /send
   ↓
waiting
   ↓
(no reply after N days)
   ↓
Celery Job #2 generates follow-up draft
```

If an inbound reply is detected:

* follow-ups stop
* thread moves to `replied`

---

## Logging

All logs are structured JSON:

```json
{
  "ts": "2026-01-28T19:22:11Z",
  "level": "INFO",
  "service": "jeeves",
  "component": "worker",
  "msg": "draft_created",
  "task_id": "...",
  "props": {
    "thread_id": "...",
    "campaign_id": "...",
    "influencer_id": "..."
  }
}
```

Designed for:

* local debugging
* future ELK / Datadog ingestion

---

## Roadmap (Next Steps)

* Real email sending (SendGrid / Gmail API)
* Real LLM integration (OpenAI / Claude)
* Influencer scoring + ranking
* UI dashboard
* DM channel support
* Multi-touch follow-up strategies
* Reply classification (interested / decline / negotiate)

---

## Status

✅ MVP complete
🚧 Actively extensible
🧠 Human-in-the-loop by design

---

**Jeeves is built to behave like a careful, professional outreach assistant — not a spam bot.**

