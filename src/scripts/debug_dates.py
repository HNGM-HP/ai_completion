from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings

def check():
    conn = get_conn(get_settings())
    with conn.cursor() as cur:
        cur.execute('SELECT id, published_at, cluster_id FROM items ORDER BY id DESC LIMIT 10')
        print("Last 10 items:")
        for r in cur.fetchall():
            print(r)

if __name__ == "__main__":
    check()
