# astrbot_plugin_dice_bet

QQ 骰子赌局插件。

核心能力：

- 注册 LLM 工具 `roll_qq_dice_for_bet`
- 通过 NapCat / OneBot 发送 QQ 自带骰子消息段
- 优先从发送回执里的 `message_id` 拉取消息，解析 Bot 自己骰子点数
- 监听群聊/私聊中的骰子消息，记录最近一次用户骰子结果
- 对比用户点数与 Bot 点数，把输赢返回给 LLM

## 使用逻辑

用户想和 Bot 打赌时，LLM 应先要求对方丢骰子。检测到用户已经丢骰子后，再调用 `roll_qq_dice_for_bet`。

工具会返回：用户点数、Bot 点数、胜负结果。


## v1.1.0 改进

- 去除 Bot 点数的随机兜底：无法确认真实 QQ 骰子结果时，本局不判定输赢。
- 按会话和用户分别记录最近骰子，群聊多人同时丢骰子时可通过 `opponent_user_id` 指定对手。
- 增加会话级异步锁，避免同一会话内并发调用导致结果串线。
- 自动清理过期骰子记录，默认有效期 300 秒。

## 安装

```bash
cd /path/to/AstrBot/data/plugins
git clone -b dev https://github.com/ikeDong/astrbot_plugin_dice_bet.git
```

重启 AstrBot 或在插件管理页重载插件。

## 工具参数

- `opponent_user_id`：指定对手 QQ 号。为空时使用当前会话最近一次非 Bot 骰子。
- `max_age_seconds`：接受对手骰子的最大时间窗口，默认 300 秒。
- `allow_without_opponent_dice`：没有对手骰子时是否仍允许 Bot 丢骰子，默认 false。
