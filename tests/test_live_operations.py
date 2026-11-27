from pathlib import Path

from asterisk_node_manager.live_operations.base import OperationContext
from asterisk_node_manager.live_operations.base import OperationError
from asterisk_node_manager.live_operations.simpleusb import SimpleUSBOperations
from asterisk_node_manager.live_operations.tasks import LiveTaskQueue, TaskRequest
from asterisk_node_manager.live_operations.usbradio import USBRadioOperations


class RecordingCLI:
    def __init__(self, responses=None):
        self.commands = []
        self.responses = responses or {}

    def run(self, command):
        self.commands.append(command)
        return self.responses.get(command, "ok")


def test_simpleusb_handlers_use_driver_commands_and_fixed_response_shape():
    cli = RecordingCLI()
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
    cli = RecordingCLI()
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
