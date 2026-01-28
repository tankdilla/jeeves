# Jeeves — Influencer Outreach MVP (Custom Build)

Jeeves is a custom-built influencer outreach MVP. It stores influencers, campaigns, and outreach threads, generates outreach drafts (stubbed by default), and supports an approval + send workflow.

> **Current status:**  
> - LLM is **stubbed (mock mode)** by default  
> - Email sending is **stubbed**  
> - No OpenAI API key required to develop or test

---

## Project Structure

```

jeeves/
backend/
main.py
db.py
models.py
schemas.py
llm.py
tasks.py
alembic.ini
alembic/
env.py
versions/

````

---

## Core Workflow

The MVP follows a simple, explicit pipeline:

1. **Create a Campaign**  
   Defines the outreach context (offer type, brand context, CTA).

2. **Create an Influencer**  
   Stores creator metadata (platform, handle, email, bio, etc.).

3. **Create an Outreach Thread**  
   Links one influencer to one campaign.

4. **Generate a Draft Message**  
   - Generates an outreach message draft  
   - Stored in `messages` with `status="draft"`  
   - Thread moves to `stage="needs_approval"`  
   - Uses a **mock LLM by default**

5. **Approve the Draft**  
   - Message moves to `status="approved"`

6. **Send (Stub)**  
   - Message marked as `status="sent"`  
   - `provider_msg_id` populated with a stub value  
   - Thread moves to `stage="waiting"`

---

## Status & Stage Definitions

### Thread Stage (`outreach_threads.stage`)
- `drafting` — thread created, no draft yet
- `needs_approval` — draft generated
- `waiting` — sent, waiting for reply

### Message Status (`messages.status`)
- `draft`
- `approved`
- `sent`

---

## Local Development Setup

### 1. Create and activate a virtual environment

From `jeeves/backend`:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install fastapi uvicorn sqlalchemy psycopg2-binary alembic pydantic-settings openai
````

> `openai` is installed even though the app runs in mock mode by default.

---

## Database Setup (Postgres)

### Option A: Docker (recommended)

```bash
docker run --name jeeves-db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=jeeves \
  -p 5432:5432 -d postgres:16
```

### Option B: Local Postgres

Ensure Postgres is running and a database named `jeeves` exists.

---

## Environment Variables

### Database

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/jeeves"
```

### LLM Mode (default = mock)

```bash
export LLM_MODE=mock
unset OPENAI_API_KEY
```

When ready to use OpenAI later:

```bash
export LLM_MODE=openai
export OPENAI_API_KEY="your_key_here"
export OPENAI_MODEL="gpt-5.2-mini"
```

---

## Run Database Migrations

From `jeeves/backend`:

```bash
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/jeeves"
alembic upgrade head
```

Expected tables:

* campaigns
* influencers
* outreach_threads
* messages
* alembic_version

---

## Start the API Server

```bash
source .venv/bin/activate
uvicorn main:app --reload
```

API:

* [http://127.0.0.1:8000](http://127.0.0.1:8000)
* Docs UI (free): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Testing the MVP Flow (cURL)

### Health Check

```bash
curl http://127.0.0.1:8000/health
```

---

### Create a Campaign

```bash
curl -X POST http://127.0.0.1:8000/campaigns \
  -H "Content-Type: application/json" \
  -d '{
    "name": "H2N Micro Influencer Test",
    "offer_type": "gifted",
    "rules": {
      "brand_context": {
        "brand_name": "Hello To Natural",
        "site": "https://www.hellotonatural.com",
        "tone": "warm, confident, not salesy"
      },
      "offer": {
        "type": "gifted",
        "details": "Gifted product set + optional affiliate code",
        "cta": "Reply with your email + shipping info"
      }
    }
  }'
```

---

### Create an Influencer

```bash
curl -X POST http://127.0.0.1:8000/influencers \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "instagram",
    "handle": "samplecreator",
    "display_name": "Sample Creator",
    "profile_url": "https://instagram.com/samplecreator",
    "email": "sample@example.com",
    "bio": "Self-care, fragrance routines, natural beauty.",
    "followers": 12000,
    "engagement_rate": 0.06
  }'
```

---

### Create a Thread

```bash
curl -X POST http://127.0.0.1:8000/threads \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_id": "CAMPAIGN_UUID",
    "influencer_id": "INFLUENCER_UUID"
  }'
```

---

### Generate a Draft (Mock LLM)

```bash
curl -X POST http://127.0.0.1:8000/messages/draft/THREAD_UUID \
  -H "Content-Type: application/json" \
  -d '{"channel":"email"}'
```

---

### Approve the Draft

```bash
curl -X POST http://127.0.0.1:8000/messages/MESSAGE_UUID/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
```

---

### Send (Stub)

```bash
curl -X POST http://127.0.0.1:8000/messages/MESSAGE_UUID/send
```

---

## Stubbing Notes

### LLM

* Controlled by `LLM_MODE`
* Default mock mode generates deterministic outreach copy
* No API key required

### Email

* Sending is stubbed
* Messages are marked as sent but no email is delivered

---

## Troubleshooting

### Tables missing / “relation does not exist”

* Confirm `DATABASE_URL`
* Run:

```bash
alembic upgrade head
```

### `psql` not found inside venv

`psql` is a system binary. Ensure it’s on PATH:

```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

---

## Next Planned Enhancements

* Real outbound email (SendGrid or Gmail API)
* Inbound email reading + reply classification
* Follow-up scheduling (Celery/cron)
* Influencer discovery + scoring
* Admin UI/dashboard

---

## Security Notes

* Never commit API keys
* Use `.env` files locally and add them to `.gitignore`
* Keep outreach approval-gated until deliverability controls are added

```

