from pathlib import Path
import socket
import time

from asterisk_node_manager.live_operations.base import AsteriskSocket, OperationContext, OperationError
from asterisk_node_manager.live_operations.queries import (
    QUERY_COMMANDS,
    query_asterisk,
    query_demo_asterisk,
)
from asterisk_node_manager.live_operations.simpleusb import SimpleUSBOperations
from asterisk_node_manager.live_operations.tasks import LiveTaskQueue, TaskRequest
from asterisk_node_manager.live_operations.usbradio import USBRadioOperations


class RecordingCLI:
    def __init__(self, responses=None):
        self.commands = []
        self.responses = responses or {}
        self.options = []

    def run(self, command, **options):
        self.commands.append(command)
        self.options.append(options)
        return self.responses.get(command, "ok")


def test_simpleusb_handlers_use_driver_commands_and_fixed_response_shape():
    cli = RecordingCLI({
        "susb active 1000": "Active (command) Simple USB Radio device set to [1000]",
        "susb show settings": "Active radio interface is [1000]\nRx Level currently set to 500",
    })
    driver = SimpleUSBOperations(cli)

    driver.list_devices()
    driver.read_settings(OperationContext(1000, "1000"))
    driver.set_value(OperationContext(1000, "1000"), "rx", 501)
    driver.reload_driver()

    assert cli.commands == [
        "susb active show",
        "susb active 1000",
        "susb show settings",
        "susb active 1000",
        "susb tune rx 501",
        "module reload chan_simpleusb.so",
    ]


def test_usbradio_handlers_use_real_read_and_reload_commands():
    cli = RecordingCLI({
        "radio active 1002": "Active (command) USB Radio device set to [1002]",
        "radio show settings": "Active radio interface is [1002]\nRx Level currently set to 500",
    })
    driver = USBRadioOperations(cli)

    driver.list_devices()
    driver.read_settings(OperationContext(1002, "1002"))
    driver.set_value(OperationContext(1002, "1002"), "txslimsp", 9100)
    driver.reload_driver()

    assert cli.commands == [
        "radio active show",
        "radio active 1002",
        "radio show settings",
        "radio tune txslimsp",
        "radio active 1002",
        "radio tune txslimsp 9100",
        "radio tune txslimsp",
        "module reload chan_usbradio.so",
    ]
    assert cli.options[5] == {"allow_empty_response": True}


def test_empty_txslimsp_write_response_still_reads_back_value():
    cli = RecordingCLI({
        "radio active 1002": "Active (command) USB Radio device set to [1002]",
        "radio tune txslimsp 9100": "",
        "radio tune txslimsp": "Current tx limiter setpoint: 9100",
    })
    driver = USBRadioOperations(cli)

    assert driver.set_value(OperationContext(1002, "1002"), "txslimsp", 9100) == (
        "Current tx limiter setpoint: 9100"
    )
    assert cli.commands == [
        "radio active 1002", "radio tune txslimsp 9100", "radio tune txslimsp"
    ]
    assert cli.options == [{}, {"allow_empty_response": True}, {}]


def test_usbradio_signal_query_is_read_only_and_returns_driver_feedback():
    cli = RecordingCLI({
        "radio active 1002": "Active (command) USB Radio device set to [1002]",
        "radio tune rxsquelch": (
            "Current Signal Strength is 432\nCurrent Squelch setting is 500"
        )
    })
    driver = USBRadioOperations(cli)

    result = driver.read_signal(OperationContext(1002, "1002"))

    assert result == "Current Signal Strength is 432\nCurrent Squelch setting is 500"
    assert cli.commands == ["radio active 1002", "radio tune rxsquelch"]


def test_demo_mock_uses_channel_driver_output_format_and_simulated_values():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    read = TaskRequest("a" * 32, "demo", "usbradio", "read_settings", 1002,
                       "1002", None, None)
    tune = TaskRequest("b" * 32, "demo", "usbradio", "set_value", 1002,
                       "1002", "rxsquelch", 512)

    settings = tasks._mock(read)["output"]
    assert settings.startswith("Active radio interface is [1002]\nDevice String is hw:3,0")
    assert "Device Serial is DEMO-USBRADIO-1002" in settings
    assert "Rx Squelch currently set to 500" in settings
    assert "Current tx limiter setpoint: 9000" in settings

    assert tasks._mock(tune)["output"] == "Changed Squelch setting to 512"
    assert "Rx Squelch currently set to 512" in tasks._mock(read)["output"]


