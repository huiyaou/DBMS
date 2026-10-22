"""问卷发布配置检查与对外序列化。"""

from math import isfinite

from bson import BSON, ObjectId
from fastapi import HTTPException

from Backend.security import utcnow


def parse_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(404, "问卷不存在")
    return ObjectId(value)


def owned_survey(db, survey_id: str, user_id) -> dict:
    survey = db.surveys.find_one({"_id": parse_id(survey_id), "owner_id": user_id})
    if not survey:
        raise HTTPException(404, "问卷不存在")
    return survey


def effective_status(survey: dict) -> str:
    if survey["status"] == "published" and survey["settings"]["expires_at"] is not None:
        if survey["settings"]["expires_at"] <= utcnow():
            return "expired"
    return survey["status"]


def serialize_survey(survey: dict) -> dict:
    return {
        "id": str(survey["_id"]),
        "title": survey["title"], "description": survey["description"],
        "status": survey["status"], "effective_status": effective_status(survey),
        "draft_revision": survey["draft_revision"], "share_code": survey["share_code"],
        "share_url": f"/survey/{survey['share_code']}",
        "settings": survey["settings"], "questions": survey["questions"],
        "created_at": survey["created_at"], "updated_at": survey["updated_at"],
        "published_at": survey["published_at"], "closed_at": survey["closed_at"],
    }


def validate_content(content: dict, *, publishing: bool = False) -> None:
    """草稿允许未填完；ID、数字范围及引用始终应正确。"""
    def reject(message):
        raise HTTPException(422, message)

    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            reject("数字条件必须是有限数值")
        if abs(value) > 9_007_199_254_740_991:
            reject("数字超出浏览器可准确表示的范围")
        if not isfinite(value):
            reject("数字条件必须是有限数值")

    def bounds(validation, lower, upper, label):
        lo, hi = validation.get(lower), validation.get(upper)
        if lo is not None and hi is not None and lo > hi:
            reject(f"{label}：最小值不能超过最大值")

    if publishing and not content["title"].strip():
        reject("请填写问卷标题")
    questions = content["questions"]
    if publishing and not questions:
        reject("至少添加一道题目后才能发布")
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)) or any(qid in {"NEXT", "END"} for qid in ids):
        reject("题目 ID 重复或使用了保留名称")
    positions = {qid: index for index, qid in enumerate(ids)}
    for index, question in enumerate(questions):
        label = f"第 {index + 1} 题"
        if publishing and not question["title"].strip():
            reject(f"{label}：请填写题目标题")
        options = question.get("options", [])
        option_ids = [o["id"] for o in options]
        if len(set(option_ids)) != len(option_ids):
            reject(f"{label}：选项 ID 重复")
        if publishing and question["type"] in {"single_choice", "multiple_choice"}:
            if len(options) < 2 or any(not o["label"].strip() for o in options):
                reject(f"{label}：至少配置两个有文字的选项")
        v = question["validation"]
        bounds(v, "min_choices", "max_choices", label)
        bounds(v, "min_length", "max_length", label)
        bounds(v, "min_value", "max_value", label)
        for key in ("min_value", "max_value"):
            if key in v:
                number(v[key])
        if publishing and question["type"] == "multiple_choice":
            if v.get("min_choices", 0) > len(options) or v.get("max_choices", 0) > len(options):
                reject(f"{label}：选择数量不能超过选项数")
            if question["required"] and v.get("max_choices") == 0:
                reject(f"{label}：必答多选题不能设置最多选择 0 项")
        if publishing and question["type"] == "number" and v.get("integer_only"):
            import math
            if "min_value" in v and "max_value" in v and math.ceil(v["min_value"]) > math.floor(v["max_value"]):
                reject(f"{label}：数值范围内没有整数")
        if publishing and question["type"] == "text" and question["required"] and v.get("max_length") == 0:
            reject(f"{label}：必答文本题不能设置最多输入 0 字")

        def target_is_valid(target):
            if target not in {"NEXT", "END"} and (target not in positions or positions[target] <= index):
                reject(f"{label}：跳转目标必须是后面的题目或结束")

        logic = question["logic"]
        target_is_valid(logic["default_target"])
        rule_ids = [r["id"] for r in logic["rules"]]
        if len(rule_ids) != len(set(rule_ids)):
            reject(f"{label}：规则 ID 重复")
        for rule in logic["rules"]:
            target_is_valid(rule["target"])
            condition = rule["condition"]
            value = condition["value"]
            if question["type"] == "single_choice" and value not in option_ids:
                reject(f"{label}：规则引用了不存在的选项")
            if question["type"] == "multiple_choice":
                if len(value) != len(set(value)) or not set(value).issubset(option_ids):
                    reject(f"{label}：规则中的选项重复或不存在")
            if question["type"] == "number":
                if condition["operator"] == "between":
                    for bound in value:
                        number(bound)
                    if value[0] > value[1]:
                        reject(f"{label}：跳转区间最小值不能超过最大值")
                else:
                    number(value)
    if publishing:
        deadline = content["settings"]["expires_at"]
        if deadline is not None and deadline <= utcnow():
            reject("截止时间必须晚于当前时间")
    # 给 MongoDB 文档元数据预留空间，避免逼近 16 MiB 上限。
    if len(BSON.encode(content)) > 8 * 1024 * 1024:
        reject("问卷内容过大")
