from __future__ import annotations

from dotenv import load_dotenv

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn


MIGRATIONS: list[str] = [
    # raw_items
    """
    CREATE TABLE IF NOT EXISTS raw_items (
      id                BIGSERIAL PRIMARY KEY,
      source_kind       TEXT NOT NULL,
      source_ref        TEXT,
      source_url        TEXT,
      retrieved_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      http_status       INTEGER,
      retrieved_headers JSONB,
      render_mode       TEXT,
      provider_chain    TEXT[],
      content_snapshot  TEXT,
      raw_payload       JSONB
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_raw_items_retrieved_at ON raw_items (retrieved_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_raw_items_source_kind  ON raw_items (source_kind)",

    # items 增量字段
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS region TEXT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS safety_flags TEXT[]",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS raw_item_id BIGINT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS dedup_group_id BIGINT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS dedup_action TEXT",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS major_update_score DOUBLE PRECISION",
    "ALTER TABLE items ADD COLUMN IF NOT EXISTS major_update_reasons JSONB",
    "CREATE INDEX IF NOT EXISTS idx_items_region ON items (region)",

    # clusters 增量字段
    "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS primary_link TEXT",
    "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS evidence_links JSONB",
    "ALTER TABLE clusters ADD COLUMN IF NOT EXISTS link_select_debug JSONB",

    # factchecks
    """
    CREATE TABLE IF NOT EXISTS factchecks (
      id              BIGSERIAL PRIMARY KEY,
      topic_kind      TEXT NOT NULL,
      topic_ref_id    BIGINT,
      claims          JSONB NOT NULL,
      evidence        JSONB NOT NULL,
      confidence      DOUBLE PRECISION,
      open_questions  JSONB,
      status          TEXT NOT NULL DEFAULT 'review',
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_factchecks_created_at ON factchecks (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_factchecks_status     ON factchecks (status)",

    # outputs
    """
    CREATE TABLE IF NOT EXISTS outputs (
      id              BIGSERIAL PRIMARY KEY,
      branch          TEXT NOT NULL,
      topic_kind      TEXT,
      topic_ref_id    BIGINT,
      factcheck_id    BIGINT,
      content         TEXT NOT NULL,
      meta            JSONB,
      status          TEXT NOT NULL DEFAULT 'pending',
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outputs_created_at ON outputs (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_outputs_branch     ON outputs (branch)",
    "ALTER TABLE outputs ADD COLUMN IF NOT EXISTS status TEXT",
    "UPDATE outputs SET status = 'pending' WHERE status IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_outputs_status     ON outputs (status)",

    # publish_log
    """
    CREATE TABLE IF NOT EXISTS publish_log (
      id              BIGSERIAL PRIMARY KEY,
      channel         TEXT NOT NULL,
      output_id       BIGINT,
      status          TEXT NOT NULL,
      error_message   TEXT,
      payload         JSONB,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_publish_log_created_at ON publish_log (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_publish_log_status     ON publish_log (status)",

    # user_feedback
    """
    CREATE TABLE IF NOT EXISTS user_feedback (
      id              BIGSERIAL PRIMARY KEY,
      topic_kind      TEXT,
      topic_ref_id    BIGINT,
      label           TEXT NOT NULL,
      reason          TEXT,
      user_id         TEXT,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_feedback_created_at ON user_feedback (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_user_feedback_topic      ON user_feedback (topic_kind, topic_ref_id)",

    # job_state 增量字段
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS last_run_id UUID",
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS items_in INTEGER",
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS items_out INTEGER",
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS latency_ms_by_step JSONB",
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS tokens_used_by_task_type JSONB",
    "ALTER TABLE job_state ADD COLUMN IF NOT EXISTS cache_hit_rate DOUBLE PRECISION",
]


def main() -> None:
    """执行 20260130 增量迁移。

    注意：只包含 IF NOT EXISTS 的幂等语句；失败时回滚。
    """

    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    conn = get_conn(settings)
    try:
        with conn:
            with conn.cursor() as cur:
                for stmt in MIGRATIONS:
                    cur.execute(stmt)
        print("MIGRATION OK")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
