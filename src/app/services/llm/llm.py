"""LLM access. The single place model logic lives.

Usage everywhere else in the app:

    from app.services.llm import LLM

    llm = LLM.initialize("gpt-5.6-luna")   # or LLM.initialize() for the .env default
    reply = llm.ask("...")                 # call at any point, as often as needed

Provider is inferred from the model name (claude-* → anthropic, otherwise
MODEL_PROVIDER from .env); API keys come from .env. No other module may talk
to a model SDK directly.
"""

from __future__ import annotations

from app.settings import get_settings

MAX_TOKENS = 16000


class LLM:
    def __init__(self, provider: str, model_name: str, client: object) -> None:
        self.provider = provider
        self.model_name = model_name
        self._client = client

    @classmethod
    def initialize(cls, model_name: str | None = None) -> "LLM":
        """Create a ready-to-use client for `model_name` (default: MODEL_NAME in .env)."""
        settings = get_settings()
        name = model_name or settings.model_name
        provider = "anthropic" if name.startswith("claude") else (
            "openai" if name.startswith(("gpt", "o")) else settings.model_provider
        )

        if provider == "anthropic":
            from anthropic import Anthropic

            return cls(provider, name, Anthropic(api_key=settings.anthropic_api_key))

        from openai import OpenAI

        return cls(provider, name, OpenAI(api_key=settings.openai_api_key))

    def chat_model(self):
        """A LangChain chat model for deep agents — the only place LangChain
        provider classes are imported."""
        settings = get_settings()
        if self.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=self.model_name, api_key=settings.anthropic_api_key,
                max_tokens=MAX_TOKENS, max_retries=5,
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=self.model_name, api_key=settings.openai_api_key, max_retries=5)

    def ask(self, prompt: str, system: str | None = None) -> str:
        """Send one prompt, return the model's text response."""
        if self.provider == "anthropic":
            response = self._client.messages.create(
                model=self.model_name,
                max_tokens=MAX_TOKENS,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in response.content if b.type == "text")

        response = self._client.responses.create(
            model=self.model_name,
            instructions=system,
            input=prompt,
        )
        return response.output_text
