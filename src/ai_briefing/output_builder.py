from __future__ import annotations

import json
import re
from typing import Dict, List

from .branch_specs import BranchSpecs


def _normalize_links(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [value.strip()] if value.strip() else []
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    return []


def _strip_markdown(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[。！？.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _format_list(lines: List[str]) -> str:
    if not lines:
        return ""
    return "\n".join([f"- {line}" for line in lines])


def _normalize_paragraphs(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = re.split(r"\n\s*\n", text)
        return [p.strip() for p in parts if p.strip()]
    return []


def _get_section_enabled(specs: BranchSpecs, path: List[str], default: bool = True) -> bool:
    node: object = specs.raw
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    if isinstance(node, dict) and "enabled" in node:
        enabled = node.get("enabled")
        return bool(enabled)
    if isinstance(node, bool):
        return node
    return default


def _get_max_items(specs: BranchSpecs, path: List[str], default: int) -> int:
    node: object = specs.raw
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    if isinstance(node, dict):
        raw = node.get("max_items")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw)
            except Exception:
                return default
    return default


def _append_factcheck_status(sections: List[str], status: str | None) -> None:
    if status == "review":
        sections.append("核验状态：待审")
    elif status == "warn":
        sections.append("核验状态：存疑")


def build_branch1_output(
    cluster: Dict,
    brief: Dict,
    specs: BranchSpecs,
    factcheck_status: str | None = None,
    title_override: str | None = None,
) -> Dict:
    title = title_override or cluster.get("title") or brief.get("title") or ""
    one_liner = brief.get("one_liner") or ""
    why_matters = brief.get("why_matters") or []
    key_features = brief.get("key_features") or []

    evidence_links = _normalize_links(cluster.get("evidence_links"))
    primary_link = str(cluster.get("primary_link") or brief.get("url") or "").strip()

    sections: List[str] = []
    if title:
        sections.append(f"**{title}**")
    if one_liner:
        sections.append(one_liner)

    why_block = _format_list([str(v) for v in why_matters if str(v).strip()])
    if why_block:
        sections.append("为什么重要")
        sections.append(why_block)

    features_block = _format_list([str(v) for v in key_features if str(v).strip()])
    if features_block:
        sections.append("关键亮点")
        sections.append(features_block)

    if primary_link:
        sections.append(f"主链接：{primary_link}")
    if evidence_links:
        sections.append("证据链接")
        sections.append(_format_list(evidence_links[:5]))

    _append_factcheck_status(sections, factcheck_status)

    if _get_section_enabled(specs, ["branch1", "sections", "try_this_week"], True):
        max_items = _get_max_items(specs, ["branch1", "sections", "try_this_week"], 3)
        try_items = [str(v) for v in key_features if str(v).strip()][:max_items]
        if try_items:
            sections.append("Try This Week (<=30min)")
            sections.append(_format_list([f"试试：{v}" for v in try_items]))

    if _get_section_enabled(specs, ["branch1", "sections", "bookmark"], True):
        max_items = _get_max_items(specs, ["branch1", "sections", "bookmark"], 5)
        bookmarks = evidence_links[:max_items]
        if primary_link and primary_link not in bookmarks:
            bookmarks = [primary_link] + bookmarks
        bookmarks = bookmarks[:max_items]
        if bookmarks:
            sections.append("Bookmark")
            sections.append(_format_list(bookmarks))

    if _get_section_enabled(specs, ["branch1", "sections", "next_watch"], True):
        sections.append("Next Watch")
        sections.append(_format_list(["出现官方公告/版本升级/安全通告时再次关注"]))

    feedback_cfg = specs.raw.get("branch1", {}).get("feedback", {})
    if feedback_cfg.get("enabled", True):
        commands = feedback_cfg.get("commands") or {}
        useful = commands.get("useful", "👍 {topic_id}")
        useless = commands.get("useless", "👎 {topic_id}")
        skip = commands.get("skip", "⏭ {topic_id}")
        topic_id = cluster.get("id")
        if topic_id is not None:
            sections.append("反馈指令")
            sections.append(
                f"{useful.format(topic_id=topic_id)} / {useless.format(topic_id=topic_id)} / {skip.format(topic_id=topic_id)}"
            )

    content = "\n\n".join([s for s in sections if s])
    meta = {
        "primary_link": primary_link,
        "evidence_links": evidence_links,
    }
    return {
        "content": content,
        "meta": meta,
    }


def build_branch2_output(
    cluster: Dict,
    brief: Dict,
    specs: BranchSpecs,
    factcheck_status: str | None,
    title_override: str | None = None,
) -> Dict:
    title = title_override or cluster.get("title") or brief.get("title") or ""
    summary = brief.get("summary") or brief.get("one_liner") or ""
    body = _normalize_paragraphs(brief.get("body"))
    points = brief.get("points") or brief.get("key_features") or []
    quote_spans = brief.get("quote_spans") or []

    primary_link = str(cluster.get("primary_link") or brief.get("url") or "").strip()
    evidence_links = _normalize_links(cluster.get("evidence_links"))

    sections: List[str] = []
    if title:
        sections.append(f"**{title}**")
    if summary:
        sections.append(summary)

    if body:
        sections.extend(body)

    points_block = _format_list([str(v) for v in points if str(v).strip()])
    if points_block:
        sections.append("要点")
        sections.append(points_block)

    content = "\n\n".join([s for s in sections if s])

    quote_max: int = 120
    quote_cfg = specs.raw.get("branch2", {}).get("quoting", {})
    if isinstance(quote_cfg, dict):
        raw = quote_cfg.get("max_quote_len")
        if isinstance(raw, int):
            quote_max = raw
        elif isinstance(raw, str):
            try:
                quote_max = int(raw)
            except Exception:
                quote_max = 120

    quote_texts: List[str] = []
    if isinstance(quote_spans, list) and quote_spans:
        for sentence in quote_spans:
            if len(quote_texts) >= 3:
                break
            text = str(sentence).strip()
            if not text:
                continue
            if len(text) > quote_max:
                text = text[:quote_max].rstrip() + "..."
            quote_texts.append(text)
    else:
        candidate_text = _strip_markdown(summary)
        for sentence in _split_sentences(candidate_text):
            if len(quote_texts) >= 3:
                break
            if len(sentence) > quote_max:
                sentence = sentence[:quote_max].rstrip() + "..."
            quote_texts.append(sentence)

    review_required = False
    review_cfg = specs.raw.get("branch2", {}).get("review", {})
    if isinstance(review_cfg, dict) and review_cfg.get("low_confidence_goes_to_review", True):
        review_required = factcheck_status == "review"

    unique_links = []
    for link in [primary_link] + evidence_links:
        if link and link not in unique_links:
            unique_links.append(link)

    meta = {
        "attribution": unique_links[:5],
        "quote_spans": quote_texts,
        "factcheck_status": factcheck_status,
        "review_required": review_required,
        "summary": summary,
        "body": body,
        "points": [str(v).strip() for v in points if str(v).strip()][:5],
        "primary_link": primary_link,
        "title": title,
    }
    return {
        "content": content,
        "meta": meta,
    }


def build_branch1_repo_output(
    repo: Dict,
    brief: Dict,
    specs: BranchSpecs,
    title_override: str | None = None,
) -> Dict:
    title = title_override or repo.get("full_name") or brief.get("title") or ""
    one_liner = brief.get("one_liner") or ""
    why_matters = brief.get("why_matters") or []
    key_features = brief.get("key_features") or []

    primary_link = str(repo.get("url") or brief.get("url") or "").strip()
    sections: List[str] = []
    if title:
        sections.append(f"**{title}**")
    if one_liner:
        sections.append(one_liner)

    why_block = _format_list([str(v) for v in why_matters if str(v).strip()])
    if why_block:
        sections.append("为什么重要")
        sections.append(why_block)

    features_block = _format_list([str(v) for v in key_features if str(v).strip()])
    if features_block:
        sections.append("关键亮点")
        sections.append(features_block)

    if primary_link:
        sections.append(f"主链接：{primary_link}")

    if _get_section_enabled(specs, ["branch1", "sections", "try_this_week"], True):
        max_items = _get_max_items(specs, ["branch1", "sections", "try_this_week"], 3)
        try_items = [str(v) for v in key_features if str(v).strip()][:max_items]
        if try_items:
            sections.append("Try This Week (<=30min)")
            sections.append(_format_list([f"试试：{v}" for v in try_items]))

    if _get_section_enabled(specs, ["branch1", "sections", "bookmark"], True) and primary_link:
        sections.append("Bookmark")
        sections.append(_format_list([primary_link]))

    if _get_section_enabled(specs, ["branch1", "sections", "next_watch"], True):
        sections.append("Next Watch")
        sections.append(_format_list(["关注版本更新、星标增速或重大安全通告"]))

    feedback_cfg = specs.raw.get("branch1", {}).get("feedback", {})
    if feedback_cfg.get("enabled", True):
        commands = feedback_cfg.get("commands") or {}
        useful = commands.get("useful", "👍 {topic_id}")
        useless = commands.get("useless", "👎 {topic_id}")
        skip = commands.get("skip", "⏭ {topic_id}")
        topic_id = repo.get("id")
        if topic_id is not None:
            sections.append("反馈指令")
            sections.append(
                f"{useful.format(topic_id=topic_id)} / {useless.format(topic_id=topic_id)} / {skip.format(topic_id=topic_id)}"
            )

    content = "\n\n".join([s for s in sections if s])
    meta = {
        "primary_link": primary_link,
        "evidence_links": [primary_link] if primary_link else [],
    }
    return {
        "content": content,
        "meta": meta,
    }


def build_branch2_repo_output(
    repo: Dict,
    brief: Dict,
    specs: BranchSpecs,
    title_override: str | None = None,
) -> Dict:
    title = title_override or repo.get("full_name") or brief.get("title") or ""
    summary = brief.get("summary") or brief.get("one_liner") or ""
    body = _normalize_paragraphs(brief.get("body"))
    points = brief.get("points") or brief.get("key_features") or []
    quote_spans = brief.get("quote_spans") or []

    primary_link = str(repo.get("url") or brief.get("url") or "").strip()
    sections: List[str] = []
    if title:
        sections.append(f"**{title}**")
    if summary:
        sections.append(summary)

    if body:
        sections.extend(body)

    points_block = _format_list([str(v) for v in points if str(v).strip()])
    if points_block:
        sections.append("要点")
        sections.append(points_block)

    content = "\n\n".join([s for s in sections if s])

    quote_max = 120
    quote_cfg = specs.raw.get("branch2", {}).get("quoting", {})
    if isinstance(quote_cfg, dict):
        raw = quote_cfg.get("max_quote_len")
        if isinstance(raw, int):
            quote_max = raw
        elif isinstance(raw, str):
            try:
                quote_max = int(raw)
            except Exception:
                quote_max = 120

    quote_texts: List[str] = []
    if isinstance(quote_spans, list) and quote_spans:
        for sentence in quote_spans:
            if len(quote_texts) >= 3:
                break
            text = str(sentence).strip()
            if not text:
                continue
            if len(text) > quote_max:
                text = text[:quote_max].rstrip() + "..."
            quote_texts.append(text)
    else:
        candidate_text = _strip_markdown(summary)
        for sentence in _split_sentences(candidate_text):
            if len(quote_texts) >= 3:
                break
            if len(sentence) > quote_max:
                sentence = sentence[:quote_max].rstrip() + "..."
            quote_texts.append(sentence)

    meta = {
        "attribution": [primary_link] if primary_link else [],
        "quote_spans": quote_texts,
        "factcheck_status": None,
        "review_required": False,
        "summary": summary,
        "body": body,
        "points": [str(v).strip() for v in points if str(v).strip()][:5],
        "primary_link": primary_link,
        "title": title,
    }
    return {
        "content": content,
        "meta": meta,
    }
