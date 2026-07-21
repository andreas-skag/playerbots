from brain.request_parser import GroupMember, parse_request


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


def _body_with_group(group):
    return {
        "messages": [{"role": "user", "content": "Andreas:can you tank?"}],
        "meta": {"bot_guid": "42", "bot_name": "Grimtok", "other_guid": "7",
                 "other_name": "Andreas", "channel": "in party chat",
                 "event": "chat", "group": group},
    }


def test_group_roster_parsed():
    # The real producer sends lowercase class names, but the parser must not
    # normalize case — it stores whatever arrives verbatim. Class-name
    # comparisons are case-insensitive downstream (brain/commands.py), so we
    # deliberately mix case here to prove the parser passes it through as-is.
    req = parse_request(_body_with_group(
        "Andreas:7:Paladin:60;Grimtok:42:warrior:60;Zinnia:43:priest:58"))
    assert req.group == [
        GroupMember(name="Andreas", guid=7, cls="Paladin", level=60),
        GroupMember(name="Grimtok", guid=42, cls="warrior", level=60),
        GroupMember(name="Zinnia", guid=43, cls="priest", level=58),
    ]


def test_group_missing_or_placeholder_is_empty():
    assert parse_request(_body_with_group("")).group == []
    assert parse_request(_body_with_group("<group>")).group == []
    body = _body_with_group("x")
    del body["meta"]["group"]
    assert parse_request(body).group == []


def test_group_malformed_entries_skipped():
    req = parse_request(_body_with_group("Broken;Andreas:7:paladin:60;A:B:C:D"))
    assert req.group == [GroupMember(name="Andreas", guid=7, cls="paladin", level=60)]
