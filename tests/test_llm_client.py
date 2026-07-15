import httpx
from clipscore.factory.llm import LLMClient, LLMError, FakeLLMClient


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_chat_json_posts_and_parses():
    seen = {}

    def h(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        import json as _j
        seen["body"] = _j.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}]})

    c = LLMClient("https://x.test/v1", "some/model", "KEY", client=_mock(h))
    assert c.chat_json("sys", "usr") == {"a": 1}
    assert seen["url"] == "https://x.test/v1/chat/completions"
    assert seen["auth"] == "Bearer KEY"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "some/model"


def test_chat_text_returns_content():
    def h(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    assert LLMClient("https://x.test/v1", "m", "K", client=_mock(h)).chat_text("s", "u") == "hello"


def test_non_200_raises_llmerror():
    def h(req):
        return httpx.Response(500, text="boom")

    import pytest
    with pytest.raises(LLMError):
        LLMClient("https://x.test/v1", "m", "K", client=_mock(h)).chat_text("s", "u")


def test_missing_key_raises():
    import pytest
    with pytest.raises(LLMError):
        LLMClient("https://x.test/v1", "m", "", client=_mock(lambda r: httpx.Response(200))).chat_text("s", "u")


def test_malformed_but_200_raises_llmerror():
    import pytest
    for body in ({"choices": []}, {"choices": [{}]}, {"choices": [{"message": {}}]}):
        def h(req, _b=body):
            return httpx.Response(200, json=_b)
        with pytest.raises(LLMError):
            LLMClient("https://x.test/v1", "m", "K", client=_mock(h)).chat_text("s", "u")


def test_fake_client_returns_canned():
    assert FakeLLMClient(json_result={"k": "v"}).chat_json("s", "u") == {"k": "v"}
    assert FakeLLMClient(text_result="cap").chat_text("s", "u") == "cap"
