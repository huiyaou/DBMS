"""复用数据库连接入口，导入本模块不会访问网络或修改数据库。"""

from typing import Any

from pymongo import MongoClient
from pymongo.database import Database

from Backend.config import DatabaseSettings


def create_client(settings: DatabaseSettings | None = None) -> MongoClient:
    settings = settings or DatabaseSettings.from_env()
    return MongoClient(
        settings.uri,
        serverSelectionTimeoutMS=settings.timeout_ms,
        connectTimeoutMS=settings.timeout_ms,
        socketTimeoutMS=settings.timeout_ms,
        tz_aware=True,
        appname="survey-system",
    )


def check_connection(client: MongoClient) -> None:
    """主动检查连接；创建 MongoClient 本身不代表已连通。"""
    client.admin.command("ping")


def get_database(
    client: MongoClient, settings: DatabaseSettings | None = None
) -> Database[dict[str, Any]]:
    settings = settings or DatabaseSettings.from_env()
    return client[settings.database_name]
