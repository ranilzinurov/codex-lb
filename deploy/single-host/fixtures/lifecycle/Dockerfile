FROM python:3.12-slim-bookworm

ARG VCS_REF
ARG FIXTURE_VERSION
ARG FAIL_READY=0

ENV FIXTURE_VERSION=${FIXTURE_VERSION} \
    FAIL_READY=${FAIL_READY}

COPY server.py /app/server.py
COPY docker-entrypoint.sh /app/scripts/docker-entrypoint.sh
RUN chmod +x /app/scripts/docker-entrypoint.sh

LABEL org.opencontainers.image.revision=$VCS_REF \
      com.codex-lb.single-host.image="true"

HEALTHCHECK --interval=1s --timeout=1s --start-period=1s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:2455/health/ready', timeout=0.5).close()"]

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
