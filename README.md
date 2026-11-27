# Asterisk Node Manager

A standalone Python application for managing Asterisk node configuration. The
repository provides a shared library, the astnode command, and a Flask web
manager. SQLAlchemy models and Alembic migrations manage the SQLite store;
bundled Jinja2 templates generate files consumed by Asterisk and apt-rpt.

The project targets Python 3.11+ and Debian 12 and 13. The application code is
licensed under GPL-3.0-or-later. The bundled Asterisk configuration baselines
are derived from AllStarLink/app_rpt and are licensed under GPL-2.0-only; see
`src/asterisk_node_manager/conf/base/README.md`. See GLOSSARY.md for project
terminology.

## Development installation

    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .
    astnode --help

Install the test extra and run the full test suite with:

    python -m pip install -e '.[test]'
    python -m pytest

The database and host settings are configured in
/etc/asterisk-node-manager/config.toml after Debian package installation. A
source checkout defaults to ./node-manager.toml. The default database location
is /var/lib/asterisk-node-manager/manager.sqlite3 in a system installation.
Dynaconf reads built-in defaults, then that TOML file, then ASTNODE-prefixed
environment variables. Nested variables use double underscores, for example
ASTNODE_PATHS__DATABASE and ASTNODE_WEB__PORT. Set ASTNODE_CONFIG to
select an explicit TOML file; if that file does not exist, startup fails.

The web service binds to 127.0.0.1:8765 by default. Web access uses the host
PAM service. PAM users can read configuration; write access is controlled by
the root-managed writer allowlist. Manage that allowlist with the root-only
commands astnode writers add USERNAME and astnode writers remove USERNAME.
The application packages full base configurations for every managed Asterisk
file. Database settings override matching baseline values, then the writer
replaces the managed files with the rendered configuration. It does not rely
on the host's `custom/` include directory. This includes `echolink.conf`.

Network profiles use schema version 2 with explicit registration method and
servers, status reporting URL and interval, node lookup method, DNS domain,
maximum DNS node ID length, and external node file fields. These values are
stored in separate SQLite columns; profiles do not accept an opaque config
object. The upload format is documented in docs/network-profile.schema.json.
Network profiles are disabled by default. Enable them in Dynaconf with
`networks.profiles_enabled = true` (or
`ASTNODE_NETWORKS__PROFILES_ENABLED=true`) and restart both services. In
single-network mode, choose the network in Dynaconf with
`networks.default_network` (or `ASTNODE_NETWORKS__DEFAULT_NETWORK`). When
multi-network mode is enabled from the Network profiles page, the web app can
set the default network there. On startup, the web and writer services scan
`paths.network_profiles_directory` (default
`/etc/asterisk-node-manager/networks`) for `*.json` profiles and insert or
update records by profile key. In Docker Compose, place profiles in the local
`network-profiles/` directory. The AllStarLink profile remains the only
network seeded by the database migration.

See docs/architecture.md for the local writer, PAM, migration, backup, and
import workflows.

## Packaging

Build a wheel with python -m build. Debian packaging metadata and systemd
units are under debian/ and packaging/systemd/.

## Docker Compose

The standard Compose file starts the web service and the privileged writer
helper as separate containers. It binds the web port to localhost and writes
generated files to `./asterisk-config` by default. The writer uses the mounted
configuration directory's group ID for new files. Set `ASTERISK_GID` in the
environment to the host Asterisk group's numeric ID when the directory group
does not match it. Start it with:

    docker compose up --build

The Compose writer does not mount the host password database. PAM can
authenticate only accounts available inside the writer container; host
operating-system accounts are supported by the native systemd deployment.
Grant web write access by adding authorized usernames to `docker/writers` or
running `docker compose exec web astnode writers add USERNAME`.

To preview the web interface without a helper, run the isolated demo Compose
file instead:

    docker compose -f compose.demo.yaml up --build

Open http://127.0.0.1:8765. The demo login is fixed to `demo` and its username
field is read-only. Demo data lives in an in-memory SQLite database and is
discarded when the service stops; generated examples are kept in a separate
volume. Diagnostics display sample output. The demo service does not start or
connect to the privileged writer helper.
Reset generated files with `docker compose -f compose.demo.yaml down -v`.
