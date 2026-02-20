from __future__ import annotations

import re
from typing import List


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _strip_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _shorten(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _first_sentence(text: str) -> str:
    if not text:
        return ""
    text = _strip_markdown(text)
    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    return parts[0].strip() if parts else text


def _trim_to_chinese(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"[\u4e00-\u9fff]", text)
    if not match:
        return text
    idx = match.start()
    if idx <= 6:
        return text
    return text[idx:]


def _pick_value(one_liner: str, why_matters: List[str]) -> str:
    candidate = _first_sentence(one_liner)
    if _has_chinese(candidate):
        return _trim_to_chinese(candidate)
    for item in why_matters:
        item_text = _first_sentence(str(item))
        if _has_chinese(item_text):
            return _trim_to_chinese(item_text)
    return "对普通人有帮助的更新"


def _pick_topic(one_liner: str, fallback: str, allow_english: bool) -> str:
    text = _strip_markdown(one_liner)
    match = re.search(r"^(.{2,20}?)(是|发布|推出|上线|宣布|开源|提出|发布了)", text)
    if match:
        topic = match.group(1).strip()
        if _has_chinese(topic) or allow_english:
            return topic
    if fallback and _has_chinese(fallback):
        return fallback.strip()
    return "最新动态"


def build_news_title(cluster_title: str, one_liner: str, why_matters: List[str]) -> str:
    value = _pick_value(one_liner, why_matters)
    topic = _pick_topic(one_liner, cluster_title, bool(value))
    if value:
        return _shorten(f"{topic}：{value}", 32)
    return _shorten(topic, 32)


def build_repo_title(repo_name: str, one_liner: str, description: str, why_matters: List[str]) -> str:
    value = _pick_value(one_liner, why_matters)
    if not value and _has_chinese(description or ""):
        value = _first_sentence(description)
    if not value:
        value = "值得关注的开源项目"
    title = f"【项目】{repo_name}：{value}"
    return _shorten(title, 36)
