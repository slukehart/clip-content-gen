"""Provider-agnostic OpenAI-compatible chat client for Pipeline B (Stage B3).

Talks to any OpenAI-compatible `/chat/completions` endpoint via plain `httpx` --
no vendor SDK (small-footprint principle: point `llm_base_url`/`llm_model` at
OpenRouter, a self-hosted Kimi/DeepSeek endpoint, or a local server by config
alone). `FakeLLMClient` is the test double used everywhere real network calls
would be inappropriate (CI, unit tests).
"""
import json

import httpx
import structlog

log = structlog.get_logger()


class LLMError(Exception):
    """Raised on any failure to obtain a usable chat response."""


class LLMClient:
    """Thin client for an OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str,
                 timeout_s: int = 60, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    def _post(self, system: str, user: str, response_format: dict | None) -> dict:
        if not self._api_key:
            raise LLMError("LLMClient called with no api_key configured")

        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        client = self._client or httpx.Client(timeout=self._timeout_s)
        try:
            try:
                resp = client.post(f"{self._base_url}/chat/completions",
                                    json=payload, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"HTTP error calling LLM endpoint: {e}") from e

            if resp.status_code != 200:
                raise LLMError(f"LLM endpoint returned {resp.status_code}: {resp.text}")

            try:
                data = resp.json()
            except ValueError as e:
                raise LLMError(f"LLM response was not valid JSON: {e}") from e

            choices = data.get("choices")
            if not choices:
                raise LLMError("LLM response had no 'choices'")

            return choices[0]["message"]["content"]
        finally:
            if self._owns_client:
                client.close()

    def chat_json(self, system: str, user: str) -> dict:
        content = self._post(system, user, response_format={"type": "json_object"})
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM response content was not valid JSON: {e}") from e

    def chat_text(self, system: str, user: str) -> str:
        return self._post(system, user, response_format=None)


class FakeLLMClient:
    """Test double: same interface as `LLMClient`, returns canned values."""

    def __init__(self, json_result: dict | None = None, text_result: str | None = None):
        self._json_result = json_result
        self._text_result = text_result

    def chat_json(self, system: str, user: str) -> dict:
        return self._json_result

    def chat_text(self, system: str, user: str) -> str:
        return self._text_result
