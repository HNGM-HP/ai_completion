import requests
import feedparser

CANDIDATES = [
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Google DeepMind (New)", "https://deepmind.google/discover/blog/rss.xml"), 
    ("Google Research", "https://research.google/blog/rss/"),
    ("OpenAI (Check)", "https://openai.com/index/rss.xml"), # Updated path often changes
    ("Microsoft AI", "https://blogs.microsoft.com/ai/feed/"),
    ("MIT News AI", "https://news.mit.edu/rss/topic/artificial-intelligence2"),
    ("Berkeley AI (BAIR)", "https://bair.berkeley.edu/blog/feed.xml"),
    ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("NVIDIA AI", "https://blogs.nvidia.com/blog/category/deep-learning/feed/"),
    ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed"),
    ("Lil'Log", "https://lilianweng.github.io/index.xml"),
]

print(f"{'Name':<25} | {'Status':<6} | {'Items':<5} | {'URL'}")
print("-" * 80)

for name, url in CANDIDATES:
    try:
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        status = resp.status_code
        count = 0
        if status == 200:
            f = feedparser.parse(resp.content)
            count = len(f.entries)
        print(f"{name:<25} | {status:<6} | {count:<5} | {url}")
    except Exception as e:
        print(f"{name:<25} | {'ERR':<6} | {0:<5} | {e}")
