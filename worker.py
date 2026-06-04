import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

# Inisialisasi Celery
celery_app = Celery(
    "synchrono_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

# Konfigurasi zona waktu
celery_app.conf.update(
    timezone="Asia/Jakarta",
    enable_utc=False,
    broker_connection_retry_on_startup=True
)

# Konfigurasi Celery Beat (Scheduler)
celery_app.conf.beat_schedule = {
    "run-audit-retention-daily": {
        "task": "audit.tasks.execute_audit_retention",
        "schedule": crontab(minute=0, hour=0), # Berjalan setiap hari jam 00:00
    }
}

# Autodiscover akan mencari file tasks.py di dalam folder 'audit'
celery_app.autodiscover_tasks(["audit"])