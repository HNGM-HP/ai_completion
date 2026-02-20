from abc import ABC, abstractmethod
import time
from abc import ABC, abstractmethod

import requests

from ..config import Settings

promptCache: dict[str, str] = {}

class LLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        ...

class GLMProvider(LLM):
    def __init__(self, settings: Settings, model_override: str | None = None):
        self.settings = settings
        self.key = settings.glm_api_key
        self.base = settings.glm_base_url.rstrip("/") if settings.glm_base_url else None
        self.model = model_override

    def generate(self, prompt: str) -> str:
        if not self.key or not self.base or not self.model:
            raise RuntimeError("GLM config missing.")
            
        url = f"{self.base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2, # 低温度偏向事实输出
        }
        
        # 按配置开启 Thinking 模式（适用于部分模型）
        if self.settings.glm_enable_thinking:
            payload["thinking"] = {"type": "enabled"}
        
        cache_key = f"glm::{self.model}::{prompt}"
        if self.settings.llm_cache_enabled and cache_key in promptCache:
            return promptCache[cache_key]

        retryMax = max(0, self.settings.llm_retry_max)
        backoffSeconds = max(1, self.settings.llm_retry_backoff_seconds)
        lastError = None

        for attempt in range(retryMax + 1):
            r = None
            try:
                # 使用可配置超时，避免卡住
                r = requests.post(url, json=payload, headers=headers, timeout=self.settings.llm_timeout_seconds)
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if self.settings.llm_cache_enabled:
                    promptCache[cache_key] = content
                return content
            except Exception as e:
                lastError = e
                print(f"GLM API Error: {e}")
                if r is not None:
                    print(f"Response Body: {r.text}")
                if attempt < retryMax:
                    time.sleep(backoffSeconds * (2 ** attempt))

        if lastError:
            raise lastError
        raise RuntimeError("LLM request failed")


class OpenAICompatibleProvider(LLM):
    def __init__(
        self,
        settings: Settings,
        model: str,
        api_key: str | None,
        base_url: str | None,
        provider_name: str,
    ):
        self.settings = settings
        self.model = model
        self.api_key = api_key
        self.base = base_url.rstrip("/") if base_url else None
        self.provider_name = provider_name

    def generate(self, prompt: str) -> str:
        if not self.api_key or not self.base or not self.model:
            raise RuntimeError(f"{self.provider_name} config missing.")

        url = f"{self.base}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }

        cache_key = f"{self.provider_name}::{self.model}::{prompt}"
        if self.settings.llm_cache_enabled and cache_key in promptCache:
            return promptCache[cache_key]

        retryMax = max(0, self.settings.llm_retry_max)
        backoffSeconds = max(1, self.settings.llm_retry_backoff_seconds)
        lastError = None

        for attempt in range(retryMax + 1):
            r = None
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=self.settings.llm_timeout_seconds)
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if self.settings.llm_cache_enabled:
                    promptCache[cache_key] = content
                return content
            except Exception as e:
                lastError = e
                print(f"{self.provider_name} API Error: {e}")
                if r is not None:
                    print(f"Response Body: {r.text}")
                if attempt < retryMax:
                    time.sleep(backoffSeconds * (2 ** attempt))

        if lastError:
            raise lastError
        raise RuntimeError("LLM request failed")

def _get_task_model(settings: Settings, task_type: str) -> str | None:
    if task_type == "report":
        return settings.llm_task_model_report
    if task_type == "factcheck":
        return settings.llm_task_model_factcheck
    if task_type == "dedup":
        return settings.llm_task_model_dedup
    if task_type == "ranking":
        return settings.llm_task_model_ranking
    if task_type == "wechat":
        return settings.llm_task_model_wechat
    return None


def _normalize_provider_name(provider: str) -> str:
    normalized = provider.strip().lower()
    aliases = {
        "zhipu": "glm",
        "glm": "glm",
        "openai": "openai",
        "deepseek": "deepseek",
        "tongyi": "tongyi",
        "qwen": "tongyi",
        "dashscope": "tongyi",
        "aliyun": "tongyi",
        "minimax": "minimax",
        "minimaxi": "minimax",
        "google": "google",
        "gemini": "google",
    }
    return aliases.get(normalized, normalized)


def parse_model_spec(model_spec: str, default_provider: str) -> tuple[str, str]:
    raw = model_spec.strip()
    if ":" in raw:
        provider, model = raw.split(":", 1)
        provider = provider.strip()
        model = model.strip()
        if provider and model:
            return _normalize_provider_name(provider), model
    return _normalize_provider_name(default_provider), raw


def _resolve_model_spec(settings: Settings, task_type: str) -> str | None:
    task_model = _get_task_model(settings, task_type)
    if task_model:
        return task_model
    if settings.llm_model:
        return settings.llm_model
    return None


def _create_openai_provider(settings: Settings, provider: str, model: str) -> LLM:
    if provider == "openai":
        return OpenAICompatibleProvider(
            settings,
            model,
            settings.openai_api_key,
            settings.openai_base_url or "https://api.openai.com/v1",
            "openai",
        )
    if provider == "deepseek":
        return OpenAICompatibleProvider(
            settings,
            model,
            settings.deepseek_api_key,
            settings.deepseek_base_url or "https://api.deepseek.com",
            "deepseek",
        )
    if provider == "tongyi":
        return OpenAICompatibleProvider(
            settings,
            model,
            settings.tongyi_api_key,
            settings.tongyi_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "tongyi",
        )
    if provider == "minimax":
        return OpenAICompatibleProvider(
            settings,
            model,
            settings.minimax_api_key,
            settings.minimax_base_url or "https://api.minimax.io/v1",
            "minimax",
        )
    if provider == "google":
        return OpenAICompatibleProvider(
            settings,
            model,
            settings.google_ai_api_key,
            settings.google_openai_base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
            "google",
        )
    raise ValueError(f"Unknown LLM provider: {provider}")


def get_llm_for_model_spec(settings: Settings, model_spec: str, default_provider: str | None = None) -> LLM:
    provider = default_provider or settings.llm_provider
    provider_name, model = parse_model_spec(model_spec, provider)
    if not model:
        raise RuntimeError("LLM model missing.")
    if provider_name == "glm":
        return GLMProvider(settings, model_override=model)
    return _create_openai_provider(settings, provider_name, model)


def get_llm(settings: Settings, task_type: str = "report") -> LLM:
    model_spec = _resolve_model_spec(settings, task_type)
    if not model_spec:
        raise RuntimeError("LLM model missing.")
    return get_llm_for_model_spec(settings, model_spec)
