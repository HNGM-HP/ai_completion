import datetime as dt
import json
import hashlib
from typing import List, Dict
import logging
from urllib.parse import urlsplit
from rapidfuzz import fuzz
from ..db import get_conn
from ..config import Settings

logger = logging.getLogger("news_ranker")

SIMILARITY_THRESHOLD = 70.0

VALUE_SIGNALS = {
    "monetization": (3.5, [
        "变现", "赚钱", "盈利", "营收", "订阅", "付费", "价格", "pricing", "revenue", "monetiz", "roi",
    ]),
    "productivity": (3.0, [
        "效率", "自动化", "workflow", "agent", "copilot", "节省时间", "降本", "提效", "automation",
    ]),
    "learning": (2.5, [
        "学习", "教程", "课程", "指南", "教学", "education", "guide", "tutorial", "course",
    ]),
    "consumer_value": (2.5, [
        "工具", "app", "应用", "插件", "个人", "家庭", "生活", "体验", "product", "tool", "assistant",
        "开源", "open-source", "open source", "免费", "free",
    ]),
    "safety_compliance": (2.0, [
        "安全", "隐私", "合规", "security", "privacy", "compliance", "风险", "审计",
    ]),
    "business_enablement": (2.0, [
        "商业", "创业", "客户", "企业", "b2b", "go-to-market", "gtm", "growth",
    ]),
}

OFFICIAL_DOMAINS = {
    "openai.com",
    "ai.googleblog.com",
    "deepmind.google",
    "research.google",
    "huggingface.co",
    "blogs.microsoft.com",
    "blogs.nvidia.com",
    "aws.amazon.com",
    "ai.meta.com",
    "anthropic.com",
    "stability.ai",
}

CODE_DOMAINS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
}

PAPER_DOMAINS = {
    "arxiv.org",
    "openreview.net",
    "papers.nips.cc",
    "aclanthology.org",
}

AUTHORITY_DOMAINS = {
    "nature.com",
    "science.org",
    "sciencedirect.com",
    "ieee.org",
    "acm.org",
}

COMMUNITY_DOMAINS = {
    "news.ycombinator.com",
    "reddit.com",
    "lobste.rs",
    "medium.com",
    "towardsdatascience.com",
}

def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()

def _get_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return ""
    return parts.netloc.lower() if parts.netloc else ""

def _stable_hash(text: str, seed: str) -> int:
    value = f"{seed}|{text}".encode("utf-8")
    return int(hashlib.md5(value).hexdigest(), 16)

def _link_priority(domain: str) -> int:
    if domain in OFFICIAL_DOMAINS:
        return 4
    if domain in CODE_DOMAINS or domain in PAPER_DOMAINS:
        return 3
    if domain in AUTHORITY_DOMAINS:
        return 2
    if domain in COMMUNITY_DOMAINS:
        return 1
    return 1

def _select_evidence_links(candidates: List[Dict], min_count: int = 3, max_count: int = 5) -> List[str]:
    evidence: List[str] = []
    seen_domains: set[str] = set()

    for c in candidates:
        if c["url"] in evidence:
            continue
        if c["domain"] in seen_domains:
            continue
        evidence.append(c["url"])
        seen_domains.add(c["domain"])
        if len(evidence) >= min_count:
            break

    if len(evidence) < min_count:
        for c in candidates:
            if c["url"] in evidence:
                continue
            evidence.append(c["url"])
            if len(evidence) >= min_count:
                break

    return evidence[:max_count]