def test_demo_signal_query_matches_usbradio_driver_output():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    signal = TaskRequest("f" * 32, "demo", "usbradio", "read_signal", 1002,
                         "1002", None, None)

    assert tasks._mock(signal)["output"] == (
        "Current Signal Strength is 500\nCurrent Squelch setting is 500"
    )


def test_demo_state_is_shared_by_nodes_using_the_same_runtime_device():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    tune = TaskRequest("a" * 32, "demo", "simpleusb", "set_value", 2000,
                       "1001", "rx", 612)
    read = TaskRequest("b" * 32, "demo", "simpleusb", "read_settings", 2001,
                       "1001", None, None)

    assert tasks._mock(tune)["output"] == "Changed setting on RX Channel to 612"
    assert "Rx Level currently set to 612" in tasks._mock(read)["output"]


def test_invalid_demo_tuning_cannot_return_success():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    invalid = TaskRequest("c" * 32, "demo", "simpleusb", "set_value", 1000,
                          "1000", "not_a_setting", "invalid")
    try:
        tasks._mock(invalid)
    except OperationError as error:
        assert "Unsupported simpleusb tuning setting" in str(error)
    else:
        raise AssertionError("an invalid demo tuning request was reported as successful")


def test_demo_device_listing_matches_channel_driver_format():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    simpleusb = TaskRequest("a" * 32, "demo", "simpleusb", "list_devices", None,
                            None, None, None)
    usbradio = TaskRequest("b" * 32, "demo", "usbradio", "list_devices", None,
                           None, None, None)

    assert tasks._mock(simpleusb)["output"] == (
        "Device [1000] is assigned to device=hw:2,0 card=2\n"
        "Device [1001] is assigned to device=unassigned card=-1"
    )
    assert tasks._mock(usbradio)["output"] == "Device [1002] is assigned to device=hw:3,0 card=3"


def test_transmitting_usbradio_settings_require_explicit_confirmation():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    try:
        tasks.submit("demo", "usbradio", "set_value", 1002, "1002", "txvoice", 501)
    except OperationError as error:
        assert "confirm_transmit is required" in str(error)
    else:
        raise AssertionError("a transmit-capable tuning request was not gated")


def test_rejected_device_selection_stops_before_read_or_tuning():
    for driver, command, follow_up in (
        (SimpleUSBOperations, "susb active usbB", "susb show settings"),
        (USBRadioOperations, "radio active usbB", "radio show settings"),
    ):
        cli = RecordingCLI({command: "No device [usbB] exists"})
        operation = driver(cli)
        context = OperationContext(1000, "usbB")
        for action in (lambda: operation.read_settings(context),
                       lambda: operation.set_value(context, "rx" if driver is SimpleUSBOperations
                                                    else "rxsquelch", 500)):
            try:
                action()
            except OperationError as error:
                assert "No device [usbB] exists" in str(error)
            else:
                raise AssertionError("a rejected device selection was allowed to continue")
        assert cli.commands == [command, command]


def test_unconfirmed_or_mismatched_active_selection_stops_the_operation():
    for driver, command, tuning_setting in (
        (SimpleUSBOperations, "susb active 1998", "rx"),
        (USBRadioOperations, "radio active 1998", "rxsquelch"),
    ):
        for response in ("", "ok", "Active (command) Radio device set to [1999]"):
            cli = RecordingCLI({command: response})
            operation = driver(cli)
            context = OperationContext(1998, "1998")
            try:
                operation.read_settings(context)
            except OperationError as error:
                assert "did not confirm" in str(error) or "instead of [1998]" in str(error)
            else:
                raise AssertionError("an unconfirmed device selection was treated as success")
            assert cli.commands == [command]

            cli = RecordingCLI({command: response})
            operation = driver(cli)
            try:
                operation.set_value(context, tuning_setting, 500)
            except OperationError:
                pass
            else:
                raise AssertionError("tuning continued after an unconfirmed device selection")
            assert cli.commands == [command]


