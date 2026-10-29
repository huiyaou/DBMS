"""临时前端验收环境：Ctrl+C 停止后仅清理本次随机测试数据库。"""

from dataclasses import replace
from uuid import uuid4

import uvicorn

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client
from Backend.main import create_app


def main():
    settings = replace(DatabaseSettings.from_env(), database_name=f"survey_system_ui_test_{uuid4().hex}")
    with create_client(settings) as client:
        check_connection(client)
        if settings.database_name in client.list_database_names():
            raise RuntimeError("临时库已存在，停止预览")
        print(f"Temporary UI database: {settings.database_name}", flush=True)
        try:
            uvicorn.run(create_app(settings), host="127.0.0.1", port=8001)
        finally:
            client.drop_database(settings.database_name)
            print("Temporary UI database removed.", flush=True)


if __name__ == "__main__":
    main()
