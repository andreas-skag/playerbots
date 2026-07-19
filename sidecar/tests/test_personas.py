from brain.memory import MemoryStore
from brain.personas import generate_card, get_persona, is_inner_circle
from brain.request_parser import BotRequest
from brain.settings import Settings


def req(channel="in world chat", bot_name="Grimtok"):
    return BotRequest(system="", speaker_name="Andreas", message="hi",
                      bot_guid=42, bot_name=bot_name, other_guid=7,
                      other_name="Andreas", channel=channel, event="chat")


def test_card_is_deterministic_and_varied():
    assert generate_card(42, "Grimtok") == generate_card(42, "Grimtok")
    # different guids must not all collapse to one card
    assert any(generate_card(42, "Grimtok") != generate_card(g, "Elaria")
               for g in range(43, 48))
    card = generate_card(42, "Grimtok")
    assert "Personality:" in card and "Speech:" in card


def test_zero_guid_falls_back_to_name():
    assert generate_card(0, "Grimtok") == generate_card(0, "Grimtok")
    assert any(generate_card(0, "Grimtok") != generate_card(0, n)
               for n in ("Elaria", "Baldrek", "Miravelle"))


def test_get_persona_caches_in_store():
    store = MemoryStore(":memory:")
    card = get_persona(store, 42, "Grimtok")
    assert store.get_persona(42) == card
    store.set_persona(42, "hand-written card")
    assert get_persona(store, 42, "Grimtok") == "hand-written card"


def test_inner_circle_by_channel_and_list():
    s = Settings()
    assert is_inner_circle(req(channel="in party chat"), s)
    assert is_inner_circle(req(channel="in guild chat"), s)
    assert is_inner_circle(req(channel="in private message"), s)
    assert not is_inner_circle(req(channel="in world chat"), s)
    s2 = Settings(inner_circle=["Grimtok"])
    assert is_inner_circle(req(channel="in world chat", bot_name="Grimtok"), s2)
