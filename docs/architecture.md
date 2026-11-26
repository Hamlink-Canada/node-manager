# Runtime architecture

The SQLite database is the configuration source of truth. SQLAlchemy defines
the persistent model and Alembic upgrades the schema. The first migration
creates the schema and seeds the initial network profile.

The astnode CLI and Flask application use the same library, database models,
and bundled Jinja2 templates. Configuration-file edits and network profile
uploads are validated and previewed before commit. A committed change is
rendered into a fixed allowlist of Asterisk configuration filenames.

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
cannot be one atomic transaction, so a failed generation is reported and can
be retried with astnode generate.

## Configuration import

sudo astnode import CONFIG_DIRECTORY previews the files and reports how many
settings and unparsed lines it found. Add --commit to import the recognized
settings and preserve unparsed lines, then regenerate the managed files.
External edits are not automatically merged into the database.
