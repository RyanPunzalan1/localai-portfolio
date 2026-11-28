# Pinned by digest (threat model gap 6), so the base can't change underneath a rebuild. The digest is the multi-platform
# index (arm64 Macs and amd64 CI). To update: `docker buildx imagetools inspect python:3.12-slim`, copy the top
# Digest, rebuild, and run the Trivy scan. CI's scan fails when a fixed vulnerability means it is time to bump it.
# Pinned 2026-11-28: python 3.12.16 on Debian trixie-slim.
FROM python:3.12-slim@sha256:5b5fe805d367f8f5a359ded6ab2652b7f9a206453ee6ee789c0045ba6ec15016
WORKDIR /app

# Patch Debian libraries at build time: zlib1g has a HIGH advisory (CVE-2026-85091) fixed in
# 1:1.3.dfsg+really1.3.1-1+deb13u1, and libzstd1 has one (CVE-2026-124851) fixed in 1.5.7+dfsg-1+deb13u1;
# the python:3.12-slim base image has neither fix yet. Only these packages are upgraded. Remove this step
# once the base image ships the fixes (CI's Trivy scan fails on HIGH findings that have a fix, so it will
# tell us).
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade zlib1g libzstd1 \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user, not root.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/docs /app/logs && chown app:app /app/docs /app/logs

# Every dependency pinned by version and hash (requirements.lock, generated from requirements.txt). --require-hashes
# makes pip refuse any file whose hash differs, and any package the lock doesn't list (threat model gap 6).
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app.py approval_view.py agent.py brain.py lesson_capture.py lessons.py lessons_agent.py pending_store.py packs_agent.py packs_gateway.py packs_manifest.py packs_registry.py port_relay.py provenance.py rag.py safety.py task_agent.py about.py data_schema.py ./
# The version, and the build information if scripts/release.py build-info was run (the [n] makes that file
# optional: a pattern that matches nothing is skipped, and VERSION always exists).
COPY VERSION build_info.jso[n] ./
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
