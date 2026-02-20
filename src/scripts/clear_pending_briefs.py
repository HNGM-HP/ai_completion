from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup")

def clear_pending():
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM briefs WHERE sent_at IS NULL")
            count = cur.fetchone()[0]
            logger.info(f"Found {count} pending briefs.")
            
            cur.execute("DELETE FROM briefs WHERE sent_at IS NULL")
            conn.commit()
            logger.info("Cleared all pending briefs.")

if __name__ == "__main__":
    clear_pending()
