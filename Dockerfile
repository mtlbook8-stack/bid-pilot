# BidPilot API — production container image.
#
# Two-stage build: stage 1 compiles wheels into a venv with build tools, stage 2
# copies the venv into a minimal runtime image. This keeps the final image small
# and free of compilers/headers (smaller attack surface, faster cold start on
# Azure Container Apps).

# ---------- Stage 1: builder ----------
# Use Microsoft Artifact Registry's Azure Linux Python image — avoids Docker
# Hub anonymous pull rate limits when building from ACR Tasks. Slim base, no
# compilers in the runtime stage.
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for any wheel that needs compilation (cryptography, aiohttp, etc.).
RUN tdnf install -y gcc glibc-devel binutils make python3-devel \
    && tdnf clean all

WORKDIR /app

# Install into an isolated venv so stage 2 only needs to copy /opt/venv.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Run as a non-root user. Container Apps doesn't require it, but it's defence in
# depth — limits what a compromised process can touch inside the container.
RUN tdnf install -y shadow-utils \
    && tdnf clean all \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /home/app --create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./src
COPY --chown=app:app data ./data

USER app

EXPOSE 8000

# Bind to 0.0.0.0 so Container Apps' ingress can reach the process. Worker count
# kept at 1 — Container Apps scales horizontally by replica, not by in-process
# workers, which keeps per-replica memory predictable for autoscaling rules.
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
