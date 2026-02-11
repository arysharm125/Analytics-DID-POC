# celery_worker.py
from celery import Celery
import os

from app.constants import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND
)

celery_app = Celery(
    'tasks', # Default name for tasks module
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND, # Use Redis to store task results
    include=['app.tasks'] # Explicitly include the tasks module
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Optional: Add settings for task retries, rate limits, etc.
    # task_track_started=True,
)

if __name__ == '__main__':
    celery_app.start()
