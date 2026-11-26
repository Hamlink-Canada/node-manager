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


def test_parser_preserves_repeated_directives_inherited_headers_and_inline_comments():
    values, preserved = parse_config(
        "extensions.conf",
        "[internal](base)\nexten => 100,1,Answer()\nsame => n,Hangup()\n",
    )
    assert "internal(base)" in values
    assert values["internal(base)"] == {}
    assert preserved["internal(base)"] == ["exten => 100,1,Answer()", "same => n,Hangup()"]

    rpt, lines = parse_config("rpt.conf", "[1234]\nhangtime = 2000 ; squelch tail\n")
    assert rpt["1234"]["hangtime"] == "2000"
    assert lines["1234"] == ["; squelch tail"]

    iax, directives = parse_config("iax.conf", "[general]\nregister => user:one@host\nregister => user:two@host\n")
    assert iax["general"] == {}
    assert directives["general"] == ["register => user:one@host", "register => user:two@host"]
