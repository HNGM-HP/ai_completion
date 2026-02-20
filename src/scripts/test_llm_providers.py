import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from ai_briefing.config import get_settings
from ai_briefing.briefing.llm import get_llm_for_model_spec, parse_model_spec


def _collect_model_specs(settings) -> list[str]:
    specs: list[str] = []
    for spec in [
        settings.llm_task_model_report,
        settings.llm_task_model_factcheck,
        settings.llm_task_model_dedup,
        settings.llm_task_model_ranking,
        settings.llm_task_model_wechat,
    ]:
        if spec:
            specs.append(spec)
    if settings.llm_model:
        specs.append(settings.llm_model)
    seen: set[str] = set()
    unique_specs: list[str] = []
    for spec in specs:
        if spec in seen:
            continue
        seen.add(spec)
        unique_specs.append(spec)
    return unique_specs


def _is_provider_configured(settings, provider: str) -> bool:
    if provider == "glm":
        return bool(settings.glm_api_key and settings.glm_base_url)
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "deepseek":
        return bool(settings.deepseek_api_key)
    if provider == "tongyi":
        return bool(settings.tongyi_api_key)
    if provider == "minimax":
        return bool(settings.minimax_api_key)
    if provider == "google":
        return bool(settings.google_ai_api_key)
    return False


def main() -> None:
    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    specs = _collect_model_specs(settings)
    if not specs:
        raise SystemExit("未找到可用模型配置")

    failed = False
    for spec in specs:
        provider, model = parse_model_spec(spec, settings.llm_provider)
        if not _is_provider_configured(settings, provider):
            print(f"跳过 {provider}:{model}（未配置 API Key）")
            continue
        print(f"测试 {provider}:{model}")
        try:
            llm = get_llm_for_model_spec(settings, spec)
            response = llm.generate("输出 ok")
            snippet = str(response).strip().replace("\n", " ")[:120]
            print(f"返回：{snippet}")
        except Exception as exc:
            failed = True
            print(f"失败：{provider}:{model} -> {exc}")

    if failed:
        raise SystemExit("LLM Provider 测试失败")
    print("LLM Provider 测试通过")


if __name__ == "__main__":
    main()
