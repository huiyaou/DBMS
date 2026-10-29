"""从实际提交实时聚合，不保存易过期的统计副本。"""

from fastapi import HTTPException


def aggregate_one(collection, pipeline):
    return next(collection.aggregate(pipeline), {})


def survey_totals(db, survey):
    query = {"survey_id": survey["_id"]}
    people = aggregate_one(db.responses, [
        {"$match": query}, {"$group": {"_id": "$respondent_id"}}, {"$count": "count"},
    ])
    return {"response_count": db.responses.count_documents(query), "participant_count": people.get("count", 0)}


def question_statistics(db, survey, question, offset=0, limit=10):
    base = [
        {"$match": {"survey_id": survey["_id"]}},
        {"$unwind": "$answers"},
        {"$match": {"answers.question_id": question["id"]}},
    ]
    totals = aggregate_one(db.responses, base + [
        {"$group": {"_id": "$respondent_id", "count": {"$sum": 1}}},
        {"$group": {"_id": None, "answered_count": {"$sum": "$count"}, "participant_count": {"$sum": 1}}},
    ])
    result = {
        "question_id": question["id"], "title": question["title"], "type": question["type"],
        "answered_count": totals.get("answered_count", 0), "participant_count": totals.get("participant_count", 0),
        "options": [], "average": None, "answers": [], "offset": offset, "limit": limit,
    }
    if question["type"] in {"single_choice", "multiple_choice"}:
        pipeline = base + ([{"$unwind": "$answers.value"}] if question["type"] == "multiple_choice" else [])
        rows = list(db.responses.aggregate(pipeline + [
            {"$group": {"_id": {"option": "$answers.value", "person": "$respondent_id"}, "count": {"$sum": 1}}},
            {"$group": {"_id": "$_id.option", "count": {"$sum": "$count"}, "people_count": {"$sum": 1}}},
        ]))
        by_option = {row["_id"]: row for row in rows}
        result["options"] = [
            {**option, "count": by_option.get(option["id"], {}).get("count", 0), "people_count": by_option.get(option["id"], {}).get("people_count", 0)}
            for option in question["options"]
        ]
    else:
        if question["type"] == "number":
            row = aggregate_one(db.responses, base + [{"$group": {"_id": None, "average": {"$avg": "$answers.value"}}}])
            result["average"] = row.get("average")
        result["answers"] = list(db.responses.aggregate(base + [
            {"$sort": {"submitted_at": -1, "_id": -1}}, {"$skip": offset}, {"$limit": limit},
            {"$project": {"_id": 0, "value": "$answers.value", "submitted_at": 1}},
        ]))
    return result


def whole_statistics(db, survey):
    return {
        "survey_id": str(survey["_id"]), "title": survey["title"], **survey_totals(db, survey),
        "questions": [question_statistics(db, survey, question) for question in survey["questions"]],
    }


def find_question(survey, question_id):
    question = next((q for q in survey["questions"] if q["id"] == question_id), None)
    if not question:
        raise HTTPException(404, "题目不存在")
    return question


def response_records(db, survey, offset, limit):
    query = {"survey_id": survey["_id"]}
    records = list(db.responses.find(query).sort([("submitted_at", -1), ("_id", -1)]).skip(offset).limit(limit))
    # 只为实名记录读取用户名；匿名记录从接口层过滤身份和 attempt_key。
    named_ids = list({r["respondent_id"] for r in records if not r["is_anonymous"]})
    names = {u["_id"]: u["username"] for u in db.users.find({"_id": {"$in": named_ids}}, {"username": 1})}
    return {
        "total": db.responses.count_documents(query), "offset": offset, "limit": limit,
        "items": [
            {
                "id": str(r["_id"]), "is_anonymous": r["is_anonymous"],
                "respondent_name": "匿名" if r["is_anonymous"] else names.get(r["respondent_id"], "已注销用户"),
                "submitted_at": r["submitted_at"], "answers": r["answers"],
            }
            for r in records
        ],
    }
