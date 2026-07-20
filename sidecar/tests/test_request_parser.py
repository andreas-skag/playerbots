from brain.request_parser import parse_request


def full_body():
    return {
        "model": "brain",
        "messages": [
            {"role": "system", "content": "You are Grimtok, an orc warrior."},
            {"role": "user", "content": "Andreas:hey, ready for Deadmines?"},
        ],
        "max_tokens": 120,
        "meta": {
            "bot_guid": "42",
            "other_guid": "7",
            "bot_name": "Grimtok",
            "other_name": "Andreas",
            "channel": "in party chat",
            "event": "chat",
        },
    }


def test_parses_full_m2_body():
    req = parse_request(full_body())
    assert req.bot_guid == 42
    assert req.other_guid == 7
    assert req.bot_name == "Grimtok"
    assert req.other_name == "Andreas"
    assert req.channel == "in party chat"
    assert req.event == "chat"
    assert req.speaker_name == "Andreas"
    assert req.message == "hey, ready for Deadmines?"
    assert "orc warrior" in req.system


def test_message_may_contain_colons():
    body = full_body()
    body["messages"][1]["content"] = "Andreas:meet at 10:30, ok?"
    req = parse_request(body)
    assert req.message == "meet at 10:30, ok?"


def test_tolerates_missing_meta():
    body = full_body()
    del body["meta"]
    req = parse_request(body)
    assert req.bot_guid == 0
    assert req.other_guid == 0
    assert req.speaker_name == "Andreas"
    assert req.event == "chat"


def test_tolerates_junk_guid():
    body = full_body()
    body["meta"]["bot_guid"] = "<bot guid>"  # unsubstituted placeholder
    req = parse_request(body)
    assert req.bot_guid == 0


def test_unsubstituted_placeholder_meta_treated_as_absent():
    body = full_body()
    body["meta"]["other_name"] = "<other name>"
    body["meta"]["channel"] = "<channel name>"
    req = parse_request(body)
    assert req.other_name == "Andreas"  # falls back to speaker from user content
    assert req.speaker_name == "Andreas"
    assert req.channel == ""


def test_null_meta_values_do_not_break_types():
    body = full_body()
    body["meta"]["bot_name"] = None
    body["meta"]["event"] = None
    req = parse_request(body)
    assert req.bot_name == ""
    assert req.event == "chat"
