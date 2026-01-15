FROM python:3.13-slim

ARG USER=appuser
ARG GROUP=appgroup
ARG LLM_PORT=8002
ARG CACHE_CONTAINER_DIR=/home/${USER}/app/cache

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_PORT=${LLM_PORT} \
    CACHE_CONTAINER_DIR=${CACHE_CONTAINER_DIR} \
    PYTHONPATH=/home/${USER}/app/src

RUN groupadd -r ${GROUP} \
    && useradd -r -g ${GROUP} ${USER}

WORKDIR /tmp/build

# deps first (for docker layer cache)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# optional dev deps (not installed in runtime image)
# COPY requirements-dev.txt ./requirements-dev.txt
# RUN pip install --no-cache-dir -r requirements-dev.txt

RUN mkdir -p /home/${USER}/app/logs ${CACHE_CONTAINER_DIR} \
    && chown -R ${USER}:${GROUP} /home/${USER}

USER ${USER}
WORKDIR /home/${USER}/app

COPY --chown=${USER}:${GROUP} src/ ./src/
COPY --chown=${USER}:${GROUP} entrypoint.sh ./entrypoint.sh

RUN chmod +x ./entrypoint.sh

EXPOSE ${LLM_PORT}

# Optional but handy: container healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/metrics' % __import__('os').environ.get('LLM_PORT','8002')).read()" || exit 1

CMD ["./entrypoint.sh"]
