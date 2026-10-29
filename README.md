# 问卷工坊
master分支下为修改完用户需求后的系统，第一次作业的内容见Homework01分支，该master分支内容与Homework02分支下的内容一致。

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

上一轮全量 65 项自动测试通过。本轮针对版本管理调整运行题目模块 6 项测试，全部通过，覆盖固定标题、修改题型选项、版本删除及发布快照保护；本轮未重复运行全量测试。测试使用随机临时库，结束时仅清理本次创建的测试库。本阶段浏览器流程尚待验收。

需要手动试用，又不想将演示数据放入正式库时，可运行：

```powershell
python -m Test.preview_server
```

访问 `http://127.0.0.1:8001/`。这是独立临时环境；正常按 Ctrl+C 停止后会清理本次测试库。强制结束进程可能使清理未执行，此时应根据该进程输出的精确数据库名确认后再处理，不要批量删除测试名前缀相同的数据库。

版本管理采用左侧版本列表与右侧详情。编号从 V0 开始，后续为 V1、V2……；删除后从页面列表消失，其他版本保留原编号和来源关系。有删除权限的可用版本旁显示删除入口。

删除常用题目会移除常用题目列表及所有题库中的对应条目；删除某版本只移除该版本及题库中引用它的条目。草稿和已发布问卷中的已复用题目及已有答卷均保留。版本详情区与版本列表均提供删除入口（按权限显示）。本轮题目模块 7 项测试通过。

版本删除后直接从左侧列表和右侧详情消失，自动选中剩余可用版本；后台版本文档、其他版本的来源引用和原编号保持不变。全部版本删除后显示“暂无可用版本”。
