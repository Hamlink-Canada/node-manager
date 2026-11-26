FROM python:3.11-slim-bookworm AS build

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpam0g-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASTNODE_DATABASE=/var/lib/asterisk-node-manager/manager.sqlite3 \
    ASTNODE_ASTERISK_DIRECTORY=/etc/asterisk \
    ASTNODE_WRITER_SOCKET=/run/asterisk-node-manager/writer.sock \
    ASTNODE_WRITER_ALLOWLIST=/etc/asterisk-node-manager/writers \
    ASTNODE_SECRET_KEY_FILE=/var/lib/asterisk-node-manager/secret-key \
    ASTNODE_LISTEN_ADDRESS=0.0.0.0 \
    ASTNODE_PORT=8765

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpam0g util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system asterisk \
    && groupadd --system asterisk-node-manager \
    && useradd --system --gid asterisk-node-manager --groups asterisk-node-manager \
       --home-dir /nonexistent --no-create-home asterisk-node-manager \
    && install -d -o asterisk-node-manager -g asterisk-node-manager \
       /var/lib/asterisk-node-manager /etc/asterisk-node-manager \
    && install -m 0640 /dev/null /etc/asterisk-node-manager/writers

WORKDIR /app
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels asterisk-node-manager \
    && rm -rf /wheels
COPY debian/asterisk-node-manager.pam /etc/pam.d/asterisk-node-manager
COPY docker/entrypoint.sh /usr/local/bin/asterisk-node-manager-entrypoint
RUN chmod 0755 /usr/local/bin/asterisk-node-manager-entrypoint

ENTRYPOINT ["/usr/local/bin/asterisk-node-manager-entrypoint"]
CMD ["astnode-web"]
