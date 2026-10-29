"""收集答案及创建者统计接口。"""

from fastapi import APIRouter, Depends, Query, Request

from Backend.answer_service import submit_response
from Backend.models import SubmissionRequest
from Backend.security import current_user
from Backend.statistics_service import find_question, question_statistics, response_records, whole_statistics
from Backend.survey_service import owned_survey


router = APIRouter(prefix="/api")


@router.post("/public/surveys/{share_code}/responses")
def submit(share_code: str, payload: SubmissionRequest, request: Request, user=Depends(current_user)):
    return submit_response(request.app.state.db, share_code, user["_id"], payload)


@router.get("/surveys/{survey_id}/statistics")
def statistics(survey_id: str, request: Request, user=Depends(current_user)):
    db = request.app.state.db
    return whole_statistics(db, owned_survey(db, survey_id, user["_id"]))


@router.get("/surveys/{survey_id}/statistics/{question_id}")
def single_question(survey_id: str, question_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    db = request.app.state.db
    survey = owned_survey(db, survey_id, user["_id"])
    return question_statistics(db, survey, find_question(survey, question_id), offset, limit)


@router.get("/surveys/{survey_id}/responses")
def records(survey_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(10, ge=1, le=100), user=Depends(current_user)):
    db = request.app.state.db
    return response_records(db, owned_survey(db, survey_id, user["_id"]), offset, limit)
