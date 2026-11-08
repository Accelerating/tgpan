from fastapi import HTTPException


def get_config(state, owner, identity):
    config = state.db.one("SELECT * FROM configs WHERE id=? AND owner_id=?", (identity, owner))
    if not config:
        raise HTTPException(404, "存储配置不存在")
    return config


def redact(config):
    return {k: v for k, v in config.items() if k not in ("token", "owner_id")}


class TelegramError(Exception):
    def __init__(self, code, description="", retry_after=None):
        self.code = code
        self.retry_after = retry_after
        description = description.lower()
        self.message_missing = "message to delete not found" in description
        if self.message_missing:
            self.detail = "Telegram 消息已不存在"
        elif code == 429:
            self.detail = f"Telegram 限流，请在 {retry_after or 60} 秒后重试"
        elif code == 401:
            self.detail = "Bot Token 无效或已被撤销，请检查机器人配置"
        elif code == 403:
            self.detail = "机器人无权操作该频道，请检查成员身份和管理员权限"
        elif "can't be deleted" in description or "cannot be deleted" in description:
            self.detail = "Telegram 拒绝删除消息：可能已超过 48 小时或缺少删除权限，可在频道内手动清理"
        elif "chat not found" in description:
            self.detail = "找不到频道，请检查频道 ID，并将机器人添加为管理员"
        elif "file is too big" in description:
            self.detail = "文件块超过 Bot API 下载限制，请检查存储块配置"
        else:
            self.detail = f"Telegram 操作失败（状态码 {code}），请检查频道配置和网络后重试"
        super().__init__(self.detail)


def safe_error(error):
    if isinstance(error, TelegramError):
        return error.detail
    if isinstance(error, ValueError) and str(error) in (
        "Telegram 文件长度与记录不一致",
        "Telegram 文件范围与记录不一致",
        "Telegram 文件地址无效",
        "目标必须是频道，请使用私有频道作为存储",
        "机器人身份不正确",
        "下载内容校验失败",
        "请将机器人设为频道管理员，并开启发布消息和删除消息权限",
    ):
        return str(error)
    return f"Telegram 操作失败（{type(error).__name__}），请检查凭据、频道权限和网络后重试"


class StorageTestFailure(Exception):
    def __init__(self, steps, error):
        self.steps = steps
        self.error = safe_error(error)
        super().__init__(self.error)
