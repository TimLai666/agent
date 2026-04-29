from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from internal.conversation_history import ConversationHistoryStore


def test_conversation_history_persists_turns_and_messages(tmp_path):
    store = ConversationHistoryStore(tmp_path)
    messages = [
        ModelRequest(parts=[UserPromptPart(content="hello")]),
        ModelResponse(parts=[TextPart(content="hi there")], model_name="test"),
    ]

    store.append_turn(
        session_id="session-1",
        user_text="hello",
        assistant_text="hi there",
        messages=messages,
        timestamp="2026-04-29T10:00:00+00:00",
    )

    sessions = store.list_sessions()
    assert [item.session_id for item in sessions] == ["session-1"]
    assert sessions[0].turn_count == 1
    assert store.load_display_history("session-1") == [("hello", "hi there")]

    loaded = store.load_message_history("session-1")
    assert len(loaded) == 2
    assert isinstance(loaded[0], ModelRequest)
    assert isinstance(loaded[1], ModelResponse)


def test_conversation_history_search_scopes(tmp_path):
    store = ConversationHistoryStore(tmp_path)
    store.append_turn(
        session_id="current",
        user_text="find alpha here",
        assistant_text="ok",
        timestamp="2026-04-29T10:00:00+00:00",
    )
    store.append_turn(
        session_id="old",
        user_text="beta",
        assistant_text="alpha in assistant reply",
        timestamp="2026-04-29T10:01:00+00:00",
    )

    current = store.search("alpha", scope="current", current_session_id="current")
    assert [item["session_id"] for item in current] == ["current"]

    specific = store.search("alpha", scope="session", session_id="old")
    assert [item["session_id"] for item in specific] == ["old"]

    all_results = store.search("alpha", scope="all")
    assert {item["session_id"] for item in all_results} == {"current", "old"}
