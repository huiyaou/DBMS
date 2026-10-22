# 数据库基础层

本模块实现 FastAPI 账号与问卷管理接口、MongoDB 连接和初始化。三个核心集合 users、surveys、responses 之外，新增 sessions 辅助集合保存登录会话哈希及过期时间。核心集合仍有五个业务索引，sessions 另有令牌唯一索引和过期 TTL 索引，各集合还自带 `_id` 唯一索引。

启动完整应用：在大作业目录执行 `python -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000`，打开 `http://127.0.0.1:8000/`。应用启动会初始化数据库，详细功能及操作步骤见项目根目录 `README.md`，接口见 `docs/API说明.md`。

## 运行

先启动 MongoDB，然后在 PowerShell 进入大作业目录：

```powershell
Set-Location 'D:\学校\大三上\DBMS\大作业1'
python -m pip install -r Backend/requirements.txt
python -m Backend.init_db
```

已有 PyMongo 时可以直接执行初始化。运行方式为 `python -m Backend.init_db`，不直接运行 `Backend/init_db.py`。

默认配置为 `mongodb://localhost:27017/` 和 `survey_system`。可选环境变量：

| 变量 | 默认值 |
| --- | --- |
| `MONGODB_URI` | `mongodb://localhost:27017/` |
| `MONGODB_DB_NAME` | `survey_system` |
| `MONGODB_TIMEOUT_MS` | `5000` |

程序直接读取进程环境变量，不会自动加载 `.env` 文件。数据库名限制为字母开头、至多 63 个字母数字下划线或横线，不允许使用系统数据库。

初始化可重复运行，不清空数据、不添加演示账号。已有文档不符合当前 schema 时停止并要求迁移；索引存在冲突或已有重复值时由 MongoDB 拒绝，不会自动删除旧索引或重复文档。初始化不是跨集合事务，如中途失败，已创建的集合或索引会保留，修复原因后可重试。应在启动业务服务前执行，初始化期间不并行写入业务数据。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `config.py` | 配置读取与检查 |
| `database.py` | 连接创建、ping 检查、取得数据库 |
| `mongo_schema.py` | 用户、问卷、提交和会话的 BSON 结构及索引定义 |
| `init_db.py` | 检查已有数据、创建集合或更新 validator、建立索引 |
| `main.py` | 账号、问卷管理、分享预览接口及前端服务 |
| `models.py` | API 请求结构、长度和类型检查 |
| `security.py` | 密码哈希、用户名规范化及 MongoDB 会话认证 |
| `survey_service.py` | 问卷配置与发布校验 |

后续业务代码可以使用：

```python
from Backend.database import check_connection, create_client, get_database

with create_client() as client:
    check_connection(client)
    db = get_database(client)
    user = db.users.find_one({"username_key": "小明"})
```

应用服务应在生命周期内复用 MongoClient，而不是每次请求重新连接。数据库中使用 BSON ObjectId 和 UTC Date；对外 API 再转换为字符串。

## 校验范围

数据库会拒绝缺失必填字段、错误 BSON 类型、未知状态/题型、未知字段、题型不对应的规则结构、重复的多选答案等。草稿可保存空标题、空题目数组和不完整选项，发布完整性留给业务层。

数据库不负责执行问卷。当前业务层已实现账号和问卷管理、配置与发布检查，并在 `answer_service.py` 实现逐题校验、路径重算、匿名策略及幂等提交。禁止多次填写时服务端强制使用 `attempt_key=once`；允许时使用本次 UUID，唯一提交索引提供并发兜底。`statistics_service.py` 实时聚合，记录接口过滤匿名身份；这些约束不是仅依靠前端完成。

答案模块：`answer_routes.py` 提供提交、全卷统计、单题统计和分页填写记录接口。规则由问卷定义解释，服务端拒绝未知题目、重复题目和被跳过题目的残留答案。代码不维护额外累计计数，避免答案与统计副本不一致。

结构当前只接受 `schema_version=1`，将来扩展时需要显式更新校验与旧数据兼容策略，不能任意写入未知结构版本。

## 数据库集成测试

```powershell
python -m unittest discover -s Test -p 'test_*.py' -v
```

测试通过配置的 MongoDB 地址，使用随机命名的 `survey_system_test_<UUID>` 独立数据库，结束时仅删除本次创建的临时库，不写入 `survey_system` 或课程实验集合。不需要安装额外测试框架。MongoDB 无法连接时测试失败，不会将未执行的检查显示为通过。

## 官方参考

- [MongoDB JSON Schema](https://www.mongodb.com/docs/manual/reference/operator/query/jsonschema/)
- [更新集合选项 collMod](https://www.mongodb.com/docs/manual/reference/command/collmod/)
- [PyMongo 索引](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/)