def test_settings_read_must_identify_the_requested_active_device():
    cli = RecordingCLI({
        "susb active 1998": "Active (command) Simple USB Radio device set to [1998]",
        "susb show settings": (
            "Active radio interface is [1999]\nDevice String is 2-1:1.0\nCard is 0"
        ),
    })
    operation = SimpleUSBOperations(cli)

    try:
        operation.read_settings(OperationContext(1998, "1998"))
    except OperationError as error:
        assert "settings for interface [1999]" in str(error)
    else:
        raise AssertionError("settings from a different active device were accepted")
    assert cli.commands == ["susb active 1998", "susb show settings"]


def test_reserved_show_device_name_is_rejected_before_any_cli_command():
    for driver, setting in (
        (SimpleUSBOperations, "rx"),
        (USBRadioOperations, "rxsquelch"),
    ):
        cli = RecordingCLI()
        operation = driver(cli)
        context = OperationContext(1998, "SHOW")
        for action in (lambda: operation.read_settings(context),
                       lambda: operation.set_value(context, setting, 500)):
            try:
                action()
            except OperationError as error:
                assert "reserved" in str(error)
            else:
                raise AssertionError("the reserved device name was accepted")
        assert cli.commands == []


def test_demo_driver_reload_restores_only_that_drivers_initial_mock_values():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    radio_tune = TaskRequest("a" * 32, "demo", "usbradio", "set_value", 1002,
                             "1002", "rxsquelch", 512)
    radio_reload = TaskRequest("b" * 32, "demo", "usbradio", "reload_driver", None,
                               None, None, None)
    simpleusb_tune = TaskRequest("c" * 32, "demo", "simpleusb", "set_value", 1000,
                                 "1000", "rx", 600)

    tasks._mock(radio_tune)
    tasks._mock(simpleusb_tune)
    assert tasks._mock(radio_reload)["output"] == "Module 'chan_usbradio.so' reloaded successfully."
    assert "Rx Squelch currently set to 500" in tasks._mock(radio_tune.__class__(
        "d" * 32, "demo", "usbradio", "read_settings", 1002, "1002", None, None))["output"]
    assert "Rx Level currently set to 600" in tasks._mock(simpleusb_tune.__class__(
        "e" * 32, "demo", "simpleusb", "read_settings", 1000, "1000", None, None))["output"]


def test_unseeded_demo_device_gets_complete_settings_and_resets_on_reload():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    tune = TaskRequest("a" * 32, "demo", "simpleusb", "set_value", 1998,
                       "usbB", "rx", 612)
    read = TaskRequest("b" * 32, "demo", "simpleusb", "read_settings", 1998,
                       "usbB", None, None)
    reload_task = TaskRequest("c" * 32, "demo", "simpleusb", "reload_driver", None,
                              None, None, None)

    assert tasks._mock(tune)["output"] == "Changed setting on RX Channel to 612"
    changed = tasks._mock(read)["output"]
    assert "Rx Level currently set to 612" in changed
    assert "Tx A Level currently set to 500" in changed
    assert "Tx B Level currently set to 500" in changed

    tasks._mock(reload_task)
    reset = tasks._mock(read)["output"]
    assert "Rx Level currently set to 500" in reset
    assert "Tx A Level currently set to 500" in reset
    assert "Tx B Level currently set to 500" in reset


def test_named_asterisk_queries_are_fixed_and_read_only():
    cli = RecordingCLI()

    assert QUERY_COMMANDS["rpt_nodes"] == "rpt localnodes"
    for query, command in QUERY_COMMANDS.items():
        assert query_asterisk(cli, query) == "ok"

    assert cli.commands == list(QUERY_COMMANDS.values())
    try:
        query_asterisk(cli, "core show version; module unload chan_simpleusb.so")
    except OperationError as error:
        assert "supported read-only Asterisk query" in str(error)
    else:
        raise AssertionError("an arbitrary command was accepted as a query")
    assert cli.commands == list(QUERY_COMMANDS.values())


def test_demo_asterisk_queries_have_representative_cli_output():
    assert query_demo_asterisk("version").startswith("Asterisk ")
    assert "OK" in query_demo_asterisk("iax_peers")
    assert "Node 1000" in query_demo_asterisk("rpt_nodes")
    try:
        query_demo_asterisk("core show version")
    except OperationError as error:
        assert "supported read-only Asterisk query" in str(error)
    else:
        raise AssertionError("an unregistered query name returned demo output")


