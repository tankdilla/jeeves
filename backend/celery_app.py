# celery_app.py
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
}