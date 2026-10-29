"""题目版本、共享、题库和跨问卷统计。"""
from copy import deepcopy
from uuid import uuid4

from bson import ObjectId
from pymongo import ReturnDocument
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from Backend.models import Question
from Backend.security import current_user, normalize_username, utcnow
from Backend.survey_service import validate_content, owned_survey, serialize_survey

router = APIRouter(prefix="/api")
adapter = TypeAdapter(Question)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionInput(Input):
    content: dict
    parent_id: str | None = None


class ShareInput(Input):
    username: str = Field(min_length=1, max_length=64)


class BankInput(Input):
    name: str = Field(min_length=1, max_length=200)


class BankItem(Input):
    question_id: str
    version_id: str


class AppendQuestion(BankItem):
    draft_revision: int = Field(ge=1, strict=True)


def oid(value):
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise HTTPException(404, "对象不存在")
    return ObjectId(value)


def accessible(db, question_id, user_id, owner=False, include_archived=False):
    query = {"_id": oid(question_id)}
    if not include_archived:
        query["archived"] = {"$ne": True}
    query.update({"owner_id": user_id} if owner else {"$or": [{"owner_id": user_id}, {"shared_with": user_id}]})
    question = db.questions.find_one(query)
    if not question:
        raise HTTPException(404, "题目不存在或无权访问")
    return question


def version(db, question, version_id, include_archived=False):
    query = {"_id": oid(version_id), "question_id": question["_id"]}
    if not include_archived:
        query["archived"] = {"$ne": True}
    item = db.question_versions.find_one(query)
    if not item:
        raise HTTPException(404, "题目版本不存在")
    return item


def normalized(content):
    data = deepcopy(content)
    data.update(id="template", required=False, logic={"rules": [], "default_target": "NEXT"})
    data.pop("source_question_id", None)
    data.pop("source_version_id", None)
    try:
        data = adapter.validate_python(data).model_dump(exclude_none=True)
    except ValidationError as error:
        raise HTTPException(422, "题目格式不正确") from error
    data["validation"] = {k: v for k, v in data["validation"].items() if v is not None}
    validate_content({"title": "题目", "description": "", "settings": {"expires_at": None}, "questions": [data]}, publishing=True)
    return data


def public_version(item):
    return {"id": str(item["_id"]), "question_id": str(item["question_id"]), "parent_id": str(item["parent_id"]) if item["parent_id"] else None, "created_at": item["created_at"], "content": item["content"], "archived": item.get("archived", False)}


def validate_sources(db, content, user_id, original=None):
    old = {q["id"]: q for q in (original or {}).get("questions", [])}
    for q in content["questions"]:
        qid, vid = q.get("source_question_id"), q.get("source_version_id")
        if not qid and not vid:
            continue
        if not qid or not vid:
            raise HTTPException(422, "题目来源不完整")
        # 已保存的引用即使共享被撤销也可以继续使用。
        previous = old.get(q["id"], {})
        if previous.get("source_question_id") == qid and previous.get("source_version_id") == vid:
            item = db.question_versions.find_one({"_id": oid(vid), "question_id": oid(qid)})
            if not item:
                raise HTTPException(422, "题目来源不存在")
        else:
            item = version(db, accessible(db, qid, user_id), vid)
        if normalized(q) != item["content"]:
            raise HTTPException(422, "题目内容与引用版本不一致，请先移除来源或创建新版本")


