from dotenv import load_dotenv
load_dotenv()

from ai_briefing.db import get_conn
from ai_briefing.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dedupe_briefs")

def clear_duplicates():
  settings = get_settings()
  with get_conn(settings) as conn:
    with conn.cursor() as cur:
      hours = settings.brief_dedup_hours
      if hours <= 0:
        logger.info("去重窗口为 0，跳过去重。")
        return
      cur.execute("""
        WITH ranked AS (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY kind, ref_id
                   ORDER BY created_at DESC, id DESC
                 ) AS rn
          FROM briefs
          WHERE ref_id IS NOT NULL
            AND created_at > NOW() - (%s || ' hours')::interval
        )
        DELETE FROM briefs b
        USING ranked r
        WHERE b.id = r.id AND r.rn > 1
      """, (hours,))
      deleted = cur.rowcount
      conn.commit()
      logger.info(f"已清理 {deleted} 条重复简报（24 小时窗口）。")

if __name__ == "__main__":
  clear_duplicates()
