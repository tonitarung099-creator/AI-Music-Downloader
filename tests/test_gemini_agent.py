from app.services.gemini_agent import GeminiAgent


def test_extract_json_accepts_markdown_fence():
    data = GeminiAgent._extract_json('```json\n{"intent":"download_queue"}\n```')
    assert data == {"intent": "download_queue"}


def test_response_text_joins_text_parts():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": '{"index":'},
                        {"text": " 2}"},
                    ]
                }
            }
        ]
    }
    assert GeminiAgent._response_text(payload) == '{"index": 2}'


def test_agent_available_only_needs_key():
    assert GeminiAgent([]).available is False
    assert GeminiAgent(["demo-key"]).available is True
