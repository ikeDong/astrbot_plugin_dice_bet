import asyncio
import random
import re
import time
from dataclasses import dataclass
from typing import Any

from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


@dataclass
class DiceRecord:
    user_id: str
    value: int
    message_id: str | None
    timestamp: float
    is_self: bool = False


class DiceBetPlugin(Star):
    """QQ 自带骰子赌局工具。"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.recent_dice: dict[str, DiceRecord] = {}
        self.self_dice: dict[str, DiceRecord] = {}

    def _session_key(self, event: AiocqhttpMessageEvent) -> str:
        gid = event.get_group_id()
        if gid:
            return f"group:{gid}"
        return f"private:{event.get_sender_id()}"

    def _extract_segments(self, raw: Any) -> list[dict]:
        if raw is None:
            return []
        if isinstance(raw, dict):
            msg = raw.get("message") or raw.get("raw_message") or raw.get("messages")
            if isinstance(msg, list):
                return [x for x in msg if isinstance(x, dict)]
            if isinstance(msg, dict):
                return [msg]
            return []
        if hasattr(raw, "get"):
            try:
                msg = raw.get("message")
                if isinstance(msg, list):
                    return [x for x in msg if isinstance(x, dict)]
            except Exception:
                return []
        return []

    def _extract_dice_value_from_segments(self, segments: list[dict]) -> int | None:
        for seg in segments:
            seg_type = str(seg.get("type", "")).lower()
            data = seg.get("data") or {}
            if seg_type == "dice":
                for key in ("result", "value", "id"):
                    val = data.get(key)
                    if val is not None:
                        try:
                            num = int(val)
                            if 1 <= num <= 6:
                                return num
                        except Exception:
                            pass
                return None
            if seg_type == "rps":
                continue
        return None

    def _extract_dice_value_from_text(self, text: str | None) -> int | None:
        if not text:
            return None
        # 常见 CQ 码：[CQ:dice,result=4] / [CQ:dice,id=4]
        m = re.search(r"\[CQ:dice(?:,[^\]]*)?(?:result|value|id)=([1-6])[^\]]*\]", text)
        if m:
            return int(m.group(1))
        if "[CQ:dice" in text or "type=dice" in text:
            return None
        return None

    def _extract_dice_value(self, raw: Any, fallback_text: str | None = None) -> int | None:
        value = self._extract_dice_value_from_segments(self._extract_segments(raw))
        if value is not None:
            return value
        return self._extract_dice_value_from_text(fallback_text)

    def _get_message_id_from_raw(self, raw: Any) -> str | None:
        if raw is None:
            return None
        try:
            mid = raw.get("message_id")
            return str(mid) if mid is not None else None
        except Exception:
            return None

    async def _send_dice(self, event: AiocqhttpMessageEvent) -> str | None:
        is_group = bool(event.get_group_id())
        session_id = event.get_group_id() if is_group else event.get_sender_id()
        payload = [{"type": "dice", "data": {}}]
        routing_params = {}
        raw_event = getattr(event.message_obj, "raw_message", None)
        try:
            if raw_event and raw_event.get("self_id"):
                routing_params["self_id"] = raw_event["self_id"]
        except Exception:
            pass

        if is_group:
            ret = await event.bot.send_group_msg(group_id=int(session_id), message=payload, **routing_params)
        else:
            ret = await event.bot.send_private_msg(user_id=int(session_id), message=payload, **routing_params)

        if isinstance(ret, dict) and ret.get("message_id") is not None:
            return str(ret.get("message_id"))
        return None

    async def _fetch_message_dice_value(self, event: AiocqhttpMessageEvent, message_id: str | None) -> int | None:
        if not message_id:
            return None
        for _ in range(6):
            try:
                ret = await event.bot.get_msg(message_id=int(message_id))
                value = self._extract_dice_value(ret, str(ret))
                if value is not None:
                    return value
            except Exception:
                pass
            await asyncio.sleep(0.35)
        return None

    def _find_recent_opponent_dice(
        self,
        session_key: str,
        opponent_user_id: str | None,
        max_age_seconds: int,
    ) -> DiceRecord | None:
        rec = self.recent_dice.get(session_key)
        if not rec:
            return None
        if time.time() - rec.timestamp > max_age_seconds:
            return None
        if opponent_user_id and rec.user_id != str(opponent_user_id):
            return None
        return rec

    @filter.llm_tool()
    async def roll_qq_dice_for_bet(
        self,
        event: AiocqhttpMessageEvent,
        opponent_user_id: str | None = None,
        max_age_seconds: int = 300,
        allow_without_opponent_dice: bool = False,
    ) -> str:
        """
        在 QQ 打赌场景中替 Bot 丢一颗 QQ 自带骰子，并把骰子点数与输赢返回给 LLM。

        使用时机：
        - 当用户明确想和 Bot 掷骰子打赌、比大小、定输赢时使用。
        - 一般应该先让对方发送 QQ 自带骰子，确认对方已经丢出结果后，再调用本工具。
        - 如果还没有检测到对方近期骰子，通常不要调用；应先让对方丢骰子。

        Args:
            opponent_user_id(string): 对手 QQ 号。可为空，为空时使用当前会话最近一个非 Bot 骰子。
            max_age_seconds(number): 接受对手骰子的最大时间窗口，默认 300 秒。
            allow_without_opponent_dice(boolean): 是否允许没有对手骰子也直接丢。默认 false。
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "失败：当前平台不是 aiocqhttp / NapCat，不能发送 QQ 自带骰子。"

        session_key = self._session_key(event)
        opponent = self._find_recent_opponent_dice(session_key, opponent_user_id, int(max_age_seconds or 300))
        if not opponent and not allow_without_opponent_dice:
            return "还没发现对方近期发出的骰子。请先让对方发送 QQ 自带骰子，Bot 再后手丢。"

        try:
            msg_id = await self._send_dice(event)
        except Exception as e:
            return f"发送 QQ 骰子失败：{e}"

        bot_value = await self._fetch_message_dice_value(event, msg_id)
        if bot_value is None:
            # 兜底：NapCat 理论上可用 get_msg 拿结果；拿不到时避免谎称确定值。
            bot_value = random.randint(1, 6)
            uncertain = True
        else:
            uncertain = False

        self_id = str(event.get_self_id())
        self_rec = DiceRecord(self_id, bot_value, msg_id, time.time(), True)
        self.self_dice[session_key] = self_rec

        if not opponent:
            suffix = "，但未能从回执确认真实点数，返回的是兜底随机值" if uncertain else ""
            return f"Bot 已发送 QQ 骰子，Bot 点数：{bot_value}{suffix}。没有对手骰子，无法判断输赢。"

        if bot_value > opponent.value:
            result = "Bot 赢了"
        elif bot_value < opponent.value:
            result = "Bot 输了"
        else:
            result = "平局"

        suffix = "。注意：未能从回执确认 Bot 真实点数，Bot 点数为兜底随机值" if uncertain else ""
        return f"对手 {opponent.user_id} 点数：{opponent.value}；Bot 点数：{bot_value}；结果：{result}{suffix}。"

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AiocqhttpMessageEvent):
        raw = getattr(event.message_obj, "raw_message", None)
        value = self._extract_dice_value(raw, event.message_str)
        if value is None:
            return

        session_key = self._session_key(event)
        user_id = str(event.get_sender_id())
        self_id = str(event.get_self_id())
        rec = DiceRecord(
            user_id=user_id,
            value=value,
            message_id=self._get_message_id_from_raw(raw),
            timestamp=time.time(),
            is_self=user_id == self_id,
        )
        if rec.is_self:
            self.self_dice[session_key] = rec
        else:
            self.recent_dice[session_key] = rec
