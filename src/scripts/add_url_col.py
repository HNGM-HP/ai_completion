from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

def migrate():
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            try:
                logger.info("Adding 'url' column to 'briefs' table...")
                cur.execute("ALTER TABLE briefs ADD COLUMN IF NOT EXISTS url TEXT")
                conn.commit()
                logger.info("Migration successful.")
            except Exception as e:
                logger.error(f"Migration failed: {e}")
                conn.rollback()

if __name__ == "__main__":
    migrate()
