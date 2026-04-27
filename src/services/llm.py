from __future__ import annotations

from httpx import AsyncClient

from core.config import Settings
from core.exceptions import ConfigurationError


SYSTEM_PROMPT = (
    "Rewrite the provided text so it is better suited for expressive speech synthesis. "
    "Preserve meaning exactly, but improve punctuation, cadence, pauses, and phrasing based "
    "on the style prompt. Return only the rewritten text."
)


class LLMPreprocessor:
    def __init__(self, settings: Settings, http_client: AsyncClient):
        self.settings = settings
        self.http_client = http_client

    async def rewrite_text(self, text: str, style_prompt: str) -> str:
        if not self.settings.llm_api_url:
            raise ConfigurationError("LLM_API_URL is not configured.")

        headers = {"Accept": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        payload = {
            "model": self.settings.llm_model,
            "system_prompt": SYSTEM_PROMPT,
            "text": text,
            "style_prompt": style_prompt,
            "max_tokens": 2048,
            "temperature": 0.15,
            "top_p": 1.00,
            "frequency_penalty": 0.00,
            "presence_penalty": 0.00,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Style prompt:\n{style_prompt}\n\n"
                        f"Original text:\n{text}\n\n"
                        "Return only the rewritten text, no emojis, nor other full words or phrases that are not part of the rewritten text."
                    ),
                },
            ],
        }


        response = await self.http_client.post(
            self.settings.llm_api_url,
            json=payload,
            headers=headers,
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()

        if isinstance(body.get("rewritten_text"), str):
            rewritten_text = body["rewritten_text"].strip()
        else:
            choices = body.get("choices") or []
            rewritten_text = ""
            if choices:
                message = choices[0].get("message") or {}
                rewritten_text = str(message.get("content") or "").strip()

        if not rewritten_text:
            raise RuntimeError("LLM preprocessing returned an empty response.")
        return rewritten_text
