from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

import logging
import requests

from .config import Settings


logger = logging.getLogger("image_generation")


@dataclass(frozen=True)
class ImageSlot:
    slot_type: str
    prompt: str
    diagram_spec: dict[str, object] | None


@dataclass(frozen=True)
class ImagePlan:
    count: int
    slots: List[ImageSlot]


def _normalize_slot_type(value: str) -> str:
    lower = value.strip().lower()
    if lower in ("cover", "inline", "demo"):
        return lower
    return "inline"


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


def _short_label(text: str, limit: int = 8) -> str:
    cleaned = re.sub(r"^[【\[]|[】\]]$", "", text.strip())
    cleaned = re.sub(r"[\s,，。.!?、;；:：()（）<>\"'“”‘’\\/]+", "", cleaned)
    if not cleaned:
        cleaned = text.strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit]
    return cleaned


def _extract_headings(paragraphs: List[str]) -> List[str]:
    headings: List[str] = []
    for paragraph in paragraphs:
        match = re.match(r"^【([^】]{1,12})】", paragraph.strip())
        if not match:
            continue
        label = _short_label(match.group(1))
        if label:
            headings.append(label)
    return headings


def _extract_heading(paragraph: str) -> str:
    match = re.match(r"^【([^】]{1,30})】", paragraph.strip())
    return match.group(1).strip() if match else ""


def _strip_heading_prefix(paragraph: str) -> str:
    return re.sub(r"^【[^】]{1,30}】\s*", "", paragraph.strip())


def _first_sentence(paragraph: str) -> str:
    text = _strip_heading_prefix(paragraph)
    sentences = _split_sentences(text)
    return sentences[0] if sentences else text


def _is_generic_heading(heading: str) -> bool:
    generic = {
        "发生了什么",
        "它是什么",
        "对生活的影响",
        "普通人如何体验",
        "如何体验",
        "普通人的参与",
        "变现可能性",
        "变现与跟进",
        "跟上AI的做法",
        "注意与限制",
        "注意",
        "限制",
        "要点",
        "来源",
        "引用",
    }
    cleaned = heading.strip()
    return cleaned in generic


def _has_actionable_content(text: str) -> bool:
    if not text:
        return False
    # 简单启发：至少包含一个动词信号，并且长度足够，避免空泛
    verbs = [
        "提出", "开发", "发布", "上线", "推出", "构建", "引入", "采用", "通过", "用于", "实现",
        "评估", "测试", "验证", "对比", "衡量", "提升", "降低", "加速", "解决", "识别", "学习",
        "推理", "生成", "检测", "优化", "改进", "导致", "影响", "出现", "源于", "干扰", "减少",
    ]
    if len(text.strip()) < 8:
        return False
    if not any(v in text for v in verbs):
        return False
    # 过滤过于空泛的句式
    vague = ["很重要", "值得关注", "带来帮助", "提升效率", "更加智能"]
    if any(v in text for v in vague) and len(text.strip()) < 16:
        return False
    return True


def _wrap_label(text: str, width: int = 10) -> str:
    clean = text.strip()
    if len(clean) <= width:
        return clean
    return clean[:width] + "\\n" + clean[width:width * 2]


def _build_main_label(heading: str, sentence: str) -> str | None:
    # 目标：可读、具体，避免把“泛标题”直接当节点
    base = sentence.strip()
    if not base:
        return None

    # 去掉显著的开场套话
    base = re.sub(r"^(本文|这篇文章|研究者|团队|作者)\s*(提出|开发|发布|介绍)", r"\2", base)
    base = re.sub(r"^我们\s*(提出|开发|发布)", r"\1", base)

    # 如果小标题不是泛标题，允许作为补充，但仍以句子为主
    if heading and not _is_generic_heading(heading):
        # 保留小标题的关键信息（最多 6 字）
        heading_short = _short_label(heading, limit=6)
        if heading_short and heading_short not in base:
            base = heading_short + "：" + base

    # 压缩长度，保留可读的中文短句
    base = base.replace("（", "(").replace("）", ")")
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > 22:
        base = base[:22]

    if not _has_actionable_content(base):
        return None
    return _wrap_label(base, width=11)


