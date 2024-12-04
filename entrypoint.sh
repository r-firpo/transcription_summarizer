#!/bin/bash

echo "Starting Gunicorn with single worker."

exec gunicorn app.app:app \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:80 \
    --log-level info \
    --access-logfile "-" \
    --error-logfile "-"