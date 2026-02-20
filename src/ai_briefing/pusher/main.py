import json
from ..db import get_conn
from ..config import Settings
from .feishu import send_text, send_output_card
from .feishu_doc import create_doc, append_blocks, build_doc_blocks

def _parse_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            return [text]
    return []

def _split_messages(header: str, blocks: list[str], max_chars: int) -> list[str]:
    messages = []
    current = header
    for block in blocks:
        block_text = block.strip()
        if not block_text:
            continue
        candidate = f"{current}\n\n{block_text}" if current else block_text
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            messages.append(current)
            current = header
        candidate = f"{current}\n\n{block_text}" if current else block_text
        if len(candidate) <= max_chars:
            current = candidate
        else:
            # 单条过长时进行截断
            trimmed = block_text[:max_chars - len(header) - 2]
            if header:
                current = f"{header}\n\n{trimmed}"
            else:
                current = trimmed
            messages.append(current)
            current = header
    if current and current != header:
        messages.append(current)
    if not messages and header:
        messages.append(header)
    return messages


def _extract_title(content: str) -> str:
    if not content:
        return "公众号稿"
    first_line = content.strip().split("\n", 1)[0].strip()
    if first_line.startswith("**") and first_line.endswith("**"):
        first_line = first_line.strip("*")
    return first_line or "公众号稿"


def push_pending_outputs(settings: Settings):
    """
    Fetch pending outputs and push to Feishu.
    Branch1: status = pending
    Branch2: status = approved
    """
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            while True:
                cur.execute(
                    """
                    SELECT id, branch, content, meta, topic_kind, topic_ref_id
                    FROM outputs
                    WHERE (branch = 'branch1' AND status = 'pending')
                       OR (branch = 'branch2' AND status = 'approved')
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                    """
                )
                rows = cur.fetchall()

                if not rows:
                    print("No more pending outputs to push.")
                    break

                output_ids = []
                branch1_ids: list[int] = []
                branch1_outputs: list[dict] = []
                branch2_docs: list[tuple[int, str, dict, str]] = []

                for row in rows:
                    oid, branch, content, meta, topic_kind, topic_ref_id = row
                    output_ids.append(oid)
                    if branch == "branch1":
                        branch1_ids.append(oid)
                        branch1_outputs.append({
                            "id": oid,
                            "content": content,
                            "topic_kind": topic_kind,
                            "topic_ref_id": topic_ref_id,
                        })
                    elif branch == "branch2":
                        meta_obj = {}
                        if isinstance(meta, str):
                            try:
                                meta_obj = json.loads(meta)
                            except Exception:
                                meta_obj = {}
                        elif isinstance(meta, dict):
                            meta_obj = meta
                        meta_title = meta_obj.get("title") if isinstance(meta_obj, dict) else None
                        title = str(meta_title).strip() if meta_title else _extract_title(content)
                        branch2_docs.append((oid, content, meta_obj, title))

                try:
                    doc_payloads = []
                    for oid, content, meta_obj, title in branch2_docs:
                        doc_id, doc_url = create_doc(settings, title)
                        blocks = build_doc_blocks(settings, title, meta_obj)
                        append_blocks(settings, doc_id, blocks)
                        doc_payloads.append({"output_id": oid, "doc_url": doc_url})
                        cur.execute(
                            "UPDATE outputs SET status = 'sent', meta = jsonb_set(COALESCE(meta, '{}'::jsonb), '{doc_url}', %s, true) WHERE id = %s",
                            (json.dumps(doc_url), oid),
                        )

                    cur.execute(
                        """
                        INSERT INTO publish_log(channel, payload, status, created_at)
                        VALUES ('feishu', %s, 'success', NOW())
                        """,
                        (json.dumps({"docs": doc_payloads}, ensure_ascii=False),),
                    )

                    conn.commit()
                    if doc_payloads:
                        print(f"Successfully created {len(doc_payloads)} docs.")
                except Exception as e:
                    conn.rollback()
                    print(f"Failed to push outputs batch: {e}")
                    raise

                if branch1_outputs:
                    try:
                        for idx, item in enumerate(branch1_outputs, start=1):
                            print(f"准备推送第 {idx}/{len(branch1_outputs)} 条卡片")
                            send_output_card(
                                settings,
                                item["id"],
                                item["content"],
                                item.get("topic_kind"),
                                item.get("topic_ref_id"),
                            )

                        if branch1_ids:
                            cur.execute(
                                "UPDATE outputs SET status = 'sent' WHERE id = ANY(%s) AND branch = 'branch1'",
                                (branch1_ids,),
                            )

                        cur.execute(
                            """
                            INSERT INTO publish_log(channel, payload, status, created_at)
                            VALUES ('feishu', %s, 'success', NOW())
                            """,
                            (json.dumps({"output_ids": branch1_ids}, ensure_ascii=False),),
                        )
                        conn.commit()
                        print(f"Successfully pushed batch of {len(branch1_ids)} outputs.")
                    except Exception as e:
                        conn.rollback()
                        print(f"Failed to push branch1 outputs batch: {e}")
                        raise

