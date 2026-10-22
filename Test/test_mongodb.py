"""真实 MongoDB 集成测试；只操作本次创建的随机临时数据库。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client
from Backend.init_db import initialize_database


def make_user() -> dict:
    token = uuid4().hex
    return {
        "_id": ObjectId(),
        "schema_version": 1,
        "username": f"测试用户_{token}",
        "username_key": f"test_{token}",
        "password_hash": "test-fixture-not-a-login-password",
        "created_at": datetime.now(timezone.utc),
    }


def make_survey(owner_id: ObjectId) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "_id": ObjectId(),
        "schema_version": 1,
        "owner_id": owner_id,
        "title": "数据库集成测试问卷",
        "description": "仅用于本次临时库测试",
        "status": "draft",
        "draft_revision": 1,
        "share_code": uuid4().hex,
        "settings": {
            "allow_anonymous": True,
            "allow_multiple_submissions": False,
            "expires_at": None,
        },
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "title": "是否住宿",
                "required": True,
                "options": [
                    {"id": "yes", "label": "是"},
                    {"id": "no", "label": "否"},
                ],
                "validation": {},
                "logic": {
                    "rules": [
                        {
                            "id": "r1",
                            "condition": {"operator": "eq", "value": "no"},
                            "target": "q3",
                        }
                    ],
                    "default_target": "NEXT",
                },
            },
            {
                "id": "q2",
                "type": "multiple_choice",
                "title": "设施",
                "required": True,
                "options": [
                    {"id": "a", "label": "洗衣房"},
                    {"id": "b", "label": "自习室"},
                ],
                "validation": {"min_choices": 1, "max_choices": 2},
                "logic": {
                    "rules": [
                        {
                            "id": "r2",
                            "condition": {"operator": "contains_any", "value": ["a"]},
                            "target": "q4",
                        }
                    ],
                    "default_target": "NEXT",
                },
            },
            {
                "id": "q3",
                "type": "text",
                "title": "建议",
                "required": False,
                "validation": {"min_length": 2, "max_length": 200},
                "logic": {"rules": [], "default_target": "NEXT"},
            },
            {
                "id": "q4",
                "type": "number",
                "title": "年龄",
                "required": True,
                "validation": {"min_value": 0, "max_value": 120, "integer_only": True},
                "logic": {
                    "rules": [
                        {
                            "id": "r3",
                            "condition": {"operator": "lt", "value": 18},
                            "target": "END",
                        },
                        {
                            "id": "r4",
                            "condition": {"operator": "between", "value": [18, 60]},
                            "target": "END",
                        },
                    ],
                    "default_target": "END",
                },
            },
        ],
        "created_at": now,
        "updated_at": now,
        "published_at": None,
        "closed_at": None,
    }


def make_response(survey_id: ObjectId, respondent_id: ObjectId) -> dict:
    return {
        "_id": ObjectId(),
        "schema_version": 1,
        "survey_id": survey_id,
        "respondent_id": respondent_id,
        "is_anonymous": True,
        "attempt_key": "once",
        "answers": [
            {"question_id": "q1", "value": "no"},
            {"question_id": "q3", "value": "希望增加自习室"},
            {"question_id": "q4", "value": 0},
        ],
        "submitted_at": datetime.now(timezone.utc),
    }


class ConfigurationTests(unittest.TestCase):
    def test_environment_configuration(self):
        with patch.dict(
            "os.environ",
            {
                "MONGODB_URI": "mongodb://127.0.0.1:27017/",
                "MONGODB_DB_NAME": "survey_example",
                "MONGODB_TIMEOUT_MS": "1234",
            },
        ):
            settings = DatabaseSettings.from_env()
        self.assertEqual(settings.database_name, "survey_example")
        self.assertEqual(settings.timeout_ms, 1234)
        self.assertEqual(settings.uri, "mongodb://127.0.0.1:27017/")

    def test_system_or_invalid_database_names_rejected(self):
        for name in ["admin", "local", "config", "", "a.b", "a/b", "a b"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                DatabaseSettings(database_name=name)

    def test_invalid_connection_settings_rejected(self):
        with self.assertRaises(ValueError):
            DatabaseSettings(uri="http://localhost:27017")
        with self.assertRaises(ValueError):
            DatabaseSettings(timeout_ms=0)


class MongoDBIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = create_client()
        cls.addClassCleanup(cls.client.close)
        check_connection(cls.client)
        cls.test_database_name = f"survey_system_test_{uuid4().hex}"
        if cls.test_database_name in cls.client.list_database_names():
            raise RuntimeError("测试库名已存在，停止以避免影响已有数据")
        cls.db = cls.client[cls.test_database_name]
        # 只清理本次生成且事先确认不存在的精确数据库名。
        cls.addClassCleanup(cls.client.drop_database, cls.test_database_name)
        initialize_database(cls.db)

    def setUp(self):
        self.owner = make_user()
        self.respondent = make_user()
        self.survey = make_survey(self.owner["_id"])
        self.response = make_response(self.survey["_id"], self.respondent["_id"])
        self.db.users.insert_many([self.owner, self.respondent])
        self.db.surveys.insert_one(self.survey)

    def assert_invalid(self, collection: str, document: dict):
        document = deepcopy(document)
        document["_id"] = ObjectId()
        with self.assertRaises(WriteError) as caught:
            self.db[collection].insert_one(document)
        self.assertEqual(caught.exception.code, 121)

    def test_valid_documents_round_trip(self):
        self.db.responses.insert_one(self.response)
        saved = self.db.responses.find_one({"_id": self.response["_id"]})
        self.assertIsInstance(saved["survey_id"], ObjectId)
        self.assertEqual(saved["submitted_at"].utcoffset().total_seconds(), 0)
        self.assertEqual(saved["answers"][-1]["value"], 0)
        self.assertEqual(saved["is_anonymous"], True)

    def test_draft_can_be_incomplete(self):
        survey = make_survey(self.owner["_id"])
        survey.update(title="", questions=[])
        self.db.surveys.insert_one(survey)
        survey = make_survey(self.owner["_id"])
        survey["questions"][0].update(title="", options=[])
        self.db.surveys.insert_one(survey)

    def test_missing_fields_rejected(self):
        for collection, original, fields in [
            ("users", self.owner, ["schema_version", "username_key", "password_hash", "created_at"]),
            ("surveys", self.survey, ["owner_id", "settings", "questions", "share_code"]),
            ("responses", self.response, ["respondent_id", "survey_id", "answers", "attempt_key"]),
        ]:
            for field in fields:
                with self.subTest(collection=collection, field=field):
                    document = deepcopy(original)
                    del document[field]
                    self.assert_invalid(collection, document)

    def test_wrong_bson_types_rejected(self):
        for collection, original, field, value in [
            ("users", self.owner, "created_at", "2026-10-20"),
            ("surveys", self.survey, "owner_id", str(self.owner["_id"])),
            ("surveys", self.survey, "draft_revision", True),
            ("responses", self.response, "survey_id", str(self.survey["_id"])),
            ("responses", self.response, "is_anonymous", "true"),
            ("responses", self.response, "respondent_id", None),
        ]:
            with self.subTest(collection=collection, field=field):
                document = deepcopy(original)
                document[field] = value
                self.assert_invalid(collection, document)

    def test_unknown_fields_rejected(self):
        for collection, original in [
            ("users", self.owner), ("surveys", self.survey), ("responses", self.response)
        ]:
            with self.subTest(collection=collection):
                document = deepcopy(original)
                document["misspelled_field"] = "unexpected"
                self.assert_invalid(collection, document)
        survey = deepcopy(self.survey)
        survey["settings"]["allow_anon"] = True
        self.assert_invalid("surveys", survey)

    def test_unknown_schema_version_status_and_question_type_rejected(self):
        user = deepcopy(self.owner)
        user["schema_version"] = 2
        self.assert_invalid("users", user)
        survey = deepcopy(self.survey)
        survey["status"] = "unknown"
        self.assert_invalid("surveys", survey)
        survey = deepcopy(self.survey)
        survey["questions"][0]["type"] = "unknown"
        self.assert_invalid("surveys", survey)

    def test_question_specific_validation_shapes(self):
        for index, validation in [
            (0, {"min_choices": 1}),
            (1, {"min_choices": "2"}),
            (1, {"max_choices": -1}),
            (2, {"min_length": True}),
            (3, {"integer_only": "true"}),
            (3, {"min_length": 2}),
        ]:
            with self.subTest(index=index, validation=validation):
                survey = deepcopy(self.survey)
                survey["questions"][index]["validation"] = validation
                self.assert_invalid("surveys", survey)
        survey = deepcopy(self.survey)
        survey["questions"][2]["options"] = []
        self.assert_invalid("surveys", survey)

    def test_question_specific_jump_conditions(self):
        for index, condition in [
            (0, {"operator": "gt", "value": 18}),
            (0, {"operator": "eq", "value": ["yes"]}),
            (1, {"operator": "contains_any", "value": "a"}),
            (1, {"operator": "contains_all", "value": []}),
            (3, {"operator": "between", "value": [1, 2, 3]}),
            (3, {"operator": "eq", "value": True}),
        ]:
            with self.subTest(index=index, condition=condition):
                survey = deepcopy(self.survey)
                survey["questions"][index]["logic"]["rules"][0]["condition"] = condition
                self.assert_invalid("surveys", survey)

    def test_all_supported_jump_operator_shapes_accepted(self):
        for index, operators, value in [
            (1, ["contains_any", "contains_all", "equals_set"], ["a", "b"]),
            (3, ["eq", "gt", "gte", "lt", "lte"], 18),
            (3, ["between"], [18, 60]),
        ]:
            for operator in operators:
                with self.subTest(operator=operator):
                    survey = make_survey(self.owner["_id"])
                    survey["questions"][index]["logic"]["rules"][0]["condition"] = {
                        "operator": operator, "value": value
                    }
                    self.db.surveys.insert_one(survey)

    def test_invalid_answer_shapes_rejected(self):
        for value in [None, True, {}, ["a", 1], ["a", "a"], [], ""]:
            with self.subTest(value=value):
                response = deepcopy(self.response)
                response["answers"][0]["value"] = value
                self.assert_invalid("responses", response)

    def test_multiselect_answer_and_numeric_types_accepted(self):
        for value in [["a", "b"], 0, 20.5, 13_800_000_000]:
            with self.subTest(value=value):
                response = deepcopy(self.response)
                response.update(_id=ObjectId(), attempt_key=uuid4().hex)
                # 此处只验证 BSON 形状，不代表答案已通过对应题目的业务校验。
                response["answers"][0]["value"] = value
                self.db.responses.insert_one(response)

    def test_unique_username_enforced(self):
        user = make_user()
        user["username_key"] = self.owner["username_key"]
        with self.assertRaises(DuplicateKeyError):
            self.db.users.insert_one(user)

    def test_unique_share_code_enforced(self):
        survey = make_survey(self.owner["_id"])
        survey["share_code"] = self.survey["share_code"]
        with self.assertRaises(DuplicateKeyError):
            self.db.surveys.insert_one(survey)

    def test_same_attempt_cannot_be_inserted_twice(self):
        self.db.responses.insert_one(self.response)
        duplicate = deepcopy(self.response)
        duplicate["_id"] = ObjectId()
        with self.assertRaises(DuplicateKeyError):
            self.db.responses.insert_one(duplicate)
        self.assertEqual(self.db.responses.count_documents({"survey_id": self.survey["_id"]}), 1)

    def test_distinct_attempts_and_distinct_people_allowed(self):
        self.db.responses.insert_one(self.response)
        for respondent, attempt in [
            (self.respondent["_id"], uuid4().hex),
            (self.respondent["_id"], uuid4().hex),
            (self.owner["_id"], "once"),
        ]:
            response = make_response(self.survey["_id"], respondent)
            response["attempt_key"] = attempt
            self.db.responses.insert_one(response)
        self.assertEqual(self.db.responses.count_documents({"survey_id": self.survey["_id"]}), 4)

    def test_concurrent_duplicate_attempt_has_one_winner(self):
        barrier = Barrier(2)

        def submit():
            response = deepcopy(self.response)
            response["_id"] = ObjectId()
            barrier.wait(timeout=5)
            try:
                self.db.responses.insert_one(response)
                return "inserted"
            except DuplicateKeyError:
                return "duplicate"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit(), range(2)))
        self.assertCountEqual(results, ["inserted", "duplicate"])
        self.assertEqual(self.db.responses.count_documents({"survey_id": self.survey["_id"]}), 1)

    def test_invalid_update_rejected_without_changing_document(self):
        before = self.db.users.find_one({"_id": self.owner["_id"]})
        with self.assertRaises(WriteError) as caught:
            self.db.users.update_one({"_id": self.owner["_id"]}, {"$set": {"created_at": "bad"}})
        self.assertEqual(caught.exception.code, 121)
        self.assertEqual(self.db.users.find_one({"_id": self.owner["_id"]}), before)

    def test_reinitialization_preserves_existing_documents(self):
        self.db.responses.insert_one(self.response)
        before = {
            name: list(self.db[name].find().sort("_id", 1))
            for name in ["users", "surveys", "responses"]
        }
        initialize_database(self.db)
        initialize_database(self.db)
        for name, documents in before.items():
            self.assertEqual(list(self.db[name].find().sort("_id", 1)), documents)

    def test_strict_error_validators_and_expected_indexes(self):
        for name in ["users", "surveys", "responses"]:
            options = self.db[name].options()
            self.assertEqual(options["validationLevel"], "strict")
            self.assertEqual(options["validationAction"], "error")
            self.assertIn("$jsonSchema", options["validator"])
        self.assertTrue(self.db.users.index_information()["uq_username_key"]["unique"])
        self.assertTrue(self.db.surveys.index_information()["uq_share_code"]["unique"])
        index = self.db.responses.index_information()["uq_response_attempt"]
        self.assertTrue(index["unique"])
        self.assertEqual(index["key"], [("survey_id", 1), ("respondent_id", 1), ("attempt_key", 1)])
        self.assertEqual(
            self.db.surveys.index_information()["ix_owner_created"]["key"],
            [("owner_id", 1), ("created_at", -1)],
        )
        self.assertEqual(
            self.db.responses.index_information()["ix_survey_submitted"]["key"],
            [("survey_id", 1), ("submitted_at", -1)],
        )

    def test_preexisting_invalid_document_requires_migration(self):
        invalid = {"_id": ObjectId(), "legacy": True}
        self.db.users.insert_one(invalid, bypass_document_validation=True)
        try:
            with self.assertRaisesRegex(ValueError, "users"):
                initialize_database(self.db)
            self.assertEqual(self.db.users.find_one({"_id": invalid["_id"]}), invalid)
        finally:
            self.db.users.delete_one({"_id": invalid["_id"]})


if __name__ == "__main__":
    unittest.main()
