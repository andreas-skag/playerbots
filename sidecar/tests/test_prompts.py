from brain.prompts import assemble, describe_sentiment
from brain.request_parser import BotRequest


def req():
    return BotRequest(system="You are Grimtok in Westfall.", speaker_name="Andreas",
                      message="ready for Deadmines?", bot_guid=42, bot_name="Grimtok",
                      other_guid=7, other_name="Andreas", channel="in party chat",
                      event="chat")


def test_describe_sentiment_bands():
    assert describe_sentiment(80) == "a close friend"
    assert describe_sentiment(30) == "a friend"
    assert describe_sentiment(10) == "a friendly acquaintance"
    assert describe_sentiment(0) == "a stranger"
    assert describe_sentiment(-10) == "someone you are wary of"
    assert describe_sentiment(-50) == "someone you dislike"
    # exact band edges
    assert describe_sentiment(60) == "a close friend"
    assert describe_sentiment(25) == "a friend"
    assert describe_sentiment(5) == "a friendly acquaintance"
    assert describe_sentiment(-5) == "someone you are wary of"
    assert describe_sentiment(-25) == "someone you dislike"


def test_assemble_builds_system_and_user(tmp_path):
    tpl = tmp_path / "chat.txt"
    tpl.write_text("{game_system}|{persona}|{relationship}|{summary}|{history}|{bot_name}|{other_name}")
    msgs = assemble(tmp_path, "gruff veteran", "Ran Deadmines once.", 30,
                    [("hi", "Hrm."), ("ready?", "Aye.")], req())
    assert msgs[0]["role"] == "system"
    sys = msgs[0]["content"]
    assert "You are Grimtok in Westfall." in sys
    assert "gruff veteran" in sys
    assert "a friend" in sys
    assert "Ran Deadmines once." in sys
    assert "Andreas: hi" in sys and "Grimtok: Hrm." in sys
    assert msgs[1] == {"role": "user", "content": "Andreas: ready for Deadmines?"}


def test_assemble_handles_empty_memory(tmp_path):
    tpl = tmp_path / "chat.txt"
    tpl.write_text("{summary}|{history}")
    msgs = assemble(tmp_path, "p", "", 0, [], req())
    assert "no shared history yet" in msgs[0]["content"]
    assert "(none)" in msgs[0]["content"]
