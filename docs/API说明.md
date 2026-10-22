# 问卷系统 API 说明

服务入口为 `http://127.0.0.1:8000`，API 路径以 `/api` 开头。请求及响应使用 JSON；登录令牌由 HttpOnly Cookie `survey_session` 携带。浏览器前端与后端同源，不需要在浏览器中另存令牌。交互式接口说明位于 `/docs`。

## 接口列表

| 方法与路径 | 请求参数 | 返回内容与权限 |
| --- | --- | --- |
| `GET /api/health` | 无 | 数据库连通时返回 `{"status":"ok"}` |
| `POST /api/auth/register` | `username`、`password` | 201；返回用户公开信息并自动登录 |
| `POST /api/auth/login` | `username`、`password` | 返回用户公开信息，设置登录 Cookie |
| `GET /api/auth/me` | 登录 Cookie | 当前账号的 `id`、`username`、`created_at` |
| `POST /api/auth/logout` | 可选登录 Cookie | 204；删除当前服务器会话并清除 Cookie，可重复调用 |
| `GET /api/surveys` | 可选 `status`、`offset`、`limit` | 当前用户的列表、总数、分页参数和状态计数 |
| `POST /api/surveys` | 问卷内容，可使用空对象保存新草稿 | 201；返回完整管理视图，服务端分配 ID、访问码和初始编辑计数 |
| `GET /api/surveys/{id}` | 问卷 ID | 仅创建者可取得完整管理视图 |
| `PUT /api/surveys/{id}` | 完整问卷内容及 `draft_revision` | 仅创建者可编辑草稿；成功递增编辑计数 |
| `POST /api/surveys/{id}/publish` | `draft_revision` | 仅创建者可发布当前版本的完整草稿 |
| `POST /api/surveys/{id}/close` | 无 | 仅创建者可关闭已发布问卷，重复关闭返回当前结果 |
| `PATCH /api/surveys/{id}/deadline` | `expires_at` | 仅创建者可调整已发布问卷截止时间，null 表示不限 |
| `GET /api/public/surveys/{share_code}` | 登录 Cookie | 实际填写所需内容、has_submitted、can_submit、last_submitted_at；不要求填写者是创建者 |
| `POST /api/public/surveys/{share_code}/responses` | attempt_id、is_anonymous、answers | 校验并保存一次填写；返回记录 ID、时间及 reused |
| `GET /api/surveys/{id}/statistics` | 登录 Cookie | 仅创建者可查看全卷统计及各题摘要 |
| `GET /api/surveys/{id}/statistics/{question_id}` | 可选 offset、limit | 仅创建者可查看单题统计；填空内容可分页读取 |
| `GET /api/surveys/{id}/responses` | 可选 offset、limit | 仅创建者可查看分页填写记录；匿名记录不返回系统身份 |

用户信息及接口响应不包含密码哈希。查询其他用户的管理接口统一返回 404；分享接口仅返回标题、说明、填写设置及题目，不返回创建者 ID 或草稿编辑计数。

## 注册和登录

用户名输入长度为 1～64 字符；去首尾空白并进行 NFKC 规范化，使用 casefold 后的键判断重复。拒绝空白或控制字符用户名。密码长度为 8～128 字符，使用 Argon2 哈希保存。错误用户名或密码统一返回 401。

Cookie 有效期为 12 小时，服务器每次请求检查会话有效期，TTL 索引清理过期记录。浏览器保存随机令牌，MongoDB `sessions` 集合保存 SHA-256 哈希。退出时撤销当前会话；应用重启后，有效会话继续使用。

## 问卷内容

创建和保存使用以下内容字段，嵌套结构见 `MongoDB设计.md`，精确类型也可查看 `/docs`：

```json
{
  "title": "问卷标题",
  "description": "问卷说明",
  "settings": {
    "allow_anonymous": true,
    "allow_multiple_submissions": false,
    "expires_at": null
  },
  "questions": []
}
```

保存已有问卷时额外提供 `draft_revision`；不接受 `owner_id`、`status`、发布时间等服务器字段。题目类型为 `single_choice`、`multiple_choice`、`text`、`number`。题目、选项和规则使用稳定 ID；前端生成 UUID，后端检查格式、重复和引用。

问卷标题最多 200 字符，说明最多 2000 字符，最多 200 题；每题最多 50 个选项和 50 条条件规则。跳转仅判断当前题答案，按照规则顺序匹配，目标为后面的题目、`NEXT` 或 `END`。文本题只有默认跳转。所有数值须有限并位于浏览器可准确表示的范围内。

