import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from ..config import Settings



def _get_chat_id(settings: Settings) -> str:
    chat_id = settings.feishu_push_chat_id
    if not chat_id:
        raise RuntimeError("FEISHU_PUSH_CHAT_ID missing.")
    return chat_id


def _get_client(settings: Settings) -> lark.Client:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("FEISHU_APP_ID/FEISHU_APP_SECRET missing.")
    return (
        lark.Client.builder()
        .app_id(settings.feishu_app_id)
        .app_secret(settings.feishu_app_secret)
        .log_level(lark.LogLevel.ERROR)
        .build()
    )


def _send_message(settings: Settings, msg_type: str, content: dict[str, object]) -> None:
    chat_id = _get_chat_id(settings)
    client = _get_client(settings)
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(chat_id)
        .msg_type(msg_type)
        .content(json.dumps(content, ensure_ascii=False))
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(body)
        .build()
    )
    resp = client.im.v1.message.create(req)
    if not resp.success():
        raise RuntimeError(f"Feishu API error: {resp.code} {resp.msg}")


def send_text(settings: Settings, text: str) -> None:
    _send_message(settings, "text", {"text": text})


def _build_action_value(
    output_id: int,
    topic_kind: str | None,
    topic_ref_id: int | None,
    label: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "output_id": output_id,
        "label": label,
    }
    if topic_kind:
        payload["topic_kind"] = topic_kind
    if topic_ref_id is not None:
        payload["topic_ref_id"] = topic_ref_id
    return payload


def build_output_card(
    output_id: int,
    content: str,
    topic_kind: str | None,
    topic_ref_id: int | None,
) -> dict[str, object]:
    safe_content = content.strip() if content else "(空内容)"
    actions = [
        {
            "tag": "button",
            "type": "primary",
            "text": {"tag": "plain_text", "content": "👍 有用"},
            "value": _build_action_value(output_id, topic_kind, topic_ref_id, "useful"),
        },
        {
            "tag": "button",
            "type": "danger",
            "text": {"tag": "plain_text", "content": "👎 没用"},
            "value": _build_action_value(output_id, topic_kind, topic_ref_id, "useless"),
        },
        {
            "tag": "button",
            "type": "default",
            "text": {"tag": "plain_text", "content": "⚠️ 纠错"},
            "value": _build_action_value(output_id, topic_kind, topic_ref_id, "correct"),
        },
    ]
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🚀 AI Briefing · AI1"},
            "template": "blue",
        },
        "elements": [
            {"tag": "markdown", "content": safe_content},
            {"tag": "action", "actions": actions},
        ],
    }


def send_output_card(
    settings: Settings,
    output_id: int,
    content: str,
    topic_kind: str | None,
    topic_ref_id: int | None,
) -> None:
    card = build_output_card(output_id, content, topic_kind, topic_ref_id)
    _send_message(settings, "interactive", card)
