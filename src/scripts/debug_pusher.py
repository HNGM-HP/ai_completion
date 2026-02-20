import logging
import sys
from dotenv import load_dotenv
load_dotenv()

from ai_briefing.config import get_settings
from ai_briefing.pusher import main as pusher
from ai_briefing.db import get_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_pusher")

def debug():
    settings = get_settings()
    conn = get_conn(settings)
    with conn.cursor() as cur:
        # Check pending
        cur.execute("SELECT count(*) FROM briefs WHERE sent_at IS NULL")
        pending = cur.fetchone()[0]
        logger.info(f"Pending briefs: {pending}")
        
    logger.info("Running pusher...")
    try:
        pusher.push_pending_briefs(settings)
    except Exception as e:
        logger.error(f"Pusher failed: {e}", exc_info=True)

if __name__ == "__main__":
    debug()
