from __future__ import annotations

import json
from typing import Dict, List

from .branch_specs import load_branch_specs
from .config import Settings


def _normalize_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []


def _build_branch1_action_items(key_features: List[str], max_items: int) -> List[str]:
    actions: List[str] = []
    for item in key_features[:max_items]:
        actions.append(f"试试：{item}")
    return actions


def _build_branch1_bookmarks(primary_link: str, evidence_links: List[str], max_items: int) -> List[str]:
    bookmarks: List[str] = []
    if primary_link:
        bookmarks.append(primary_link)
    for link in evidence_links:
        if link in bookmarks:
            continue
        bookmarks.append(link)
        if len(bookmarks) >= max_items:
            break
    return bookmarks


def _build_branch1_next_watch(max_items: int) -> List[str]:
    signals = [
        "开放源码/权重或复现实验",
        "公布 API 价格与配额",
        "提供可复用评测与基准",
        "明确兼容性/生态集成",
    ]
    return signals[:max_items]


def build_branch1_output(settings: Settings, brief: Dict, cluster: Dict, factcheck_meta: Dict | None) -> Dict:
    specs = load_branch_specs(settings.branch_specs_file)
    branch_cfg = specs.raw.get("branch1") or {}
    if not branch_cfg.get("enabled", True):
        return {}

    sections = branch_cfg.get("sections") or {}
    try_cfg = sections.get("try_this_week") or {}
    bookmark_cfg = sections.get("bookmark") or {}
    next_watch_cfg = sections.get("next_watch") or {}

    one_liner = brief.get("one_liner") or ""
    why_matters = _normalize_list(brief.get("why_matters"))
    key_features = _normalize_list(brief.get("key_features"))

    primary_link = cluster.get("primary_link") or brief.get("url") or ""
    evidence_links = _normalize_list(cluster.get("evidence_links"))

    lines: List[str] = []
    title = cluster.get("title") or brief.get("title") or ""
    if title:
        lines.append(f"# {title}")
    if one_liner:
        lines.append(one_liner)

    if why_matters:
        lines.append("\n对我有什么用")
        for w in why_matters:
            lines.append(f"- {w}")

    if key_features:
        lines.append("\n关键变化")
        for k in key_features:
            lines.append(f"- {k}")

    if try_cfg.get("enabled", True):
        max_items = int(try_cfg.get("max_items", 3))
        timebox_minutes = int(try_cfg.get("timebox_minutes", 30))
        actions = _build_branch1_action_items(key_features, max_items)
        if actions:
            lines.append(f"\n本周可试（≤{timebox_minutes}分钟）")
            for a in actions:
                lines.append(f"- {a}")

    if bookmark_cfg.get("enabled", True):
        max_items = int(bookmark_cfg.get("max_items", 5))
        bookmarks = _build_branch1_bookmarks(primary_link, evidence_links, max_items)
        if bookmarks:
            lines.append("\n证据链接")
            for b in bookmarks:
                lines.append(f"- {b}")

    if next_watch_cfg.get("enabled", True):
        max_items = int(next_watch_cfg.get("max_items", 3))
        next_watch = _build_branch1_next_watch(max_items)
        if next_watch:
            lines.append("\n后续关注")
            for n in next_watch:
                lines.append(f"- {n}")

    content = "\n".join(lines).strip()
    meta = {
        "primary_link": primary_link,
        "evidence_links": evidence_links,
        "factcheck": factcheck_meta or {},
    }

    return {
        "branch": "branch1",
        "content": content,
        "meta": meta,
    }


def build_branch2_output(settings: Settings, brief: Dict, cluster: Dict, factcheck_meta: Dict | None) -> Dict:
    specs = load_branch_specs(settings.branch_specs_file)
    branch_cfg = specs.raw.get("branch2") or {}
    if not branch_cfg.get("enabled", True):
        return {}

    review_cfg = branch_cfg.get("review") or {}
    low_conf_review = review_cfg.get("low_confidence_goes_to_review", True)

    one_liner = brief.get("one_liner") or ""
    why_matters = _normalize_list(brief.get("why_matters"))
    key_features = _normalize_list(brief.get("key_features"))

    primary_link = cluster.get("primary_link") or brief.get("url") or ""
    evidence_links = _normalize_list(cluster.get("evidence_links"))

    title = cluster.get("title") or brief.get("title") or ""
    lines: List[str] = []
    if title:
        lines.append(f"# {title}")
    if one_liner:
        lines.append(one_liner)

    if why_matters:
        lines.append("\n为什么重要")
        for w in why_matters:
            lines.append(f"- {w}")

    if key_features:
        lines.append("\n核心亮点")
        for k in key_features:
            lines.append(f"- {k}")

    if primary_link or evidence_links:
        lines.append("\n来源")
        if primary_link:
            lines.append(f"- {primary_link}")
        for link in evidence_links:
            if link == primary_link:
                continue
            lines.append(f"- {link}")

    content = "\n".join(lines).strip()

    attribution: List[str] = []
    if primary_link:
        attribution.append(primary_link)
    for link in evidence_links:
        if link not in attribution:
            attribution.append(link)

    review_required = False
    if low_conf_review and factcheck_meta:
        if factcheck_meta.get("status") == "review":
            review_required = True

    meta = {
        "primary_link": primary_link,
        "evidence_links": evidence_links,
        "attribution": attribution,
        "quote_spans": [],
        "review_required": review_required,
        "factcheck": factcheck_meta or {},
    }

    return {
        "branch": "branch2",
        "content": content,
        "meta": meta,
    }
