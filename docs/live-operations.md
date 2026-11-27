# Live Asterisk operations API

Live operations are available to authenticated users in the writer allowlist.
They run from the Flask worker thread; the root helper continues to publish
generated configuration files.

`GET /api/live-operations` returns the supported drivers, operations and
tuning settings. `POST /api/live-operations` accepts a JSON object:

```json
{"driver":"simpleusb","operation":"list_devices"}
```

Supported operations are `list_devices`, `read_settings`, and `set_value`.
Read and set operations also require a configured `node_number`. The driver
must match that node's `rxchannel`. Set requests include `setting` and integer
`value`. The response is `202 Accepted` with a task ID. Poll
`GET /api/live-operations/{task_id}` for `queued`, `running`, `succeeded`, or
`failed` status. Only the writer who submitted the task can poll it. Queue-full
requests return `503` with `Retry-After: 2`. Task records expire after one hour
or when evicted from the 500-record LRU; they are lost on service restart.

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

Save those corresponding fields in the web app to persist their values. USBRadio
`txvoice`, `txtone`, `auxvoice`, and `txslimsp` have no matching persistent
fields in the current web app, so saving node configuration does not persist
those live values. All unsaved changes remain live until an Asterisk reload is
requested, which reverts them. The manager does not request reloads.

Live operations require a running Asterisk instance with the selected radio
driver available. Demo mode uses mock data and never connects to Asterisk.
