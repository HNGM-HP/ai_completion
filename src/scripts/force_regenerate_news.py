import sys
import os
# 将 src 目录加入 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ai_briefing.db import get_conn
from ai_briefing.config import get_settings
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reset_history")

def reset():
    settings = get_settings()
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            # 删除近期新闻简报，强制重新生成
            hours = max(6, int(settings.news_window_hours))
            logger.info(f"删除最近 {hours} 小时的新闻简报，准备重新生成...")
            cur.execute("DELETE FROM briefs WHERE kind='news' AND created_at > NOW() - (%s || ' hours')::interval", (hours,))
            
            deleted = cur.rowcount
            conn.commit()
            logger.info(f"已删除 {deleted} 条记录，可运行 --run-rss 重新生成简报。")

if __name__ == "__main__":
    reset()