def _select_cluster_links(cluster_id: int, items: List[Dict]) -> Dict:
    candidates: List[Dict] = []
    for item in items:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        domain = _get_domain(url) or (item.get("domain") or "").strip().lower()
        if not domain:
            continue
        candidates.append({
            "url": url,
            "domain": domain,
        })

    if not candidates:
        return {
            "primary_link": "",
            "evidence_links": [],
            "debug": {"candidate_count": 0, "filtered_arxiv": False},
        }

    non_arxiv = [c for c in candidates if c["domain"] != "arxiv.org"]
    filtered = non_arxiv if non_arxiv else candidates

    seed = str(cluster_id)
    for c in filtered:
        c["priority"] = _link_priority(c["domain"])
        c["tie"] = _stable_hash(c["url"], seed)

    ordered = sorted(filtered, key=lambda c: (-c["priority"], c["tie"]))
    primary = ordered[0]["url"] if ordered else ""
    evidence = _select_evidence_links(ordered)
    primary_domain = ordered[0]["domain"] if ordered else ""
    primary_priority = ordered[0]["priority"] if ordered else 0
    priority_label = {
        4: "official",
        3: "code_or_paper",
        2: "authority",
        1: "community",
    }.get(primary_priority, "community")

    debug = {
        "candidate_count": len(candidates),
        "filtered_arxiv": bool(non_arxiv),
        "primary_domain": primary_domain,
        "primary_priority": priority_label,
    }

    return {
        "primary_link": primary,
        "evidence_links": evidence,
        "debug": debug,
    }

def _window_hours(hours: int) -> int:
    try:
        hours = int(hours)
    except Exception:
        hours = 72
    return max(hours, 6)

def _value_score(text: str) -> float:
    normalized = _normalize_text(text)
    score = 0.0
    for _, (weight, keywords) in VALUE_SIGNALS.items():
        if any(k in normalized for k in keywords):
            score += weight
    return score

def _value_signals(text: str) -> List[str]:
    normalized = _normalize_text(text)
    signals = []
    for key, (_, keywords) in VALUE_SIGNALS.items():
        if any(k in normalized for k in keywords):
            signals.append(key)
    return signals

def cluster_news(settings: Settings, hours: int = 24, similarity_threshold: float = SIMILARITY_THRESHOLD):
    """
    Cluster news items from the last N hours.
    """
    window_hours = _window_hours(hours)
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            # 1. 读取近期活跃的聚类
            cur.execute("""
                SELECT id, title, last_seen_at FROM clusters 
                WHERE last_seen_at > NOW() - (%s || ' hours')::interval
            """, (window_hours,))
            active_clusters = [{'id': r[0], 'title': r[1]} for r in cur.fetchall()]
            
            # 2. 读取最近 N 小时未聚类的条目
            cur.execute("""
                SELECT id, title, COALESCE(domain, source) AS src, COALESCE(published_at, fetched_at) AS ts
                FROM items 
                WHERE cluster_id IS NULL 
                  AND COALESCE(published_at, fetched_at) > NOW() - (%s || ' hours')::interval
                ORDER BY ts DESC
            """, (window_hours,))
            items = [{'id': r[0], 'title': r[1], 'source': r[2], 'published_at': r[3]} for r in cur.fetchall()]
            
            logger.info(f"Found {len(items)} unclustered items.")
            
            for item in items:
                best_match = None
                best_score = 0
                
                # 尝试匹配已有聚类
                for cluster in active_clusters:
                    score = fuzz.token_set_ratio(item['title'], cluster['title'])
                    if score > best_score:
                        best_score = score
                        best_match = cluster
                
                if best_match and best_score >= similarity_threshold:
                    # 归入已有聚类
                    cur.execute("UPDATE items SET cluster_id = %s WHERE id = %s", (best_match['id'], item['id']))
                    # 更新聚类最近出现时间
                    cur.execute("UPDATE clusters SET last_seen_at = GREATEST(last_seen_at, %s) WHERE id = %s", (item['published_at'], best_match['id']))
                else:
                    # 新建聚类
                    # 字段: title, first_seen_at, last_seen_at, score, kind
                    cur.execute("""
                        INSERT INTO clusters (title, first_seen_at, last_seen_at, score, kind)
                        VALUES (%s, %s, %s, 0, 'news')
                        RETURNING id
                    """, (item['title'], item['published_at'], item['published_at']))
                    row = cur.fetchone()
                    if not row:
                        continue
                    new_cid = row[0]
                    
                    cur.execute("UPDATE items SET cluster_id = %s WHERE id = %s", (new_cid, item['id']))
                    
                    active_clusters.append({'id': new_cid, 'title': item['title']})

            # 更新聚类的条目数与最新时间
            cur.execute("""
                UPDATE clusters AS c
                SET item_count = s.item_count,
                    last_seen_at = s.last_seen_at
                FROM (
                    SELECT cluster_id,
                           COUNT(*) AS item_count,
                           MAX(COALESCE(published_at, fetched_at)) AS last_seen_at
                    FROM items
                    WHERE cluster_id IS NOT NULL
                    GROUP BY cluster_id
                ) AS s
                WHERE c.id = s.cluster_id
                  AND c.last_seen_at > NOW() - (%s || ' hours')::interval
            """, (window_hours,))

        conn.commit()

