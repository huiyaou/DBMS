"""数据库配置：从环境变量读取，默认连接本地 MongoDB。"""

from dataclasses import dataclass
import os
import re


@dataclass(frozen=True)
class DatabaseSettings:
    uri: str = "mongodb://localhost:27017/"
    database_name: str = "survey_system"
    timeout_ms: int = 5000

    def __post_init__(self) -> None:
        if not self.uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URI 必须是 MongoDB 连接地址")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,62}", self.database_name):
            raise ValueError("数据库名须以字母开头，使用字母、数字、下划线或横线，最多 63 字符")
        if self.database_name.lower() in {"admin", "config", "local"}:
            raise ValueError("不能使用 MongoDB 系统数据库")
        if self.timeout_ms <= 0:
            raise ValueError("MONGODB_TIMEOUT_MS 必须大于 0")

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
            database_name=os.getenv("MONGODB_DB_NAME", "survey_system"),
            timeout_ms=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
        )
