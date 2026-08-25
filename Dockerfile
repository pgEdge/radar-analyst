# syntax=docker/dockerfile:1.7

############################
# Stage 1: build the Astro console
############################
FROM node:22-alpine AS web-build
WORKDIR /w
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

############################
# Stage 2: build + install the Python wheel
############################
FROM python:3.13-slim AS py-build
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml hatch_build.py README.md LICENCE ./
COPY src/ ./src/
COPY --from=web-build /w/dist/ ./web/dist/
RUN pip install --upgrade pip build && \
    python -m build --wheel

############################
# Stage 3: minimal runtime
############################
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --system radar && \
    useradd --system --gid radar --home-dir /app --shell /usr/sbin/nologin radar && \
    mkdir -p /data/blobs && chown -R radar:radar /data && \
    mkdir -p /app && chown -R radar:radar /app
WORKDIR /app
# Copy to a directory so the wheel keeps its PEP-427 filename
# ({dist}-{version}-{python}-{abi}-{platform}.whl): pip parses
# that filename and rejects any rename like "radar_analyst.whl".
COPY --from=py-build /app/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels
USER radar
EXPOSE 8080
# Inside a container the service must bind 0.0.0.0, because a
# container's own loopback is not reachable from the host. What keeps
# the analyst local is the host-side publish: docker-compose binds
# 127.0.0.1:8080. Do not "fix" this to 127.0.0.1 here, and do not
# publish the port without a 127.0.0.1 prefix.
ENV RADAR_ANALYST_LISTEN=0.0.0.0:8080 \
    RADAR_ANALYST_BLOB_DIR=/data/blobs
CMD ["python", "-m", "radar_analyst"]
