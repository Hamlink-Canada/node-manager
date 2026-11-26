#!/bin/sh
set -eu

if [ "${1:-}" = "astnode-web" ] && [ "$(id -u)" -eq 0 ]; then
    astnode init
    if [ ! -s "$ASTNODE_SECRET_KEY_FILE" ]; then
        mkdir -p "$(dirname "$ASTNODE_SECRET_KEY_FILE")"
        umask 077
        python -c 'import secrets; print(secrets.token_hex(32))' > "$ASTNODE_SECRET_KEY_FILE"
    fi
    database_path=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().database)')
    database_directory=$(dirname "$database_path")
    mkdir -p "$database_directory" "$(dirname "$ASTNODE_SECRET_KEY_FILE")"
    mkdir -p "$ASTNODE_ASTERISK_DIRECTORY"
    if python -c 'from asterisk_node_manager.config import load_settings; raise SystemExit(0 if load_settings().demo_mode else 1)'; then
        demo_output=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().demo_output_directory)')
        mkdir -p "$demo_output"
        chown -R asterisk-node-manager:asterisk-node-manager "$demo_output"
    fi
    chown asterisk-node-manager:asterisk-node-manager "$database_directory" "$database_path"
    chown root:asterisk-node-manager "$ASTNODE_SECRET_KEY_FILE"
    chmod 0640 "$ASTNODE_SECRET_KEY_FILE"
    exec setpriv --reuid=asterisk-node-manager --regid=asterisk-node-manager \
        --init-groups "$@"
fi

exec "$@"
