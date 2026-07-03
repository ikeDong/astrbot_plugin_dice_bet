# astrbot_plugin_dice_bet

QQ 骰子 / 猜拳赌局插件。

核心能力：

- 注册 LLM 工具 `roll_qq_dice_for_bet` 和 `play_qq_rps_for_bet`
- 通过 NapCat / OneBot 发送 QQ 自带骰子、猜拳消息段
- 优先从发送回执里的 `message_id` 拉取消息，解析 Bot 自己的真实结果
- 监听群聊/私聊中的骰子和猜拳消息，记录最近一次用户结果
- 对比用户结果与 Bot 结果，把输赢返回给 LLM

## 使用逻辑

用户想和 Bot 打赌时，LLM 应先要求对方丢骰子或发猜拳。检测到用户已经发送对应 QQ 魔法表情后，再调用对应工具。

工具会返回：用户结果、Bot 结果、胜负结果。


## v1.2.0 改进

- 新增 QQ 自带猜拳赌局工具 `play_qq_rps_for_bet`。
- 复用骰子的回执拉取和消息监听逻辑，无法确认真实 QQ 结果时不判定输赢。
- 按会话和用户分别记录最近骰子 / 猜拳，群聊多人同时游戏时可通过 `opponent_user_id` 指定对手。
- 增加会话级异步锁，避免同一会话内并发调用导致结果串线。
- 自动清理过期游戏记录，默认有效期 300 秒。

## 安装

```bash
cd /path/to/AstrBot/data/plugins
git clone -b dev https://github.com/ikeDong/astrbot_plugin_dice_bet.git
```

重启 AstrBot 或在插件管理页重载插件。

## 工具参数

- `opponent_user_id`：指定对手 QQ 号。为空时使用当前会话最近一次非 Bot 游戏结果。
- `max_age_seconds`：接受对手游戏结果的最大时间窗口，默认 300 秒。
- `allow_without_opponent_dice`：没有对手骰子时是否仍允许 Bot 丢骰子，默认 false。
- `allow_without_opponent_rps`：没有对手猜拳时是否仍允许 Bot 发猜拳，默认 false。