@router.post("/questions", status_code=201)
def create_question(payload: QuestionInput, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    content = normalized(payload.content)
    if payload.parent_id:
        raise HTTPException(422, "新题目不能指定来源版本")
    question = {"schema_version": 1, "owner_id": user["_id"], "shared_with": [], "created_at": utcnow()}
    db.questions.insert_one(question)
    item = {"schema_version": 1, "question_id": question["_id"], "parent_id": None, "created_by": user["_id"], "created_at": utcnow(), "content": content}
    db.question_versions.insert_one(item)
    return public_version(item)


@router.get("/questions")
def list_questions(request: Request, user=Depends(current_user)):
    db = request.app.state.db
    result = []
    for q in db.questions.find({"archived": {"$ne": True}, "$or": [{"owner_id": user["_id"]}, {"shared_with": user["_id"]}]}).sort("created_at", -1):
        items = []
        for index, stored in enumerate(db.question_versions.find({"question_id": q["_id"]}).sort([("created_at", 1), ("_id", 1)])):
            item = public_version(stored)
            item.update(number=index, can_delete=q["owner_id"] == user["_id"] or stored["created_by"] == user["_id"])
            items.append(item)
        result.append({"id": str(q["_id"]), "is_owner": q["owner_id"] == user["_id"], "versions": items})
    return result


@router.post("/questions/{question_id}/versions", status_code=201)
def add_version(question_id: str, payload: QuestionInput, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, question_id, user["_id"])
    parent = version(db, q, payload.parent_id) if payload.parent_id else None
    if not parent:
        raise HTTPException(422, "请指定来源版本")
    content = normalized(payload.content)
    if content["title"] != parent["content"]["title"]:
        raise HTTPException(422, "创建新版本时不能修改题目标题；如需更换标题，请新建题目")
    item = {"schema_version": 1, "question_id": q["_id"], "parent_id": parent["_id"], "created_by": user["_id"], "created_at": utcnow(), "content": content}
    db.question_versions.insert_one(item)
    return public_version(item)


@router.delete("/questions/{question_id}/versions/{version_id}", status_code=204)
def delete_version(question_id: str, version_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, question_id, user["_id"], include_archived=True)
    v = version(db, q, version_id, include_archived=True)
    if q["owner_id"] != user["_id"] and v["created_by"] != user["_id"]:
        raise HTTPException(403, "只能删除自己的题目版本")
    db.question_versions.update_one({"_id": v["_id"]}, {"$set": {"archived": True}})
    db.question_banks.update_many({}, {"$pull": {"items": {"version_id": v["_id"]}}})


@router.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, question_id, user["_id"], owner=True, include_archived=True)
    db.questions.update_one({"_id": q["_id"]}, {"$set": {"archived": True}})
    db.question_banks.update_many({}, {"$pull": {"items": {"question_id": q["_id"]}}})