def _classify_stage(heading: str, sentence: str) -> str:
    text = f"{heading} {sentence}".strip()
    if any(k in text for k in ["问题", "痛点", "挑战", "难点", "缺乏", "不足", "难以", "瓶颈"]):
        return "problem"
    if any(k in text for k in ["方法", "机制", "框架", "系统", "通过", "采用", "构建", "流程", "思路"]):
        return "mechanism"
    if any(k in text for k in ["评估", "基准", "测试", "验证", "benchmark", "对比", "指标", "实验"]):
        return "eval"
    if any(k in text for k in ["结果", "应用", "落地", "提升", "降低", "加速", "带来", "影响"]):
        return "outcome"
    return "other"


def _score_stage_candidate(stage: str, text: str) -> int:
    # 简单词频评分，便于挑选更“原理导向”的句子
    weights = {
        "problem": ["问题", "挑战", "难点", "不足", "瓶颈"],
        "mechanism": ["通过", "采用", "构建", "机制", "流程", "框架"],
        "eval": ["评估", "测试", "验证", "基准", "对比", "指标"],
        "outcome": ["结果", "应用", "落地", "提升", "降低", "加速"],
    }
    keywords = weights.get(stage, [])
    return sum(1 for k in keywords if k in text)


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[。！？.!?]+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def normalize_image_plan(value: object, max_count: int) -> ImagePlan:
    if not isinstance(value, dict):
        return ImagePlan(count=0, slots=[])

    raw_count = value.get("count")
    if isinstance(raw_count, int):
        count = int(raw_count)
    elif isinstance(raw_count, str):
        try:
            count = int(raw_count)
        except Exception:
            count = 0
    else:
        count = 0

    slots: List[ImageSlot] = []
    raw_slots = value.get("slots")
    if isinstance(raw_slots, list):
        for item in raw_slots:
            if not isinstance(item, dict):
                continue
            slot_type = _normalize_slot_type(str(item.get("type", "inline")))
            prompt = str(item.get("prompt", "")).strip()
            diagram_spec = item.get("diagram")
            if not isinstance(diagram_spec, dict):
                diagram_spec = item.get("diagram_spec")
            if not isinstance(diagram_spec, dict):
                diagram_spec = None
            if not prompt and not diagram_spec:
                continue
            slots.append(ImageSlot(slot_type=slot_type, prompt=prompt, diagram_spec=diagram_spec))

    if count <= 0 and slots:
        count = len(slots)

    count = max(0, min(count, max_count, len(slots)))
    if count == 0:
        return ImagePlan(count=0, slots=[])
    return ImagePlan(count=count, slots=slots[:count])


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _get_date_dir(settings: Settings) -> str:
    tz = ZoneInfo("Asia/Shanghai")
    date_str = datetime.now(tz).strftime(settings.feishu_doc_date_format)
    return os.path.join(settings.image_output_dir, date_str)


def _sanitize_file_name(text: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:40] if len(cleaned) > 40 else cleaned


def _build_image_name(title: str, index: int) -> str:
    base = _sanitize_file_name(title) or "image"
    return f"{base}{index:02d}.png"


def _save_image_bytes(directory: str, content: bytes, file_name: str) -> str:
    _ensure_dir(directory)
    file_path = os.path.join(directory, file_name)
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path


def _download_image(url: str, directory: str, file_name: str) -> str | None:
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code >= 400:
            logger.warning(f"图片下载失败: {resp.status_code}")
            return None
        return _save_image_bytes(directory, resp.content, file_name)
    except Exception:
        return None


