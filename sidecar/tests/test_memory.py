from brain.memory import MemoryStore


def make_store():
    return MemoryStore(":memory:")


def test_record_and_recent_ordering():
    s = make_store()
    s.record_interaction(42, 7, "Andreas", "in party chat", "hi", "Hrm. Whelp.")
    s.record_interaction(42, 7, "Andreas", "in party chat", "ready?", "Aye.")
    assert s.recent(42, 7) == [("hi", "Hrm. Whelp."), ("ready?", "Aye.")]
    assert s.recent(42, 99) == []  # other pair untouched


def test_recent_respects_limit():
    s = make_store()
    for i in range(10):
        s.record_interaction(42, 7, "Andreas", "say", f"m{i}", f"r{i}")
    got = s.recent(42, 7, limit=3)
    assert got == [("m7", "r7"), ("m8", "r8"), ("m9", "r9")]


def test_sentiment_defaults_zero_and_clamps():
    s = make_store()
    assert s.sentiment(42, 7) == 0
    assert s.adjust_sentiment(42, 7, 5) == 5
    assert s.adjust_sentiment(42, 7, 1000) == 100
    assert s.adjust_sentiment(42, 7, -1000) == -100


def test_summary_roundtrip_and_unsummarized():
    s = make_store()
    i1 = s.record_interaction(42, 7, "Andreas", "say", "a", "b")
    i2 = s.record_interaction(42, 7, "Andreas", "say", "c", "d")
    assert s.summary(42, 7) == ("", 0)
    assert [r[0] for r in s.unsummarized(42, 7)] == [i1, i2]
    s.set_summary(42, 7, "They ran Deadmines together.", i1)
    assert s.summary(42, 7) == ("They ran Deadmines together.", i1)
    assert [r[0] for r in s.unsummarized(42, 7)] == [i2]


def test_persona_roundtrip():
    s = make_store()
    assert s.get_persona(42) is None
    s.set_persona(42, "gruff veteran")
    assert s.get_persona(42) == "gruff veteran"
