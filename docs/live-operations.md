# Live Asterisk operations API

Live operations are available to authenticated users in the writer allowlist.
They run from the Flask worker thread; the root helper continues to publish
generated configuration files.

`GET /api/live-operations` returns the supported drivers, operations and
tuning settings. `POST /api/live-operations` accepts a JSON object:

```json
{"driver":"simpleusb","operation":"list_devices"}
```

Supported operations are `list_devices`, `read_settings`, `set_value`, and
`reload_driver`. `list_devices` returns only the devices known to that loaded
channel driver; it does not scan host USB devices. Read and set operations also
require a configured `node_number`. The driver must match that node's
`rxchannel`. Set requests include `setting` and integer `value`. USBRadio
`txvoice` and `txtone` requests must also include `"confirm_transmit": true`:
those driver commands key the transmitter and send a 1 kHz test tone for about
five seconds. The response is `202 Accepted` with a task ID. Poll
`GET /api/live-operations/{task_id}` for `queued`, `running`, `succeeded`, or
`failed` status. Only the writer who submitted the task can poll it. Queue-full
requests return `503` with `Retry-After: 2`. Task records expire after one hour
or when evicted from the 500-record LRU; they are lost on service restart.
`reload_driver` reloads only the selected channel-driver module. The result
warns that unsaved live values can be replaced by saved configuration. Demo
mode resets simulated live values to the saved defaults when this operation is
requested.

The fixed tuning allowlist is:

| Driver | Setting | Accepted values |
| --- | --- | --- |
| SimpleUSB | `rx`, `txa`, `txb` | Integer 0–999 |
| USBRadio | `rxsquelch`, `txvoice`, `txtone`, `auxvoice` | Integer 0–999 |
| USBRadio | `txslimsp` | Integer 5000–13000 |

Every successful `set_value` task returns `persisted: false` and a warning.
Live changes are not saved. The current web configuration has these matching
persistent fields:

| Live tuning value | Saved field in node configuration |
| --- | --- |
| SimpleUSB `rx` | `simpleusb.conf` `rxmixerset` |
| SimpleUSB `txa` | `simpleusb.conf` `txmixaset` |
| SimpleUSB `txb` | `simpleusb.conf` `txmixbset` |
| USBRadio `rxsquelch` | `usbradio.conf` `rxsquelchadj` |
| USBRadio `txvoice` | `usbradio.conf` `txmixaset` or `txmixbset`, depending on the configured output |
| USBRadio `txtone` | `usbradio.conf` `txctcssadj` |
| USBRadio `auxvoice` | `usbradio.conf` `txmixaset` or `txmixbset`, depending on the configured output |

Save those corresponding fields in the web app to persist their values.
USBRadio `txslimsp` has no matching persistent field in the current web app,
so saving node configuration does not persist that live value. All unsaved
changes remain live until a driver reload is requested, which reapplies saved
configuration. The manager does not reload automatically.

Live operations require a running Asterisk instance with the selected radio
driver available. Demo mode returns mock output in the same format as the
driver CLI and marks task results as `simulated: true`; it never connects to
Asterisk. Device listing and settings mock strings follow the channel-driver
output format. See the AllStarLink `chan_simpleusb` and `chan_usbradio` sources
for the command output formats and tuning behavior.
