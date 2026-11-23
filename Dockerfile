FROM python:3.12-slim
WORKDIR /app

# Patch one Debian library at build time: zlib1g has a HIGH advisory (CVE-2026-85091) fixed in
# 1:1.3.dfsg+really1.3.1-1+deb13u1, and the python:3.12-slim base image does not have it yet. Only
# this package is upgraded. Remove this step once the base image ships the fix (CI's Trivy scan
# fails on HIGH findings that have a fix, so it will tell us).
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user, not root.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/docs /app/logs && chown app:app /app/docs /app/logs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py approval_view.py agent.py brain.py lesson_capture.py lessons.py lessons_agent.py pending_store.py packs_agent.py packs_gateway.py packs_manifest.py packs_registry.py provenance.py rag.py safety.py task_agent.py ./
COPY packs/ packs/
COPY .streamlit/ .streamlit/
# Security evaluation dashboard (read-only views of experiment results). Same image, started as its own
# service in docker-compose.yml; the chat app's command below is unchanged.
COPY security_dashboard.py ./
COPY dashboard/ dashboard/
USER app

EXPOSE 8501 8502
# Binds to all interfaces inside the container only. docker-compose.yml publishes
# the port on 127.0.0.1 only. Do not publish it to 0.0.0.0 (there is no login).
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
