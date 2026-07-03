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
