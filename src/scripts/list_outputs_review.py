from __future__ import annotations

from dotenv import load_dotenv

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn


def main() -> None:
    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, branch, topic_kind, topic_ref_id, created_at
                FROM outputs
                WHERE status = 'review'
                ORDER BY created_at DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()

    print("id\tbranch\ttopic_kind\ttopic_ref_id\tcreated_at")
    for row in rows:
        print(f"{row[0]}\t{row[1]}\t{row[2]}\t{row[3]}\t{row[4]}")


if __name__ == "__main__":
    main()
