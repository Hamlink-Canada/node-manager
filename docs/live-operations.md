# Live Asterisk operations API

Live operations are available to authenticated users in the writer allowlist.
They use the Asterisk CLI socket from the Flask worker thread; the root helper
continues to publish generated configuration files.

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
Live changes are not saved. Save the desired value in the web app for
persistence; the live value remains until an Asterisk reload is requested,
when the unsaved change is reverted. The manager does not request reloads.

The web service account must be able to access the configured Asterisk CLI
socket. The API reports a corrective socket permission or path error if it
cannot connect. Demo mode uses mock data and never connects to Asterisk.