def score_clusters(settings: Settings, hours: int = 72):
    """
    Calculate score for clusters based on item count, diversity, freshness.
    """
    window_hours = _window_hours(hours)
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            # 读取最近 N 小时内的聚类
            cur.execute("""
                SELECT id, first_seen_at, last_seen_at FROM clusters
                WHERE last_seen_at > NOW() - (%s || ' hours')::interval
            """, (window_hours,))
            clusters = cur.fetchall()
            
            for cid, created_at, last_seen_at in clusters:
                # 读取聚类内条目
                cur.execute("SELECT title, summary, COALESCE(domain, source), COALESCE(published_at, fetched_at) FROM items WHERE cluster_id = %s", (cid,))
                items = cur.fetchall()
                count = len(items)
                if count == 0:
                    continue
                
                # 来源多样性（域名）
                sources = set(i[2] for i in items if i[2])
                sourceCount = len(sources)
                officialCount = len([s for s in sources if s in OFFICIAL_DOMAINS])
                sourceQuality = "official" if officialCount > 0 else "community"
                if officialCount > 0 and officialCount < sourceCount:
                    sourceQuality = "mixed"
                
                # 价值信号（对普通人有用）
                text_blob = " ".join([f"{i[0]} {i[1] or ''}" for i in items])
                value_score = _value_score(text_blob)
                valueSignals = _value_signals(text_blob)

                # 时效性
                now = dt.datetime.now(dt.timezone.utc)
                last_seen_at = last_seen_at or created_at or now
                hours_since = max(0.0, (now - last_seen_at).total_seconds() / 3600.0)
                freshness_score = max(0.0, (window_hours - hours_since) / window_hours)

                # 用户反馈（近 30 天）
                cur.execute("""
                    SELECT label, COUNT(*)
                    FROM user_feedback
                    WHERE topic_kind = 'news'
                      AND topic_ref_id = %s
                      AND created_at > NOW() - INTERVAL '30 DAYS'
                    GROUP BY label
                """, (cid,))
                feedback_counts = {row[0]: row[1] for row in cur.fetchall()}
                feedback_score = (
                    feedback_counts.get("useful", 0) * 2.0
                    - feedback_counts.get("useless", 0) * 2.0
                    - feedback_counts.get("skip", 0) * 5.0
                )

                # 评分公式：优先普通人价值
                score = (count * 1.0) + (sourceCount * 2.0) + (value_score * 5.0) + (freshness_score * 3.0)
                score += feedback_score

                meta = {
                    "value_signals": valueSignals,
                    "value_score": value_score,
                    "source_count": sourceCount,
                    "source_quality": sourceQuality,
                    "item_count": count,
                    "freshness_score": freshness_score,
                    "feedback_score": feedback_score,
                    "feedback_counts": feedback_counts,
                }
                
                cur.execute("UPDATE clusters SET score = %s, meta = %s WHERE id = %s", (score, json.dumps(meta, ensure_ascii=False), cid))
        conn.commit()

