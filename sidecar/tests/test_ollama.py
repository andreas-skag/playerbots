from brain.ollama import pick_model
from brain.settings import Settings


def test_pick_model_routes_by_tier():
    s = Settings(chat_model="big", utility_model="small")
    assert pick_model(s, "inner") == "big"
    assert pick_model(s, "ambient") == "small"
    assert pick_model(s, "utility") == "small"