def push_pending_briefs(settings: Settings):
    """
    Fetch unsent briefs from DB, format them into a message, and push to Feishu.
    """
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            while True:
                # 取一批未发送的简报
                cur.execute("""
                    SELECT id, kind, ref_id, title, one_liner, why_matters, bullets, tags, created_at, url
                    FROM briefs
                    WHERE sent_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                """)
                rows = cur.fetchall()
                
                if not rows:
                    print("No more pending briefs to push.")
                    break
                
                message_lines = ["🚀 AI Briefing · 价值优先"]
                brief_ids = []
                blocks = []
                blocksByKind = {"repo": [], "news": []}
                kind_counts = {"repo": 0, "news": 0}
                
                for row in rows:
                    bid, kind, ref_id, title, one_liner, why, bullets, tags, created, url = row
                    brief_ids.append(bid)
                    if kind in kind_counts:
                        kind_counts[kind] += 1
                    
                    block_lines = []

                    # 图标
                    icon = "📦" if kind == 'repo' else "📰"

                    # 标题行
                    kind_label = "项目" if kind == 'repo' else "新闻"
                    block_lines.append(f"{icon} [{kind_label}] {title}")

                    # 一句话概括
                    if one_liner and one_liner != title:
                        block_lines.append(f"ℹ️ {one_liner}")

                    # 价值点
                    for w in _parse_list(why):
                        block_lines.append(f"💡 {w}")

                    # 亮点列表
                    for b in _parse_list(bullets):
                        block_lines.append(f"• {b}")

                    # 标签
                    tag_list = [t.lstrip('#') for t in _parse_list(tags)]
                    if tag_list:
                        tag_text = " ".join([f"#{t}" for t in tag_list])
                        block_lines.append(f"🏷️ {tag_text}")

                    # 链接
                    if url:
                        block_lines.append(f"🔗 {url}")

                    blockText = "\n".join(block_lines)
                    blocks.append(blockText)
                    if kind in blocksByKind:
                        blocksByKind[kind].append(blockText)
                    
                max_chars = max(500, settings.feishu_max_chars)
                messages = []
                if settings.feishu_group_by_kind:
                    if blocksByKind["repo"]:
                        messages.extend(_split_messages("🚀 AI Briefing · 项目", blocksByKind["repo"], max_chars))
                    if blocksByKind["news"]:
                        messages.extend(_split_messages("🚀 AI Briefing · 新闻", blocksByKind["news"], max_chars))
                else:
                    messages = _split_messages(message_lines[0], blocks, max_chars)

                # 推送到飞书
                try:
                    print(f"待推送数量：项目 {kind_counts['repo']}，新闻 {kind_counts['news']}")
                    for idx, full_text in enumerate(messages, start=1):
                        print(f"准备推送第 {idx}/{len(messages)} 条消息，字符数 {len(full_text)}")
                        send_text(settings, full_text)
                    
                    # 标记为已发送
                    cur.execute("""
                        UPDATE briefs 
                        SET sent_at = NOW() 
                        WHERE id = ANY(%s)
                    """, (brief_ids,))
                    
                    # 写入推送日志
                    cur.execute("""
                        INSERT INTO push_log(channel, payload, status, created_at)
                        VALUES ('feishu', %s, 'success', NOW())
                    """, (json.dumps({"texts": messages}),))
                    
                    conn.commit()
                    print(f"Successfully pushed batch of {len(brief_ids)} briefs.")
                    
                except Exception as e:
                    conn.rollback()
                    print(f"Failed to push briefs batch: {e}")
                    raise
