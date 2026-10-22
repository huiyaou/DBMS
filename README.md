# 问卷工坊
## 启动与环境依赖

先**保持 MongoDB 运行**，然后在新的 PowerShell 窗口执行：

```powershell
python -m pip install -r Backend/requirements.txt
python -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/`，先注册自己的账号即可使用。停止服务时在该窗口按 Ctrl+C；MongoDB 的独立窗口继续保留。

服务启动时会检查 MongoDB 并初始化集合及索引，不清空已有数据、不创建默认账号。也可以单独执行 `python -m Backend.init_db`。注册后自动登录，关闭和重新打开网页仍可使用有效会话。

默认连接 `mongodb://localhost:27017/`，数据库 `survey_system`。可通过 `MONGODB_URI`、`MONGODB_DB_NAME`、`MONGODB_TIMEOUT_MS` 环境变量调整。不自动读取 `.env`。默认适用于本机 HTTP；通过 HTTPS 使用时设置 `SURVEY_COOKIE_SECURE=1`。

## 目录

| 位置 | 用途 |
| --- | --- |
| `Backend/main.py` | 应用入口及 API 路由 |
| `Backend/models.py` | API 输入模型 |
| `Backend/security.py` | 用户名规范化、密码哈希、Cookie 会话认证 |
| `Backend/survey_service.py` | 问卷配置校验及序列化 |
| `Backend/answer_service.py` | 答题校验、规则跳转、路径重算与幂等提交 |
| `Backend/answer_routes.py` / `statistics_service.py` | 答案收集、填写记录与统计接口 |
| `Backend/config.py` / `database.py` | MongoDB 配置与连接 |
| `Backend/mongo_schema.py` / `init_db.py` | 集合校验与索引初始化 |
| `Frontend/` | 页面、样式和交互 |
| `Test/` | 数据库、API 测试及临时浏览器验收服务 |
| [docs/MongoDB设计.md](docs/MongoDB设计.md) | 数据结构及业务约定 |
| [docs/API说明.md](docs/API说明.md) | 接口、参数、状态码与权限规则 |
| [docs/项目完成报告.md](docs/项目完成报告.md) | 项目目标、系统设计、关键逻辑、AI 使用、测试与问题解决 |

## 测试

在项目目录执行：

```powershell
python -m unittest discover -s Test -p 'test_*.py' -v
```

本轮 60 项测试通过，其中 22 项新增测试覆盖实际答题、匿名与重复填写、并发、统计与分页。测试使用随机临时库，结束时仅清理本次创建的测试库。浏览器还验证了返回改选后跳过已答题、数值错误提示、匿名和实名两次提交、数字平均值与匿名明细，以及 390 像素宽度布局。

需要手动试用、又不想将演示数据放入正式库时，可运行：

```powershell
python -m Test.preview_server
```

访问 `http://127.0.0.1:8001/`。这是独立临时环境；正常按 Ctrl+C 停止后会清理本次测试库。强制结束进程可能使清理未执行，此时应根据该进程输出的精确数据库名确认后再处理，不要批量删除测试名前缀相同的数据库。
