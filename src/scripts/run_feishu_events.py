import json
import logging
import os
import sys

from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.event.callback.model import p2_card_action_trigger
from lark_oapi.ws import Client as WsClient

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ai_briefing.config import get_settings
from ai_briefing.db import get_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("feishu_events")

ALLOWED_LABELS = {"useful", "useless", "correct", "skip"}


def _parse_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _get_user_id(operator: p2_card_action_trigger.CallBackOperator | None) -> str:
    if not operator:
        return ""
    return operator.user_id or operator.open_id or operator.union_id or ""


def _build_toast(message: str) -> p2_card_action_trigger.P2CardActionTriggerResponse:
    toast = p2_card_action_trigger.CallBackToast()
    toast.type = "success"
    toast.content = message
    resp = p2_card_action_trigger.P2CardActionTriggerResponse()
    resp.toast = toast
    return resp


def _should_skip_feedback(
    cur,
    user_id: str,
    topic_kind: str,
    topic_ref_id: int,
    label: str,
) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM user_feedback
        WHERE user_id = %s
          AND topic_kind = %s
          AND topic_ref_id = %s
          AND label = %s
          AND created_at > NOW() - INTERVAL '1 DAY'
        LIMIT 1
        """,
        (user_id, topic_kind, topic_ref_id, label),
    )
    return cur.fetchone() is not None


def _record_feedback(
    settings,
    user_id: str,
    label: str,
    topic_kind: str,
    topic_ref_id: int,
    output_id: int | None,
) -> None:
    reason = None
    if output_id is not None:
        reason = json.dumps({"output_id": output_id}, ensure_ascii=False)
    with get_conn(settings) as conn:
        with conn.cursor() as cur:
            if _should_skip_feedback(cur, user_id, topic_kind, topic_ref_id, label):
                return
            cur.execute(
                """
                INSERT INTO user_feedback (topic_kind, topic_ref_id, label, reason, user_id, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (topic_kind, topic_ref_id, label, reason, user_id),
            )
            if label == "correct" and output_id is not None:
                cur.execute(
                    "UPDATE outputs SET status = 'review' WHERE id = %s",
                    (output_id,),
                )
        conn.commit()


def handle_card_action(
    data: p2_card_action_trigger.P2CardActionTrigger,
) -> p2_card_action_trigger.P2CardActionTriggerResponse:
    event = data.event
    if not event or not event.action:
        return _build_toast("反馈无效")

    action_value = event.action.value or {}
    if not isinstance(action_value, dict):
        return _build_toast("反馈无效")

    label = str(action_value.get("label") or "").strip()
    if label not in ALLOWED_LABELS:
        return _build_toast("反馈无效")

    topic_kind = str(action_value.get("topic_kind") or "").strip()
    topic_ref_id = _parse_int(action_value.get("topic_ref_id"))
    output_id = _parse_int(action_value.get("output_id"))

    if not topic_kind:
        topic_kind = "output"
    if topic_ref_id is None and output_id is not None:
        topic_ref_id = output_id
    if topic_ref_id is None:
        return _build_toast("反馈缺少关联")

    user_id = _get_user_id(event.operator)
    if not user_id:
        return _build_toast("反馈缺少用户信息")

    settings = get_settings()
    try:
        _record_feedback(settings, user_id, label, topic_kind, topic_ref_id, output_id)
    except Exception as e:
        logger.error(f"反馈写入失败: {e}")
        return _build_toast("反馈写入失败")

    toast_msg = {
        "useful": "已记录：有用",
        "useless": "已记录：没用",
        "correct": "已记录：纠错",
        "skip": "已记录：跳过",
    }.get(label, "已记录反馈")
    return _build_toast(toast_msg)


def main() -> None:
    load_dotenv("/opt/ai_briefing/.env")
    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise SystemExit("FEISHU_APP_ID/FEISHU_APP_SECRET missing")

    handler = (
        EventDispatcherHandler.builder(
            "",
            "",
            lark.LogLevel.INFO,
        )
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )

    ws_client = WsClient(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        log_level=lark.LogLevel.INFO,
        event_handler=handler,
        domain=lark.FEISHU_DOMAIN,
        auto_reconnect=True,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
