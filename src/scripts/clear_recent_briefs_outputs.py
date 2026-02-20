from __future__ import annotations

import argparse

from dotenv import load_dotenv

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear recent briefs and outputs")
    parser.add_argument("--hours", type=int, default=48)
    args = parser.parse_args()

    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM outputs WHERE created_at > NOW() - (%s || ' hours')::interval",
                (args.hours,),
            )
            cur.execute(
                "DELETE FROM briefs WHERE created_at > NOW() - (%s || ' hours')::interval",
                (args.hours,),
            )
        conn.commit()

    print("OK")


if __name__ == "__main__":
    main()
