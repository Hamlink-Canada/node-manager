# Base Asterisk configurations

These configuration baselines are derived from the `configs/rpt` examples in
[AllStarLink/app_rpt](https://github.com/AllStarLink/app_rpt/tree/master/configs/rpt).
The sample node stanzas, example passwords, sample registrations, and
`custom/` include directives have been removed. `echolink.conf` and
`savenode.conf` contain generic defaults without sample account credentials.

The upstream configuration files are licensed under GPL-2.0-only; see
`LICENSE.GPL-2.0-only`. The application code remains GPL-3.0-or-later.
Database values replace matching baseline settings during generation, and
node and network settings replace the corresponding baseline values. The
writer replaces each managed output file with the fully rendered result.
