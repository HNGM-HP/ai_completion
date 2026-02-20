from __future__ import annotations

import argparse
import datetime as dt

from dotenv import load_dotenv

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn


LABEL_MAP = {
    "👍": "useful",
    "👎": "useless",
    "⏭": "skip",
}


def _parse_command(command: str) -> tuple[str | None, int | None]:
    parts = command.strip().split()
    if len(parts) < 2:
        return None, None
    label_raw = parts[0].strip()
    label = LABEL_MAP.get(label_raw)
    if not label:
        return None, None
    try:
        topic_ref_id = int(parts[1])
    except Exception:
        return None, None
    return label, topic_ref_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Record user feedback")
    parser.add_argument("--command", type=str, help="例如: '👍 123'")
    parser.add_argument("--topic-kind", type=str, choices=["news", "repo"], default="news")
    parser.add_argument("--topic-ref-id", type=int)
    parser.add_argument("--label", type=str, choices=["useful", "useless", "skip"])
    parser.add_argument("--reason", type=str)
    parser.add_argument("--user-id", type=str)

    args = parser.parse_args()

    label = args.label
    topic_ref_id = args.topic_ref_id
    if args.command:
        label, topic_ref_id = _parse_command(args.command)
        if not label or topic_ref_id is None:
            raise SystemExit("command 解析失败，示例：'👍 123'")

    if not label or topic_ref_id is None:
        raise SystemExit("必须提供 command 或者 label + topic_ref_id")

    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_feedback (topic_kind, topic_ref_id, label, reason, user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    args.topic_kind,
                    topic_ref_id,
                    label,
                    args.reason,
                    args.user_id,
                    dt.datetime.now(dt.timezone.utc),
                ),
            )
        conn.commit()

    print("OK")


if __name__ == "__main__":
    main()