@router.post("/surveys/{survey_id}/questions", status_code=200)
def append_question(survey_id: str, payload: AppendQuestion, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    survey = owned_survey(db, survey_id, user["_id"])
    if survey["status"] not in {"draft", "published"}:
        raise HTTPException(409, "已关闭问卷不能增加题目")
    q = accessible(db, payload.question_id, user["_id"])
    v = version(db, q, payload.version_id)
    def same_content(x):
        return all(x.get(key) == v["content"].get(key) for key in ("type", "title", "options", "validation"))
    if any(x.get("source_question_id") == payload.question_id or same_content(x) for x in survey["questions"]):
        raise HTTPException(409, "这份问卷已包含此题，请选择其他题目")
    if len(survey["questions"]) >= 200:
        raise HTTPException(422, "问卷最多包含 200 道题目")
    item = {**deepcopy(v["content"]), "id": uuid4().hex, "source_question_id": payload.question_id, "source_version_id": payload.version_id}
    candidate = {**survey, "questions": [*survey["questions"], item]}
    validate_content(candidate)
    saved = db.surveys.find_one_and_update(
        {"_id": survey["_id"], "owner_id": user["_id"], "status": survey["status"], "draft_revision": payload.draft_revision},
        {"$push": {"questions": item}, "$inc": {"draft_revision": 1}, "$set": {"updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if not saved:
        raise HTTPException(409, "问卷已变化，请重新选择后加入")
    return serialize_survey(saved)


@router.post("/questions/{question_id}/share", status_code=204)
def share_question(question_id: str, payload: ShareInput, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, question_id, user["_id"], owner=True)
    _, key = normalize_username(payload.username)
    recipient = db.users.find_one({"username_key": key})
    if not recipient:
        raise HTTPException(404, "用户不存在")
    db.questions.update_one({"_id": q["_id"]}, {"$addToSet": {"shared_with": recipient["_id"]}})


@router.get("/questions/{question_id}/usage")
def usage(question_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    accessible(db, question_id, user["_id"])
    surveys = db.surveys.find({"owner_id": user["_id"], "questions.source_question_id": question_id})
    return [{"id": str(s["_id"]), "title": s["title"], "status": s["status"], "versions": [q["source_version_id"] for q in s["questions"] if q.get("source_question_id") == question_id]} for s in surveys]


@router.get("/questions/{question_id}/versions/{version_id}/statistics")
def statistics(question_id: str, version_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, question_id, user["_id"])
    v = version(db, q, version_id)
    surveys = list(db.surveys.find({"owner_id": user["_id"], "questions.source_version_id": version_id}))
    mapping = {s["_id"]: {x["id"] for x in s["questions"] if x.get("source_question_id") == question_id and x.get("source_version_id") == version_id} for s in surveys}
    answers, people = [], set()
    for r in db.responses.find({"survey_id": {"$in": list(mapping)}}):
        for answer in r["answers"]:
            if answer["question_id"] in mapping[r["survey_id"]]:
                answers.append(answer["value"])
                people.add(r["respondent_id"])
    content = v["content"]
    result = {"survey_count": len(surveys), "answered_count": len(answers), "participant_count": len(people), "type": content["type"], "options": [], "average": None, "answers": []}
    if content["type"] in {"single_choice", "multiple_choice"}:
        result["options"] = [{**o, "count": sum(o["id"] in a if isinstance(a, list) else o["id"] == a for a in answers)} for o in content["options"]]
    elif content["type"] == "number":
        result["average"] = sum(answers) / len(answers) if answers else None
        result["answers"] = answers
    else:
        result["answers"] = answers
    return result


@router.post("/banks", status_code=201)
def create_bank(payload: BankInput, request: Request, user=Depends(current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "题库名称不能为空")
    bank = {"schema_version": 1, "owner_id": user["_id"], "name": name, "items": [], "created_at": utcnow()}
    request.app.state.db.question_banks.insert_one(bank)
    return {"id": str(bank["_id"]), "name": name, "items": []}


@router.get("/banks")
def list_banks(request: Request, user=Depends(current_user)):
    return [{"id": str(b["_id"]), "name": b["name"], "items": [{"question_id": str(i["question_id"]), "version_id": str(i["version_id"])} for i in b["items"]]} for b in request.app.state.db.question_banks.find({"owner_id": user["_id"]})]


@router.patch("/banks/{bank_id}")
def rename_bank(bank_id: str, payload: BankInput, request: Request, user=Depends(current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "题库名称不能为空")
    result = request.app.state.db.question_banks.update_one({"_id": oid(bank_id), "owner_id": user["_id"]}, {"$set": {"name": name}})
    if not result.matched_count:
        raise HTTPException(404, "题库不存在")
    return {"id": bank_id, "name": name}


@router.delete("/banks/{bank_id}", status_code=204)
def delete_bank(bank_id: str, request: Request, user=Depends(current_user)):
    result = request.app.state.db.question_banks.delete_one({"_id": oid(bank_id), "owner_id": user["_id"]})
    if not result.deleted_count:
        raise HTTPException(404, "题库不存在")


@router.put("/banks/{bank_id}/items")
def put_bank_item(bank_id: str, payload: BankItem, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    q = accessible(db, payload.question_id, user["_id"])
    v = version(db, q, payload.version_id)
    bank = db.question_banks.find_one({"_id": oid(bank_id), "owner_id": user["_id"]})
    if not bank:
        raise HTTPException(404, "题库不存在")
    # 一个题库对每题保留一个选定版本。
    items = [item for item in bank["items"] if item["question_id"] != q["_id"]]
    items.append({"question_id": q["_id"], "version_id": v["_id"]})
    db.question_banks.update_one({"_id": bank["_id"], "owner_id": user["_id"]}, {"$set": {"items": items}})
    return {"ok": True}


@router.delete("/banks/{bank_id}/items/{question_id}", status_code=204)
def delete_bank_item(bank_id: str, question_id: str, request: Request, user=Depends(current_user)):
    result = request.app.state.db.question_banks.update_one({"_id": oid(bank_id), "owner_id": user["_id"]}, {"$pull": {"items": {"question_id": oid(question_id)}}})
    if not result.matched_count:
        raise HTTPException(404, "题库不存在")
