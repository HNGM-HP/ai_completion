import requests
import feedparser
import time

url = "https://huggingface.co/blog/feed.xml"
print(f"Fetching {url} with requests...")
start = time.time()
try:
    resp = requests.get(url, timeout=10.0)
    print(f"Requests status: {resp.status_code}, Time: {time.time() - start:.2f}s")
    
    print("Parsing with feedparser...")
    f = feedparser.parse(resp.content)
    print(f"Entries: {len(f.entries)}")
except Exception as e:
    print(f"Failed: {e}")
