from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "reasoning",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    include=["reasoning.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # enable_utc=False disamakan dengan worker.py (celery_app utama) — kalau beda,
    # crontab/interval beat schedule ditafsirkan di timezone berbeda antara dua
    # Celery app ini walau sama-sama declare timezone="Asia/Jakarta"
    # (lihat BUG_FIXING_GUIDE.md #9).
    timezone="Asia/Jakarta",
    enable_utc=False,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_default_queue="reasoning_queue"
)
