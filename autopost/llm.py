import logging
import time
import os

from openai import APIError, OpenAI, RateLimitError

from .config import Settings

log = logging.getLogger("autopost.llm")

PREFERRED_PREFIXES = ("deepseek", "qwen", "google/gemma", "google/gemini", "meta-llama", "mistralai")


class LLMUnavailable(Exception):
    """Все модели временно недоступны. Новость не помечаем как ошибочную."""


class LLMClient:
    def __init__(self, s: Settings):
        self._fallbacks: list[str] | None = None
        self.provider = s.ai_provider
        # max_retries=0: повторами управляем сами, иначе SDK делает скрытые запросы.
        if s.ai_provider == "openrouter":
            self.client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=s.openrouter_key,
                default_headers={"X-Title": "pop-culture-autopost"},
                max_retries=0,
            )
            self.primary = s.openrouter_model
        elif s.ai_provider == "groq":
            self.client = OpenAI(base_url="https://api.groq.com/openai/v1",
                                 api_key=s.groq_key, max_retries=0)
            self.primary = s.groq_model
        elif s.ai_provider == "ollama":
            self.client = OpenAI(base_url=s.ollama_url, api_key="ollama", max_retries=0)
            self.primary = s.ollama_model
        elif s.ai_provider == "custom":
            self.client = OpenAI(
                base_url=os.getenv("CUSTOM_BASE_URL", ""),
                api_key=os.getenv("CUSTOM_API_KEY", ""),
                max_retries=0,
            )
            self.primary = os.getenv("CUSTOM_MODEL", "")
        else:
            raise ValueError(f"неизвестный AI_PROVIDER: {s.ai_provider}")

    def _discover_free_models(self) -> list[str]:
        """Для OpenRouter берёт доступные :free модели из /models как фолбэк."""
        if self.provider != "openrouter":
            return []
        try:
            ids = [m.id for m in self.client.models.list().data if m.id.endswith(":free")]
        except Exception as e:
            log.warning("не удалось получить список моделей: %s", e)
            return []
        ids = [i for i in ids if i != self.primary]
        ids.sort(key=lambda i: (0 if i.startswith(PREFERRED_PREFIXES) else 1, i))
        return ids

    def complete(self, system: str, user: str) -> str:
        if self._fallbacks is None:
            self._fallbacks = self._discover_free_models()[:6]

        for model in [self.primary, *self._fallbacks]:
            for attempt in range(2):
                try:
                    r = self.client.chat.completions.create(
                        model=model,
                        temperature=0.3,
                        max_tokens=800,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": user}],
                    )
                    text = (r.choices[0].message.content or "").strip()
                    if text:
                        return text
                    log.warning("%s вернула пустой ответ", model)
                    break
                except RateLimitError:
                    log.warning("%s: 429, перехожу к следующей модели", model)
                    break
                except APIError as e:
                    status = getattr(e, "status_code", None)
                    if status and 400 <= status < 500:
                        log.warning("%s: ошибка %s, пропускаю модель: %s", model, status, e)
                        break
                    log.warning("%s: ошибка API: %s", model, e)
                    time.sleep(2 ** attempt)
        raise LLMUnavailable("все модели недоступны")