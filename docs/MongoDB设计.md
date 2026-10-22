# 问卷系统 MongoDB 数据库设计

本系统使用 Python + FastAPI 和 MongoDB，数据库名为 `survey_system`。`users`、`surveys`、`responses` 分别保存账号、问卷和填写记录，`sessions` 保存登录会话。系统支持问卷管理、逐题填写、条件跳转、匿名与重复填写控制，以及全卷和单题统计。

## 1 设计结论

| 集合 | 一条文档代表什么 | 主要内容 |
| --- | --- | --- |
| `users` | 一个账号 | 用户名、密码哈希、注册时间 |
| `surveys` | 一份问卷 | 创建者、发布状态、填写设置，以及嵌入的题目、选项、校验规则、跳转规则 |
| `responses` | 一次成功提交 | 所属问卷、填写者、匿名标记、各题答案、提交时间 |
| `sessions`（辅助） | 一次有效登录会话 | 令牌哈希、用户 ID、创建与过期时间 |

关系如下：

```text
users._id ← surveys.owner_id       一个用户可以创建多份问卷
surveys._id ← responses.survey_id  一份问卷可以收到多次提交
users._id ← responses.respondent_id 一个用户可以填写多份问卷

surveys.questions[]              题目嵌入问卷
responses.answers[]              一次提交的答案嵌入提交记录
users._id ← sessions.user_id     登录会话引用用户
```

后端根据引用 ID 检查对象是否存在，并验证当前用户的访问权限。

### 为什么这样划分

- 打开问卷时通常要一起读取题目、选项和规则，因此将它们嵌入一份问卷。
- 填写记录会随着提交持续增长，因此单独保存，避免一个问卷文档中的答案数组不断增大。
- 用户有独立的登录和权限需求，单独保存，通过 ID 引用。
- 同一份提交的所有答案一起保存，避免只写入一半答案。
- 第一阶段直接根据填写记录计算统计，不另外维护统计集合或累计计数，减少数据不一致。

### 为什么采用文档结构

关系模型通常将问卷、题目、选项、规则和答案拆成多张表，再通过外键和连接还原问卷。本项目主要围绕整份问卷读取配置、围绕一次提交保存答案，因此将共同访问的数据组成文档。

不同题型使用不同的校验字段，MongoDB 子文档可以按题型保存对应配置。新增题型时可扩展题目结构；已有填写记录继续引用原问卷。统计使用 MongoDB 聚合管道完成。这种设计符合本项目使用 MongoDB 的要求，也与问卷的嵌套结构和访问方式一致。

### 业务规则

1. 填写者先登录。匿名提交对问卷创建者隐藏账号身份，系统内部保留账号 ID，用于控制重复填写。
2. 设置 `allow_anonymous=true` 表示填写者可以选择匿名；否则只能实名提交。每条提交保存当次的 `is_anonymous`。
3. 跳转只允许指向后面的题目或结束，防止出现循环；多个规则同时满足时使用配置顺序中的第一条。
4. 必答与题型约束只对实际作答路径上的题目生效。被跳过的必答题不要求填写。
5. 发布后固定题目、选项、校验、跳转，以及匿名和重复填写策略，使已收集答案保持统一含义。截止时间可调整；手动关闭为最终状态。
6. 每次成功提交保存一条完整记录，填写页面在提交前提供答案检查。

## 2 通用字段和类型

| 字段或约定 | 类型及含义 |
| --- | --- |
| 集合文档 `_id` | BSON `ObjectId` |
| `owner_id`、`survey_id`、`respondent_id` | BSON `ObjectId` |
| 时间 | BSON `Date`，统一按 UTC 保存；网页展示时转换时区 |
| `schema_version` | 整数，初始为 `1`，表示文档结构的版本，用于以后兼容或迁移 |
| 题目、选项和规则 ID | 前端生成的稳定字符串，通常为 UUID，后端检查格式、唯一性和引用；示例中的 `q1`、`opt_yes` 是可读缩写 |

