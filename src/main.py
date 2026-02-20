import argparse
import sys
import json
import datetime as dt
import logging
from dotenv import load_dotenv

# 读取环境变量
load_dotenv()

from ai_briefing.config import Settings, get_settings
from ai_briefing.collector import github, rss
from ai_briefing.ranker import repo as repo_ranker
from ai_briefing.ranker import news as news_ranker
from ai_briefing.briefing import generator
from ai_briefing.briefing.dedup import getRecentBriefRefIds
from ai_briefing.pusher import main as pusher
from ai_briefing import factcheck
from ai_briefing.branch_specs import load_branch_specs
from ai_briefing.output_builder import (
    build_branch1_output,
    build_branch2_output,
    build_branch1_repo_output,
    build_branch2_repo_output,
)
from ai_briefing.title_builder import build_news_title, build_repo_title
from ai_briefing.image_generation import build_graphviz_plan_from_content, generate_images
from ai_briefing.db import get_conn

# 初始化日志（强制输出到 stdout）
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
root_logger.addHandler(handler)
logger = logging.getLogger("main")

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

def _build_branch2_fallback(content: dict) -> dict:
    summary = content.get("one_liner") or ""
    points = content.get("key_features") or []
    if not isinstance(points, list):
        points = []
    return {
        "summary": summary,
        "points": points[:4],
        "quote_spans": [summary] if summary else [],
        "image_plan": {"count": 0, "slots": []},
    }