def test_asterisk_query_uses_the_existing_task_queue():
    tasks = LiveTaskQueue(Path("unused"), demo_mode=True)
    queued = tasks.submit_query("operator", "uptime")

    for _ in range(200):
        result = tasks.get(queued["task_id"], "operator")
        if result["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.005)

    assert result["status"] == "succeeded"
    assert result["result"]["simulated"] is True
    assert "System uptime:" in result["result"]["output"]


def test_queued_tuning_rejects_a_changed_node_device_binding(monkeypatch):
    import asterisk_node_manager.live_operations.tasks as task_module

    sent = []
    monkeypatch.setattr(task_module, "execute_operation", lambda *args: sent.append(args))

    def stale_binding(_task):
        raise OperationError("Node 1998's configured device changed while queued; no CLI command was sent.")

    tasks = LiveTaskQueue(Path("unused"), binding_validator=stale_binding)
    queued = tasks.submit("operator", "simpleusb", "set_value", 1998, "usbA", "rx", 600)

    for _ in range(200):
        result = tasks.get(queued["task_id"], "operator")
        if result["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.005)

    assert result["status"] == "failed"
    assert "changed while queued" in result["error"]
    assert sent == []


def test_socket_timeout_after_dispatch_marks_task_outcome_unknown(monkeypatch):
    import asterisk_node_manager.live_operations.base as base_module

    class TimedOutSocket:
        def __init__(self):
            self.responses = [b"Asterisk ready\n"]
            self.sent = []

        def settimeout(self, _timeout):
            pass

        def connect(self, _path):
            pass

        def sendall(self, request):
            self.sent.append(request)

        def recv(self, _size):
            if self.responses:
                return self.responses.pop(0)
            raise socket.timeout()

        def close(self):
            pass

    fake_socket = TimedOutSocket()
    monkeypatch.setattr(base_module.socket, "socket", lambda *_args, **_kwargs: fake_socket)

    try:
        AsteriskSocket(Path("unused")).run("susb tune rx 600")
    except OperationError as error:
        assert error.outcome_unknown is True
        assert "read the current settings before retrying" in str(error)
    else:
        raise AssertionError("a missing post-dispatch response was reported as confirmed")
    assert fake_socket.sent


def test_socket_can_accept_empty_reply_only_when_explicitly_requested(monkeypatch):
    import asterisk_node_manager.live_operations.base as base_module

    class EmptyReplySocket:
        def __init__(self):
            self.responses = [b"Asterisk ready\n", b""]

        def settimeout(self, _timeout):
            pass

        def connect(self, _path):
            pass

        def sendall(self, _request):
            pass

        def recv(self, _size):
            return self.responses.pop(0)

        def close(self):
            pass

    monkeypatch.setattr(base_module.socket, "socket", lambda *_args, **_kwargs: EmptyReplySocket())
    cli = AsteriskSocket(Path("unused"))

    assert cli.run("radio tune txslimsp 9100", allow_empty_response=True) == ""
    try:
        cli.run("radio show settings")
    except OperationError as error:
        assert error.outcome_unknown is True
    else:
        raise AssertionError("an unapproved empty response was accepted")


def test_task_reports_unknown_outcome_and_retains_reconciliation_warning(monkeypatch):
    import asterisk_node_manager.live_operations.tasks as task_module

    def unknown_outcome(*_args):
        raise OperationError("response lost", outcome_unknown=True)

    monkeypatch.setattr(task_module, "execute_operation", unknown_outcome)
    tasks = LiveTaskQueue(Path("unused"))
    queued = tasks.submit("operator", "simpleusb", "set_value", 1998, "usbA", "rx", 600)

    for _ in range(200):
        result = tasks.get(queued["task_id"], "operator")
        if result["status"] in {"succeeded", "failed", "outcome_unknown"}:
            break
        time.sleep(0.005)

    assert result["status"] == "outcome_unknown"
    assert "may have changed live Asterisk state" in result["warning"]


def test_task_cache_trims_total_records_but_preserves_active_work():
    tasks = LiveTaskQueue(Path("unused"))
    for index in range(500):
        tasks._tasks[f"completed-{index}"] = {"status": "succeeded"}
    tasks._tasks["running"] = {"status": "running"}
    tasks._tasks["queued"] = {"status": "queued"}

    tasks._trim()

    assert len(tasks._tasks) == 500
    assert tasks._tasks["running"]["status"] == "running"
    assert tasks._tasks["queued"]["status"] == "queued"
