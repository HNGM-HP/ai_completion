import concurrent.futures
import datetime as dt
import hashlib
import json
import logging
import os
import random
import re
from typing import Dict, List, Optional
from urllib.parse import urlsplit

import yaml
from .llm import get_llm
from ..config import Settings

logger = logging.getLogger("briefing_generator")

promptTemplatesCache = None
promptTemplatesMtime = None

def loadPromptTemplates(settings: Settings) -> Dict:
    global promptTemplatesCache
    global promptTemplatesMtime

    templatePath = settings.prompt_templates_file
    if not templatePath or not os.path.exists(templatePath):
        return {}

    mtime = os.path.getmtime(templatePath)
    if promptTemplatesCache is not None and promptTemplatesMtime == mtime:
        return promptTemplatesCache

    try:
        with open(templatePath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"读取模板失败: {e}")
        return {}

    promptTemplatesCache = data
    promptTemplatesMtime = mtime
    return data

def getRepoPromptTemplate(settings: Settings) -> str:
    templates = loadPromptTemplates(settings)
    template = templates.get("repo_template") if isinstance(templates, dict) else None
    return template or ""

def getNewsPromptTemplate(settings: Settings) -> str:
    templates = loadPromptTemplates(settings)
    template = templates.get("news_template") if isinstance(templates, dict) else None
    return template or ""

def getNewsPromptTemplateBranch2(settings: Settings) -> str:
    templates = loadPromptTemplates(settings)
    template = templates.get("news_template_branch2") if isinstance(templates, dict) else None
    return template or ""

def getRepoPromptTemplateBranch2(settings: Settings) -> str:
    templates = loadPromptTemplates(settings)
    template = templates.get("repo_template_branch2") if isinstance(templates, dict) else None
    return template or ""

def _run_parallel(items: List[Dict], fn, max_workers: int) -> List[Optional[Dict]]:
    if max_workers <= 1:
        return [fn(item) for item in items]
    results: List[Optional[Dict]] = [None] * len(items)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(fn, item): idx for idx, item in enumerate(items)}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = None
    return results

