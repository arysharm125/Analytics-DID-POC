# celery_worker.py
from celery import Celery
import os

# Use environment variables for Redis URL, default to localhost
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND_URL = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    'tasks', # Default name for tasks module
    broker=REDIS_URL,
    backend=RESULT_BACKEND_URL, # Use Redis to store task results
    include=['tasks'] # Explicitly include the tasks module
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
