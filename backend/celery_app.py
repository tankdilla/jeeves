# celery_app.py
from dotenv import load_dotenv
load_dotenv()

import os
from celery import Celery

from celery.schedules import crontab

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", BROKER_URL)

celery_app = Celery(
    "jeeves",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["tasks"],
)

celery_app.conf.timezone = "America/Chicago"
celery_app.conf.task_track_started = True

celery_app.conf.beat_schedule = {
    "generate-initial-drafts-every-minute": {
        "task": "tasks.generate_initial_drafts",
        "schedule": crontab(minute="*/1"),
        "args": (25,),
    },
    "generate-followups-every-hour": {
        "task": "tasks.generate_followup_drafts",
        "schedule": crontab(minute=0, hour="*/1"),
        "args": (3, 25),  # 3 days since last send, limit 25
    },
    "score-influencers-nightly": {
        "task": "tasks.score_influencers",
        "schedule": crontab(minute=0, hour=2),
        "args": (200, 24),
    },
    "campaign-fill-and-draft-every-30-min": {
        "task": "tasks.campaign_fill_and_draft",
        "schedule": crontab(minute="*/30"),
        "args": ("<PASTE_CAMPAIGN_UUID_HERE>",),
        "kwargs": {"min_score": 70.0, "max_new_threads": 25, "require_email": True},
    },

}