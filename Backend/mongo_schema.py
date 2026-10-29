"""MongoDB 文档结构校验及索引定义。

这里只约束数据形状。引用对象、权限、题目 ID 唯一性、发布完整性、
校验上下界、作答路径和问卷截止时间由后续业务层负责。
"""

from copy import deepcopy
from typing import Any

from pymongo import ASCENDING, DESCENDING, IndexModel


Schema = dict[str, Any]
NUMBER: Schema = {"bsonType": ["int", "long", "double"]}
NONNEGATIVE_INTEGER: Schema = {"bsonType": ["int", "long"], "minimum": 0}
IDENTIFIER: Schema = {"bsonType": "string", "minLength": 1}


def object_schema(properties: Schema, required: list[str] | None = None) -> Schema:
    """禁止未声明字段，避免字段拼写错误被静默存入数据库。"""
    schema: Schema = {
        "bsonType": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def condition_schema(operators: list[str], value_schema: Schema) -> Schema:
    return object_schema(
        {
            "operator": {"bsonType": "string", "enum": operators},
            "value": deepcopy(value_schema),
        },
        ["operator", "value"],
    )


def logic_schema(question_type: str) -> Schema:
    if question_type == "single_choice":
        condition = condition_schema(["eq"], IDENTIFIER)
    elif question_type == "multiple_choice":
        condition = condition_schema(
            ["contains_any", "contains_all", "equals_set"],
            {
                "bsonType": "array",
                "items": deepcopy(IDENTIFIER),
                "minItems": 1,
                "uniqueItems": True,
            },
        )
    elif question_type == "number":
        condition = {
            "oneOf": [
                condition_schema(["eq", "gt", "gte", "lt", "lte"], NUMBER),
                condition_schema(
                    ["between"],
                    {
                        "bsonType": "array",
                        "items": deepcopy(NUMBER),
                        "minItems": 2,
                        "maxItems": 2,
                    },
                ),
            ]
        }
    else:
        condition = None

    rule = object_schema(
        {
            "id": deepcopy(IDENTIFIER),
            "condition": condition or {"bsonType": "object"},
            "target": deepcopy(IDENTIFIER),
        },
        ["id", "condition", "target"],
    )
    rules: Schema = {"bsonType": "array", "items": rule}
    if question_type == "text":
        rules["maxItems"] = 0
    return object_schema(
        {"rules": rules, "default_target": deepcopy(IDENTIFIER)},
        ["rules", "default_target"],
    )


def question_schema(question_type: str, validation_fields: Schema) -> Schema:
    properties: Schema = {
        "id": deepcopy(IDENTIFIER),
        "type": {"bsonType": "string", "enum": [question_type]},
        # 草稿允许标题为空或选项未配置完整，发布时由业务层做完整性校验。
        "title": {"bsonType": "string"},
        "required": {"bsonType": "bool"},
        "validation": object_schema(validation_fields),
        "logic": logic_schema(question_type),
    }
    required = list(properties)
    properties["source_question_id"] = {"bsonType": ["string", "null"]}
    properties["source_version_id"] = {"bsonType": ["string", "null"]}
    if question_type in {"single_choice", "multiple_choice"}:
        properties["options"] = {
            "bsonType": "array",
            "items": object_schema(
                {"id": deepcopy(IDENTIFIER), "label": {"bsonType": "string"}},
                ["id", "label"],
            ),
        }
        required.append("options")
    return object_schema(properties, required)


QUESTION_SCHEMA: Schema = {
    "oneOf": [
        question_schema("single_choice", {}),
        question_schema(
            "multiple_choice",
            {
                "min_choices": deepcopy(NONNEGATIVE_INTEGER),
                "max_choices": deepcopy(NONNEGATIVE_INTEGER),
            },
        ),
        question_schema(
            "text",
            {
                "min_length": deepcopy(NONNEGATIVE_INTEGER),
                "max_length": deepcopy(NONNEGATIVE_INTEGER),
            },
        ),
        question_schema(
            "number",
            {
                "min_value": deepcopy(NUMBER),
                "max_value": deepcopy(NUMBER),
                "integer_only": {"bsonType": "bool"},
            },
        ),
    ]
}

BASE_FIELDS: Schema = {
    "_id": {"bsonType": "objectId"},
    # 仅接受当前实现认识的结构版本，升级时显式调整及兼容。
    "schema_version": {"bsonType": ["int", "long"], "enum": [1]},
}


def document_schema(fields: Schema) -> Schema:
    properties = {**deepcopy(BASE_FIELDS), **fields}
    return object_schema(properties, list(properties))


USERS_SCHEMA = document_schema(
    {
        "username": deepcopy(IDENTIFIER),
        "username_key": deepcopy(IDENTIFIER),
        "password_hash": deepcopy(IDENTIFIER),
        "created_at": {"bsonType": "date"},
    }
)

SURVEYS_SCHEMA = document_schema(
    {
        "owner_id": {"bsonType": "objectId"},
        "title": {"bsonType": "string"},
        "description": {"bsonType": "string"},
        "status": {"bsonType": "string", "enum": ["draft", "published", "closed"]},
        "draft_revision": {"bsonType": ["int", "long"], "minimum": 1},
        "share_code": deepcopy(IDENTIFIER),
        "settings": object_schema(
            {
                "allow_anonymous": {"bsonType": "bool"},
                "allow_multiple_submissions": {"bsonType": "bool"},
                "expires_at": {"bsonType": ["date", "null"]},
            },
            ["allow_anonymous", "allow_multiple_submissions", "expires_at"],
        ),
        "questions": {"bsonType": "array", "items": QUESTION_SCHEMA},
        "created_at": {"bsonType": "date"},
        "updated_at": {"bsonType": "date"},
        "published_at": {"bsonType": ["date", "null"]},
        "closed_at": {"bsonType": ["date", "null"]},
    }
)

RESPONSES_SCHEMA = document_schema(
    {
        "survey_id": {"bsonType": "objectId"},
        "respondent_id": {"bsonType": "objectId"},
        "is_anonymous": {"bsonType": "bool"},
        "attempt_key": deepcopy(IDENTIFIER),
        "answers": {
            "bsonType": "array",
            "items": object_schema(
                {
                    "question_id": deepcopy(IDENTIFIER),
                    "value": {
                        "oneOf": [
                            {"bsonType": "string", "minLength": 1},
                            {
                                "bsonType": "array",
                                "items": deepcopy(IDENTIFIER),
                                "minItems": 1,
                                "uniqueItems": True,
                            },
                            deepcopy(NUMBER),
                        ]
                    },
                },
                ["question_id", "value"],
            ),
        },
        "submitted_at": {"bsonType": "date"},
    }
)

# 三个核心业务集合外，增加登录会话集合；只保存随机令牌的哈希。
SESSIONS_SCHEMA = document_schema(
    {
        "token_hash": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
        "user_id": {"bsonType": "objectId"},
        "created_at": {"bsonType": "date"},
        "expires_at": {"bsonType": "date"},
    }
)

COLLECTION_SCHEMAS = {
    "users": USERS_SCHEMA,
    "surveys": SURVEYS_SCHEMA,
    "responses": RESPONSES_SCHEMA,
    "sessions": SESSIONS_SCHEMA,
    "questions": document_schema({"owner_id": {"bsonType": "objectId"}, "shared_with": {"bsonType": "array", "items": {"bsonType": "objectId"}}, "created_at": {"bsonType": "date"}}),
    "question_versions": document_schema({"question_id": {"bsonType": "objectId"}, "parent_id": {"bsonType": ["objectId", "null"]}, "created_by": {"bsonType": "objectId"}, "created_at": {"bsonType": "date"}, "content": QUESTION_SCHEMA}),
    "question_banks": document_schema({"owner_id": {"bsonType": "objectId"}, "name": {"bsonType": "string", "minLength": 1}, "items": {"bsonType": "array", "items": object_schema({"question_id": {"bsonType": "objectId"}, "version_id": {"bsonType": "objectId"}}, ["question_id", "version_id"])}, "created_at": {"bsonType": "date"}}),
}

# 删除只从题库隐藏；发布快照、来源关系和统计仍需要历史文档。
for _name in ("questions", "question_versions"):
    COLLECTION_SCHEMAS[_name]["properties"]["archived"] = {"bsonType": "bool"}

COLLECTION_INDEXES = {
    "questions": [IndexModel([("owner_id", ASCENDING)], name="ix_question_owner"), IndexModel([("shared_with", ASCENDING)], name="ix_question_shared")],
    "question_versions": [IndexModel([("question_id", ASCENDING), ("created_at", ASCENDING)], name="ix_question_versions")],
    "question_banks": [IndexModel([("owner_id", ASCENDING)], name="ix_bank_owner")],
    "sessions": [
        IndexModel([("token_hash", ASCENDING)], name="uq_session_token", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="ttl_session_expiry", expireAfterSeconds=0),
    ],
    "users": [
        IndexModel([("username_key", ASCENDING)], name="uq_username_key", unique=True),
    ],
    "surveys": [
        IndexModel([("share_code", ASCENDING)], name="uq_share_code", unique=True),
        IndexModel(
            [("owner_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_owner_created",
        ),
    ],
    "responses": [
        IndexModel(
            [("survey_id", ASCENDING), ("submitted_at", DESCENDING)],
            name="ix_survey_submitted",
        ),
        IndexModel(
            [
                ("survey_id", ASCENDING),
                ("respondent_id", ASCENDING),
                ("attempt_key", ASCENDING),
            ],
            name="uq_response_attempt",
            unique=True,
        ),
    ],
}
