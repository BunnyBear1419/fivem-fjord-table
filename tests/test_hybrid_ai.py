import asyncio

import hybrid_ai


def test_hybrid_ai_is_optional_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert hybrid_ai.is_configured() is False
    assert asyncio.run(hybrid_ai.answer_question(1, 2, "where is that?")) is None


def test_hybrid_ai_keeps_short_lived_context_per_member(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    hybrid_ai._sessions.clear()
    calls = []

    def fake_completion(messages):
        calls.append(messages)
        return "It is at Postal 3009."

    monkeypatch.setattr(hybrid_ai, "_request_completion", fake_completion)
    first = asyncio.run(hybrid_ai.answer_question(10, 20, "Where is the doctor?", "Blackmarket Doctor — Postal 3009"))
    second = asyncio.run(hybrid_ai.answer_question(10, 20, "Where is that?"))

    assert first == "It is at Postal 3009."
    assert second == "It is at Postal 3009."
    assert any(message["content"] == "Where is the doctor?" for message in calls[1])
    assert any(message["content"] == "It is at Postal 3009." for message in calls[1])
    assert "Do not provide actionable chemical synthesis" in calls[0][0]["content"]
    assert len(hybrid_ai._sessions[( "10", "20")]["messages"]) <= hybrid_ai.MAX_HISTORY_MESSAGES
