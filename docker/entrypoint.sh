#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    if [ -n "${ASTNODE_ASTERISK_GID:-}" ]; then
        asterisk_gid=$ASTNODE_ASTERISK_GID
    elif [ -d "$ASTNODE_ASTERISK_DIRECTORY" ]; then
        asterisk_gid=$(stat -c '%g' "$ASTNODE_ASTERISK_DIRECTORY")
    else
        asterisk_gid=
    fi
    case "$asterisk_gid" in
        ''|*[!0-9]*) ;;
        *) groupmod --non-unique --gid "$asterisk_gid" asterisk ;;
    esac
fi

if [ "${1:-}" = "astnode-web" ] && [ "$(id -u)" -eq 0 ]; then
    demo_mode=$(python -c 'from asterisk_node_manager.config import load_settings; print(int(load_settings().demo_mode))')
    if [ "$demo_mode" != "1" ]; then
        astnode init
    fi
    if [ ! -s "$ASTNODE_SECRET_KEY_FILE" ]; then
        mkdir -p "$(dirname "$ASTNODE_SECRET_KEY_FILE")"
        umask 077
        python -c 'import secrets; print(secrets.token_hex(32))' > "$ASTNODE_SECRET_KEY_FILE"
    fi
    mkdir -p "$ASTNODE_ASTERISK_DIRECTORY"
    mkdir -p "$(dirname "$ASTNODE_SECRET_KEY_FILE")"
    if [ "$demo_mode" = "1" ]; then
        demo_output=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().demo_output_directory)')
        mkdir -p "$demo_output"
        chown -R asterisk-node-manager:asterisk-node-manager "$demo_output"
    else
        database_path=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().database)')
        database_directory=$(dirname "$database_path")
        mkdir -p "$database_directory"
        chown asterisk-node-manager:asterisk-node-manager "$database_directory" "$database_path"
    fi
    chown root:asterisk-node-manager "$ASTNODE_SECRET_KEY_FILE"
    chmod 0640 "$ASTNODE_SECRET_KEY_FILE"
    exec setpriv --reuid=asterisk-node-manager --regid=asterisk-node-manager \
        --init-groups "$@"
fi

exec "$@"
