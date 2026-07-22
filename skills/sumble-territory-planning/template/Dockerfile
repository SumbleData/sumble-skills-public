# Minimal container for the zero-dependency territory-planning app.
# Stdlib-only, so no pip install. Cloud Run / fly.io set $PORT; the app reads
# $PORT and $HOST (must bind 0.0.0.0 to be reachable in a container). Basic auth
# activates in the container via BASIC_AUTH_PASS (set as a deploy secret).
#
# NOTE: the container filesystem is ephemeral, so accept/reject decisions written
# to territory.csv do not survive a restart. Deploy this to SHOW a plan; do the
# reviewing locally, or export actions.csv before the instance recycles.
FROM python:3.12-slim
WORKDIR /app
COPY . /app
ENV HOST=0.0.0.0
CMD ["python", "app.py"]
