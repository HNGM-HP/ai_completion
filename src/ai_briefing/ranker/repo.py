import datetime as dt
from typing import List, Dict
from ..db import get_conn
from ..config import Settings

def calculate_repo_score(repo: Dict, snapshot_24h_ago: Dict) -> float:
    """
    Calculate a score for ranking repositories.
    Factors:
    - Star growth (24h)
    - Freshness (last pushed)
    - Open issues (signal of usage/feedback)
    """
    stars_now = repo['stars']
    stars_then = snapshot_24h_ago['stars'] if snapshot_24h_ago else 0
    
    delta_stars = stars_now - stars_then
    
    # 新鲜度：按天衰减
    last_pushed = repo['last_pushed_at']
    if isinstance(last_pushed, str):
        last_pushed = dt.datetime.fromisoformat(last_pushed.replace("Z", "+00:00"))
    
    now = dt.datetime.now(dt.timezone.utc)
    days_since_push = (now - last_pushed).days
    freshness_factor = 1.0 / (max(days_since_push, 1) ** 0.5) # 衰减函数

    # 评分公式
    # 基于涨星增长
    score = (delta_stars * 2.0) + (stars_now * 0.01) 
    score *= freshness_factor
    
    # Issues 加权（小权重，存在通常代表活跃度）
    score += min(repo['open_issues'], 50) * 0.1

    return score

def get_top_repos(settings: Settings, limit: int = 10):
    """
    Fetch repos, compare with snapshots, calculate score, and return Top N.
    """
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT topic_ref_id FROM user_feedback
                WHERE topic_kind = 'repo'
                  AND label = 'skip'
                  AND created_at > NOW() - INTERVAL '30 DAYS'
            """)
            skip_ids = {r[0] for r in cur.fetchall()}

            # 读取全部仓库
            cur.execute("""
                SELECT id, full_name, url, description, stars, forks, open_issues, last_pushed_at, language 
                FROM repos
            """)
            descs = cur.description or []
            if not descs:
                return []
            columns = [desc[0] for desc in descs]
            rows = cur.fetchall() or []
            repos = [dict(zip(columns, row)) for row in rows if row[0] not in skip_ids]
            
            scored_repos = []
            for repo in repos:
                cur.execute("""
                    SELECT label, COUNT(*)
                    FROM user_feedback
                    WHERE topic_kind = 'repo'
                      AND topic_ref_id = %s
                      AND created_at > NOW() - INTERVAL '30 DAYS'
                    GROUP BY label
                """, (repo['id'],))
                feedback_counts = {row[0]: row[1] for row in cur.fetchall()}
                feedback_score = (
                    feedback_counts.get("useful", 0) * 2.0
                    - feedback_counts.get("useless", 0) * 2.0
                    - feedback_counts.get("skip", 0) * 5.0
                )

                # 获取约 24 小时前快照
                cur.execute("""
                    SELECT stars, forks, open_issues, captured_at 
                    FROM repo_snapshots 
                    WHERE repo_id = %s 
                      AND captured_at >= NOW() - INTERVAL '30 HOURS'
                      AND captured_at <= NOW() - INTERVAL '20 HOURS'
                    ORDER BY captured_at DESC LIMIT 1
                """, (repo['id'],))
                
                snap = cur.fetchone()
                snapshot_24h = None
                if snap:
                    snapshot_24h = {
                        'stars': snap[0],
                        'forks': snap[1],
                        'open_issues': snap[2]
                    }
                else:
                    # 如果没有 24 小时前快照，默认增量为 0
                    snapshot_24h = {'stars': repo['stars']} # 等效为 0 增量
                
                score = calculate_repo_score(repo, snapshot_24h)
                score += feedback_score
                repo['score'] = score
                repo['delta_24h'] = repo['stars'] - snapshot_24h['stars']
                repo['feedback_score'] = feedback_score
                repo['feedback_counts'] = feedback_counts
                scored_repos.append(repo)
            
            # 按分数排序
            scored_repos.sort(key=lambda x: x['score'], reverse=True)
            
            return scored_repos[:limit]