def get_top_clusters(settings: Settings, limit: int = 5, hours: int = 72) -> List[Dict]:
    """
    Get top N news clusters with their items.
    """
    window_hours = _window_hours(hours)
    results = []
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            # 1. 获取已发送的聚类 ID，避免重复
            cur.execute("""
                SELECT ref_id FROM briefs 
                WHERE kind = 'news' 
                  AND created_at > NOW() - INTERVAL '24 HOURS'
            """)
            sent_ids = [r[0] for r in cur.fetchall()]

            # 2. 获取用户明确跳过的聚类（近 30 天）
            cur.execute("""
                SELECT DISTINCT topic_ref_id FROM user_feedback
                WHERE topic_kind = 'news'
                  AND label = 'skip'
                  AND created_at > NOW() - INTERVAL '30 DAYS'
            """)
            skip_ids = [r[0] for r in cur.fetchall()]
            
            # 2. 查询未发送的高分聚类
            base_query = """
                SELECT id, title, score, first_seen_at FROM clusters
                WHERE last_seen_at > NOW() - (%s || ' hours')::interval
            """
            params: List = [window_hours]
            if sent_ids:
                base_query += " AND id != ANY(%s)"
                params.append(sent_ids)
            if skip_ids:
                base_query += " AND id != ANY(%s)"
                params.append(skip_ids)
            base_query += " ORDER BY score DESC LIMIT %s "
            params.append(limit)
            cur.execute(base_query, tuple(params))
            rows = cur.fetchall()
            
            for row in rows:
                cid = row[0]
                cluster = {
                    'id': cid,
                    'title': row[1],
                    'score': row[2],
                    'created_at': row[3], # 实际为 first_seen_at
                    'items': []
                }
                
                # 获取聚类内条目
                cur.execute("""
                    SELECT title, url, COALESCE(domain, source), summary, COALESCE(published_at, fetched_at), raw_item_id
                    FROM items WHERE cluster_id = %s
                    ORDER BY COALESCE(published_at, fetched_at) DESC
                    LIMIT 5
                """, (cid,))
                items_rows = cur.fetchall()
                for ir in items_rows:
                    cluster['items'].append({
                        'title': ir[0],
                        'url': ir[1],
                        'source': ir[2],
                        'summary': ir[3],
                        'published_at': ir[4],
                        'raw_item_id': ir[5],
                    })

                cur.execute("""
                    SELECT url, COALESCE(domain, source) AS domain
                    FROM items WHERE cluster_id = %s
                    ORDER BY COALESCE(published_at, fetched_at) DESC
                    LIMIT 20
                """, (cid,))
                link_items = [
                    {"url": r[0], "domain": r[1]} for r in cur.fetchall()
                ]
                links = _select_cluster_links(cid, link_items)
                cluster["primary_link"] = links["primary_link"]
                cluster["evidence_links"] = links["evidence_links"]

                cur.execute(
                    "UPDATE clusters SET primary_link = %s, evidence_links = %s, link_select_debug = %s WHERE id = %s",
                    (
                        links["primary_link"],
                        json.dumps(links["evidence_links"], ensure_ascii=False),
                        json.dumps(links["debug"], ensure_ascii=False),
                        cid,
                    ),
                )
                
                results.append(cluster)
    return results

def get_top_clusters_with_backfill(settings: Settings, limit: int) -> List[Dict]:
    windowHours = settings.news_window_hours
    threshold = SIMILARITY_THRESHOLD
    stepCount = 0

    results = get_top_clusters(settings, limit=limit, hours=windowHours)
    if len(results) >= limit:
        return results

    while stepCount < settings.news_backfill_max_steps:
        stepCount += 1
        windowHours = windowHours * max(1, settings.news_backfill_window_multiplier)
        threshold = max(30.0, threshold - float(settings.news_backfill_threshold_step))
        logger.info(f"补齐步骤 {stepCount}: window={windowHours}h, threshold={threshold}")

        cluster_news(settings, hours=windowHours, similarity_threshold=threshold)
        score_clusters(settings, hours=windowHours)
        results = get_top_clusters(settings, limit=limit, hours=windowHours)
        if len(results) >= limit:
            break

    return results
