"""请求模型：检查输入类型和长度，发布完整性在 survey_service 中检查。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Text = Annotated[str, Field(strict=True, max_length=200)]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Number = StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=100000)]


class Credentials(InputModel):
    username: Annotated[str, Field(strict=True, min_length=1, max_length=64)]
    password: Annotated[str, Field(strict=True, min_length=8, max_length=128)]


class Option(InputModel):
    id: Identifier
    label: Text


class SingleCondition(InputModel):
    operator: Literal["eq"]
    value: Identifier


class MultipleCondition(InputModel):
    operator: Literal["contains_any", "contains_all", "equals_set"]
    value: Annotated[list[Identifier], Field(min_length=1, max_length=50)]


class NumericComparison(InputModel):
    operator: Literal["eq", "gt", "gte", "lt", "lte"]
    value: Number


class NumericRange(InputModel):
    operator: Literal["between"]
    value: Annotated[list[Number], Field(min_length=2, max_length=2)]


class SingleRule(InputModel):
    id: Identifier
    condition: SingleCondition
    target: Identifier


class MultipleRule(InputModel):
    id: Identifier
    condition: MultipleCondition
    target: Identifier


class NumericRule(InputModel):
    id: Identifier
    condition: Annotated[NumericComparison | NumericRange, Field(discriminator="operator")]
    target: Identifier


class SingleLogic(InputModel):
    rules: Annotated[list[SingleRule], Field(max_length=50)] = Field(default_factory=list)
    default_target: Identifier = "NEXT"


class MultipleLogic(InputModel):
    rules: Annotated[list[MultipleRule], Field(max_length=50)] = Field(default_factory=list)
    default_target: Identifier = "NEXT"


class NumericLogic(InputModel):
    rules: Annotated[list[NumericRule], Field(max_length=50)] = Field(default_factory=list)
    default_target: Identifier = "NEXT"


class TextLogic(InputModel):
    rules: Annotated[list, Field(max_length=0)] = Field(default_factory=list)
    default_target: Identifier = "NEXT"


class SingleValidation(InputModel):
    pass


class MultipleValidation(InputModel):
    min_choices: Count | None = None
    max_choices: Count | None = None


class TextValidation(InputModel):
    min_length: Count | None = None
    max_length: Count | None = None


class NumericValidation(InputModel):
    min_value: Number | None = None
    max_value: Number | None = None
    integer_only: StrictBool = False


class BaseQuestion(InputModel):
    id: Identifier
    title: Text = ""
    required: StrictBool = False
    source_question_id: str | None = None
    source_version_id: str | None = None


class SingleQuestion(BaseQuestion):
    type: Literal["single_choice"]
    options: Annotated[list[Option], Field(max_length=50)] = Field(default_factory=list)
    validation: SingleValidation = Field(default_factory=SingleValidation)
    logic: SingleLogic = Field(default_factory=SingleLogic)


class MultipleQuestion(BaseQuestion):
    type: Literal["multiple_choice"]
    options: Annotated[list[Option], Field(max_length=50)] = Field(default_factory=list)
    validation: MultipleValidation = Field(default_factory=MultipleValidation)
    logic: MultipleLogic = Field(default_factory=MultipleLogic)


class TextQuestion(BaseQuestion):
    type: Literal["text"]
    validation: TextValidation = Field(default_factory=TextValidation)
    logic: TextLogic = Field(default_factory=TextLogic)


class NumericQuestion(BaseQuestion):
    type: Literal["number"]
    validation: NumericValidation = Field(default_factory=NumericValidation)
    logic: NumericLogic = Field(default_factory=NumericLogic)


Question = Annotated[
    SingleQuestion | MultipleQuestion | TextQuestion | NumericQuestion,
    Field(discriminator="type"),
]


class SurveySettings(InputModel):
    allow_anonymous: StrictBool = False
    allow_multiple_submissions: StrictBool = False
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("截止时间必须包含时区")
        return value


class SurveyContent(InputModel):
    title: Text = ""
    description: Annotated[str, Field(strict=True, max_length=2000)] = ""
    settings: SurveySettings = Field(default_factory=SurveySettings)
    questions: Annotated[list[Question], Field(max_length=200)] = Field(default_factory=list)


class SurveySave(SurveyContent):
    draft_revision: Annotated[int, Field(strict=True, ge=1)]


class RevisionRequest(InputModel):
    draft_revision: Annotated[int, Field(strict=True, ge=1)]


class DeadlineRequest(InputModel):
    expires_at: datetime | None

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value):
        return SurveySettings.require_timezone(value)


class AnswerInput(InputModel):
    question_id: Identifier
    value: (
        Annotated[str, Field(strict=True, max_length=100000)]
        | Annotated[list[Identifier], Field(max_length=50)]
        | Number
    )


class SubmissionRequest(InputModel):
    attempt_id: UUID
    is_anonymous: StrictBool = False
    answers: Annotated[list[AnswerInput], Field(max_length=200)]
