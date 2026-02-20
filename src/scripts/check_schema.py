from dotenv import load_dotenv
load_dotenv("/opt/ai_briefing/.env")
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings

EXPECTED_TABLES: dict[str, list[str]] = {
    "items": [
        "region",
        "safety_flags",
        "raw_item_id",
        "dedup_group_id",
        "dedup_action",
        "major_update_score",
        "major_update_reasons",
    ],
    "clusters": [
        "primary_link",
        "evidence_links",
        "link_select_debug",
    ],
    "raw_items": [
        "source_kind",
        "retrieved_at",
        "http_status",
        "retrieved_headers",
        "render_mode",
        "provider_chain",
        "content_snapshot",
        "raw_payload",
    ],
    "factchecks": [
        "topic_kind",
        "topic_ref_id",
        "claims",
        "evidence",
        "confidence",
        "open_questions",
        "status",
        "created_at",
    ],
    "outputs": [
        "branch",
        "content",
        "meta",
        "status",
        "created_at",
    ],
    "publish_log": [
        "channel",
        "output_id",
        "status",
        "created_at",
    ],
    "user_feedback": [
        "topic_kind",
        "topic_ref_id",
        "label",
        "created_at",
    ],
    "job_state": [
        "state",
        "items_in",
        "items_out",
        "latency_ms_by_step",
        "tokens_used_by_task_type",
        "cache_hit_rate",
    ],
}


def _get_columns(cur, table_name: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def check_schema():
    conn = get_conn(get_settings())
    with conn.cursor() as cur:
        failed: list[str] = []

        for table_name, expected_cols in EXPECTED_TABLES.items():
            cols = _get_columns(cur, table_name)
            if not cols:
                failed.append(f"missing table: {table_name}")
                continue
            for col in expected_cols:
                if col not in cols:
                    failed.append(f"missing column: {table_name}.{col}")

        if failed:
            print("SCHEMA FAIL")
            for line in failed:
                print(line)
            raise SystemExit(2)

        print("SCHEMA OK")

if __name__ == "__main__":
    check_schema()
