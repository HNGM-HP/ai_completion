from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


def _check_required_keys() -> list[str]:
    missing: list[str] = []
    for key in [
        "DATABASE_URL",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_PUSH_CHAT_ID",
        "FEISHU_DOC_FOLDER_TOKEN",
    ]:
        if not os.getenv(key):
            missing.append(key)
    return missing


def _check_bool_env(key: str, default: str) -> None:
    raw = os.getenv(key, default)
    if raw is None:
        return
    if raw.lower() not in ("true", "false", "1", "0", "yes", "no"):
        raise ValueError(f"{key} 不是合法布尔值")


def _check_int_env(key: str, default: str) -> None:
    raw = os.getenv(key, default)
    if raw is None:
        return
    try:
        int(raw)
    except ValueError as e:
        raise ValueError(f"{key} 不是合法整数") from e


def _check_path_env(key: str, default: str) -> None:
    raw = os.getenv(key, default)
    if not raw:
        return
    p = Path(raw)
    if not p.exists():
        raise FileNotFoundError(f"{key} 指向的文件不存在: {p}")


def _ensure_dir_env(key: str, default: str) -> None:
    raw = os.getenv(key, default)
    if not raw:
        return
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)


def _check_database_url() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL 缺失")
    parsed = urlparse(database_url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL scheme 必须是 postgres/postgresql")
    if not parsed.hostname or not parsed.path:
        raise ValueError("DATABASE_URL 解析失败（缺少 host 或 dbname）")


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


def _parse_model_spec(raw: str, default_provider: str) -> tuple[str, str]:
    value = raw.strip()
    if not value:
        raise ValueError("模型配置为空")
    if ":" in value:
        provider, model = value.split(":", 1)
        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ValueError(f"模型配置格式不正确: {raw}")
        return _normalize_provider_name(provider), model
    return _normalize_provider_name(default_provider), value


def _collect_model_specs(default_provider: str) -> list[str]:
    specs: list[str] = []
    for key in [
        "LLM_TASK_MODEL_REPORT",
        "LLM_TASK_MODEL_FACTCHECK",
        "LLM_TASK_MODEL_DEDUP",
        "LLM_TASK_MODEL_RANKING",
        "LLM_TASK_MODEL_WECHAT",
    ]:
        value = os.getenv(key)
        if value:
            specs.append(value)
    llm_model = os.getenv("LLM_MODEL")
    if llm_model:
        specs.append(llm_model)
    return specs


def _check_llm_providers() -> None:
    default_provider = os.getenv("LLM_PROVIDER", "glm").strip() or "glm"
    model_specs = _collect_model_specs(default_provider)

    if not model_specs:
        raise SystemExit("LLM_MODEL 或 LLM_TASK_MODEL_* 缺失")

    used_providers: set[str] = set()
    for spec in model_specs:
        provider, model = _parse_model_spec(spec, default_provider)
        if not model:
            raise SystemExit(f"模型配置缺少 model: {spec}")
        used_providers.add(provider)

    if "glm" in used_providers:
        if not os.getenv("GLM_API_KEY") or not os.getenv("GLM_BASE_URL"):
            raise SystemExit("GLM_API_KEY/GLM_BASE_URL 缺失")

    if "openai" in used_providers and not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY 缺失")
    if "deepseek" in used_providers and not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY 缺失")
    if "tongyi" in used_providers and not os.getenv("TONGYI_API_KEY"):
        raise SystemExit("TONGYI_API_KEY 缺失")
    if "minimax" in used_providers and not os.getenv("MINIMAX_API_KEY"):
        raise SystemExit("MINIMAX_API_KEY 缺失")
    if "google" in used_providers and not os.getenv("GOOGLE_AI_API_KEY"):
        raise SystemExit("GOOGLE_AI_API_KEY 缺失")


def main() -> None:
    """环境变量自检。

    注意：不打印任何密钥/连接串明文，仅输出通过/失败信息。
    """

    load_dotenv("/opt/ai_briefing/.env")

    missing = _check_required_keys()
    if missing:
        raise SystemExit(f"缺少必填环境变量: {', '.join(missing)}")

    _check_database_url()

    _check_int_env("LLM_TIMEOUT_SECONDS", "60")
    _check_int_env("LLM_MAX_WORKERS", "1")
    _check_int_env("LLM_RETRY_MAX", "1")
    _check_int_env("LLM_RETRY_BACKOFF_SECONDS", "2")

    _check_bool_env("LLM_CACHE_ENABLED", "true")
    _check_bool_env("FEISHU_GROUP_BY_KIND", "true")
    _check_bool_env("GLM_ENABLE_THINKING", "false")
    _check_bool_env("X_ENABLED", "true")

    _check_llm_providers()

    _check_path_env("RSS_SOURCES_FILE", "/opt/ai_briefing/configs/rss_sources.yaml")
    _check_path_env("PROMPT_TEMPLATES_FILE", "/opt/ai_briefing/configs/prompt_templates.yaml")
    _check_path_env("BRANCH_SPECS_FILE", "/opt/ai_briefing/configs/branch_specs.yaml")
    _ensure_dir_env("IMAGE_OUTPUT_DIR", "/opt/ai_briefing/images")

    image_model = os.getenv("IMAGE_MODEL", "").strip().lower()
    if image_model.startswith("google:") and not os.getenv("GOOGLE_AI_API_KEY"):
        raise SystemExit("IMAGE_MODEL 使用 google 时必须配置 GOOGLE_AI_API_KEY")

    print("ENV OK")


if __name__ == "__main__":
    main()
