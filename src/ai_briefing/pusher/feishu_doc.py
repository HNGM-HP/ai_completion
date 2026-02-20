from __future__ import annotations

import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from ..config import Settings


def get_tenant_access_token(settings: Settings) -> str:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("FEISHU_APP_ID/FEISHU_APP_SECRET missing.")
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu auth HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu auth error: {data}")
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError("Feishu auth token missing")
    return token


def _get_beijing_date_str(settings: Settings) -> str:
    tz = ZoneInfo("Asia/Shanghai")
    return datetime.now(tz).strftime(settings.feishu_doc_date_format)


def _list_files_in_folder(settings: Settings, parent_token: str) -> list[dict]:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        "https://open.feishu.cn/open-apis/drive/v1/files",
        headers=headers,
        params={"folder_token": parent_token, "page_size": 200},
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu list files HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu list files error: {data}")
    return data.get("data", {}).get("files", []) or data.get("data", {}).get("items", []) or []


def _create_folder(settings: Settings, parent_token: str, name: str) -> str:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "name": name,
        "folder_token": parent_token,
    }
    resp = requests.post(
        "https://open.feishu.cn/open-apis/drive/v1/files/create_folder",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu create folder HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu create folder error: {data}")
    token_value = data.get("data", {}).get("token") or data.get("data", {}).get("folder_token")
    if not token_value:
        raise RuntimeError(f"Feishu create folder missing token: {data}")
    return token_value


def get_or_create_daily_folder_token(settings: Settings) -> str | None:
    if not settings.feishu_doc_folder_token:
        return None
    if not settings.feishu_doc_daily_folder:
        return settings.feishu_doc_folder_token

    date_name = _get_beijing_date_str(settings)
    files = _list_files_in_folder(settings, settings.feishu_doc_folder_token)
    for item in files:
        name = item.get("name") or item.get("title")
        file_type = item.get("type") or item.get("file_type") or ""
        token_value = item.get("token") or item.get("folder_token")
        if name == date_name and token_value and str(file_type) in ("folder", "docx_folder", "folder"):
            return token_value

    return _create_folder(settings, settings.feishu_doc_folder_token, date_name)


def create_doc(settings: Settings, title: str) -> tuple[str, str]:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "title": title,
    }
    folder_token = get_or_create_daily_folder_token(settings)
    if folder_token:
        payload["folder_token"] = folder_token
    resp = requests.post(
        "https://open.feishu.cn/open-apis/docx/v1/documents",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu create doc HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu create doc error: {data}")
    doc_id = data.get("data", {}).get("document", {}).get("document_id")
    doc_url = data.get("data", {}).get("document", {}).get("url")
    if not doc_id:
        raise RuntimeError(f"Feishu create doc missing id: {data}")
    if not doc_url:
        doc_url = f"https://docs.feishu.cn/docx/{doc_id}"
    return doc_id, doc_url


def get_document_root_block_id(settings: Settings, doc_id: str) -> str:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks",
        headers=headers,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu get blocks HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu get blocks error: {data}")
    items = data.get("data", {}).get("items", [])
    if not items:
        raise RuntimeError(f"Feishu get blocks empty: {data}")
    block_id = items[0].get("block_id")
    if not isinstance(block_id, str) or not block_id:
        raise RuntimeError(f"Feishu get blocks missing block_id: {data}")
    return block_id


def _paragraph_block(text: str) -> dict:
    return {
        "block_type": 2,
        "text": {
            "elements": [
                {
                    "text_run": {"content": text},
                }
            ]
        },
    }


def _normalize_paragraphs(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = re.split(r"\n\s*\n", text)
        return [p.strip() for p in parts if p.strip()]
    return []


def _local_image_block(file_path: str) -> dict:
    return {
        "block_type": 27,
        "image": {
            "local_path": file_path,
        },
    }


def create_image_block(settings: Settings, doc_id: str) -> str:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    root_block_id = get_document_root_block_id(settings, doc_id)
    payload = {"children": [{"block_type": 27, "image": {}}]}
    resp = requests.post(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{root_block_id}/children",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu create image block HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu create image block error: {data}")
    children = data.get("data", {}).get("children", [])
    if not isinstance(children, list) or not children:
        raise RuntimeError(f"Feishu create image block missing children: {data}")
    block_id = children[0].get("block_id")
    if not block_id:
        raise RuntimeError(f"Feishu create image block missing block_id: {data}")
    return block_id


def upload_docx_image(settings: Settings, image_block_id: str, file_path: str) -> str:
    if not os.path.exists(file_path):
        raise RuntimeError(f"image not found: {file_path}")
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}"}
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        files = {"file": (file_name, f)}
        data = {
            "file_name": file_name,
            "parent_type": settings.image_docx_parent_type,
            "parent_node": image_block_id,
            "size": str(file_size),
        }
        resp = requests.post(
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers=headers,
            data=data,
            files=files,
            timeout=60,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu upload image HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu upload image error: {data}")
    file_token = data.get("data", {}).get("file_token")
    if not file_token:
        raise RuntimeError(f"Feishu upload image missing file_token: {data}")
    return file_token


def update_image_block(settings: Settings, doc_id: str, block_id: str, file_token: str) -> None:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"replace_image": {"token": file_token}}
    resp = requests.patch(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu update image block HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu update image block error: {data}")


def _append_blocks_raw(settings: Settings, doc_id: str, blocks: list[dict]) -> None:
    token = get_tenant_access_token(settings)
    headers = {"Authorization": f"Bearer {token}"}
    if not blocks:
        return
    root_block_id = get_document_root_block_id(settings, doc_id)
    payload = {"children": blocks}
    resp = requests.post(
        f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{root_block_id}/children",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Feishu append blocks HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get("code") not in (0, "0"):
        raise RuntimeError(f"Feishu append blocks error: {data}")


def append_blocks(settings: Settings, doc_id: str, blocks: list[dict]) -> None:
    if not blocks:
        return
    pending: list[dict] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("block_type") == 27 and isinstance(block.get("image"), dict):
            image = block.get("image") or {}
            file_path = image.get("local_path")
            if file_path:
                if pending:
                    _append_blocks_raw(settings, doc_id, pending)
                    pending = []
                image_block_id = create_image_block(settings, doc_id)
                file_token = upload_docx_image(settings, image_block_id, file_path)
                update_image_block(settings, doc_id, image_block_id, file_token)
                continue
        pending.append(block)
    if pending:
        _append_blocks_raw(settings, doc_id, pending)


def build_doc_blocks(settings: Settings, title: str, meta: dict) -> list[dict]:
    blocks: list[dict] = []
    summary = meta.get("summary") if isinstance(meta, dict) else None
    body = meta.get("body") if isinstance(meta, dict) else None
    points = meta.get("points") if isinstance(meta, dict) else None
    quote_spans = meta.get("quote_spans") if isinstance(meta, dict) else None
    attribution = meta.get("attribution") if isinstance(meta, dict) else None
    images = meta.get("images") if isinstance(meta, dict) else None

    if summary:
        blocks.append(_paragraph_block(str(summary)))

    body_paragraphs = _normalize_paragraphs(body)
    if body_paragraphs:
        for paragraph in body_paragraphs:
            blocks.append(_paragraph_block(paragraph))

    if isinstance(points, list) and points:
        blocks.append(_paragraph_block("要点"))
        for p in points:
            text = str(p).strip()
            if text:
                blocks.append(_paragraph_block(f"- {text}"))

    if isinstance(images, list) and images:
        order = {"cover": 0, "inline": 1, "demo": 2}
        sorted_images = sorted(
            [img for img in images if isinstance(img, dict)],
            key=lambda item: order.get(str(item.get("slot")), 3),
        )
        for img in sorted_images:
            file_path = img.get("path")
            if not file_path:
                continue
            try:
                blocks.append(_local_image_block(file_path))
            except Exception:
                blocks.append(_paragraph_block(f"图片链接：{file_path}"))

    if isinstance(quote_spans, list) and quote_spans:
        blocks.append(_paragraph_block("引用"))
        for q in quote_spans:
            text = str(q).strip()
            if text:
                blocks.append(_paragraph_block(f"- {text}"))

    if isinstance(attribution, list) and attribution:
        blocks.append(_paragraph_block("来源"))
        for u in attribution:
            text = str(u).strip()
            if text:
                blocks.append(_paragraph_block(f"- {text}"))

    return blocks