def _generate_image_glm(settings: Settings, prompt: str, file_name: str) -> tuple[str | None, str | None]:
    base_url = (settings.glm_base_url or "").rstrip("/")
    if not base_url:
        logger.warning("图片生成失败: GLM_BASE_URL 缺失")
        return None, None

    model = settings.image_model
    if not model:
        logger.warning("图片生成失败: 模型缺失")
        return None, None

    url = f"{base_url}/images/generations"
    headers = {
        "Authorization": f"Bearer {settings.glm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model.replace("glm:", ""),
        "prompt": prompt,
        "size": settings.image_size,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=settings.llm_timeout_seconds)
    if resp.status_code >= 400:
        logger.warning(f"图片生成失败: {resp.status_code} {resp.text}")
        return None, None
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        logger.warning(f"图片生成失败: 返回数据为空 {data}")
        return None, None
    item = items[0]
    if isinstance(item, dict) and "url" in item:
        return item.get("url"), None
    if isinstance(item, dict) and "b64_json" in item:
        raw = item.get("b64_json")
        if isinstance(raw, str) and raw:
            content = base64.b64decode(raw)
            path = _save_image_bytes(_get_date_dir(settings), content, file_name)
            return None, path
    logger.warning(f"图片生成失败: 返回数据格式不支持 {item}")
    return None, None


