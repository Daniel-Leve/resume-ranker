"""
Phase 4 LLM Client Interface and Groq Implementation.
Supports pluggable providers, structured JSON output, exponential backoff, and Retry-After handling.
"""
from __future__ import annotations

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

from phase4 import config

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    parsed_json: Optional[Dict[str, Any]] = None


class LLMClient(ABC):
    """Abstract interface for LLM completions."""

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Execute a chat completion request."""
        pass

    def complete_structured(
        self,
        messages: List[Dict[str, str]],
        schema_class: Type[T],
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Tuple[T, LLMResponse]:
        """
        Execute completion with JSON mode, validate with Pydantic,
        and retry once with error feedback if schema validation fails.
        """
        resp = self.complete(messages, json_mode=True, temperature=temperature, model=model)
        try:
            parsed = json.loads(resp.content)
            validated = schema_class.model_validate(parsed)
            return validated, resp
        except (json.JSONDecodeError, ValidationError) as err:
            logger.warning("Pydantic validation failed on LLM response (%s). Retrying with error feedback...", err)
            retry_messages = list(messages)
            retry_messages.append({"role": "assistant", "content": resp.content})
            retry_messages.append({
                "role": "user",
                "content": f"Your previous output failed validation: {err}. Please re-output strictly valid JSON conforming to the requested schema."
            })
            retry_resp = self.complete(retry_messages, json_mode=True, temperature=temperature, model=model)
            # Accumulate tokens
            retry_resp.prompt_tokens += resp.prompt_tokens
            retry_resp.completion_tokens += resp.completion_tokens
            retry_resp.total_tokens += resp.total_tokens
            parsed = json.loads(retry_resp.content)
            validated = schema_class.model_validate(parsed)
            return validated, retry_resp


class GroqClient(LLMClient):
    """Production Groq LLM client with rate limiting, retry-after, and exponential backoff."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 5,
        base_backoff_sec: float = 2.0,
    ) -> None:
        self.api_key = api_key or config.GROQ_API_KEY
        self.default_model = model or config.GROQ_MODEL
        self.max_retries = max_retries
        self.base_backoff_sec = base_backoff_sec
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                try:
                    from api.auth.secrets import get_groq_api_key
                    self.api_key = get_groq_api_key()
                except Exception:
                    pass
            if not self.api_key:
                raise ValueError("GROQ_API_KEY environment variable is not set. Please configure your API key.")
            from groq import Groq
            self._client = Groq(api_key=self.api_key)
        return self._client

    def complete(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> LLMResponse:
        client = self._get_client()
        target_model = model or self.default_model

        kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        attempt = 0
        while True:
            try:
                chat_completion = client.chat.completions.create(**kwargs)
                choice = chat_completion.choices[0]
                content = choice.message.content or "{}"
                usage = getattr(chat_completion, "usage", None)

                prompt_tokens = usage.prompt_tokens if usage else 0
                completion_tokens = usage.completion_tokens if usage else 0
                total_tokens = usage.total_tokens if usage else (prompt_tokens + completion_tokens)

                return LLMResponse(
                    content=content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    model=target_model,
                )

            except Exception as exc:
                err_str = str(exc)
                if "model_not_found" in err_str or "does not exist or you do not have access" in err_str:
                    fallback_models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
                    switched = False
                    for fb in fallback_models:
                        if fb != kwargs.get("model"):
                            logger.warning("Model %s unavailable on Groq, switching to fallback model %s", kwargs.get("model"), fb)
                            kwargs["model"] = fb
                            target_model = fb
                            switched = True
                            break
                    if switched:
                        continue

                attempt += 1
                if attempt > self.max_retries:
                    logger.error("Groq request failed after %d attempts: %s", attempt, exc)
                    raise

                retry_after_sec = None
                # Check for rate limit retry-after in headers or message
                if hasattr(exc, "response") and exc.response is not None:
                    retry_header = exc.response.headers.get("retry-after")
                    if retry_header:
                        try:
                            retry_after_sec = float(retry_header)
                        except (ValueError, TypeError):
                            pass

                if retry_after_sec is None:
                    # Exponential backoff with jitter
                    retry_after_sec = (self.base_backoff_sec * (2 ** (attempt - 1))) + random.uniform(0.1, 1.0)

                logger.warning(
                    "Groq API error on attempt %d/%d (%s). Backing off for %.2fs...",
                    attempt, self.max_retries, exc, retry_after_sec
                )
                time.sleep(retry_after_sec)


class MockLLMClient(LLMClient):
    """Deterministic Mock LLM client for testing without external API calls."""

    def __init__(self, canned_responses: Optional[List[str]] = None) -> None:
        self.canned_responses = list(canned_responses) if canned_responses else []
        self.call_count = 0
        self.last_messages: List[Dict[str, str]] = []

    def complete(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages

        if self.canned_responses:
            content = self.canned_responses.pop(0)
        else:
            content = json.dumps({"status": "mock_response", "count": self.call_count})

        # Rough token estimation for test simulation
        prompt_tokens = sum(len(m.get("content", "")) // 4 for m in messages)
        completion_tokens = len(content) // 4

        return LLMResponse(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model or "mock-model",
        )
