import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


@dataclass
class GameRecord:
    user_id: str
    value: int
    message_id: str | None
    timestamp: float
    is_self: bool = False


class DiceBetPlugin(Star):
    """QQ 自带骰子 / 猜拳赌局工具。"""

    RPS_NAMES = {
        1: "石头",
        2: "剪刀",
        3: "布",
    }

    def __init__(self, context: Context):
        super().__init__(context)
        self.recent_dice: dict[str, dict[str, GameRecord]] = {}
        self.self_dice: dict[str, GameRecord] = {}
        self.recent_rps: dict[str, dict[str, GameRecord]] = {}
        self.self_rps: dict[str, GameRecord] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        self.default_max_age_seconds = 300

    def _get_lock(self, session_key: str) -> asyncio.Lock:
        lock = self.session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self.session_locks[session_key] = lock
        return lock

    def _cleanup_expired(self, session_key: str, max_age_seconds: int | None = None) -> None:
        max_age = int(max_age_seconds or self.default_max_age_seconds)
        now = time.time()
        users = self.recent_dice.get(session_key)
        if users:
            for uid in list(users.keys()):
                if now - users[uid].timestamp > max_age:
                    users.pop(uid, None)
            if not users:
                self.recent_dice.pop(session_key, None)
        rec = self.self_dice.get(session_key)
        if rec and now - rec.timestamp > max_age:
            self.self_dice.pop(session_key, None)
        users = self.recent_rps.get(session_key)
        if users:
            for uid in list(users.keys()):
                if now - users[uid].timestamp > max_age:
                    users.pop(uid, None)
            if not users:
                self.recent_rps.pop(session_key, None)
        rec = self.self_rps.get(session_key)
        if rec and now - rec.timestamp > max_age:
            self.self_rps.pop(session_key, None)

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

    def _extract_game_value_from_segments(self, segments: list[dict], seg_name: str, min_value: int, max_value: int) -> int | None:
        for seg in segments:
            seg_type = str(seg.get("type", "")).lower()
            data = seg.get("data") or {}
            if seg_type != seg_name:
                continue
            for key in ("result", "value", "id"):
                val = data.get(key)
                if val is not None:
                    try:
                        num = int(val)
                        if min_value <= num <= max_value:
                            return num
                    except Exception:
                        pass
            return None
        return None

    def _extract_dice_value_from_segments(self, segments: list[dict]) -> int | None:
        return self._extract_game_value_from_segments(segments, "dice", 1, 6)

    def _extract_rps_value_from_segments(self, segments: list[dict]) -> int | None:
        return self._extract_game_value_from_segments(segments, "rps", 1, 3)

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

    def _extract_rps_value_from_text(self, text: str | None) -> int | None:
        if not text:
            return None
        m = re.search(r"\[CQ:rps(?:,[^\]]*)?(?:result|value|id)=([1-3])[^\]]*\]", text)
        if m:
            return int(m.group(1))
        if "[CQ:rps" in text or "type=rps" in text:
            return None
        return None

    def _extract_rps_value(self, raw: Any, fallback_text: str | None = None) -> int | None:
        value = self._extract_rps_value_from_segments(self._extract_segments(raw))
        if value is not None:
            return value
        return self._extract_rps_value_from_text(fallback_text)

    def _get_message_id_from_raw(self, raw: Any) -> str | None:
        if raw is None:
            return None
        try:
            mid = raw.get("message_id")
            return str(mid) if mid is not None else None
        except Exception:
            return None

    async def _send_game_magic(self, event: AiocqhttpMessageEvent, seg_name: str) -> str | None:
        is_group = bool(event.get_group_id())
        session_id = event.get_group_id() if is_group else event.get_sender_id()
        payload = [{"type": seg_name, "data": {}}]
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

    async def _fetch_message_game_value(self, event: AiocqhttpMessageEvent, message_id: str | None, seg_name: str) -> int | None:
        if not message_id:
            return None
        extractor = self._extract_dice_value if seg_name == "dice" else self._extract_rps_value
        for _ in range(6):
            try:
                ret = await event.bot.get_msg(message_id=int(message_id))
                value = extractor(ret, str(ret))
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
    ) -> GameRecord | None:
        self._cleanup_expired(session_key, max_age_seconds)
        users = self.recent_dice.get(session_key) or {}
        if opponent_user_id:
            rec = users.get(str(opponent_user_id))
            if not rec:
                return None
            if time.time() - rec.timestamp > max_age_seconds:
                return None
            return rec
        records = [r for r in users.values() if time.time() - r.timestamp <= max_age_seconds]
        if not records:
            return None
        return max(records, key=lambda r: r.timestamp)

    def _find_recent_opponent_rps(
        self,
        session_key: str,
        opponent_user_id: str | None,
        max_age_seconds: int,
    ) -> GameRecord | None:
        self._cleanup_expired(session_key, max_age_seconds)
        users = self.recent_rps.get(session_key) or {}
        if opponent_user_id:
            rec = users.get(str(opponent_user_id))
            if not rec:
                return None
            if time.time() - rec.timestamp > max_age_seconds:
                return None
            return rec
        records = [r for r in users.values() if time.time() - r.timestamp <= max_age_seconds]
        if not records:
            return None
        return max(records, key=lambda r: r.timestamp)

    def _judge_rps(self, bot_value: int, opponent_value: int) -> str:
        if bot_value == opponent_value:
            return "平局"
        if (bot_value, opponent_value) in ((1, 2), (2, 3), (3, 1)):
            return "Bot 赢了"
        return "Bot 输了"

    async def _send_and_record_self_game(
        self,
        event: AiocqhttpMessageEvent,
        session_key: str,
        seg_name: str,
    ) -> tuple[int | None, str | None, str | None]:
        try:
            msg_id = await self._send_game_magic(event, seg_name)
        except Exception as e:
            return None, None, str(e)

        bot_value = await self._fetch_message_game_value(event, msg_id, seg_name)
        if bot_value is None:
            return None, msg_id, None

        self_id = str(event.get_self_id())
        self_rec = GameRecord(self_id, bot_value, msg_id, time.time(), True)
        if seg_name == "dice":
            self.self_dice[session_key] = self_rec
        else:
            self.self_rps[session_key] = self_rec
        return bot_value, msg_id, None

    @filter.llm_tool()
    async def roll_qq_dice(
        self,
        event: AiocqhttpMessageEvent,
        judge_with_opponent: bool = False,
        opponent_user_id: str | None = None,
        max_age_seconds: int = 300,
    ) -> str:
        """
        替 Bot 发送一颗 QQ 自带骰子，并返回 Bot 自己的真实点数；需要对局时可同时判定输赢。

        使用时机：
        - 用户只是让 Bot 丢骰子、摇骰子、发一个 QQ 骰子时，直接调用本工具，judge_with_opponent 保持 false。
        - 用户明确想打赌、比大小、定输赢时，先让对方发送 QQ 自带骰子；检测到对方结果后调用本工具，并设置 judge_with_opponent=true。
        - 如果 judge_with_opponent=true 但没有检测到对方近期骰子，工具不会发送骰子，会提示先让对方发送。

        Args:
            judge_with_opponent(boolean): 是否按最近的对手骰子判定输赢，默认 false。
            opponent_user_id(string): 对手 QQ 号。可为空，为空时使用当前会话最近一个非 Bot 骰子。
            max_age_seconds(number): 接受对手骰子的最大时间窗口，默认 300 秒。
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "失败：当前平台不是 aiocqhttp / NapCat，不能发送 QQ 自带骰子。"

        session_key = self._session_key(event)
        opponent = None
        if judge_with_opponent:
            opponent = self._find_recent_opponent_dice(session_key, opponent_user_id, int(max_age_seconds or 300))
            if not opponent:
                return "还没发现对方近期发出的骰子。请先让对方发送 QQ 自带骰子，Bot 再后手丢。"

        async with self._get_lock(session_key):
            bot_value, _, error = await self._send_and_record_self_game(event, session_key, "dice")
            if error:
                return f"发送 QQ 骰子失败：{error}"
            if bot_value is None:
                return "Bot 已发送 QQ 骰子，但未能从平台回执确认真实点数。"

            if not judge_with_opponent:
                return f"Bot 已发送 QQ 骰子，点数：{bot_value}。"

            if bot_value > opponent.value:
                result = "Bot 赢了"
            elif bot_value < opponent.value:
                result = "Bot 输了"
            else:
                result = "平局"

            return f"对手 {opponent.user_id} 点数：{opponent.value}；Bot 点数：{bot_value}；结果：{result}。"

    @filter.llm_tool()
    async def play_qq_rps(
        self,
        event: AiocqhttpMessageEvent,
        judge_with_opponent: bool = False,
        opponent_user_id: str | None = None,
        max_age_seconds: int = 300,
    ) -> str:
        """
        替 Bot 发送一个 QQ 自带猜拳魔法表情，并返回 Bot 自己的真实结果；需要对局时可同时判定输赢。

        使用时机：
        - 用户只是让 Bot 发石头剪刀布、猜拳、QQ 猜拳时，直接调用本工具，judge_with_opponent 保持 false。
        - 用户明确想猜拳对局、打赌、定输赢时，先让对方发送 QQ 自带猜拳；检测到对方结果后调用本工具，并设置 judge_with_opponent=true。
        - 如果 judge_with_opponent=true 但没有检测到对方近期猜拳，工具不会发送猜拳，会提示先让对方发送。

        Args:
            judge_with_opponent(boolean): 是否按最近的对手猜拳判定输赢，默认 false。
            opponent_user_id(string): 对手 QQ 号。可为空，为空时使用当前会话最近一个非 Bot 猜拳。
            max_age_seconds(number): 接受对手猜拳的最大时间窗口，默认 300 秒。
        """
        if not isinstance(event, AiocqhttpMessageEvent):
            return "失败：当前平台不是 aiocqhttp / NapCat，不能发送 QQ 自带猜拳。"

        session_key = self._session_key(event)
        opponent = None
        if judge_with_opponent:
            opponent = self._find_recent_opponent_rps(session_key, opponent_user_id, int(max_age_seconds or 300))
            if not opponent:
                return "还没发现对方近期发出的猜拳。请先让对方发送 QQ 自带猜拳，Bot 再后手发。"

        async with self._get_lock(session_key):
            bot_value, _, error = await self._send_and_record_self_game(event, session_key, "rps")
            if error:
                return f"发送 QQ 猜拳失败：{error}"
            if bot_value is None:
                return "Bot 已发送 QQ 猜拳，但未能从平台回执确认真实结果。"

            bot_name = self.RPS_NAMES.get(bot_value, str(bot_value))
            if not judge_with_opponent:
                return f"Bot 已发送 QQ 猜拳，结果：{bot_name}。"

            opponent_name = self.RPS_NAMES.get(opponent.value, str(opponent.value))
            result = self._judge_rps(bot_value, opponent.value)
            return f"对手 {opponent.user_id} 结果：{opponent_name}；Bot 结果：{bot_name}；结果：{result}。"

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AiocqhttpMessageEvent):
        raw = getattr(event.message_obj, "raw_message", None)
        dice_value = self._extract_dice_value(raw, event.message_str)
        rps_value = self._extract_rps_value(raw, event.message_str)
        if dice_value is None and rps_value is None:
            return

        session_key = self._session_key(event)
        user_id = str(event.get_sender_id())
        self_id = str(event.get_self_id())
        message_id = self._get_message_id_from_raw(raw)
        self._cleanup_expired(session_key)

        if dice_value is not None:
            rec = GameRecord(
                user_id=user_id,
                value=dice_value,
                message_id=message_id,
                timestamp=time.time(),
                is_self=user_id == self_id,
            )
            if rec.is_self:
                self.self_dice[session_key] = rec
            else:
                self.recent_dice.setdefault(session_key, {})[user_id] = rec

        if rps_value is not None:
            rec = GameRecord(
                user_id=user_id,
                value=rps_value,
                message_id=message_id,
                timestamp=time.time(),
                is_self=user_id == self_id,
            )
            if rec.is_self:
                self.self_rps[session_key] = rec
            else:
                self.recent_rps.setdefault(session_key, {})[user_id] = rec
