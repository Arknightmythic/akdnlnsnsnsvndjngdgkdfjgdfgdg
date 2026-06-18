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
        "schedule": crontab(minute=0, hour=0), # Berjalan setiap hari jam 00:00
    },
    
    # --- TAMBAHKAN JADWAL BARU DI SINI ---
    "flush-access-logs-every-10-seconds": {
        # Nama ini harus sama dengan parameter 'name' pada @celery_app.task di file tasks.py
        "task": "retrieval.flush_access_logs", 
        "schedule": 10.0, # Berjalan setiap 10 detik
    }
}


celery_app.autodiscover_tasks(["audit", "processing", "retrieval"])