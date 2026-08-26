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

LABEL org.opencontainers.image.title="pgEdge Radar Analyst" \
      org.opencontainers.image.description="Assesses radar diagnostic archives" \
      org.opencontainers.image.source="https://github.com/pgEdge/radar-analyst" \
      org.opencontainers.image.licenses="PostgreSQL"

# Nothing is installed here beyond the wheel and its dependencies.
# PostgreSQL is a separate service: docker-compose runs the pgEdge
# minimal image alongside this one, and a package install uses the
# system server. Either way the analyst is told where it is with
# RADAR_ANALYST_STATE_DB_URL.
RUN groupadd --system --gid 10001 radar && \
    useradd --system --uid 10001 --gid radar --home-dir /app \
        --shell /usr/sbin/nologin radar && \
    mkdir -p /data && chown radar:radar /data && \
    mkdir -p /app && chown -R radar:radar /app
WORKDIR /app
# Copy to a directory so the wheel keeps its PEP-427 filename
# ({dist}-{version}-{python}-{abi}-{platform}.whl): pip parses
# that filename and rejects any rename like "radar_analyst.whl".
COPY --from=py-build /app/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080
# Uploaded radar archives and the generated admin token live here.
# Mount a volume and that directory is the whole of what the analyst
# writes; the assessments themselves live in PostgreSQL.
VOLUME ["/data"]

# Inside a container the service must bind 0.0.0.0, because a
# container's own loopback is not reachable from the host. What keeps
# the analyst local is the host-side publish: docker-compose binds
# 127.0.0.1:8080. Do not "fix" this to 127.0.0.1 here, and do not
# publish the port without the 127.0.0.1 prefix.
ENV RADAR_ANALYST_LISTEN=0.0.0.0:8080 \
    RADAR_ANALYST_DATA_DIR=/data

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request as u; \
u.urlopen('http://127.0.0.1:8080/readyz').read()"

# The entrypoint runs as root only long enough to make the volume
# writable, then drops to the unprivileged `radar` user.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "radar_analyst"]