def run_github(settings: Settings):
    logger.info(">>> Starting GitHub Pipeline")
    
    # 1. 采集
    logger.info("Running GitHub Collector...")
    try:
        github.run(settings)
    except Exception as e:
        logger.error(f"GitHub Collector failed: {e}")
        
    # 2. 排序
    logger.info("Ranking Repos...")
    try:
        top_repos = repo_ranker.get_top_repos(settings, limit=settings.daily_top_repos)
        logger.info(f"Selected {len(top_repos)} top repos.")

        # 3. 生成简报
        repoIds = [repo['id'] for repo in top_repos]
        skipRepoIds = getRecentBriefRefIds(settings, "repo", repoIds, settings.brief_dedup_hours)
        repoCandidates = [repo for repo in top_repos if repo['id'] not in skipRepoIds]
        logger.info(f"Repo 候选 {len(top_repos)}，去重 {len(skipRepoIds)}，生成 {len(repoCandidates)}")

        if not repoCandidates:
            logger.info("Repo 候选为空，跳过生成。")
            return

        logger.info("Generating Repo Briefs...")
        briefs_data = generator.generate_repo_briefs(settings, repoCandidates)
        branch2_briefs = generator.generate_repo_briefs_branch2(settings, repoCandidates)
        branch2_by_id = {b["source_id"]: b for b in branch2_briefs}
        repo_by_id = {repo['id']: repo for repo in repoCandidates}
        
        specs = load_branch_specs(settings.branch_specs_file)
        # 写入 Repo 简报
        with get_conn(settings) as conn:
            with conn.cursor() as cur:
                new_saved = 0
                for b in briefs_data:
                    # 去重检查
                    if settings.brief_dedup_hours > 0:
                        cur.execute(
                            "SELECT id FROM briefs WHERE kind='repo' AND ref_id=%s AND created_at > NOW() - (%s || ' hours')::interval",
                            (str(b['source_id']), settings.brief_dedup_hours)
                        )
                        if cur.fetchone():
                            continue

                    repo_info = repo_by_id.get(b['source_id'], {})
                    title = build_repo_title(
                        repo_info.get('full_name', ''),
                        b['content'].get('one_liner', ''),
                        repo_info.get('description', ''),
                        b['content'].get('why_matters', []),
                    )
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
                    new_saved += 1

                    output_payloads = []
                    branch2_brief = None
                    branch2_content = None
                    if specs.raw.get("branch1", {}).get("enabled", True):
                        output_payloads.append((
                            "branch1",
                            build_branch1_repo_output(repo_info, b['content'], specs, title_override=title),
                        ))
                    if specs.raw.get("branch2", {}).get("enabled", True):
                        branch2_brief = branch2_by_id.get(b['source_id'])
                        if branch2_brief:
                            branch2_content = branch2_brief['content']
                            output_payloads.append((
                                "branch2",
                                build_branch2_repo_output(repo_info, branch2_content, specs, title_override=title),
                            ))
                        else:
                            fallback_content = _build_branch2_fallback(b['content'])
                            branch2_content = fallback_content
                            output_payloads.append((
                                "branch2",
                                build_branch2_repo_output(repo_info, fallback_content, specs, title_override=title),
                            ))

                    for branch, payload in output_payloads:
                        meta = payload.get("meta") or {}
                        if branch == "branch2" and branch2_content:
                            plan = build_graphviz_plan_from_content(branch2_content, title, settings.image_max_count)
                            images = generate_images(settings, plan, title)
                            slots: list[dict[str, object]] = []
                            for s in plan.slots:
                                slot_item: dict[str, object] = {"type": s.slot_type}
                                if s.diagram_spec:
                                    slot_item["diagram"] = s.diagram_spec
                                slots.append(slot_item)
                            meta["image_plan"] = {
                                "count": plan.count,
                                "slots": slots,
                            }
                            meta["images"] = images
                        status = "approved" if branch == "branch2" else "pending"
                        cur.execute(
                            """
                            INSERT INTO outputs (branch, topic_kind, topic_ref_id, factcheck_id, content, meta, status, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                branch,
                                "repo",
                                b['source_id'],
                                None,
                                payload["content"],
                                json.dumps(meta, ensure_ascii=False),
                                status,
                                b['created_at'],
                            ),
                        )
            conn.commit()
        logger.info(f"Saved {new_saved} repo briefs.")
    except Exception as e:
        logger.error(f"GitHub Pipeline failed during Ranking/Briefing: {e}")

def run_rss(settings: Settings, collect_only: bool = False, brief_only: bool = False):
    logger.info(">>> Starting RSS/News Pipeline")
    
    # 运行流程判定
    do_collect = not brief_only
    do_brief = not collect_only
    
    # 1. 采集
    if do_collect:
        logger.info("Running RSS Collector...")
        try:
            rss.run(settings)
        except Exception as e:
            logger.error(f"RSS Collector failed: {e}")

    # 2. 聚类/排序 & 3. 生成简报
    if do_brief:
        logger.info("Clustering & Scoring News...")
        try:
            news_ranker.cluster_news(settings, hours=settings.news_window_hours)
            news_ranker.score_clusters(settings, hours=settings.news_window_hours)

            top_clusters = news_ranker.get_top_clusters_with_backfill(settings, limit=settings.daily_top_news)
            cluster_by_id = {c['id']: c for c in top_clusters}
            logger.info(f"Selected {len(top_clusters)} top news clusters.")

            # 3. 生成简报
            clusterIds = [c['id'] for c in top_clusters]
            skipClusterIds = getRecentBriefRefIds(settings, "news", clusterIds, settings.brief_dedup_hours)
            clusterCandidates = [c for c in top_clusters if c['id'] not in skipClusterIds]
            logger.info(f"新闻候选 {len(top_clusters)}，去重 {len(skipClusterIds)}，生成 {len(clusterCandidates)}")

            if not clusterCandidates:
                logger.info("新闻候选为空，跳过生成。")
                return

            factcheck_results = {}
            try:
                factcheck_results = factcheck.run_factcheck_for_clusters(settings, clusterCandidates)
                logger.info(f"Factcheck 完成: {len(factcheck_results)}")
            except Exception as e:
                logger.error(f"Factcheck 失败: {e}")

            logger.info("Generating News Briefs...")
            news_briefs = generator.generate_news_briefs(settings, clusterCandidates)
            branch2_news_briefs = generator.generate_news_briefs_branch2(settings, clusterCandidates)
            branch2_news_by_id = {b["source_id"]: b for b in branch2_news_briefs}
            specs = load_branch_specs(settings.branch_specs_file)
            
            # 写入新闻简报
            with get_conn(settings) as conn:
                with conn.cursor() as cur:
                    new_saved = 0
                    for b in news_briefs:
                        # 去重检查
                        if settings.brief_dedup_hours > 0:
                            cur.execute(
                                "SELECT id FROM briefs WHERE kind='news' AND ref_id=%s AND created_at > NOW() - (%s || ' hours')::interval",
                                (str(b['source_id']), settings.brief_dedup_hours)
                            )
                            if cur.fetchone():
                                continue

                        cluster_info = cluster_by_id.get(b['source_id'], {})
                        title = build_news_title(
                            cluster_info.get('title', ''),
                            b['content'].get('one_liner', ''),
                            b['content'].get('why_matters', []),
                        )
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
                        new_saved += 1

                        factcheck_info = factcheck_results.get(int(b['source_id'])) if factcheck_results else None
                        factcheck_id = factcheck_info.get('id') if factcheck_info else None
                        factcheck_status = factcheck_info.get('status') if factcheck_info else None

                        output_payloads = []
                        branch2_news_brief = None
                        branch2_news_content = None
                        cluster_for_output = dict(cluster_info)
                        cluster_for_output["title"] = title
                        if specs.raw.get("branch1", {}).get("enabled", True):
                            output_payloads.append((
                                "branch1",
                                build_branch1_output(cluster_for_output, b['content'], specs, factcheck_status, title_override=title),
                            ))
                        if specs.raw.get("branch2", {}).get("enabled", True):
                            branch2_news_brief = branch2_news_by_id.get(b['source_id'])
                            if branch2_news_brief:
                                branch2_news_content = branch2_news_brief['content']
                                output_payloads.append((
                                    "branch2",
                                    build_branch2_output(cluster_for_output, branch2_news_content, specs, factcheck_status, title_override=title),
                                ))
                            else:
                                fallback_content = _build_branch2_fallback(b['content'])
                                branch2_news_content = fallback_content
                                output_payloads.append((
                                    "branch2",
                                    build_branch2_output(cluster_for_output, fallback_content, specs, factcheck_status, title_override=title),
                                ))

                        for branch, payload in output_payloads:
                            review_required = False
                            meta = payload.get("meta") or {}
                            if isinstance(meta, dict):
                                review_required = bool(meta.get("review_required"))
                            if branch == "branch2" and branch2_news_content:
                                plan = build_graphviz_plan_from_content(branch2_news_content, title, settings.image_max_count)
                                images = generate_images(settings, plan, title)
                                slots: list[dict[str, object]] = []
                                for s in plan.slots:
                                    slot_item: dict[str, object] = {"type": s.slot_type}
                                    if s.diagram_spec:
                                        slot_item["diagram"] = s.diagram_spec
                                    slots.append(slot_item)
                                meta["image_plan"] = {
                                    "count": plan.count,
                                    "slots": slots,
                                }
                                meta["images"] = images
                            if branch == "branch2":
                                status = "review" if review_required else "approved"
                            else:
                                status = "pending"
                            cur.execute(
                                """
                                INSERT INTO outputs (branch, topic_kind, topic_ref_id, factcheck_id, content, meta, status, created_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    branch,
                                    "news",
                                    b['source_id'],
                                    factcheck_id,
                                    payload["content"],
                                    json.dumps(meta, ensure_ascii=False),
                                    status,
                                    b['created_at'],
                                ),
                            )
                conn.commit()
            logger.info(f"Saved {new_saved} news briefs.")
        except Exception as e:
            logger.error(f"RSS Pipeline failed during Clustering/Briefing: {e}")

