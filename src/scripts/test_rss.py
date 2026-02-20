import feedparser
import time

url = "https://openai.com/index/rss.xml" # Use a known one
print(f"Fetching {url}...")
start = time.time()
f = feedparser.parse(url)
print(f"Time: {time.time() - start:.2f}s")
print(f"Status: {f.get('status')}")
print(f"Entries: {len(f.entries)}")
if f.entries:
    print(f"Title: {f.entries[0].title}")
else:
    print(f"Bozo: {f.get('bozo')}, Exception: {f.get('bozo_exception')}")
