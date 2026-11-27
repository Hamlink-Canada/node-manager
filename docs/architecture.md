# Runtime architecture

The SQLite database is the configuration source of truth. SQLAlchemy defines
the persistent model and Alembic upgrades the schema. The first migration
creates the schema and seeds the initial network profile.

Network profile files are discovered from the configured profile directory on
web and writer service startup. Each valid `*.json` file is upserted by its
stable profile key; invalid files are skipped and logged. Dynaconf's
`networks.profiles_enabled` option controls whether profile management and
per-node profile assignment are available. When per-node multi-network mode is
disabled, Dynaconf's `networks.default_network` selects the network used for
all nodes. When per-node multi-network mode is enabled, the default can be
selected in the web application and is stored in SQLite.

Network profiles store their registration method and server addresses, status
reporting options, and node lookup settings in explicit SQL columns. Profile
JSON uses schema version 2 and lists these fields directly; arbitrary config
objects are not stored. Status reporting and node lookup values are emitted as
per-node `rpt.conf` settings. Registration server fields describe the service
endpoint; registration directives still require credentials for each node.

The astnode CLI and Flask application use the same library and database
models. Flask templates and static assets live under the package's `web/`
directory; Asterisk configuration templates live under `conf/`.
Configuration-file edits and network profile uploads are validated and
previewed before commit. A committed change is rendered into a fixed allowlist
of Asterisk configuration filenames. Each file starts from its packaged base
configuration; database values replace matching defaults and typed node and
network values replace their corresponding base values. The generated output
contains the complete configuration and does not depend on Asterisk's
`custom/` include directory. This includes `echolink.conf`.

The web service runs as the asterisk-node-manager system user. It cannot
write Asterisk configuration files. It connects to the root-owned,
systemd-activated Unix socket for three limited operations:

- Authenticate a username through the configured host PAM service.
- Render the current database and replace the fixed generated files.
- Run one of the fixed read-only Asterisk diagnostics.

The helper does not accept arbitrary command lines or file paths. It stages
all generated files, preserves existing ownership and mode, and rolls back
replacements if a write fails. New files use mode 0640 and the asterisk
group when present. Asterisk reload is not requested.
The writer reconciles the database to the generated files when it starts, and
the web service requests a fresh generation before it begins listening. This
repairs an interrupted file publication or a process restart from the current
database.

The Docker Compose writer does not mount the host password database. Its PAM
service can authenticate only accounts available inside its own container.
Host operating-system accounts are supported by the native systemd deployment.

PAM users can view managed configuration. Only usernames in the root-owned
writer allowlist can change it or download and restore database backups. Use
sudo astnode writers add USERNAME and sudo astnode writers remove USERNAME
to manage that allowlist.

## Database and file recovery

Use sudo astnode init to apply Alembic migrations and sudo astnode generate
to render the database again. astnode backup PATH copies the SQLite database
to the supplied path. sudo astnode restore PATH restores it and regenerates
files. The web interface provides the same backup and restore operations.

Restore validates the SQLite database before replacing the active database.
Generated files are rendered after restore; if rendering fails, the database
copy is rolled back. A database transaction and multiple filesystem updates
cannot be one atomic transaction. The web request restores the previous
database when generation fails, and service startup reconciles files from the
database. Run sudo astnode generate to request reconciliation manually.

## Configuration import

sudo astnode import CONFIG_DIRECTORY previews the files and reports how many
settings and unparsed lines it found. Add --commit to import the recognized
settings and preserve unparsed lines, then regenerate the managed files.
External edits are not automatically merged into the database.
