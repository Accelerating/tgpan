# Telegram 配置

使用官方云端 Telegram Bot API，通过 HTTPX 发起 HTTPS 请求；不再需要 my.telegram.org 申请应用，也不需要 api_id、api_hash、手机号授权、Telethon 会话或自建 Bot API 服务。

## Telegram 端准备

1. 打开官方 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示创建机器人并保存 Bot Token。
2. 创建一个私有频道作为存储容器，关闭消息自动删除。
3. 将机器人设为频道管理员，开启“发布消息”和“删除消息”权限。
4. 在频道发布一条初始化消息，复制其消息链接，例如 `https://t.me/c/1234567890/2`。本项目的频道 ID 为中间数字前拼 `-100`，即 `-1001234567890`；最后一段是消息编号，不包含在频道 ID 中。
5. 登录网盘 → 设置 → 添加配置，填写配置名称、Bot Token 和频道 ID，点击“测试连接”。

不需要设置 Webhook。第一版不接收机器人聊天命令，文件通过网盘页面管理，不自动导入频道内手动发送的附件。

## 配置与连接测试

每个用户可保存多组独立 Bot Token 和频道。Token 用 Fernet 加密保存，查询配置时不回传。第一组自动为默认配置，也可以切换默认；已有文件及任务仍绑定原配置。名称可修改，Token 和频道需通过新增配置更换。被文件、未结束任务或清理记录引用的配置禁止删除。

配置以紧凑卡片显示，测试连接、设为默认、重命名和删除集中在同一操作区；手机端操作区换行显示。

测试依次执行 getMe、getChat/getChatMember（频道类型和管理员发布/删除权限）、上传小文件、getFile 下载内容校验、删除测试消息。失败时保留已经通过的步骤并显示安全错误说明，不暴露 Token 或临时下载地址。超时或网络异常可能使测试消息残留，可在频道手动删除。

连接测试最多运行 90 秒，全站最多 2 个、每个帐号最多 1 个并发，忙时直接返回 429。远程测试不占用全局修改锁，不阻塞文件移动或分享撤销；测试中的配置暂不能删除，测试结束或取消后释放占用。

## 文件存储与限制

普通上传附件最大 50MB，云端 getFile 下载最大 20MB，因此每个存储块默认 16MiB，逻辑文件仍支持最大 5GB。sendDocument 返回的 `message_id` 用于删除，`document.file_id` 用于后续 getFile 下载，两者都持久化；不依赖 Bot API 未提供的任意历史消息查询能力。临时下载链接在每次下载时获取，不直接暴露给浏览器。

Bot API 通常只能删除发送不超过 48 小时的消息。永久删除文件后后台尽力删除附件；超期或无权限时在传输页保留失败清理记录，明确提示手动清理。远端消息已被手动删除时，重试清理视为成功。

网络通过可选 `TGPAN_PROXY_URL` 配置 HTTP/HTTPS/SOCKS5 代理。429 限流错误展示 Telegram 返回的 retry_after，用户等待后重试。网络超时和权限错误不会在页面回传含 Token 的请求 URL。

参考：[BotFather](https://core.telegram.org/bots/features#creating-a-new-bot)、[发送文件](https://core.telegram.org/bots/api#senddocument)、[获取文件](https://core.telegram.org/bots/api#getfile)、[删除消息](https://core.telegram.org/bots/api#deletemessage)。
