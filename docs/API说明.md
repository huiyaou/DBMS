# API 说明

## 第一阶段概况

原有账号、问卷、发布、答题、问卷统计和记录接口保留，登录依赖 Cookie，会话和写请求保持原有检查。浏览器可查看 /docs 中的完整接口参数。

## 题目及版本

| 方法和路径 | 作用 |
| --- | --- |
| POST /api/questions | 创建题目和首个版本，body 包含 content |
| GET /api/questions | 查询自己创建或获共享的题目和版本 |
| POST /api/questions/{question_id}/versions | 基于 parent_id 和 content 创建版本，也可用旧内容恢复 |
| POST /api/questions/{question_id}/share | 所有者按 username 共享给用户 |
| GET /api/questions/{question_id}/usage | 查看当前用户拥有且使用该题的问卷 |
| GET /api/questions/{question_id}/versions/{version_id}/statistics | 查看当前用户拥有的问卷中该版本的统计 |

题目 content 使用已有题型结构；保存版本时重置问卷内题目 ID、必答和跳转设置。问卷草稿可携带 source_question_id 与 source_version_id，后端核对来源权限及题目内容一致性。

## 题库

| 方法和路径 | 作用 |
| --- | --- |
| POST /api/banks | 以 name 创建题库 |
| GET /api/banks | 列出自己的题库及所选版本 |
| PATCH /api/banks/{bank_id} | 修改题库名称 |
| DELETE /api/banks/{bank_id} | 删除题库，保留题目和问卷 |
| PUT /api/banks/{bank_id}/items | 指定 question_id、version_id，加入题目或切换版本 |
| DELETE /api/banks/{bank_id}/items/{question_id} | 从题库移除题目 |

题库每道题保留一个选定版本。无权访问的题目和题库返回 404，输入不合规则返回 422。查看使用情况和统计不会泄露其他用户的问卷。

## 版本编辑删除与问卷追加

| 方法和路径 | 作用 |
| --- | --- |
| DELETE /api/questions/{question_id}/versions/{version_id} | 归档版本，保留历史引用，移除对应题库条目 |
| DELETE /api/questions/{question_id} | 所有者归档整题，保留发布快照 |
| POST /api/surveys/{survey_id}/questions | 向草稿或已发布问卷末尾追加题目 |

追加请求包含 question_id、version_id、draft_revision。已关闭问卷、同题不同版本重复加入或修订号过期返回 409；无权管理问卷返回 404。此接口不接受旧题内容修改，普通 PUT 保存接口仍限草稿。新增题默认非必答并使用 NEXT 跳转；原有规则不变。

编辑任意版本继续使用 POST /questions/{question_id}/versions 并指定该版本 parent_id；不会覆盖来源版本。GET /questions 返回稳定的版本 number、archived 和 can_delete，前端使用这些字段呈现版本历史和权限。删除版本不改变历史编号。版本所有者或题目所有者可删除版本，只有题目所有者可删除整题。

创建新版本时 content.title 必须与 parent_id 指定版本的标题完全一致，否则返回 422 且不创建版本；题型、选项和校验仍可修改。GET /questions 的版本 number 从 0 开始，已删除历史仍占原编号，界面显示 V0、V1、V2 等。

题目与版本删除支持重复请求：同一有权访问的对象已归档时仍返回 204，继续清理题库条目。整题删除不写入 surveys 或 responses；单版本删除仅移除 question_banks.items 中该 version_id 对应条目。不存在或无权限对象仍返回业务 404。
