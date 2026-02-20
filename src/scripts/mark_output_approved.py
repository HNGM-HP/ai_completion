from __future__ import annotations

import argparse

from dotenv import load_dotenv

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark output as approved")
    parser.add_argument("--output-id", type=int, required=True)
    args = parser.parse_args()

    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE outputs SET status = 'approved' WHERE id = %s",
                (args.output_id,),
            )
        conn.commit()

    print("OK")


if __name__ == "__main__":
    main()
