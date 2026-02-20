import concurrent.futures
import datetime as dt
import hashlib
import json
import logging
import os
import re
from typing import List, Dict, Optional, Mapping
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests
import yaml

from ..config import Settings
from ..db import get_conn

logger = logging.getLogger("rss_collector")

DROP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "ref",
    "ref_src",
    "fbclid",
    "gclid",
    "igshid",
    "spm",
    "mc_cid",
    "mc_eid",
}

def load_sources(path: str) -> List[Dict]:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    if not isinstance(data, list):
        raise ValueError("rss_sources.yaml must be a list of sources")
    return data

def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    filtered = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in DROP_QUERY_PARAMS]
    query = urlencode(filtered, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))

def extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return ""
    return parts.netloc.lower() if parts.netloc else ""

def normalize_title(title: str) -> str:
    if not title:
        return ""
    return re.sub(r"\s+", " ", title.strip().lower())

def build_content_snapshot(title: str, summary: str, max_len: int = 800) -> str:
    combined = f"{title}\n{summary}".strip()
    if len(combined) <= max_len:
        return combined
    return combined[:max_len]

def extract_headers(headers: Mapping[str, str]) -> Dict:
    return {
        "etag": headers.get("ETag") or headers.get("Etag"),
        "last_modified": headers.get("Last-Modified"),
        "content_type": headers.get("Content-Type"),
    }

def parse_published_at(value: object) -> dt.datetime:
    if isinstance(value, (list, tuple)) and len(value) >= 6:
        try:
            parts = [int(v) for v in value[:6]]
            return dt.datetime(*parts, tzinfo=dt.timezone.utc)
        except Exception:
            return dt.datetime.now(dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)

def fetch_feed(url: str, tags: List[str]) -> List[Dict]:
    logger.info(f"Starting fetch for {url}...")
    try:
        # 使用超时避免阻塞
        # 10 秒连接，45 秒读取
        resp = requests.get(url, timeout=(10.0, 45.0), headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code != 200:
            logger.error(f"Failed to fetch {url}, status: {resp.status_code}")
            return []
            
        f = feedparser.parse(resp.content)
        header_info = extract_headers(resp.headers)
        
        items = []
        # 最多处理前 100 条
        for entry in f.entries[:100]:
            # 处理日期
            published_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
            pub_date = parse_published_at(published_parsed)
            
            # 内容摘要
            summary = str(entry.get('summary', '') or entry.get('description', '') or '')
            title = str(entry.get('title', 'No Title') or 'No Title')
            url_link = str(entry.get('link', '') or '')
            content_snapshot = build_content_snapshot(title, summary)
            
            items.append({
                'title': title,
                'url': url_link,
                'summary': summary,
                'published_at': pub_date,
                'source_tags': tags,
                'source_feed_url': url,
                'http_status': resp.status_code,
                'retrieved_headers': header_info,
                'render_mode': 'rss',
                'provider_chain': ['feedparser'],
                'content_snapshot': content_snapshot,
            })
        return items
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return []

def run(settings: Settings):
    candidates = [
        settings.rss_sources_file,
        "/opt/ai_briefing/configs/rss_sources.yaml",
        "./configs/rss_sources.yaml",
    ]
    sources_path = next((p for p in candidates if p and os.path.exists(p)), settings.rss_sources_file)
    if not os.path.exists(sources_path):
        logger.error(f"Failed to load sources: file not found: {sources_path}")
        return
    if settings.rss_sources_file and sources_path != settings.rss_sources_file:
        logger.info(f"已切换到可用的 RSS 源文件: {sources_path}")
    logger.info(f"Loading sources from {sources_path}")
    try:
        sources = load_sources(sources_path)
    except Exception as e:
        logger.error(f"Failed to load sources: {e}")
        return

    items_to_save = []
    
    # 并发抓取（限制线程数保证稳定）
    worker_count = max(1, min(settings.rss_max_workers, len(sources)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_source = {}
        for src in sources:
            url = src.get('url')
            if not url:
                logger.warning(f"Skipping source with missing url: {src}")
                continue
            future_to_source[executor.submit(fetch_feed, url, src.get('tags', []))] = src
        
        for future in concurrent.futures.as_completed(future_to_source):
            src = future_to_source[future]
            try:
                # 写入来源名称便于存储
                fetched = future.result()
                for item in fetched:
                    item['source_name'] = src.get('name', 'Unknown Source')
                items_to_save.extend(fetched)
                logger.info(f"Fetched {len(fetched)} items from {src.get('name', 'Unknown Source')}")
            except Exception as e:
                logger.error(f"Error fetching {src.get('name', 'Unknown Source')}: {e}")

    new_count = 0
    dup_count = 0
    skip_count = 0
    conn = get_conn(settings)
    try:
        with conn.cursor() as cur:
            for item in items_to_save:
                url = (item.get('url') or "").strip()
                canonical_url = canonicalize_url(url)
                domain = extract_domain(canonical_url or url)
                title = item.get('title', '').strip()
                summary = item.get('summary', '').strip()
                published_at = item.get('published_at')

                hash_source = canonical_url or f"{normalize_title(title)}|{domain}"
                if not hash_source.strip():
                    skip_count += 1
                    logger.warning("Skipping item with empty hash source")
                    continue
                hash_key = hashlib.md5(hash_source.encode('utf-8')).hexdigest()

                raw = {
                    "source_tags": item.get("source_tags", []),
                    "source_name": item.get("source_name", ""),
                }

                raw_payload = {
                    "title": title,
                    "url": url or canonical_url,
                    "summary": summary,
                    "published_at": published_at.isoformat() if published_at else None,
                    "source_tags": item.get("source_tags", []),
                    "source_name": item.get("source_name", ""),
                    "feed_url": item.get("source_feed_url", ""),
                }

                raw_item_id: Optional[int] = None
                try:
                    cur.execute("""
                        INSERT INTO raw_items (
                            source_kind, source_ref, source_url, retrieved_at, http_status, retrieved_headers,
                            render_mode, provider_chain, content_snapshot, raw_payload
                        )
                        VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        "rss",
                        item.get("source_feed_url"),
                        url or canonical_url,
                        item.get("http_status"),
                        json.dumps(item.get("retrieved_headers") or {}, ensure_ascii=False),
                        item.get("render_mode") or "rss",
                        item.get("provider_chain") or ["feedparser"],
                        item.get("content_snapshot") or build_content_snapshot(title, summary),
                        json.dumps(raw_payload, ensure_ascii=False),
                    ))
                    row = cur.fetchone()
                    if row:
                        raw_item_id = row[0]
                except Exception as ex:
                    logger.error(f"Error inserting raw_item {url}: {ex}")

                try:
                    cur.execute("""
                        INSERT INTO items (hash_key, url, canonical_url, title, summary, source, published_at, fetched_at, domain, raw, raw_item_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        hash_key,
                        url or canonical_url,
                        canonical_url or None,
                        title or "No Title",
                        summary,
                        item.get('source_name', 'Unknown Source'),
                        published_at,
                        domain or None,
                        json.dumps(raw, ensure_ascii=False),
                        raw_item_id,
                    ))
                    if cur.rowcount:
                        new_count += 1
                    else:
                        dup_count += 1
                except Exception as ex:
                    logger.error(f"Error inserting item {url}: {ex}")
        conn.commit()
    except Exception as e:
        logger.error(f"Database error in RSS run: {e}")
        conn.rollback()
    finally:
        conn.close()

    logger.info(f"Collected {new_count} new items (Multi-threaded). Duplicates: {dup_count}, Skipped: {skip_count}.")
