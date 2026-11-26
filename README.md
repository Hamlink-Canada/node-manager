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