def _generate_image_google(settings: Settings, prompt: str, file_name: str) -> tuple[str | None, str | None]:
    if not settings.google_ai_api_key:
        logger.warning("图片生成失败: GOOGLE_AI_API_KEY 缺失")
        return None, None

    model = settings.image_model or ""
    model_name = model.replace("google:", "").strip()
    if not model_name:
        logger.warning("图片生成失败: IMAGE_MODEL 缺失")
        return None, None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:predict"
    headers = {
        "x-goog-api-key": settings.google_ai_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "instances": [
            {"prompt": prompt},
        ],
        "parameters": {
            "sampleCount": 1,
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=settings.llm_timeout_seconds)
    if resp.status_code >= 400:
        logger.warning(f"图片生成失败: {resp.status_code} {resp.text}")
        return None, None
    data = resp.json()
    predictions = data.get("predictions") if isinstance(data, dict) else None
    if not isinstance(predictions, list) or not predictions:
        logger.warning(f"图片生成失败: 返回数据为空 {data}")
        return None, None
    item = predictions[0]
    raw = None
    if isinstance(item, dict):
        raw = item.get("bytesBase64Encoded") or item.get("imageBytes")
    if isinstance(raw, str) and raw:
        content = base64.b64decode(raw)
        path = _save_image_bytes(_get_date_dir(settings), content, file_name)
        return None, path
    logger.warning(f"图片生成失败: 返回数据格式不支持 {item}")
    return None, None


def _generate_image(settings: Settings, prompt: str, file_name: str) -> tuple[str | None, str | None]:
    model = settings.image_model or ""
    lower = model.lower()
    if lower.startswith("google:") or lower.startswith("imagen-") or lower.startswith("gemini-"):
        return _generate_image_google(settings, prompt, file_name)
    return _generate_image_glm(settings, prompt, file_name)


def _escape_dot_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _node_shape(node_type: str) -> str:
    normalized = node_type.strip().lower()
    shape_map = {
        "start": "ellipse",
        "end": "ellipse",
        "decision": "diamond",
        "data": "parallelogram",
        "process": "box",
        "note": "note",
    }
    return shape_map.get(normalized, "box")


def _title_text(raw_title: str) -> str:
    text = str(raw_title or "").strip()
    if not text:
        return ""
    # 只保留前 28 字，避免标题过长挤压布局
    if len(text) > 28:
        text = text[:28] + "…"
    return text


def _node_kind(node: dict[str, object]) -> str:
    kind = str(node.get("kind") or "main").strip().lower()
    if kind in ("main", "callout"):
        return kind
    return "main"


def _node_group(node: dict[str, object]) -> str:
    value = str(node.get("group") or "").strip()
    return value


def _stage_color(stage: str) -> str:
    palette = {
        "happen": "#DBEAFE",
        "impact": "#DCFCE7",
        "how": "#E0E7FF",
        "caution": "#FFE4E6",
        "other": "#E2E8F0",
    }
    return palette.get(stage, palette["other"])


def _gradient(fill_left: str, fill_right: str) -> str:
    return f"{fill_left}:{fill_right}"


def _pick_main_chain_labels(labels: List[str], max_items: int) -> List[str]:
    # 保留：旧逻辑已不再使用，避免破坏外部引用
    return labels[:max_items]


def _pick_examples(points: List[str], keywords: List[str], max_items: int) -> List[str]:
    candidates: List[str] = []
    for p in points:
        text = str(p).strip()
        if not text:
            continue
        if any(k in text for k in keywords):
            candidates.append(text)
    if not candidates:
        return []
    result: List[str] = []
    seen: set[str] = set()
    for item in candidates:
        label = _short_label(item, limit=10)
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(label)
        if len(result) >= max_items:
            break
    return result


def _stage_from_heading(heading: str) -> str:
    text = heading.strip()
    if not text:
        return "other"
    if any(key in text for key in ["发生", "更新", "发布", "推出", "上线", "改变", "新功能"]):
        return "happen"
    if any(key in text for key in ["影响", "改变", "意义", "生活", "省时", "省钱", "效率"]):
        return "impact"
    if any(key in text for key in ["体验", "上手", "使用", "入门", "变现", "赚钱", "跟上", "怎么做"]):
        return "how"
    if any(key in text for key in ["注意", "限制", "风险", "坑", "成本", "付费", "合规"]):
        return "caution"
    return "other"


def _group_title_for_stage(stage: str) -> str:
    mapping = {
        "happen": "发生了什么",
        "impact": "对生活的影响",
        "how": "如何体验/变现",
        "caution": "注意与限制",
        "other": "补充",
    }
    return mapping.get(stage, "补充")


def _pick_callouts(summary: str, points: List[str], max_items: int) -> List[str]:
    keywords = ["门槛", "成本", "风险", "限制", "付费", "免费", "收益", "机会", "适合", "不适合", "隐私", "合规"]
    candidates: List[str] = []
    for p in points:
        text = str(p).strip()
        if not text:
            continue
        if any(k in text for k in keywords):
            candidates.append(text)
    if len(candidates) < max_items:
        for sentence in _split_sentences(summary):
            if any(k in sentence for k in keywords):
                candidates.append(sentence)

    dedup: List[str] = []
    seen: set[str] = set()
    for item in candidates:
        label = _short_label(item, limit=14)
        if not label or label in seen:
            continue
        seen.add(label)
        dedup.append(label)
        if len(dedup) >= max_items:
            break
    return dedup


def _build_graphviz_dot(diagram_spec: dict[str, object], title: str, font_name: str) -> str:
    layout = str(diagram_spec.get("layout", "TB")).upper().strip()
    if layout not in ("TB", "LR"):
        layout = "TB"
    rankdir = "LR" if layout == "LR" else "TB"

    lines = [
        "digraph G {",
        f"  rankdir={rankdir};",
        "  splines=ortho;",
        "  nodesep=0.40;",
        "  ranksep=0.65;",
        "  pad=0.25;",
        "  bgcolor=\"#F8FAFC:#ECFEFF\";",
        "  gradientangle=135;",
        f"  graph [charset=\"UTF-8\", fontname=\"{_escape_dot_text(font_name)}\", labelloc=\"t\", fontsize=20, fontcolor=\"#0F172A\", style=\"filled\"];",
        f"  node [fontname=\"{_escape_dot_text(font_name)}\", style=\"rounded,filled\", color=\"#94A3B8\", fontcolor=\"#0F172A\", fillcolor=\"#E2E8F0\", fontsize=14, penwidth=1.2];",
        f"  edge [fontname=\"{_escape_dot_text(font_name)}\", color=\"#64748B\", fontcolor=\"#334155\", fontsize=12, penwidth=1.3, arrowsize=0.8];",
    ]

    has_title_node = bool(diagram_spec.get("title_node"))
    if title and not has_title_node:
        lines.append(f"  label=\"{_escape_dot_text(title)}\";")

    nodes = diagram_spec.get("nodes")
    edges = diagram_spec.get("edges")
    groups = diagram_spec.get("groups") or diagram_spec.get("clusters")

    node_list: list[dict[str, object]] = []
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                node_list.append(node)

    group_nodes: dict[str, list[dict[str, object]]] = {}
    for node in node_list:
        group_id = _node_group(node)
        if not group_id:
            group_id = "__default__"
        group_nodes.setdefault(group_id, []).append(node)

    def render_node(node_id: str, node: dict[str, object], idx: int) -> None:
        label = str(node.get("label") or node_id).strip()
        node_type = str(node.get("type") or "process")
        shape = _node_shape(node_type)
        kind = _node_kind(node)
        stage = str(node.get("stage") or "other")
        variant = str(node.get("variant") or "").strip().lower()

        if variant == "title":
            lines.append(
                f"    \"{_escape_dot_text(node_id)}\" [label=\"{_escape_dot_text(label)}\", shape=\"box\", style=\"rounded,filled\", fillcolor=\"{_gradient('#E0F2FE', '#E9D5FF')}\", gradientangle=0, color=\"#7C3AED\", fontsize=18, penwidth=1.4, fontcolor=\"#0F172A\"];"
            )
            return

        if variant == "header":
            lines.append(
                f"    \"{_escape_dot_text(node_id)}\" [label=\"{_escape_dot_text(label)}\", shape=\"box\", style=\"rounded,filled\", fillcolor=\"{_gradient('#C7D2FE', '#D8B4FE')}\", gradientangle=0, color=\"#7C3AED\", fontsize=13, penwidth=1.2];"
            )
            return

        if variant == "pill":
            lines.append(
                f"    \"{_escape_dot_text(node_id)}\" [label=\"{_escape_dot_text(label)}\", shape=\"box\", style=\"rounded,filled\", fillcolor=\"{_gradient('#BAE6FD', '#BBF7D0')}\", gradientangle=0, color=\"#0EA5E9\", fontsize=14, penwidth=1.2];"
            )
            return

        if kind == "callout":
            lines.append(
                f"    \"{_escape_dot_text(node_id)}\" [label=\"{_escape_dot_text(label)}\", shape=\"{shape}\", style=\"filled\", fillcolor=\"#FEF3C7\", color=\"#F59E0B\", fontsize=12, penwidth=1.1];"
            )
            return
        fill = _stage_color(stage)
        lines.append(
            f"    \"{_escape_dot_text(node_id)}\" [label=\"{_escape_dot_text(label)}\", shape=\"{shape}\", fillcolor=\"{fill}\"];"
        )

    # render groups as clusters
    group_meta: list[dict[str, object]] = []
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict):
                group_meta.append(group)

    group_label_by_id: dict[str, str] = {}
    for group in group_meta:
        gid = str(group.get("id") or "").strip()
        glabel = str(group.get("label") or "").strip()
        if gid and glabel:
            group_label_by_id[gid] = glabel

    rendered_node_ids: set[str] = set()
    idx_counter = 0

    for group_id, nodes_in_group in group_nodes.items():
        if group_id == "__default__":
            continue
        group_label = group_label_by_id.get(group_id) or str(group_id)
        lines.append(f"  subgraph cluster_{_escape_dot_text(group_id)} {{")
        lines.append("    style=\"rounded\";")
        lines.append("    color=\"#CBD5E1\";")
        lines.append("    penwidth=1.1;")
        lines.append(f"    label=\"{_escape_dot_text(group_label)}\";")
        lines.append("    fontcolor=\"#334155\";")
        lines.append(f"    fontname=\"{_escape_dot_text(font_name)}\";")
        lines.append("    fontsize=13;")
        for node in nodes_in_group:
            idx_counter += 1
            node_id = str(node.get("id") or node.get("name") or f"n{idx_counter}").strip() or f"n{idx_counter}"
            rendered_node_ids.add(node_id)
            render_node(node_id, node, idx_counter)
        lines.append("  }")

    # default group
    if "__default__" in group_nodes:
        for node in group_nodes["__default__"]:
            idx_counter += 1
            node_id = str(node.get("id") or node.get("name") or f"n{idx_counter}").strip() or f"n{idx_counter}"
            if node_id in rendered_node_ids:
                continue
            render_node(node_id, node, idx_counter)

    # rank constraints
    raw_ranks = diagram_spec.get("ranks")
    if isinstance(raw_ranks, list):
        for rank in raw_ranks:
            if not isinstance(rank, list) or not rank:
                continue
            items = [str(v).strip() for v in rank if str(v).strip()]
            if len(items) < 2:
                continue
            quoted = " ".join([f"\"{_escape_dot_text(v)}\"" for v in items])
            lines.append(f"  {{ rank=same; {quoted}; }}")

    edge_list: list[dict[str, object]] = []
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, dict):
                edge_list.append(edge)

    for edge in edge_list:
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if not source or not target:
            continue
        label = str(edge.get("label") or "").strip()
        edge_kind = str(edge.get("kind") or "main").strip().lower()
        edge_role = str(edge.get("role") or "").strip().lower()
        extra = ""
        if edge_kind == "callout":
            extra = ", style=\"dashed\", color=\"#F59E0B\", penwidth=1.1, arrowsize=0.7"
        if edge_role == "split":
            extra = ", color=\"#7C3AED\", penwidth=2.0, arrowsize=0.9"
        if label:
            lines.append(
                f"  \"{_escape_dot_text(source)}\" -> \"{_escape_dot_text(target)}\" [label=\"{_escape_dot_text(label)}\"{extra}];"
            )
        else:
            lines.append(
                f"  \"{_escape_dot_text(source)}\" -> \"{_escape_dot_text(target)}\" [{extra.lstrip(', ')}];" if extra else f"  \"{_escape_dot_text(source)}\" -> \"{_escape_dot_text(target)}\";"
            )

    lines.append("}")
    return "\n".join(lines)


