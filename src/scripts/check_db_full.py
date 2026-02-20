from dotenv import load_dotenv
load_dotenv()
from ai_briefing.db import get_conn
from ai_briefing.config import get_settings

def check():
    conn = get_conn(get_settings())
    with conn.cursor() as cur:
        print('Repos:', cur.execute('SELECT count(*) FROM repos').fetchone()[0])
        try:
            print('Items (RSS):', cur.execute('SELECT count(*) FROM items').fetchone()[0])
        except Exception as e:
            print(f'Items check failed: {e}')
            
        try:
            print('Clusters:', cur.execute('SELECT count(*) FROM clusters').fetchone()[0])
        except Exception as e:
            print(f'Clusters check failed: {e}')
            
        print('Briefs:', cur.execute('SELECT count(*) FROM briefs').fetchone()[0])
        
        # Check News Briefs specifically
        print('News Briefs:', cur.execute("SELECT count(*) FROM briefs WHERE kind='news'").fetchone()[0])
        
        # Check content language
        cur.execute("SELECT one_liner FROM briefs WHERE kind='news' ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            print(f"Latest News Brief: {row[0]}")
            
        print('PushLog:', cur.execute('SELECT count(*) FROM push_log').fetchone()[0])

if __name__ == "__main__":
    check()
