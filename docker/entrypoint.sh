#!/bin/sh
set -eu

if [ "${1:-}" = "astnode-web" ] && [ "$(id -u)" -eq 0 ]; then
    astnode init
    if [ ! -s "$ASTNODE_SECRET_KEY_FILE" ]; then
        mkdir -p "$(dirname "$ASTNODE_SECRET_KEY_FILE")"
        umask 077
        python -c 'import secrets; print(secrets.token_hex(32))' > "$ASTNODE_SECRET_KEY_FILE"
    fi
    mkdir -p "$ASTNODE_ASTERISK_DIRECTORY"
    if [ "${ASTNODE_DEMO:-0}" = "1" ] || [ "${ASTNODE_DEMO:-false}" = "true" ]; then
        demo_output="${ASTNODE_DEMO_OUTPUT_DIRECTORY:-/demo-output}"
        mkdir -p "$demo_output"
        chown -R asterisk-node-manager:asterisk-node-manager "$demo_output"
    fi
    chown -R asterisk-node-manager:asterisk-node-manager /var/lib/asterisk-node-manager
    exec setpriv --reuid=asterisk-node-manager --regid=asterisk-node-manager \
        --init-groups "$@"
fi

exec "$@"
