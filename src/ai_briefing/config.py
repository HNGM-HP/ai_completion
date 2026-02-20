import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    github_token: str | None
    feishu_app_id: str | None
    feishu_app_secret: str | None
    feishu_doc_folder_token: str | None
    feishu_push_chat_id: str | None
    feishu_event_encrypt_key: str | None
    feishu_event_verification_token: str | None
    feishu_max_chars: int
    feishu_group_by_kind: bool
    llm_provider: str
    llm_model: str | None
    glm_api_key: str | None
    glm_base_url: str | None
    glm_enable_thinking: bool
    openai_api_key: str | None
    openai_base_url: str | None
    deepseek_api_key: str | None
    deepseek_base_url: str | None
    tongyi_api_key: str | None
    tongyi_base_url: str | None
    minimax_api_key: str | None
    minimax_base_url: str | None
    google_openai_base_url: str | None
    llm_timeout_seconds: int
    llm_max_workers: int
    llm_retry_max: int
    llm_retry_backoff_seconds: int
    llm_cache_enabled: bool
    prompt_templates_file: str
    rss_sources_file: str
    rss_max_workers: int
    news_window_hours: int
    brief_dedup_hours: int
    news_backfill_max_steps: int
    news_backfill_window_multiplier: int
    news_backfill_threshold_step: int
    daily_top_news: int
    daily_top_repos: int
    hourly_top_repos: int
    branch_specs_file: str
    x_enabled: bool
    llm_task_model_report: str | None
    llm_task_model_factcheck: str | None
    llm_task_model_dedup: str | None
    llm_task_model_ranking: str | None
    llm_task_model_wechat: str | None
    feishu_doc_daily_folder: bool
    feishu_doc_date_format: str
    image_prompt_enabled: bool
    image_output_dir: str
    image_max_count: int
    image_size: str
    image_model: str | None
    google_ai_api_key: str | None
    image_docx_parent_type: str
    graphviz_font: str | None

def _get_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None

def get_settings() -> Settings:
    return Settings(
        database_url=os.environ["DATABASE_URL"],
        github_token=os.getenv("GITHUB_TOKEN"),
        feishu_app_id=os.getenv("FEISHU_APP_ID"),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET"),
        feishu_doc_folder_token=os.getenv("FEISHU_DOC_FOLDER_TOKEN"),
        feishu_push_chat_id=_get_optional_env("FEISHU_PUSH_CHAT_ID"),
        feishu_event_encrypt_key=_get_optional_env("FEISHU_EVENT_ENCRYPT_KEY"),
        feishu_event_verification_token=_get_optional_env("FEISHU_EVENT_VERIFICATION_TOKEN"),
        feishu_max_chars=int(os.getenv("FEISHU_MAX_CHARS", 3000)),
        feishu_group_by_kind=os.getenv("FEISHU_GROUP_BY_KIND", "true").lower() in ("true", "1", "yes"),
        llm_provider=os.getenv("LLM_PROVIDER", "glm"),
        llm_model=_get_optional_env("LLM_MODEL"),
        glm_api_key=os.getenv("GLM_API_KEY"),
        glm_base_url=os.getenv("GLM_BASE_URL"),
        glm_enable_thinking=os.getenv("GLM_ENABLE_THINKING", "false").lower() in ("true", "1", "yes"),
        openai_api_key=_get_optional_env("OPENAI_API_KEY"),
        openai_base_url=_get_optional_env("OPENAI_BASE_URL"),
        deepseek_api_key=_get_optional_env("DEEPSEEK_API_KEY"),
        deepseek_base_url=_get_optional_env("DEEPSEEK_BASE_URL"),
        tongyi_api_key=_get_optional_env("TONGYI_API_KEY"),
        tongyi_base_url=_get_optional_env("TONGYI_BASE_URL"),
        minimax_api_key=_get_optional_env("MINIMAX_API_KEY"),
        minimax_base_url=_get_optional_env("MINIMAX_BASE_URL"),
        google_openai_base_url=_get_optional_env("GOOGLE_OPENAI_BASE_URL"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", 60)),
        llm_max_workers=int(os.getenv("LLM_MAX_WORKERS", 1)),
        llm_retry_max=int(os.getenv("LLM_RETRY_MAX", 1)),
        llm_retry_backoff_seconds=int(os.getenv("LLM_RETRY_BACKOFF_SECONDS", 2)),
        llm_cache_enabled=os.getenv("LLM_CACHE_ENABLED", "true").lower() in ("true", "1", "yes"),
        prompt_templates_file=os.getenv("PROMPT_TEMPLATES_FILE", "/opt/ai_briefing/configs/prompt_templates.yaml"),
        rss_sources_file=os.getenv("RSS_SOURCES_FILE", "/opt/ai_briefing/configs/rss_sources.yaml"),
        rss_max_workers=int(os.getenv("RSS_MAX_WORKERS", 10)),
        news_window_hours=int(os.getenv("NEWS_WINDOW_HOURS", 72)),
        brief_dedup_hours=int(os.getenv("BRIEF_DEDUP_HOURS", 24)),
        news_backfill_max_steps=int(os.getenv("NEWS_BACKFILL_MAX_STEPS", 2)),
        news_backfill_window_multiplier=int(os.getenv("NEWS_BACKFILL_WINDOW_MULTIPLIER", 2)),
        news_backfill_threshold_step=int(os.getenv("NEWS_BACKFILL_THRESHOLD_STEP", 5)),
        daily_top_news=int(os.getenv("DAILY_TOP_NEWS", 10)),
        daily_top_repos=int(os.getenv("DAILY_TOP_REPOS", 10)),
        hourly_top_repos=int(os.getenv("HOURLY_TOP_REPOS", 5)),
        branch_specs_file=os.getenv("BRANCH_SPECS_FILE", "/opt/ai_briefing/configs/branch_specs.yaml"),
        x_enabled=os.getenv("X_ENABLED", "true").lower() in ("true", "1", "yes"),
        llm_task_model_report=_get_optional_env("LLM_TASK_MODEL_REPORT"),
        llm_task_model_factcheck=_get_optional_env("LLM_TASK_MODEL_FACTCHECK"),
        llm_task_model_dedup=_get_optional_env("LLM_TASK_MODEL_DEDUP"),
        llm_task_model_ranking=_get_optional_env("LLM_TASK_MODEL_RANKING"),
        llm_task_model_wechat=_get_optional_env("LLM_TASK_MODEL_WECHAT"),
        feishu_doc_daily_folder=os.getenv("FEISHU_DOC_DAILY_FOLDER", "false").lower() in ("true", "1", "yes"),
        feishu_doc_date_format=os.getenv("FEISHU_DOC_DATE_FORMAT", "%Y-%m-%d"),
        image_prompt_enabled=os.getenv("IMAGE_PROMPT_ENABLED", "false").lower() in ("true", "1", "yes"),
        image_output_dir=os.getenv("IMAGE_OUTPUT_DIR", "/opt/ai_briefing/images"),
        image_max_count=int(os.getenv("IMAGE_MAX_COUNT", 3)),
        image_size=os.getenv("IMAGE_SIZE", "1024x1024"),
        image_model=_get_optional_env("IMAGE_MODEL"),
        google_ai_api_key=_get_optional_env("GOOGLE_AI_API_KEY"),
        image_docx_parent_type=os.getenv("IMAGE_DOCX_PARENT_TYPE", "docx_image"),
        graphviz_font=_get_optional_env("GRAPHVIZ_FONT"),
    )
