#!/bin/sh
set -eu

asterisk_directory=${ASTNODE_PATHS__ASTERISK_DIRECTORY:-/etc/asterisk}
secret_key_file=${ASTNODE_WEB__SECRET_KEY_FILE:-/etc/asterisk-node-manager/secret-key}

if [ "$(id -u)" -eq 0 ]; then
    if [ -n "${ASTNODE_ASTERISK_GID:-}" ]; then
        asterisk_gid=$ASTNODE_ASTERISK_GID
    elif [ -d "$asterisk_directory" ]; then
        asterisk_gid=$(stat -c '%g' "$asterisk_directory")
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
    if [ "$demo_mode" != "1" ] && [ ! -s "$secret_key_file" ]; then
        mkdir -p "$(dirname "$secret_key_file")"
        umask 077
        python -c 'import secrets; print(secrets.token_hex(32))' > "$secret_key_file"
    fi
    mkdir -p "$asterisk_directory"
    if [ "$demo_mode" != "1" ]; then
        mkdir -p "$(dirname "$secret_key_file")"
    fi
    if [ "$demo_mode" = "1" ]; then
        demo_output=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().demo_output_directory)')
        mkdir -p "$demo_output"
        chown -R asterisk-node-manager:asterisk-node-manager "$demo_output"
    else
        database_path=$(python -c 'from asterisk_node_manager.config import load_settings; print(load_settings().database)')
        database_directory=$(dirname "$database_path")
        mkdir -p "$database_directory"
        chown asterisk-node-manager:asterisk-node-manager "$database_directory" "$database_path"
        if [ -e "${database_path}.lock" ]; then
            chown asterisk-node-manager:asterisk-node-manager "${database_path}.lock"
            chmod 0600 "${database_path}.lock"
        fi
    fi
    if [ "$demo_mode" != "1" ]; then
        chown root:asterisk-node-manager "$secret_key_file"
        chmod 0640 "$secret_key_file"
    fi
    exec setpriv --reuid=asterisk-node-manager --regid=asterisk-node-manager \
        --init-groups "$@"
fi

exec "$@"