def run_pusher(settings: Settings):
    logger.info(">>> Starting Pusher")
    try:
        pusher.push_pending_outputs(settings)
    except Exception as e:
        logger.error(f"Pusher failed: {e}")

def main():
    parser = argparse.ArgumentParser(description="AI Briefing Pipeline Runner")
    parser.add_argument("--run-github", action="store_true", help="Run GitHub pipeline")
    parser.add_argument("--run-rss", action="store_true", help="Run RSS/News pipeline")
    parser.add_argument("--rss-collect-only", action="store_true", help="Run RSS Collector ONLY")
    parser.add_argument("--rss-brief-only", action="store_true", help="Run RSS Briefing ONLY (requires existing data)")
    parser.add_argument("--run-all", action="store_true", help="Run ALL pipelines")
    parser.add_argument("--push-only", action="store_true", help="Run Pusher ONLY (send pending briefs)")
    parser.add_argument("--no-push", action="store_true", help="Skip pushing to Feishu")
    
    args = parser.parse_args()
    
    settings = get_settings()
    
    if args.run_all:
        args.run_github = True
        args.run_rss = True
    
    if args.run_github:
        run_github(settings)
        
    if args.run_rss or args.rss_collect_only or args.rss_brief_only:
        run_rss(settings, collect_only=args.rss_collect_only, brief_only=args.rss_brief_only)
        
    # 自动推送逻辑：
    # 1. 未禁止推送（--no-push）
    # 2. 且执行了生成步骤（github/rss/run-all/rss-brief-only）
    is_generation_run = args.run_github or args.run_rss or args.run_all or args.rss_brief_only
    
    if args.push_only:
        run_pusher(settings)
    elif not args.no_push and is_generation_run:
        run_pusher(settings)
    elif not (is_generation_run or args.rss_collect_only):
        print("Please specify --run-github, --run-rss, --run-all, --push-only, or RSS sub-commands")
        parser.print_help()

if __name__ == "__main__":
    main()
