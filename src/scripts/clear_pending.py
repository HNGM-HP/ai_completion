from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings

def run():
    conn = get_conn(get_settings())
    with conn.cursor() as cur:
        cur.execute("UPDATE briefs SET sent_at = NOW() WHERE sent_at IS NULL")
        print(f"Cleared {cur.rowcount} pending briefs.")
    conn.commit()

if __name__ == "__main__":
    run()
