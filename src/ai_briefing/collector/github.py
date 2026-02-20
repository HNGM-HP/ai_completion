import datetime as dt
import json
import logging
import requests
from ..config import Settings
from ..db import get_conn

GQL_ENDPOINT = "https://api.github.com/graphql"

SEARCH_QUERIES = [
    'topic:llm stars:>200',
    'topic:rag stars:>100',
    'topic:agents stars:>100',
]

GQL = """
query($q:String!, $n:Int!, $cursor:String) {
  search(query:$q, type:REPOSITORY, first:$n, after:$cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on Repository {
        nameWithOwner
        url
        description
        stargazerCount
        forkCount
        issues(states:OPEN) { totalCount }
        primaryLanguage { name }
        repositoryTopics(first:20) { nodes { topic { name } } }
        createdAt
        pushedAt
        defaultBranchRef { name }
      }
    }
  }
}
"""

logger = logging.getLogger("github_collector")

def fetch_repos(settings: Settings, query: str, batch: int = 50, max_results: int = 100):
    headers = {"Authorization": f"Bearer {settings.github_token}"}
    cursor = None
    count = 0
    while True:
        if count >= max_results:
            break
        r = requests.post(
            GQL_ENDPOINT,
            json={"query": GQL, "variables": {"q": query, "n": batch, "cursor": cursor}},
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()["data"]["search"]
        for node in data["nodes"]:
            yield node
            count += 1
            if count >= max_results: 
                return
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]

def upsert_repo_and_snapshot(conn, repo: dict, captured_at: dt.datetime):
    topics = [n["topic"]["name"] for n in repo["repositoryTopics"]["nodes"]]
    full = repo["nameWithOwner"]

    raw_payload = {
        "full_name": full,
        "url": repo.get("url"),
        "description": repo.get("description"),
        "topics": topics,
        "language": repo["primaryLanguage"]["name"] if repo.get("primaryLanguage") else None,
        "stars": repo.get("stargazerCount"),
        "forks": repo.get("forkCount"),
        "open_issues": repo.get("issues", {}).get("totalCount"),
        "created_at": repo.get("createdAt"),
        "pushed_at": repo.get("pushedAt"),
        "default_branch": repo["defaultBranchRef"]["name"] if repo.get("defaultBranchRef") else None,
    }

    with conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO raw_items (
                    source_kind, source_ref, source_url, retrieved_at, http_status, retrieved_headers,
                    render_mode, provider_chain, content_snapshot, raw_payload
                )
                VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
            """, (
                "github",
                full,
                repo.get("url"),
                200,
                json.dumps({}, ensure_ascii=False),
                "api",
                ["github_graphql"],
                f"{full}\n{repo.get('description') or ''}".strip(),
                json.dumps(raw_payload, ensure_ascii=False),
            ))
        except Exception as e:
            logger.warning(f"raw_items 写入失败: {e}")

        cur.execute("""
        INSERT INTO repos(full_name, url, description, topics, language, created_at, last_pushed_at,
                          default_branch, stars, forks, open_issues)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (full_name) DO UPDATE SET
          url=EXCLUDED.url,
          description=EXCLUDED.description,
          topics=EXCLUDED.topics,
          language=EXCLUDED.language,
          last_pushed_at=EXCLUDED.last_pushed_at,
          default_branch=EXCLUDED.default_branch,
          stars=EXCLUDED.stars,
          forks=EXCLUDED.forks,
          open_issues=EXCLUDED.open_issues
        RETURNING id
        """, (
            full, repo["url"], repo.get("description"), topics,
            (repo["primaryLanguage"]["name"] if repo["primaryLanguage"] else None),
            repo["createdAt"], repo["pushedAt"],
            (repo["defaultBranchRef"]["name"] if repo["defaultBranchRef"] else None),
            repo["stargazerCount"], repo["forkCount"], repo["issues"]["totalCount"],
        ))
        repo_id = cur.fetchone()[0]

        cur.execute("""
        INSERT INTO repo_snapshots(repo_id, captured_at, stars, forks, open_issues)
        VALUES (%s,%s,%s,%s,%s)
        """, (repo_id, captured_at, repo["stargazerCount"], repo["forkCount"], repo["issues"]["totalCount"]))

def run(settings: Settings):
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is required for GitHub collector.")
    captured_at = dt.datetime.now(dt.timezone.utc)
    with get_conn(settings) as conn:
        for q in SEARCH_QUERIES:
            for repo in fetch_repos(settings, q):
                upsert_repo_and_snapshot(conn, repo, captured_at)
        conn.commit()
