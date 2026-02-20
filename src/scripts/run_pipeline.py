import sys
import json
import datetime as dt
import logging
from dotenv import load_dotenv

# 在加载配置前先读取环境变量
load_dotenv()

from ai_briefing.config import Settings, get_settings
from ai_briefing.collector import github, rss
from ai_briefing.ranker import repo as ranker
from ai_briefing.ranker import news as news_ranker
from ai_briefing.briefing import generator
from ai_briefing.briefing.dedup import getRecentBriefRefIds
from ai_briefing.pusher import main as pusher
from ai_briefing.db import get_conn

# 初始化日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pipeline")

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

def run_github_pipeline():
    settings = get_settings()
    
    # 1. 采集
    logger.info("Starting GitHub Collector...")
    try:
        github.run(settings)
    except Exception as e:
        logger.error(f"Collector failed: {e}")
        # 采集失败直接终止
        sys.exit(1)

    # 2. 排序
    logger.info("Ranking Repos...")
    top_repos = ranker.get_top_repos(settings, limit=settings.daily_top_repos)
    logger.info(f"Selected {len(top_repos)} top repos.")

    # 3. 生成简报
    logger.info("Generating Briefs...")
    repoIds = [repo['id'] for repo in top_repos]
    skipRepoIds = getRecentBriefRefIds(settings, "repo", repoIds, settings.brief_dedup_hours)
    repoCandidates = [repo for repo in top_repos if repo['id'] not in skipRepoIds]
    logger.info(f"Repo 候选 {len(top_repos)}，去重 {len(skipRepoIds)}，生成 {len(repoCandidates)}")

    briefs_data = generator.generate_repo_briefs(settings, repoCandidates)
    repo_by_id = {repo['id']: repo for repo in repoCandidates}
    
    # 写入简报到数据库
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            for b in briefs_data:
                # 按 briefs 表结构写入
                repo_info = repo_by_id.get(b['source_id'], {})
                title = repo_info.get('full_name') or b['content'].get('one_liner', 'Repo Update')
                if settings.brief_dedup_hours > 0:
                    cur.execute(
                        "SELECT id FROM briefs WHERE kind='repo' AND ref_id=%s AND created_at > NOW() - (%s || ' hours')::interval",
                        (str(b['source_id']), settings.brief_dedup_hours)
                    )
                    if cur.fetchone():
                        continue

                cur.execute("""
                    INSERT INTO briefs (kind, ref_id, title, one_liner, why_matters, bullets, tags, created_at, url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    'repo',
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
    logger.info(f"Saved {len(briefs_data)} briefs to DB.")

    # ==========================
    # 阶段 2：RSS & 新闻
    # ==========================
    logger.info("Starting RSS Collector...")
    try:
        rss.run(settings)
    except Exception as e:
        logger.error(f"RSS Collector failed: {e}")
        # 采集失败仍可尝试基于旧数据继续

    logger.info("Clustering & Scoring News...")
    news_ranker.cluster_news(settings, hours=settings.news_window_hours)
    news_ranker.score_clusters(settings, hours=settings.news_window_hours)
    
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

    # 4. 推送
    logger.info("Pushing to Feishu...")
    pusher.push_pending_briefs(settings)
    logger.info("Done.")

if __name__ == "__main__":
    run_github_pipeline()