草稿允许空标题、空题目或尚未填写选项，保存时检查 ID 唯一性、引用、向后跳转和上下界关系。发布时进一步检查标题、至少一题、题目标题、选择题至少两个非空选项、多选数量及整数范围是否可满足、截止时间是否在未来。

截止时间使用带时区的 ISO 8601，例如 `2026-11-01T23:59:00+08:00`，按 UTC 保存；缺少时区返回 422。已到期的已发布问卷可通过更新截止时间重新开放；手动关闭为最终状态。

## 列表与编辑冲突

列表的 `status` 可为 `draft`、`published`、`closed`、`expired`；不传则查询全部。`offset` 默认 0，`limit` 默认 12，最大 100。`total` 是筛选后的数量，`counts` 是当前用户全部问卷的各状态数量。

返回的 `status` 是存储状态；`effective_status` 会将已过截止时间的 published 问卷标记为 expired。

编辑及发布时同时匹配用户、草稿状态与编辑计数，避免旧页面覆盖新修改或发布未经校验的新内容。发生 409 时应重新打开当前问卷，再处理修改。发布后不再允许修改题目和填写策略，仅可调整截止时间或关闭。

## 错误响应

| 状态码 | 含义 |
| --- | --- |
| 401 | 未登录、会话过期、登录凭据错误 |
| 403 | 浏览器跨站写请求被拒绝 |
| 404 | 对象不存在、无管理权限或问卷尚未发布 |
| 409 | 用户名重复、草稿版本冲突或当前状态不允许操作 |
| 410 | 分享问卷已关闭或已截止 |
| 422 | 输入格式不正确或配置不满足要求 |
| 503 | 数据库暂不可用 |

业务错误的 `detail` 通常为中文说明；逐题答案校验错误返回包含 `message`、`question_id` 的对象；输入模型错误为字段错误数组。前端展示适合用户的提示。API 响应不缓存，拒绝不同 Origin 或明确 cross-site 的写请求。

## 答案提交

```json
{
  "attempt_id": "2c0641cc-6dbb-46a5-8a11-856a8bf87881",
  "is_anonymous": true,
  "answers": [
    {"question_id": "q1", "value": "opt_no"},
    {"question_id": "q3", "value": "希望增加自习空间"},
    {"question_id": "q4", "value": 20}
  ]
}
```

`attempt_id` 是一次填写的 UUID，新的一次填写使用新 UUID，网络重试复用原 UUID。后端根据登录会话和问卷设置确定填写者、问卷、提交时间和 `attempt_key`。成功返回 200，包含 `id`、`submitted_at`、`reused`；`reused=true` 表示返回原成功记录。

后端按问卷配置从第一题重算路径，检查路径上的必答和各题约束。被跳过的必答题不要求回答，路径外答案返回 422。可选空白文本/空选择按未答处理，已有回答仍受最短长度或最小选择数约束；数字 0 是有效答案。文本去首尾空白，字数按 Unicode 码点计。多选检查重复项后按选项定义顺序保存。

未发布、关闭或截止的问卷拒绝新提交。已成功请求的相同重试即使在关闭后仍可返回原结果，不会产生新提交。禁止多次填写时使用固定 once 键，允许时使用本次 UUID；并发由唯一索引保证同一键只保存一份。相同键内容不同返回 409，不覆盖旧答案。

未允许匿名却请求匿名返回 422。系统内部保留账号 ID，创建者可见的 records 接口只返回 id、is_anonymous、respondent_name、submitted_at、answers；匿名记录的 respondent_name 为“匿名”，不返回 respondent_id、attempt_key 或用户名。实名记录展示用户名，不返回账号 ID。

## 统计返回及分页

全卷返回 survey_id、title、response_count、participant_count、questions。response_count 为提交份数，participant_count 为按账号去重的人数。每题含 question_id、title、type、answered_count、participant_count、options、average、answers、offset、limit。

单选和多选的 options 按原问卷顺序包含 id、label、count（选择次数）、people_count（不同填写者人数）。未选项补零。单选同时展示次数与人数，多选按次数展示。被跳过或未填的题目不计入 answered_count。

数字 average 为实际数值的平均值，空结果为 null；文本和数字 answers 包含 value、submitted_at。全卷只预览每题前 10 条填空内容；读取全部内容使用单题接口 offset、limit 分页，limit 默认 20、最大 100。填写记录接口同样分页，默认 10、最大 100。数据通过 MongoDB aggregation 直接从成功提交计算，打开或刷新结果页更新，不持久化统计副本。

全卷统计按题依次读取已提交数据，持续有新提交时，各项结果对应各自的查询时刻。打开或刷新结果页重新计算统计。
