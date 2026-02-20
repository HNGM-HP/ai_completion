import json
import datetime as dt
import logging
from dotenv import load_dotenv

load_dotenv()

from ai_briefing.config import Settings, get_settings
from ai_briefing.collector import rss
from ai_briefing.ranker import news as news_ranker
from ai_briefing.briefing import generator
from ai_briefing.briefing.dedup import getRecentBriefRefIds
from ai_briefing.db import get_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rss_only")

def _serialize_list(value):
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        return value
    return None

def _normalize_tags(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []

def run():
    settings = get_settings()
    logger.info("Starting RSS Collector...")
    try:
        rss.run(settings)
    except Exception as e:
        logger.error(f"RSS failed: {e}")
        
    logger.info("Clustering...")
    try:
        news_ranker.cluster_news(settings, hours=settings.news_window_hours)
        news_ranker.score_clusters(settings, hours=settings.news_window_hours)
    except Exception as e:
        logger.error(f"Clustering failed: {e}")
        
    top_clusters = news_ranker.get_top_clusters_with_backfill(settings, limit=settings.daily_top_news)
    cluster_by_id = {c['id']: c for c in top_clusters}
    logger.info(f"Selected {len(top_clusters)} top news clusters.")

    logger.info("Generating News Briefs...")
    clusterIds = [c['id'] for c in top_clusters]
    skipClusterIds = getRecentBriefRefIds(settings, "news", clusterIds, settings.brief_dedup_hours)
    clusterCandidates = [c for c in top_clusters if c['id'] not in skipClusterIds]
    logger.info(f"新闻候选 {len(top_clusters)}，去重 {len(skipClusterIds)}，生成 {len(clusterCandidates)}")

    news_briefs = generator.generate_news_briefs(settings, clusterCandidates)
    
    # 写入新闻简报
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            for b in news_briefs:
                cluster_info = cluster_by_id.get(b['source_id'], {})
                title = cluster_info.get('title') or b['content'].get('one_liner', 'News Update')
                if settings.brief_dedup_hours > 0:
                    cur.execute(
                        "SELECT id FROM briefs WHERE kind='news' AND ref_id=%s AND created_at > NOW() - (%s || ' hours')::interval",
                        (str(b['source_id']), settings.brief_dedup_hours)
                    )
                    if cur.fetchone():
                        continue

                cur.execute("""
                    INSERT INTO briefs (kind, ref_id, title, one_liner, why_matters, bullets, tags, created_at, url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    'news',
                    b['source_id'],
                    title,
                    b['content'].get('one_liner'),
                    _serialize_list(b['content'].get('why_matters')),
                    json.dumps(b['content'].get('key_features', []), ensure_ascii=False),
                    _normalize_tags(b['content'].get('tags', [])),
                    b['created_at'],
                    b['content'].get('url', '')
                ))
        conn.commit()
    logger.info(f"Saved {len(news_briefs)} news briefs to DB.")

    logger.info("Done.")

if __name__ == "__main__":
    run()