def _extract_json(text: str) -> Dict:
    if not text:
        raise ValueError("Empty LLM response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)

def _normalize_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []

def _normalize_tags(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return []


def _normalize_paragraphs(value) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = re.split(r"\n\s*\n", text)
        return [p.strip() for p in parts if p.strip()]
    return []


def _should_discard(parsed: Dict) -> bool:
    if not isinstance(parsed, dict):
        return True
    value = parsed.get("discard")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    summary = str(parsed.get("summary") or "").strip()
    body = _normalize_paragraphs(parsed.get("body"))
    points = _normalize_list(parsed.get("points"))
    if len(summary) < 60:
        return True
    if len(body) < 4:
        return True
    if len(points) < 3:
        return True
    return False

def _build_items_text(items: List[Dict]) -> str:
    parts: List[str] = []
    for idx, item in enumerate(items[:5]):
        title = item.get("title", "")
        source = item.get("source", "")
        parts.append(f"{idx+1}. {title} (Source: {source})")
    return "\n".join(parts)

def buildPromptFromTemplate(template: str, values: Dict) -> str:
    if not template:
        return ""
    try:
        return template.format_map(values)
    except KeyError as e:
        logger.error(f"模板缺少占位符: {e}")
        return ""

def _get_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return ""
    return parts.netloc.lower() if parts.netloc else ""

def _select_cluster_url(cluster: Dict) -> str:
    primary_link = cluster.get("primary_link")
    if isinstance(primary_link, str) and primary_link.strip():
        return primary_link.strip()

    evidence_links = cluster.get("evidence_links")
    if isinstance(evidence_links, list):
        for link in evidence_links:
            if isinstance(link, str) and link.strip():
                return link.strip()

    items = cluster.get("items", [])
    if not items:
        return ""

    urls = [item.get("url", "") for item in items if item.get("url")]
    if not urls:
        return ""

    block_domains = {"arxiv.org"}
    non_blocked = [u for u in urls if _get_domain(u) not in block_domains]

    seed_source = str(cluster.get("id") or cluster.get("title") or "")
    seed = int(hashlib.md5(seed_source.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)

    if non_blocked:
        return rng.choice(non_blocked)
    return rng.choice(urls)

def generate_repo_brief(settings: Settings, repo: Dict) -> Dict:
    """
    Generate a brief for a single repository using LLM.
    """
    llm = get_llm(settings, "report")
    
    defaultPrompt = f"""
    你是一位擅长解读 AI 产品和技术趋势的科技解说员，
    任务是把【一个具体项目】讲清楚，并突出对普通人的现实价值。

    请用【普通人也能听懂的语言】解读下面的信息，要求：

    【总原则（非常重要）】
    - 只解读“下面给出的这一项信息”，不要自行合并其他工具、产品或研究
    - 不做“AI 很厉害”的泛泛而谈，必须紧扣具体内容
    - 不夸大、不虚构、不脑补论文里没有的结论
    - 重点写清楚：普通人/小团队能获得什么现实收益（变现、效率、学习、生活改善、安全合规）
    - **信息完整性优先**：不要为了追求简短而丢掉核心信息。在保持逻辑清晰的前提下，把事情讲透。

    【表达风格】
    - 像在给一个理解力很强、对科技很好奇的普通人讲新东西
    - 专业但不堆术语，用白话解释关键概念
    - 重点放在「和以前有什么不一样」「为什么对普通人有用」

    【字段写作要求】
    1. one_liner  
    - 核心概要：用 1-2 句话清晰说明这是个什么东西 / 这项研究在干嘛。
    - 必须具体，不能是“帮助 AI 更智能”这种泛句。

    2. why_matters  
    - 返回 2-3 条列表。
    - 先说明：它解决了什么问题（痛点）。
    - 再说明：为什么这件事值得关注（带一点现实场景与收益）。

    3. key_features  
    - 每一条都要包含：
    - 一个明确的技术点（不要只写效果）。
    - 一个生活化比喻，帮助理解这个技术点。
    - 强调“新方法 / 新思路 / 新变化”。
    - **注意**：每个亮点的描述要有血有肉，不要只写干巴巴的短语。

    4. tags  
    - 使用偏“科技新闻读者”也能理解的标签
    - 不要堆过多学术名词

    【项目信息】
    Repo: {repo['full_name']}
    URL: {repo['url']}
    Description: {repo['description']}
    Topics: {repo.get('topics', [])}
    Language: {repo.get('language')}

    【输出格式要求】
    请只输出一个 JSON 对象，用于直接作为科技简报或新闻解读使用：
    {{
    "one_liner": "核心概要说明这项研究或系统在做什么",
    "why_matters": ["它解决了什么问题", "为什么值得关注"],
    "key_features": [
    "亮点 1：具体技术点 + 详细解释 + 生活化比喻",
    "亮点 2：具体技术点 + 详细解释 + 生活化比喻"
    ],
    "tags": ["标签1", "标签2"]
    }}
    """

    promptValues = {
        "repo_full_name": repo.get("full_name", ""),
        "repo_url": repo.get("url", ""),
        "repo_description": repo.get("description", ""),
        "repo_topics": repo.get("topics", []),
        "repo_language": repo.get("language"),
    }
    repoTemplate = getRepoPromptTemplate(settings)
    prompt = buildPromptFromTemplate(repoTemplate, promptValues) or defaultPrompt


    
    try:
        response_text = llm.generate(prompt)
        parsed = _extract_json(response_text)
        parsed['one_liner'] = parsed.get('one_liner') or repo.get('description') or repo.get('full_name')
        parsed['why_matters'] = _normalize_list(parsed.get('why_matters'))
        parsed['key_features'] = _normalize_list(parsed.get('key_features'))
        parsed['tags'] = _normalize_tags(parsed.get('tags'))
        parsed['url'] = repo['url']
        return parsed
    except Exception as e:
        # LLM 失败时的兜底内容
        description = repo.get('description') or repo.get('full_name') or ""
        return {
            "one_liner": description or "开源项目更新。",
            "why_matters": ["GitHub 上正在被关注的项目。", "规则摘要生成。"],
            "key_features": [],
            "tags": list(repo.get('topics', [])) + ["规则生成"],
            "url": repo['url']
        }

def generate_news_brief(settings: Settings, cluster: Dict) -> Dict:
    """
    Generate a brief for a news cluster using LLM.
    """
    llm = get_llm(settings, "report")
    
    # 聚类条目列表：{title, url, source, content_snippet}
    items_text = _build_items_text(cluster.get('items', []))
    
    defaultPrompt = f"""
    你是一位擅长解读 AI 产品和技术趋势的科技解说员。
    请解读下面的信息，生成一篇普通人也能看懂、能用得上的科技简报。

    文章列表:
    {items_text}

    聚类主题: {cluster.get('title', '')}

    【参考范文风格】
    **GAF** 是一篇刚发布在 arXiv 的新论文，提出了一种专门用于 **生成式应用安全的防火墙架构**。该系统类似于传统的 Web 应用防火墙（WAF），不过是针对大型语言模型（LLM）及其相关应用流程设计的...（详细描述背景、机制和目标）

    **为什么重要？**
    * 现有的 prompt 安全机制各自为政...
    * GAF 提出在“应用层”做统一审查...

    【写作要求】
    1. **main_content (对应 one_liner 字段)**: 
       - 输出一段 **详实的介绍段落**（不是一句话，而是完整的 3-5 行段落）。
       - 开头必须明确：**项目名称** 是什么（e.g. "**Method-X** 是一个..."）。
       - 适当使用 markdown **加粗** 核心概念。
       - 把事情的背景、核心机制、解决了什么问题都融合在这一段里讲清楚。
       - 必须点出：对普通人/小团队/个人用户的现实价值（变现、效率、学习、生活改善、安全合规等）。

    2. **why_matters**: 
       - 返回一个 **字符串列表** (List[str])。
       - 列出 2-3 点，解释为什么这很重要（痛点、行业影响、普通人收益）。

    3. **key_features**: 
       - 返回一个 **字符串列表** (List[str])。
       - 列出 2-3 个核心亮点或技术特征。

    4. **tags**: 
       - 标签列表。

    【输出格式要求 (JSON Only)】
    {{
        "one_liner": "详细的主体段落内容（支持 Markdown 加粗）...",
        "why_matters": ["原因点1...", "原因点2..."],
        "key_features": ["亮点1...", "亮点2..."],
    "tags": ["tag1", "tag2"]
    }}
    """

    promptValues = {
        "items_text": items_text,
        "cluster_title": cluster.get("title", ""),
    }
    newsTemplate = getNewsPromptTemplate(settings)
    prompt = buildPromptFromTemplate(newsTemplate, promptValues) or defaultPrompt

    try:
        response_text = llm.generate(prompt)
        parsed = _extract_json(response_text)
        parsed['one_liner'] = parsed.get('one_liner') or cluster.get('title', 'News Update')
        parsed['why_matters'] = _normalize_list(parsed.get('why_matters'))
        parsed['key_features'] = _normalize_list(parsed.get('key_features'))
        parsed['tags'] = _normalize_tags(parsed.get('tags'))
        # 使用可复现随机选择的主链接（优先非 arxiv）
        parsed['url'] = _select_cluster_url(cluster)
        return parsed
    except Exception as e:
        items = cluster.get('items', [])
        fallback_title = cluster.get('title', '')
        fallback_summary = items[0].get('summary') if items else ""
        fallback_one_liner = fallback_summary or fallback_title or "新闻更新。"
        return {
            "one_liner": fallback_one_liner,
            "why_matters": ["规则摘要生成。"],
            "key_features": [],
            "tags": ["规则生成"],
            "url": ""
        }

def generate_repo_briefs(settings: Settings, repos: List[Dict]) -> List[Dict]:
    for repo in repos:
        repo_name = repo.get('full_name') or repo.get('url') or "unknown"
        logger.info(f"生成 Repo 简报: {repo_name}")

    contents = _run_parallel(repos, lambda r: generate_repo_brief(settings, r), settings.llm_max_workers)
    briefs = []
    for repo, content in zip(repos, contents):
        if not content:
            continue
        briefs.append({
            "source_id": repo['id'],
            "source_type": "repo",
            "content": content,
            "created_at": dt.datetime.now(dt.timezone.utc)
        })
    return briefs

def generate_repo_briefs_branch2(settings: Settings, repos: List[Dict]) -> List[Dict]:
    template = getRepoPromptTemplateBranch2(settings)
    if not template:
        return []
    llm = get_llm(settings, "wechat")
    max_workers = max(1, settings.llm_max_workers)

    def _gen(repo: Dict) -> Optional[Dict]:
        prompt = buildPromptFromTemplate(template, {
            "repo_full_name": repo.get("full_name", ""),
            "repo_url": repo.get("url", ""),
            "repo_description": repo.get("description", ""),
            "repo_topics": ", ".join(repo.get("topics", []) or []),
            "repo_language": repo.get("language", ""),
        })
        if not prompt:
            return None
        try:
            response_text = llm.generate(prompt)
            parsed = _extract_json(response_text)
            if _should_discard(parsed):
                reason = parsed.get("reason") if isinstance(parsed, dict) else ""
                repo_name = repo.get("full_name") or repo.get("url") or "unknown"
                logger.info(f"Branch2 丢弃 repo: {repo_name} ({str(reason).strip()})")
                return None
            parsed["url"] = repo.get("url", "")
            return {
                "source_id": repo["id"],
                "source_type": "repo",
                "content": parsed,
                "created_at": dt.datetime.now(dt.timezone.utc)
            }
        except Exception:
            return None

    contents = _run_parallel(repos, _gen, max_workers)
    return [c for c in contents if c]

def generate_news_briefs(settings: Settings, clusters: List[Dict]) -> List[Dict]:
    for cluster in clusters:
        cluster_title = cluster.get('title') or cluster.get('id') or "unknown"
        logger.info(f"生成新闻简报: {cluster_title}")

    contents = _run_parallel(clusters, lambda c: generate_news_brief(settings, c), settings.llm_max_workers)
    briefs = []
    for cluster, content in zip(clusters, contents):
        if not content:
            continue
        briefs.append({
            "source_id": cluster['id'],
            "source_type": "news",
            "content": content,
            "created_at": dt.datetime.now(dt.timezone.utc)
        })
    return briefs

def generate_news_briefs_branch2(settings: Settings, clusters: List[Dict]) -> List[Dict]:
    template = getNewsPromptTemplateBranch2(settings)
    if not template:
        return []
    llm = get_llm(settings, "wechat")
    max_workers = max(1, settings.llm_max_workers)

    def _gen(cluster: Dict) -> Optional[Dict]:
        items_text = _build_items_text(cluster.get("items", []))
        prompt = buildPromptFromTemplate(template, {
            "items_text": items_text,
            "cluster_title": cluster.get("title", ""),
        })
        if not prompt:
            return None
        try:
            response_text = llm.generate(prompt)
            parsed = _extract_json(response_text)
            if _should_discard(parsed):
                reason = parsed.get("reason") if isinstance(parsed, dict) else ""
                title = cluster.get("title") or cluster.get("id") or "unknown"
                logger.info(f"Branch2 丢弃 news: {title} ({str(reason).strip()})")
                return None
            parsed["url"] = _select_cluster_url(cluster)
            return {
                "source_id": cluster["id"],
                "source_type": "news",
                "content": parsed,
                "created_at": dt.datetime.now(dt.timezone.utc)
            }
        except Exception:
            return None

    contents = _run_parallel(clusters, _gen, max_workers)
    return [c for c in contents if c]
