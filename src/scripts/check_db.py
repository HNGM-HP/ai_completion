from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings

def check():
    conn = get_conn(get_settings())
    with conn.cursor() as cur:
        print('Repos:', cur.execute('SELECT count(*) FROM repos').fetchone()[0])
        print('Briefs:', cur.execute('SELECT count(*) FROM briefs').fetchone()[0])
        print('PushLog:', cur.execute('SELECT count(*) FROM push_log').fetchone()[0])

if __name__ == "__main__":
    check()
