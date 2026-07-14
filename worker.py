import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()


celery_app = Celery(
    "synchrono_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)


celery_app.conf.update(
    timezone="Asia/Jakarta",
    enable_utc=False,
    broker_connection_retry_on_startup=True,
    task_default_queue="audit_queue",
    result_expires=3600,
)


celery_app.conf.beat_schedule = {
    "run-audit-retention-daily": {
        "task": "audit.tasks.execute_audit_retention",
        "schedule": crontab(minute=0, hour=0),  
    },

    "flush-access-logs-every-10-seconds": {
        "task": "retrieval.flush_access_logs",
        "schedule": 10.0,  
    }
}


celery_app.autodiscover_tasks(["audit", "processing", "retrieval", "custom_mapping"])