# Asterisk Node Manager

A standalone Python application for managing Asterisk node configuration. The
repository provides a shared library, the astnode command, and a Flask web
manager. SQLAlchemy models and Alembic migrations manage the SQLite store;
bundled Jinja2 templates generate files consumed by Asterisk and apt-rpt.

The project targets Python 3.11+ and Debian 12 and 13. It is licensed under
GPL-3.0-or-later. See GLOSSARY.md for project terminology.

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

The web service binds to 127.0.0.1:8765 by default. Web access uses the host
PAM service. PAM users can read configuration; write access is controlled by
the root-managed writer allowlist. Manage that allowlist with the root-only
commands astnode writers add USERNAME and astnode writers remove USERNAME.
The network profile upload format is documented in
docs/network-profile.schema.json.

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
