## Phase 1: Make the system *observable* (do this next)

Right now the agent works, but you can’t *see* what it’s doing without cURL or SQL.

### 1️⃣ Add “read” endpoints (highest ROI, very fast)

Add endpoints so you can inspect what the agent created.

**Recommended endpoints**

* `GET /threads/{thread_id}/messages`
* `GET /messages/{message_id}`
* `GET /threads?stage=needs_approval`
* `GET /threads?stage=waiting`

Why this matters:

* You can debug without digging into Postgres
* This becomes the backbone of a future UI
* Makes testing 10× easier

⏱️ Time: ~30–45 minutes

---

### 2️⃣ Add lightweight logging

Add structured logs for:

* draft generation
* approvals
* sends

Example:

```python
logger.info(
  "draft_generated",
  extra={"thread_id": str(thread.id), "mode": os.getenv("LLM_MODE")}
)
```

Why:

* You’ll want to know *when* things ran and *why*
* Makes background jobs debuggable later

⏱️ Time: ~15 minutes

---

## Phase 2: Turn it into an **agent**, not just an API

Right now *you* drive the flow. The agent should.

### 3️⃣ Add a background job that auto-generates drafts

Use Celery or a simple cron for now.

**Job behavior**

* Find threads with `stage="drafting"`
* Generate drafts automatically
* Leave them in `needs_approval`

This is your **first real “agent behavior”**.

⏱️ Time: ~1–2 hours

---

### 4️⃣ Add follow-up scheduling logic

Add a job that:

* Finds threads in `waiting`
* If `sent_at > N days ago` and no reply → generate follow-up draft

This is where agents shine.

**Key rule**

* Follow-ups should *always* require approval at first

⏱️ Time: ~1 hour

---

## Phase 3: Real-world usefulness

Now it starts replacing manual work.

### 5️⃣ Replace the send stub with real email

Pick **one**:

#### Option A: SendGrid (recommended first)

* Simple
* Reliable
* Outbound only (fine for MVP)

#### Option B: Gmail API

* More setup
* Enables inbound reply parsing later

**What to store**

* provider message ID
* sender email
* thread mapping

⏱️ Time: 1–2 hours

---

### 6️⃣ Add inbound reply handling (huge value)

Once emails go out, replies matter.

**Basic version**

* Poll inbox
* Attach reply to thread
* Update thread stage to `replied`

**Later**

* Classify reply intent (interested / not interested / pricing)
* Draft suggested response

⏱️ Time: 2–3 hours (worth it)

---

## Phase 4: Influencer discovery & scoring

This is where ROI increases.

### 7️⃣ Add influencer scoring (even if discovery is manual)

You already have the schema—now use it.

**Scoring inputs**

* follower count
* engagement rate
* bio keyword match
* email present
* brand fit flags

Even a simple score (0–100) helps you:

* prioritize outreach
* measure what converts

⏱️ Time: ~1 hour

---

### 8️⃣ Add discovery inputs (don’t over-automate yet)

Start with:

* CSV import
* manual entry + scoring
* later: API-based discovery

Avoid scraping early—focus on **quality over volume**.

---

## Phase 5: UX & scaling

Only after the backend proves itself.

### 9️⃣ Simple admin UI

You don’t need anything fancy:

* list threads
* view drafts
* approve/send buttons

Tools:

* Retool
* simple React + FastAPI
* even a server-rendered admin page

⏱️ Time: varies (but optional early)

---

### 🔟 LLM upgrade (last, not first)

When everything else works:

* switch `LLM_MODE=openai`
* add structured JSON output
* personalize more deeply
* add reply classification

This should be a **drop-in improvement**, not a rewrite.

---

## The “don’t do this yet” list (important)

Avoid these until later:

* ❌ Full social DM automation
* ❌ Scraping platforms aggressively
* ❌ Auto-negotiating rates
* ❌ High-volume sending

Those get people banned. You’re doing this the right way.

---

## If you want a concrete next task (recommended)

Your **best next step** is:

> **Add read-only endpoints to view messages and threads**

If you want, I can:

* paste the exact router code for those endpoints
* or outline the first Celery job step-by-step
* or wire SendGrid cleanly into your existing `/send` endpoint

Just tell me which one you want to do next.