def _render_graphviz_image(
    settings: Settings,
    diagram_spec: dict[str, object],
    title: str,
    directory: str,
    file_name: str,
) -> str | None:
    dot_path = shutil.which("dot")
    if not dot_path:
        logger.warning("Graphviz 未安装，跳过图像生成")
        return None
    font_name = settings.graphviz_font or "Noto Sans CJK SC"
    dot_content = _build_graphviz_dot(diagram_spec, title, font_name)
    _ensure_dir(directory)
    output_path = os.path.join(directory, file_name)
    try:
        subprocess.run(
            [dot_path, "-Tpng", "-o", output_path],
            input=dot_content.encode("utf-8"),
            check=True,
            timeout=30,
        )
    except Exception as e:
        logger.warning(f"Graphviz 生成失败: {e}")
        return None
    if not os.path.exists(output_path):
        logger.warning("Graphviz 输出文件缺失")
        return None
    return output_path


def build_graphviz_plan_from_content(
    content: dict[str, object],
    title: str,
    max_count: int,
) -> ImagePlan:
    if max_count <= 0:
        return ImagePlan(count=0, slots=[])
    if not isinstance(content, dict):
        return ImagePlan(count=0, slots=[])

    summary = str(content.get("summary") or content.get("one_liner") or "").strip()
    body = _normalize_paragraphs(content.get("body"))
    points_raw = content.get("points") or content.get("key_features") or []
    points_list: List[str] = []
    if isinstance(points_raw, list):
        points_list = [str(v).strip() for v in points_raw if str(v).strip()]
    elif isinstance(points_raw, str) and points_raw.strip():
        points_list = [points_raw.strip()]
    point_list = points_list

    # 原理导向：输入/前提 -> 机制/方法 -> 评估/验证 -> 结果/影响
    candidates: List[dict[str, str]] = []
    for paragraph in body:
        heading = _extract_heading(paragraph)
        sentence = _first_sentence(paragraph)
        label = _build_main_label(heading, sentence)
        if not label:
            continue
        stage = _classify_stage(heading, sentence)
        score = _score_stage_candidate(stage, f"{heading} {sentence}")
        candidates.append({
            "stage": stage,
            "label": label,
            "raw": f"{heading} {sentence}".strip(),
            "score": str(score),
        })

    if len(candidates) < 3:
        return ImagePlan(count=0, slots=[])

    stage_order = ["problem", "mechanism", "eval", "outcome"]
    picked: List[dict[str, str]] = []
    used_labels: set[str] = set()
    for stage in stage_order:
        stage_items = [c for c in candidates if c["stage"] == stage]
        stage_items.sort(key=lambda x: int(x.get("score") or "0"), reverse=True)
        for item in stage_items:
            if item["label"] in used_labels:
                continue
            used_labels.add(item["label"])
            picked.append(item)
            break

    # 回退：补齐到 3-4 个节点
    if len(picked) < 3:
        rest = [c for c in candidates if c["label"] not in used_labels]
        for item in rest:
            used_labels.add(item["label"])
            picked.append(item)
            if len(picked) >= 3:
                break

    # 仍不足，直接不出图（宁缺毋滥）
    if len(picked) < 3:
        return ImagePlan(count=0, slots=[])

    # 最多 4 个主节点
    picked = picked[:4]

    nodes: List[dict[str, object]] = []
    edges: List[dict[str, object]] = []
    groups: List[dict[str, object]] = []
    ranks: List[list[str]] = []

    title_node_id = "t0"
    title_text = _title_text(title)
    if title_text:
        nodes.append({
            "id": title_node_id,
            "label": _wrap_label(title_text, width=14),
            "type": "box",
            "variant": "title",
            "kind": "main",
            "stage": "happen",
            "group": "main",
        })

    stage_to_color = {
        "problem": "impact",
        "mechanism": "how",
        "eval": "happen",
        "outcome": "caution",
        "other": "other",
    }

    for idx, item in enumerate(picked, start=1):
        node_type = "start" if idx == 1 else "process"
        if idx == len(picked):
            node_type = "process"
        stage = item.get("stage") or "other"
        nodes.append({
            "id": f"n{idx}",
            "label": item["label"],
            "type": node_type,
            "variant": "pill",
            "kind": "main",
            "stage": stage_to_color.get(stage, "other"),
            "group": "main",
        })
        if idx > 1:
            edges.append({"from": f"n{idx - 1}", "to": f"n{idx}", "label": "", "kind": "main"})

    if title_text:
        edges.insert(0, {"from": title_node_id, "to": "n1", "label": "", "kind": "main"})

    groups.append({"id": "main", "label": "原理链路", "nodes": [f"n{i}" for i in range(1, len(picked) + 1)] + ([title_node_id] if title_text else [])})

    # 可选：影响/参与分支（需要足够具体的信息，否则不生成）
    impact_examples = _pick_examples(point_list, ["电池", "材料", "建筑", "医疗", "能源", "环保", "耐用", "成本", "效率"], max_items=2)
    people_examples = _pick_examples(point_list, ["体验", "使用", "上手", "关注", "学习", "投资", "社区", "机会"], max_items=2)

    if len(impact_examples) >= 1 and len(people_examples) >= 1:
        split_from = f"n{len(picked)}"
        impact_header = "b1"
        people_header = "b2"

        nodes.extend([
            {"id": impact_header, "label": "对生活的影响", "type": "box", "variant": "header", "kind": "main", "stage": "impact", "group": "impact"},
            {"id": people_header, "label": "普通人的参与", "type": "box", "variant": "header", "kind": "main", "stage": "how", "group": "people"},
        ])
        edges.append({"from": split_from, "to": impact_header, "label": "", "kind": "main", "role": "split"})
        edges.append({"from": split_from, "to": people_header, "label": "", "kind": "main", "role": "split"})

        ranks.append([impact_header, people_header])

        # 左分支
        impact_nodes: List[str] = [impact_header]
        for i, label in enumerate(impact_examples[:2], start=1):
            nid = f"i{i}"
            impact_nodes.append(nid)
            nodes.append({"id": nid, "label": _wrap_label(label, width=10), "type": "box", "variant": "pill", "kind": "main", "stage": "impact", "group": "impact"})
            edges.append({"from": impact_header, "to": nid, "label": "", "kind": "main"})

        quality_id = "i3"
        nodes.append({"id": quality_id, "label": "提升生活质量", "type": "box", "variant": "header", "kind": "main", "stage": "impact", "group": "impact"})
        for nid in impact_nodes[1:]:
            edges.append({"from": nid, "to": quality_id, "label": "", "kind": "main"})
        impact_nodes.append(quality_id)
        groups.append({"id": "impact", "label": "对生活的影响", "nodes": impact_nodes})

        # 右分支
        people_nodes: List[str] = [people_header]
        how_id = "p1"
        money_id = "p2"
        nodes.extend([
            {"id": how_id, "label": "如何体验", "type": "box", "variant": "header", "kind": "main", "stage": "how", "group": "people"},
            {"id": money_id, "label": "跟进与机会", "type": "box", "variant": "header", "kind": "main", "stage": "how", "group": "people"},
        ])
        edges.append({"from": people_header, "to": how_id, "label": "", "kind": "main"})
        edges.append({"from": people_header, "to": money_id, "label": "", "kind": "main"})
        ranks.append([how_id, money_id])
        people_nodes.extend([how_id, money_id])

        exp_id = "p3"
        exp_label = people_examples[0]
        nodes.append({"id": exp_id, "label": _wrap_label(exp_label, width=12), "type": "box", "variant": "pill", "kind": "main", "stage": "how", "group": "people"})
        edges.append({"from": how_id, "to": exp_id, "label": "", "kind": "main"})
        people_nodes.append(exp_id)

        mon_id = "p4"
        mon_label = people_examples[1] if len(people_examples) > 1 else "关注学习/社区"
        nodes.append({"id": mon_id, "label": _wrap_label(mon_label, width=12), "type": "box", "variant": "pill", "kind": "main", "stage": "how", "group": "people"})
        edges.append({"from": money_id, "to": mon_id, "label": "", "kind": "main"})
        people_nodes.append(mon_id)
        groups.append({"id": "people", "label": "普通人的参与", "nodes": people_nodes})

    # 旁注只放“门槛/成本/风险/收益”中具体的一两条
    callouts = _pick_callouts(summary, point_list, max_items=2)
    if callouts:
        anchor_id = "n2" if len(picked) >= 2 else "n1"
        for idx, text in enumerate(callouts, start=1):
            cid = f"c{idx}"
            nodes.append({"id": cid, "label": _wrap_label(text, width=12), "type": "note", "kind": "callout", "stage": "how", "group": "main"})
            edges.append({"from": cid, "to": anchor_id, "label": "", "kind": "callout"})

    diagram_spec = {"layout": "TB", "nodes": nodes, "edges": edges, "groups": groups, "ranks": ranks, "title_node": bool(title_text)}

    slot = ImageSlot(slot_type="cover", prompt="", diagram_spec=diagram_spec)
    return ImagePlan(count=min(1, max_count), slots=[slot])


def generate_images(settings: Settings, plan: ImagePlan, title: str) -> List[dict]:
    if not settings.image_prompt_enabled or plan.count <= 0:
        return []

    directory = _get_date_dir(settings)
    images: List[dict] = []
    for idx, slot in enumerate(plan.slots[:plan.count], start=1):
        file_name = _build_image_name(title, idx)
        url = None
        path = None
        if slot.diagram_spec:
            path = _render_graphviz_image(settings, slot.diagram_spec, title, directory, file_name)
        if not path and slot.prompt:
            url, path = _generate_image(settings, slot.prompt, file_name)
        if url and not path:
            downloaded = _download_image(url, directory, file_name)
            path = downloaded
        if not path and not url:
            logger.warning(f"图片生成失败: prompt={slot.prompt}")
            continue
        images.append({
            "slot": slot.slot_type,
            "prompt": slot.prompt,
            "diagram": slot.diagram_spec,
            "url": url,
            "path": path,
        })
    return images
