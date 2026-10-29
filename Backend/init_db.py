"""在大作业1目录运行：python -m Backend.init_db。"""

import sys

from pymongo.database import Database
from pymongo.errors import PyMongoError

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client, get_database
from Backend.mongo_schema import COLLECTION_INDEXES, COLLECTION_SCHEMAS


def initialize_database(db: Database) -> dict[str, list[str]]:
    """创建或更新校验与索引，可重复执行；从不删除集合或文档。

    更新前检查已有数据。若旧数据不符合新结构则停止，交由显式迁移处理，
    不会为了初始化成功而自动改写或清空数据。此流程不是跨集合事务。
    """
    if db.name.lower() in {"admin", "config", "local"}:
        raise ValueError("不能初始化 MongoDB 系统数据库")

    existing = {item["name"]: item for item in db.list_collections()}
    for name, schema in COLLECTION_SCHEMAS.items():
        if name not in existing:
            continue
        if existing[name]["type"] != "collection":
            raise ValueError(f"{name} 不是普通集合，停止初始化")
        invalid = db[name].count_documents({"$nor": [{"$jsonSchema": schema}]}, limit=1)
        if invalid:
            raise ValueError(f"{name} 含有不符合当前结构的数据，请先显式迁移；未删除任何数据")

    result = {}
    for name, schema in COLLECTION_SCHEMAS.items():
        options = {
            "validator": {"$jsonSchema": schema},
            "validationLevel": "strict",
            "validationAction": "error",
        }
        if name in existing:
            db.command({"collMod": name, **options})
        else:
            db.create_collection(name, **options)
        result[name] = db[name].create_indexes(COLLECTION_INDEXES[name])
    return result


def main() -> int:
    try:
        settings = DatabaseSettings.from_env()
        with create_client(settings) as client:
            check_connection(client)
            db = get_database(client, settings)
            result = initialize_database(db)
            print(f"Database ready: {db.name}")
            for name, indexes in result.items():
                print(f"  {name}: strict validator; indexes: {', '.join(indexes)}")
            print("Existing documents were preserved. No sample data was inserted.")
        return 0
    except (ValueError, PyMongoError) as error:
        # 不打印包含认证凭据的连接地址或完整服务器错误。
        code = getattr(error, "code", None)
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Initialization failed: {detail}; code={code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
