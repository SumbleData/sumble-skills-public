# Minimal container for the zero-dependency account-scoring demo app.
# The app is stdlib-only, so no pip install is needed.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Cloud Run sets $PORT (default 8080). The app reads $PORT and $HOST; it must
# bind 0.0.0.0 to be reachable in a container.
ENV HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
