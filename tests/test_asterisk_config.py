Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
from asterisk_node_manager.asterisk_config import SECRET_VALUE, is_secret_key, parse_config


def test_parse_config_keeps_sections_comments_and_unparsed_lines():
    values, preserved = parse_config(
        "rpt.conf",
        "; global comment\n[general]\nbindport = 4569\n\n[1234]\nrxchannel=SimpleUSB/1234\ncustom syntax\n",
    )

    assert values == {"general": {"bindport": "4569"}, "1234": {"rxchannel": "SimpleUSB/1234"}}
    assert preserved[""] == ["; global comment"]
    assert preserved["general"] == [""]
    assert preserved["1234"] == ["custom syntax"]


def test_unknown_file_does_not_parse_key_value_lines():
    values, preserved = parse_config("outside.conf", "[x]\nkey=value\n")
    assert values == {"x": {}}
    assert preserved["x"] == ["key=value"]


def test_secret_detection_covers_password_tokens_and_credentials():
    assert is_secret_key("registerpassword")
    assert is_secret_key("api_key")
    assert is_secret_key("auth-token")
    assert not is_secret_key("callerid")
    assert SECRET_VALUE == "[hidden]"
