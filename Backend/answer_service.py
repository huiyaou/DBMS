"""实际答题路径、逐题校验和原子提交；规则由问卷配置驱动。"""

from math import isfinite

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from Backend.security import utcnow
from Backend.survey_service import effective_status


MISSING = object()


def answer_error(question, message):
    raise HTTPException(422, {
        "message": f"{question['title']}：{message}",
        "question_id": question["id"],
    })


def validate_answer(question, value=MISSING):
    kind, rules = question["type"], question["validation"]
    if isinstance(value, str) and kind == "text":
        value = value.strip()
    empty = (kind in {"text", "single_choice"} and value == "") or (kind == "multiple_choice" and value == [])
    if value is MISSING or empty:
        if question["required"]:
            answer_error(question, "此题为必答题")
        return MISSING

    def invalid(message):
        answer_error(question, message)

    options = [item["id"] for item in question.get("options", [])]
    if kind == "single_choice":
        if not isinstance(value, str) or value not in options:
            invalid("请选择一个有效选项")
    elif kind == "multiple_choice":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            invalid("请选择有效选项")
        if len(value) != len(set(value)) or not set(value).issubset(options):
            invalid("选项重复或不存在")
        lower = max(rules.get("min_choices", 0), 1 if question["required"] else 0)
        if len(value) < lower:
            invalid(f"至少选择 {lower} 项")
        if "max_choices" in rules and len(value) > rules["max_choices"]:
            invalid(f"最多选择 {rules['max_choices']} 项")
        # 统一顺序后保存，网络重试时选择顺序不同仍算同一份答案。
        value = [item for item in options if item in value]
    elif kind == "text":
        if not isinstance(value, str):
            invalid("请输入文字")
        if len(value) < rules.get("min_length", 0):
            invalid(f"至少输入 {rules['min_length']} 字")
        if len(value) > rules.get("max_length", 100000):
            invalid(f"最多输入 {rules.get('max_length', 100000)} 字")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid("请输入数字")
        if abs(value) > 9_007_199_254_740_991 or not isfinite(value):
            invalid("请输入可准确表示的有限数值")
        if rules.get("integer_only") and int(value) != value:
            invalid("必须输入整数")
        if "min_value" in rules and value < rules["min_value"]:
            invalid(f"不能小于 {rules['min_value']}")
        if "max_value" in rules and value > rules["max_value"]:
            invalid(f"不能大于 {rules['max_value']}")
    return value


def condition_matches(condition, value):
    operator, target = condition["operator"], condition["value"]
    if operator == "eq": return value == target
    if operator == "gt": return value > target
    if operator == "gte": return value >= target
    if operator == "lt": return value < target
    if operator == "lte": return value <= target
    if operator == "between": return target[0] <= value <= target[1]
    if operator == "contains_any": return bool(set(value) & set(target))
    if operator == "contains_all": return set(target).issubset(value)
    if operator == "equals_set": return set(value) == set(target)
    raise HTTPException(422, "问卷条件配置异常，请联系创建者")


def canonical_answers(survey, submitted):
    questions = survey["questions"]
    positions = {q["id"]: index for index, q in enumerate(questions)}
    answers = {}
    for answer in submitted:
        qid = answer["question_id"]
        if qid in answers or qid not in positions:
            raise HTTPException(422, "答案含有重复题目或不存在的题目")
        answers[qid] = answer["value"]
    visited, normalized = set(), []
    index = 0
    while index < len(questions):
        question = questions[index]
        visited.add(question["id"])
        value = validate_answer(question, answers.get(question["id"], MISSING))
        if value is not MISSING:
            normalized.append({"question_id": question["id"], "value": value})
        target = question["logic"]["default_target"]
        if value is not MISSING:
            for rule in question["logic"]["rules"]:
                if condition_matches(rule["condition"], value):
                    target = rule["target"]
                    break
        if target == "END":
            break
        next_index = index + 1 if target == "NEXT" else positions.get(target, -1)
        if next_index <= index:
            raise HTTPException(422, "问卷跳转配置异常，请联系创建者")
        index = next_index
    if set(answers) - visited:
        raise HTTPException(422, "答案包含已被跳过的题目，请清理后重新提交")
    return normalized


def public_survey_view(db, share_code, user_id):
    survey = db.surveys.find_one({"share_code": share_code, "status": {"$ne": "draft"}})
    if not survey:
        raise HTTPException(404, "问卷尚未发布或不存在")
    if effective_status(survey) != "published":
        raise HTTPException(410, "问卷已关闭或已到截止时间")
    previous = db.responses.find_one(
        {"survey_id": survey["_id"], "respondent_id": user_id},
        {"_id": 1, "submitted_at": 1}, sort=[("submitted_at", -1)],
    )
    return {
        "survey_id": str(survey["_id"]),
        **{key: survey[key] for key in ("title", "description", "settings", "questions")},
        "has_submitted": previous is not None,
        "can_submit": previous is None or survey["settings"]["allow_multiple_submissions"],
        "last_submitted_at": previous["submitted_at"] if previous else None,
    }


def submit_response(db, share_code, user_id, payload):
    survey = db.surveys.find_one({"share_code": share_code, "status": {"$ne": "draft"}})
    if not survey:
        raise HTTPException(404, "问卷尚未发布或不存在")
    accepted_at = utcnow()
    if payload.is_anonymous and not survey["settings"]["allow_anonymous"]:
        raise HTTPException(422, "这份问卷不允许匿名填写")
    key = str(payload.attempt_id) if survey["settings"]["allow_multiple_submissions"] else "once"
    selector = {"survey_id": survey["_id"], "respondent_id": user_id, "attempt_key": key}
    existing = db.responses.find_one(selector)
    if not existing and (survey["status"] != "published" or (survey["settings"]["expires_at"] is not None and survey["settings"]["expires_at"] <= accepted_at)):
        raise HTTPException(410, "问卷已关闭或已到截止时间")
    answers = canonical_answers(survey, [item.model_dump() for item in payload.answers])

    def result(document, reused):
        if document["answers"] != answers or document["is_anonymous"] != payload.is_anonymous:
            raise HTTPException(409, "本次填写已经提交，不能覆盖；如问卷允许多次填写，请开始新的填写")
        return {"id": str(document["_id"]), "submitted_at": document["submitted_at"], "reused": reused}

    if existing:
        return result(existing, True)
    document = {
        "schema_version": 1, **selector, "is_anonymous": payload.is_anonymous,
        "answers": answers, "submitted_at": accepted_at,
    }
    try:
        db.responses.insert_one(document)
    except DuplicateKeyError:
        # 并发重复请求由数据库唯一索引兜底，不使用先查后写作为唯一保证。
        existing = db.responses.find_one(selector)
        if existing:
            return result(existing, True)
        raise HTTPException(409, "提交发生冲突，请重试") from None
    return result(document, False)