题目和选项使用稳定 ID 关联，调整草稿顺序或显示文字时保留 ID。API 将 ObjectId 和时间序列化为字符串，入库前转换为对应 BSON 类型。

`schema_version` 用于文档结构迁移；发布后的固定题目定义用于解释已提交答案。

## 3 users 用户集合

```javascript
{
  _id: ObjectId("000000000000000000000001"),
  schema_version: 1,
  username: "小明",
  username_key: "小明",
  password_hash: "<Argon2密码哈希>",
  created_at: ISODate("2026-10-20T07:00:00Z")
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `_id` | 是 | 用户 ID |
| `schema_version` | 是 | 文档结构版本 |
| `username` | 是 | 显示用用户名 |
| `username_key` | 是 | 去除首尾空白并进行统一规范化后的用户名，用于登录及唯一性检查 |
| `password_hash` | 是 | 专用密码哈希库生成的结果，包含其所需参数；不保存明文密码 |
| `created_at` | 是 | 注册时间 |

注册和登录统一使用 `unicodedata.normalize("NFKC", username.strip()).casefold()` 生成查询键。保留 `username` 展示原用户名，使用 `username_key` 实现大小写等价查询及唯一索引。

`password_hash` 不返回给前端。问卷和填写记录中不复制用户名，以免用户信息修改后出现多个副本不一致。

### 登录会话辅助集合

登录会话存入 MongoDB，支持应用重启后保持登录，以及退出时立即撤销当前会话。

```javascript
{
  _id: ObjectId("000000000000000000000200"),
  schema_version: 1,
  token_hash: "<随机会话令牌的64位十六进制SHA-256哈希>",
  user_id: ObjectId("000000000000000000000001"),
  created_at: ISODate("2026-10-20T07:00:00Z"),
  expires_at: ISODate("2026-10-20T19:00:00Z")
}
```

`token_hash` 为随机令牌的 64 位十六进制 SHA-256 哈希。浏览器通过 HttpOnly Cookie 保存原始令牌，数据库保存其哈希。会话有效期为 12 小时；后端每次访问检查 `expires_at`，TTL 索引负责清理过期会话。退出时删除当前会话。

## 4 surveys 问卷集合

### 4.1 问卷主体示例

以下是包含四种内部题型的完整结构示例。作业的填空题在内部细分为 `text` 和 `number`。

```javascript
{
  _id: ObjectId("000000000000000000000010"),
  schema_version: 1,
  owner_id: ObjectId("000000000000000000000001"),
  title: "校园生活调查",
  description: "了解大家的校园生活情况",
  status: "published",
  draft_revision: 3,
  share_code: "a7Kp9r2X",
  settings: {
    allow_anonymous: true,
    allow_multiple_submissions: false,
    expires_at: ISODate("2026-11-01T15:59:59Z")
  },
  questions: [
    {
      id: "q1",
      type: "single_choice",
      title: "你是否在校住宿？",
      required: true,
      options: [
        { id: "opt_yes", label: "是" },
        { id: "opt_no", label: "否" }
      ],
      validation: {},
      logic: {
        rules: [
          {
            id: "r1",
            condition: { operator: "eq", value: "opt_no" },
            target: "q3"
          }
        ],
        default_target: "NEXT"
      }
    },
    {
      id: "q2",
      type: "multiple_choice",
      title: "你使用哪些宿舍设施？",
      required: true,
      options: [
        { id: "opt_laundry", label: "洗衣房" },
        { id: "opt_study", label: "自习室" },
        { id: "opt_gym", label: "健身区" }
      ],
      validation: { min_choices: 1, max_choices: 2 },
      logic: { rules: [], default_target: "NEXT" }
    },
    {
      id: "q3",
      type: "text",
      title: "你对校园生活有什么建议？",
      required: false,
      validation: { min_length: 2, max_length: 200 },
      logic: { rules: [], default_target: "NEXT" }
    },
    {
      id: "q4",
      type: "number",
      title: "你的年龄？",
      required: true,
      validation: { min_value: 0, max_value: 120, integer_only: true },
      logic: { rules: [], default_target: "END" }
    }
  ],
  created_at: ISODate("2026-10-20T07:10:00Z"),
  updated_at: ISODate("2026-10-20T07:20:00Z"),
  published_at: ISODate("2026-10-20T07:20:00Z"),
  closed_at: null
}
```

### 4.2 主体字段说明

| 字段 | 含义 |
| --- | --- |
| `owner_id` | 创建者 ID，用于查询自己的问卷和校验管理权限 |
| `title` / `description` | 问卷标题和说明 |
| `status` | `draft` 草稿、`published` 已发布、`closed` 已关闭 |
| `draft_revision` | 草稿编辑计数，初始为 1；保存和发布时匹配该值，处理多个页面的编辑冲突 |
| `share_code` | 随机且唯一的访问码，对应 `/survey/{share_code}`；访问后进行登录和状态检查 |
| `settings.allow_anonymous` | 是否允许选择匿名提交 |
| `settings.allow_multiple_submissions` | 是否允许同一账号多次提交 |
| `settings.expires_at` | 截止时间；`null` 表示不设置截止时间 |
| `questions` | 有序题目数组；数组顺序就是默认作答顺序，不另存冗余题号 |
| `created_at` / `updated_at` | 创建和最后修改时间 |
| `published_at` / `closed_at` | 未发生时为 `null` |

状态转换为 `draft → published → closed`。后端结合 `status` 和截止时间计算有效状态：已发布问卷到期后显示为 `expired`，停止受理新提交，问卷和填写记录继续保留。调整截止时间可以重新开放到期问卷。

草稿保存允许题目配置尚未填完，保存时检查字段类型、ID 和引用；发布时检查完整配置。草稿修改以 `owner_id`、`status: "draft"` 和预期 `draft_revision` 为条件，成功时原子递增编辑计数。发布先读取并校验草稿，再按相同条件及读取到的编辑计数更新状态。计数或状态变化时返回 409，由用户重新读取当前问卷后处理修改。

### 4.3 题型和校验规则

| `type` | 答案类型 | 规则字段 |
| --- | --- | --- |
| `single_choice` | 一个选项 ID 字符串 | `required`；选项必须存在 |
| `multiple_choice` | 选项 ID 数组 | `min_choices`、`max_choices`；选项必须存在且不可重复 |
| `text` | 字符串 | `min_length`、`max_length` |
| `number` | BSON 数值，使用 int、long 或 double | `min_value`、`max_value`、`integer_only` |

规则值的约定：

- 未设置的上界或下界字段省略；`0` 按具体数值约束处理。
- “必须选 2 个”表示 `min_choices=2` 且 `max_choices=2`。
- 非必答题可以不填；一旦填写，仍要满足最短长度、最小选择数等规则。
- 必答多选题至少选择一项；配置中的最少选择数若更大则采用更大值。
- 文本统一去除首尾空白，结果为空时作为未回答。前后端统一按 Unicode 码点计数，后端使用 Python 字符串 `len()`。
- 数字 `0` 是有效答案。数值检查包括类型、有限性、范围和整数限制，布尔值、NaN 和无穷大返回校验错误。
- 数值绝对值最大为 `9_007_199_254_740_991`，与浏览器可准确表示的整数范围保持一致；手机号示例可使用整数限制。数字题统一提供平均值统计。

发布前检查题目 ID 和选项 ID 不重复、选项至少两个、题目标题非空、各下界不大于上界，以及多选数量不超过选项数。选择题配置 `options`；文本和数字题使用各自的校验字段。

### 4.4 跳转规则结构

规则保存在所属题目的 `logic.rules` 中，条件判断当前题目的答案。后端通过通用操作符解释器读取规则，创建者在问卷中配置条件和目标。

| 题型 | 操作符 | `value` 示例 | 含义 |
| --- | --- | --- | --- |
| 单选 | `eq` | `"opt_no"` | 选中某个选项 |
| 多选 | `contains_any` | `["opt_a", "opt_b"]` | 至少选中其中一项 |
| 多选 | `contains_all` | `["opt_a", "opt_b"]` | 两项都选中，可以同时选其他项 |
| 多选 | `equals_set` | `["opt_a", "opt_b"]` | 恰好选中这两项，忽略顺序 |
| 数字 | `eq` / `gt` / `gte` / `lt` / `lte` | `18` | 相等、大于、大于等于、小于、小于等于 |
| 数字 | `between` | `[18, 60]` | 在闭区间 18 到 60 内 |

目标可以是题目 ID、`NEXT` 或 `END`。`NEXT` 表示数组中下一题，最后一题的 `NEXT` 等同于结束；`END` 表示到达可提交状态，仍需显式提交。

例如，数字题可配置：

```javascript
{
  rules: [
    {
      id: "r_age",
      condition: { operator: "lt", value: 18 },
      target: "END"
    }
  ],
  default_target: "NEXT"
}
```

执行顺序：校验当前答案 → 从前往后查找第一个满足条件的规则 → 使用它的目标；没有满足条件的规则时使用 `default_target`。非必答题未填写时，不匹配条件规则，直接使用默认目标。

发布时检查操作符与题型匹配、选项引用存在、数值区间合法、目标题目存在，且所有显式题目目标都在当前题目之后。题目位置沿路径递增，保证填写过程最终到达结束。

## 5 responses 填写记录集合

```javascript
{
  _id: ObjectId("000000000000000000000100"),
  schema_version: 1,
  survey_id: ObjectId("000000000000000000000010"),
  respondent_id: ObjectId("000000000000000000000002"),
  is_anonymous: true,
  attempt_key: "once",
  answers: [
    { question_id: "q1", value: "opt_no" },
    { question_id: "q3", value: "希望增加自习空间" },
    { question_id: "q4", value: 20 }
  ],
  submitted_at: ISODate("2026-10-20T08:00:00Z")
}
```

上例中，`q1` 选择“不住宿”后跳过 `q2`，所以没有 `q2` 的答案。这种缺失是合法的，即使 `q2.required=true`。

| 字段 | 说明 |
| --- | --- |
| `survey_id` | 对应哪份问卷 |
| `respondent_id` | 后端从当前登录会话取得的填写者账号 |
| `is_anonymous` | 当次是否选择匿名，由后端校验问卷是否允许 |
| `attempt_key` | 控制只填一次以及重复请求，具体规则见下文 |
| `answers` | 本次实际填写的答案，一个题目最多一条；可选未填题和被跳过题不保存答案 |
| `submitted_at` | 后端接受本次提交的时间 |

多选答案示例为 `{ question_id: "q2", value: ["opt_laundry", "opt_study"] }`。答案不再重复保存题目标题、题型和选项文字，读取时根据 `survey_id` 找到发布后固定的问卷定义。

### 5.1 防止多次填写和重复请求

- 禁止重复填写时，后端强制令 `attempt_key="once"`。
- 允许重复填写时，每次新的填写使用一个新的 UUID 作为 `attempt_key`；同一次提交重试必须复用原 UUID。
- 为 `(survey_id, respondent_id, attempt_key)` 建立唯一索引。
- 因此不允许多次填写时，同一用户的两次并发提交只能成功插入一次；允许多次填写时，不同 UUID 可以保存为多条记录，同一个 UUID 的网络重试不会重复插入。
- 后端读取问卷设置，确定最终的 `attempt_key`。
- 遇到唯一键冲突时，读取原提交；内容和匿名选择相同则返回原结果，内容不同则返回 409。比较多选答案时先检查重复项并统一顺序。

唯一索引从数据库层约束并发写入，比“先查有没有填写过，再直接插入”可靠。参见 [MongoDB 唯一索引](https://www.mongodb.com/docs/manual/core/index-unique/)。

### 5.2 匿名记录的展示

匿名提交内部保存 `respondent_id`，用于登录关联和重复填写控制。填写页面说明匿名含义；创建者的记录接口将填写者显示为“匿名”，并过滤 `respondent_id`、用户名和 `attempt_key`。

实名记录也只能由有权查看该问卷的创建者访问。数据库操作只由后端执行，前端不直接连接 MongoDB。

## 6 提交校验与并发处理

后端收到提交时依次完成：

1. 从认证信息得到当前账号，读取问卷，检查它为 `published`，且检查时刻早于截止时间。
2. 校验匿名选择和重复填写策略。
3. 检查答案数组中是否有重复题目、未知题目、未知选项和错误类型。
4. 从第一题开始，根据提交答案重新执行校验和跳转，计算实际作答路径。
5. 对路径上必答题检查缺失；对已填题检查规则。缺失的可选题走默认目标。
6. 拒绝路径外的残留答案，防止更改前面的答案后，把已被跳过题目的旧答案也提交统计。
7. 生成可信字段，将整次提交作为一个文档插入 `responses`；校验失败不写入正式记录。

新提交以读取问卷时的状态和受理时间判断资格：问卷开放且未到截止时间时受理，已受理请求继续完成写入。关闭后受理的新请求返回 410。已成功请求的相同重试可返回原记录。

一次提交的全部答案写入同一个文档，利用单文档原子性完整保存。不同填写者分别写入独立文档；同一填写尝试通过唯一索引去重。统计在查询时聚合，提交过程只需插入填写记录。参见 [MongoDB 原子性与事务](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/)。

## 7 索引设计

| 集合 | 索引 | 类型 | 用途 |
| --- | --- | --- | --- |
| `users` | `{ username_key: 1 }` | 唯一 | 防止等价用户名重复注册，加速登录查询 |
| `surveys` | `{ share_code: 1 }` | 唯一 | 根据访问链接找问卷，防止访问码重复 |
| `surveys` | `{ owner_id: 1, created_at: -1 }` | 普通 | 按创建时间展示自己的问卷 |
| `responses` | `{ survey_id: 1, submitted_at: -1 }` | 普通 | 问卷填写记录列表及按问卷筛选统计 |
| `responses` | `{ survey_id: 1, respondent_id: 1, attempt_key: 1 }` | 唯一 | 重复填写限制和提交重试去重 |
| `sessions` | `{ token_hash: 1 }` | 唯一 | 查找登录会话，避免令牌哈希重复 |
| `sessions` | `{ expires_at: 1 }` | TTL，expireAfterSeconds=0 | 清理过期会话，不删除用户和问卷 |

各集合还自带 `_id` 唯一索引。`share_code` 在创建草稿时即生成并必填，随机碰撞时重新生成；避免唯一索引下多条草稿都缺失或为 `null`。

题目 ID 在同一问卷内唯一，选项 ID 在所属题目内唯一，由后端检查数组中的重复值。`responses` 中的同一题目 ID 随不同填写记录重复出现。

## 8 数据库校验与后端校验的分工

四个集合的 MongoDB `$jsonSchema` validator 在 `Backend/mongo_schema.py` 定义，通过 `Backend/init_db.py` 创建或更新，采用 `validationLevel=strict` 和 `validationAction=error` 拒绝非法结构写入。各层检查内容如下。

| 位置 | 应负责的检查 |
| --- | --- |
| MongoDB validator | 顶层必填字段、ObjectId/Date/bool/数组等类型、`schema_version`、状态和题型枚举、题目和答案子文档基本结构、题型对应的规则字段形状 |
| MongoDB 唯一索引 | 用户名唯一、访问码唯一、并发提交去重 |
| FastAPI 业务校验 | 引用对象存在、owner 权限、发布配置完整、ID 在数组中不重复、约束上下界关系、跳转目标合法、答案匹配对应题型、路径上的必答、是否到期、匿名权限 |

MongoDB 负责文档结构，后端结合问卷定义执行引用检查、作答校验和跳转。参见 [MongoDB Schema Validation](https://www.mongodb.com/docs/manual/core/schema-validation/)。

答案 `value` 在数据库中可为字符串、字符串数组或数值，后端根据对应题目检查具体类型。草稿和发布采用不同的完整性要求，各阶段均执行 BSON 类型校验。

## 9 查询和统计口径

### 9.1 常用查询

| 操作 | 查询条件或过程 |
| --- | --- |
| 登录 | 根据 `username_key` 查用户，后端验证密码哈希 |
| 查看我的问卷 | `surveys.find({ owner_id: 当前用户ID })`，按 `created_at` 倒序 |
| 管理问卷 | 使用 `_id` 和 `owner_id` 同时筛选 |
| 打开问卷 | 根据 `share_code` 查找，再检查登录、发布状态和截止时间 |
| 查看填写结果 | 先确认问卷属于当前用户，再按 `survey_id` 查询 `responses` |
| 查看单题统计 | 先校验权限和题目 ID，再筛选该问卷、该题的答案 |

列表和明细需要分页；第一阶段可使用 `limit/skip`。统计读取已成功插入的正式提交，不将未提交草稿或被跳过题目当成回答。

### 9.2 统计定义

- 整份问卷：提交总次数，以及不同 `respondent_id` 的参与账号数。
- 单选题：展示各选项的选择次数和不同填写者人数，以及该题的回答次数和不同回答者人数。
- 多选题：展开数组后统计各选项被选择的次数；一个提交内不允许重复选项。次数之和可能大于该题回答次数。
- 文本题：分页展示实际填写内容，不把未答或被跳过的题目补成空字符串。
- 数字题：统计实际数值答案的平均值和回答次数，没有答案时平均值返回 `null`。
- 单题回答次数的分母只包含真正回答该题的提交；跳过和可选未填不计入。
- 选项按问卷定义的顺序完整展示，未被选择的选项计数为 `0`。

实现上使用 aggregation：先 `$match` 筛选问卷，再 `$unwind` 展开 `answers`；单题再筛选 `question_id`，单选用 `$group`，多选额外展开 `value`，数字用 `$avg`。需要不同填写者人数时，对相应组内的 `respondent_id` 去重后计数，仅返回聚合数量，不泄露匿名账号。



| 场景 | 预期结果 |
| --- | --- |
| 两次注册规范化后相同的用户名 | 第二次被拒绝 |
| 用户 B 修改用户 A 的问卷 | 被拒绝，原问卷不变 |
| 发布跳转到不存在题目的问卷 | 发布被拒绝 |
| 发布跳转到前面题目的问卷 | 发布被拒绝 |
| 多选必须选 2 个，实际只选 1 个 | 提交被拒绝 |
| 数字要求 0～120 整数，输入 150 或 20.5 | 提交被拒绝 |
| 合法填写数字 0 | 保存成功，参与统计 |
| 跳过某道必答题 | 路径有效时允许提交 |
| 提交包含已被跳过题目的残留答案 | 被拒绝，前端清理后重新提交 |
| 未开放匿名却设置匿名标记 | 被拒绝 |
| 匿名且禁止多次填写，同一用户再次提交 | 被拒绝或对相同请求返回原结果 |
| 禁止多次填写时，同一用户同时提交两份不同答案 | 只保存一条，另一条报冲突 |
| 允许多次填写，使用不同 attempt_key | 分别保存两条 |
| 允许多次填写，同一次请求重试复用 attempt_key | 不重复保存 |
| 问卷已关闭或检查时已过期 | 不受理新提交 |
| 发布后尝试修改题目或重复填写策略 | 被拒绝 |
| 某题没有回答 | 数字平均值为 null，选项计数为 0 |
| 创建者查看匿名提交详情 | 接口不返回可关联的填写者身份字段 |


