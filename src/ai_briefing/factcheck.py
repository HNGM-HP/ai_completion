from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Dict, List, Optional

from .branch_specs import load_branch_specs
from .briefing.llm import get_llm
from .config import Settings
from .db import get_conn


logger = logging.getLogger("factcheck")


def _extract_json(text: str) -> Dict:
    if not text:
        raise ValueError("Empty LLM response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _normalize_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []


def _normalize_confidence(value: float | int | str | None) -> float:
    if isinstance(value, (int, float)):
        conf = float(value)
    elif isinstance(value, str):
        try:
            conf = float(value.strip())
        except Exception:
            return 0.0
    else:
        return 0.0
    if conf < 0.0:
        return 0.0
    if conf > 1.0:
        return 1.0
    return conf


def _build_factcheck_prompt(cluster: Dict, evidence_lines: List[str]) -> str:
    evidence_text = "\n".join([f"- {line}" for line in evidence_lines])
    return f"""
你是一名严格的事实核验员，请根据以下证据片段，对主题中的可证伪陈述进行核验。

主题: {cluster.get('title', '')}

证据片段:
{evidence_text}

输出要求：
1) claims: 每条一句话、可证伪
2) evidence: 每条包含 url 和 snippet（必须来自上面的证据片段）
3) confidence: 0~1 之间的小数
4) open_questions: 无法核验的点

只输出 JSON 对象：
{{
  "claims": ["..."],
  "evidence": [{{"url": "...", "snippet": "..."}}],
  "confidence": 0.0,
  "open_questions": ["..."]
}}
"""


def _collect_evidence_lines(cur, items: List[Dict], max_items: int = 6) -> List[str]:
    raw_ids = [i.get("raw_item_id") for i in items if i.get("raw_item_id")]
    raw_map: Dict[int, Dict] = {}
    if raw_ids:
        cur.execute(
            "SELECT id, content_snapshot, source_url FROM raw_items WHERE id = ANY(%s)",
            (raw_ids,),
        )
        for row in cur.fetchall():
            raw_map[row[0]] = {
                "snapshot": row[1] or "",
                "source_url": row[2] or "",
            }

    evidence_lines: List[str] = []
    for item in items:
        if len(evidence_lines) >= max_items:
            break
        raw_item_id = item.get("raw_item_id")
        raw_info = raw_map.get(raw_item_id) if raw_item_id else None
        url = item.get("url") or (raw_info.get("source_url") if raw_info else "")
        snippet = (raw_info.get("snapshot") if raw_info else "") or item.get("summary") or ""
        title = item.get("title") or ""
        line = f"{title} | {url} | {snippet}".strip(" |")
        if line:
            evidence_lines.append(line)

    return evidence_lines


def _get_status(confidence: float, low: float, high: float) -> str:
    if confidence >= high:
        return "pass"
    if confidence >= low:
        return "warn"
    return "review"


def run_factcheck_for_clusters(settings: Settings, clusters: List[Dict]) -> Dict[int, Dict]:
    specs = load_branch_specs(settings.branch_specs_file)
    factcheck_cfg = specs.raw.get("factcheck") or {}
    enabled = factcheck_cfg.get("enabled", True)
    raw_max = factcheck_cfg.get("max_evidence")
    if isinstance(raw_max, int):
        max_evidence = raw_max
    elif isinstance(raw_max, str):
        try:
            max_evidence = int(raw_max)
        except Exception:
            max_evidence = 6
    else:
        max_evidence = 6
    if not enabled:
        return {}

    llm = get_llm(settings, "factcheck")
    results: Dict[int, Dict] = {}

    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            for cluster in clusters:
                cluster_id_value = cluster.get("id")
                if isinstance(cluster_id_value, int):
                    cluster_id_int = cluster_id_value
                elif isinstance(cluster_id_value, str):
                    try:
                        cluster_id_int = int(cluster_id_value)
                    except Exception:
                        continue
                else:
                    continue

                items = cluster.get("items", [])
                evidence_lines = _collect_evidence_lines(cur, items, max_items=max_evidence)
                if not evidence_lines:
                    continue

                prompt = _build_factcheck_prompt(cluster, evidence_lines)
                try:
                    response_text = llm.generate(prompt)
                    parsed = _extract_json(response_text)
                except Exception as e:
                    logger.warning(f"事实核验失败: {cluster.get('id')}, {e}")
                    parsed = {
                        "claims": [],
                        "evidence": [],
                        "confidence": 0.0,
                        "open_questions": ["事实核验失败"],
                    }

                claims = _normalize_list(parsed.get("claims"))
                evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
                open_questions = _normalize_list(parsed.get("open_questions"))
                confidence = _normalize_confidence(parsed.get("confidence"))

                status = _get_status(confidence, specs.confidence_thresholds.low, specs.confidence_thresholds.high)
                cur.execute(
                    """
                    INSERT INTO factchecks (topic_kind, topic_ref_id, claims, evidence, confidence, open_questions, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        "news",
                        cluster_id_int,
                        json.dumps(claims, ensure_ascii=False),
                        json.dumps(evidence, ensure_ascii=False),
                        confidence,
                        json.dumps(open_questions, ensure_ascii=False),
                        status,
                        dt.datetime.now(dt.timezone.utc),
                    ),
                )
                row = cur.fetchone()
                if row:
                    results[cluster_id_int] = {
                        "id": row[0],
                        "status": status,
                        "confidence": confidence,
                    }
        conn.commit()

    return results
