"""收集答案、实际跳转与实时统计；全部使用本次独立临时库。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
import unittest
from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client
from Backend.main import create_app
from Backend.security import utcnow
from test_mongodb import make_survey


class AnswerCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mongo = create_client()
        cls.addClassCleanup(cls.mongo.close)
        check_connection(cls.mongo)
        name = f"survey_system_answer_test_{uuid4().hex}"
        if name in cls.mongo.list_database_names():
            raise RuntimeError("临时数据库已存在，停止测试")
        cls.addClassCleanup(cls.mongo.drop_database, name)
        cls.settings = replace(DatabaseSettings.from_env(), database_name=name)
        cls.db = cls.mongo[name]

    def new_client(self, prefix):
        client = self.enterContext(TestClient(create_app(self.settings)))
        name = prefix + uuid4().hex[:12]
        result = client.post("/api/auth/register", json={"username": name, "password": "test-password-123"})
        self.assertEqual(result.status_code, 201, result.text)
        return client, result.json()

    def setUp(self):
        self.author, self.author_user = self.new_client("author_")
        self.person, self.person_user = self.new_client("person_")

    def form(self, *, multiple=False, anonymous=True, jumps=False):
        fixture = make_survey(None)
        body = {k: fixture[k] for k in ("title", "description", "settings", "questions")}
        body["settings"].update(allow_multiple_submissions=multiple, allow_anonymous=anonymous)
        if not jumps:
            for q in body["questions"]: q["logic"]["rules"] = []
        return body

    def publish(self, body=None):
        result = self.author.post("/api/surveys", json=body or self.form())
        self.assertEqual(result.status_code, 201, result.text)
        survey = result.json()
        result = self.author.post(f"/api/surveys/{survey['id']}/publish", json={"draft_revision": 1})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def payload(self, *, numeric=20, text="校园建议", choice="yes", multi=None, anonymous=False):
        values = {"q1": choice, "q2": multi if multi is not None else ["a"], "q4": numeric}
        if text is not None: values["q3"] = text
        return {"attempt_id": str(uuid4()), "is_anonymous": anonymous, "answers": [{"question_id": k, "value": v} for k, v in values.items()]}

    def submit(self, survey, body=None, client=None):
        return (client or self.person).post(f"/api/public/surveys/{survey['share_code']}/responses", json=body or self.payload())

    def count(self, survey):
        return self.db.responses.count_documents({"survey_id": ObjectId(survey["id"])})

    def test_valid_submission_saved_with_server_identity(self):
        survey = self.publish()
        result = self.submit(survey, self.payload(numeric=0))
        self.assertEqual(result.status_code, 200, result.text)
        record = self.db.responses.find_one({"_id": ObjectId(result.json()["id"])})
        self.assertEqual(str(record["respondent_id"]), self.person_user["id"])
        self.assertEqual(record["attempt_key"], "once")
        self.assertEqual(record["answers"][-1]["value"], 0)
        self.assertNotIn("respondent_id", result.json())
        public = self.person.get(f"/api/public/surveys/{survey['share_code']}").json()
        self.assertTrue(public["has_submitted"])
        self.assertFalse(public["can_submit"])

    def test_required_validation_rejects_missing_without_partial_write(self):
        survey = self.publish()
        for qid in ["q1", "q2", "q4"]:
            with self.subTest(qid=qid):
                body = self.payload()
                body["answers"] = [a for a in body["answers"] if a["question_id"] != qid]
                result = self.submit(survey, body)
                self.assertEqual(result.status_code, 422, result.text)
                self.assertEqual(result.json()["detail"]["question_id"], qid)
        self.assertEqual(self.count(survey), 0)

    def test_numeric_and_text_bounds_types_and_integer(self):
        survey = self.publish()
        for value in [-1, 121, 20.5, True, "20", "", [], 10 ** 100]:
            with self.subTest(value=value):
                self.assertEqual(self.submit(survey, self.payload(numeric=value)).status_code, 422)
        for text in ["字", "a" * 201, 100, ["a"], []]:
            with self.subTest(text=text):
                self.assertEqual(self.submit(survey, self.payload(text=text)).status_code, 422)
        self.assertEqual(self.submit(survey, self.payload(text="😀😀", numeric=120)).status_code, 200)

    def test_multiple_choice_limits_unknown_and_repeated_options(self):
        body = self.form()
        body["questions"][1]["validation"] = {"min_choices": 2, "max_choices": 2}
        survey = self.publish(body)
        for values in [["a"], ["a", "a"], ["a", "missing"], ["a", "b", "c"]]:
            with self.subTest(values=values):
                self.assertEqual(self.submit(survey, self.payload(multi=values)).status_code, 422)
        self.assertEqual(self.submit(survey, self.payload(multi=["b", "a"])).status_code, 200)

    def test_optional_empty_text_omitted(self):
        survey = self.publish()
        result = self.submit(survey, self.payload(text="   "))
        self.assertEqual(result.status_code, 200)
        row = self.db.responses.find_one({"_id": ObjectId(result.json()["id"])})
        self.assertNotIn("q3", [a["question_id"] for a in row["answers"]])

    def test_unknown_duplicate_question_and_forged_identity_rejected(self):
        survey = self.publish()
        for mutation in ["unknown", "duplicate", "identity", "policy"]:
            body = self.payload()
            if mutation == "unknown": body["answers"].append({"question_id": "unknown", "value": "x"})
            if mutation == "duplicate": body["answers"].append(deepcopy(body["answers"][0]))
            if mutation == "identity": body["respondent_id"] = self.author_user["id"]
            if mutation == "policy": body["attempt_key"] = "forged"
            with self.subTest(mutation=mutation):
                self.assertEqual(self.submit(survey, body).status_code, 422)
        self.assertEqual(self.count(survey), 0)

    def test_single_jump_skips_required_and_rejects_stale_answers(self):
        survey = self.publish(self.form(jumps=True))
        payload = self.payload(choice="no")
        self.assertEqual(self.submit(survey, payload).status_code, 422)
        payload["answers"] = [a for a in payload["answers"] if a["question_id"] != "q2"]
        self.assertEqual(self.submit(survey, payload).status_code, 200)

    def test_multiple_condition_operators_and_first_match_order(self):
        for operator, match, miss in [
            ("contains_any", ["a", "c"], ["c"]),
            ("contains_all", ["a", "b", "c"], ["a", "c"]),
            ("equals_set", ["b", "a"], ["a", "b", "c"]),
        ]:
            with self.subTest(operator=operator):
                content = self.form(multiple=True)
                q = content["questions"][1]
                q["options"].append({"id": "c", "label": "第三项"})
                q["validation"] = {"min_choices": 1, "max_choices": 3}
                q["logic"]["rules"] = [{"id": "r", "condition": {"operator": operator, "value": ["a", "b"]}, "target": "END"}]
                content["questions"] = [q, content["questions"][2]]
                content["questions"][1]["required"] = True
                survey = self.publish(content)
                body = {"attempt_id": str(uuid4()), "answers": [{"question_id": "q2", "value": match}]}
                self.assertEqual(self.submit(survey, body).status_code, 200)
                body["attempt_id"] = str(uuid4()); body["answers"][0]["value"] = miss
                self.assertEqual(self.submit(survey, body).status_code, 422)
        content = self.form(jumps=True)
        q = content["questions"][1]
        q["logic"]["rules"] = [
            {"id": "first", "condition": {"operator": "contains_any", "value": ["a"]}, "target": "q4"},
            {"id": "second", "condition": {"operator": "contains_all", "value": ["a", "b"]}, "target": "END"},
        ]
        survey = self.publish(content)
        self.assertEqual(self.submit(survey, self.payload(multi=["a", "b"], text=None)).status_code, 200)

    def test_numeric_jump_operators_and_closed_interval_boundaries(self):
        for operator, threshold, hits, miss in [
            ("eq", 20, [20], 21), ("gt", 18, [19], 18), ("gte", 18, [18], 17),
            ("lt", 18, [17], 18), ("lte", 18, [18], 19), ("between", [18, 60], [18, 60], 17),
        ]:
            with self.subTest(operator=operator):
                body = self.form(multiple=True)
                q = body["questions"][3]
                q["logic"] = {"rules": [{"id": "r", "condition": {"operator": operator, "value": threshold}, "target": "END"}], "default_target": "NEXT"}
                text = body["questions"][2]; text["required"] = True
                body["questions"] = [q, text]
                survey = self.publish(body)
                for value in hits:
                    result = self.submit(survey, {"attempt_id": str(uuid4()), "answers": [{"question_id": "q4", "value": value}]})
                    self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(self.submit(survey, {"attempt_id": str(uuid4()), "answers": [{"question_id": "q4", "value": miss}]}).status_code, 422)

    def test_blank_optional_answer_uses_default_not_rules(self):
        body = self.form()
        body["questions"][0]["required"] = False
        body["questions"][0]["logic"]["rules"] = [{"id": "r", "condition": {"operator": "eq", "value": "yes"}, "target": "END"}]
        survey = self.publish(body)
        self.assertEqual(self.submit(survey, {"attempt_id": str(uuid4()), "answers": []}).status_code, 422)
        payload = self.payload(); payload["answers"] = [a for a in payload["answers"] if a["question_id"] != "q1"]
        self.assertEqual(self.submit(survey, payload).status_code, 200)

    def test_anonymity_policy_and_author_record_filtering(self):
        survey = self.publish(self.form(anonymous=False))
        self.assertEqual(self.submit(survey, self.payload(anonymous=True)).status_code, 422)
        survey = self.publish()
        self.assertEqual(self.submit(survey, self.payload(anonymous=True)).status_code, 200)
        records = self.author.get(f"/api/surveys/{survey['id']}/responses").json()
        item = records["items"][0]
        self.assertEqual(item["respondent_name"], "匿名")
        for field in ["respondent_id", "attempt_key", "username"]: self.assertNotIn(field, item)
        self.assertNotIn(self.person_user["username"], str(records))

    def test_once_idempotence_and_cannot_overwrite(self):
        survey = self.publish()
        body = self.payload(multi=["a", "b"])
        first = self.submit(survey, body).json()
        body["attempt_id"] = str(uuid4()); body["answers"][1]["value"] = ["b", "a"]
        retry = self.submit(survey, body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(retry.json()["reused"])
        self.assertEqual(first["id"], retry.json()["id"])
        self.assertEqual(self.submit(survey, self.payload(numeric=21)).status_code, 409)
        self.assertEqual(self.count(survey), 1)

    def test_multiple_attempts_distinct_and_retry_unique(self):
        survey = self.publish(self.form(multiple=True))
        body = self.payload()
        self.assertEqual(self.submit(survey, body).status_code, 200)
        self.assertTrue(self.submit(survey, body).json()["reused"])
        self.assertEqual(self.submit(survey, self.payload(numeric=21)).status_code, 200)
        self.assertEqual(self.count(survey), 2)
        self.assertTrue(self.person.get(f"/api/public/surveys/{survey['share_code']}").json()["can_submit"])

    def test_concurrent_once_conflicting_answers_save_one(self):
        survey = self.publish()
        barrier = Barrier(2)
        def submit(value):
            barrier.wait(timeout=5)
            return self.submit(survey, self.payload(numeric=value)).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(submit, [20, 21]))
        self.assertCountEqual(statuses, [200, 409])
        self.assertEqual(self.count(survey), 1)

    def test_concurrent_same_retry_saved_once(self):
        survey = self.publish(self.form(multiple=True))
        body = self.payload(); barrier = Barrier(2)
        def submit(_):
            barrier.wait(timeout=5)
            return self.submit(survey, body).json()
        with ThreadPoolExecutor(max_workers=2) as executor: results = list(executor.map(submit, range(2)))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertCountEqual([r["reused"] for r in results], [False, True])
        self.assertEqual(self.count(survey), 1)

    def test_different_people_can_submit_concurrently(self):
        other, _ = self.new_client("other_")
        survey = self.publish(); barrier = Barrier(2)
        def submit(client):
            barrier.wait(timeout=5)
            return self.submit(survey, client=client).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(list(executor.map(submit, [self.person, other])), [200, 200])
        self.assertEqual(self.count(survey), 2)

    def test_draft_closed_expired_and_successful_retry_after_close(self):
        draft = self.author.post("/api/surveys", json=self.form()).json()
        self.assertEqual(self.submit(draft).status_code, 404)
        survey = self.publish(); body = self.payload()
        saved = self.submit(survey, body).json()
        self.author.post(f"/api/surveys/{survey['id']}/close")
        self.assertEqual(self.submit(survey, body).json()["id"], saved["id"])
        other, _ = self.new_client("later_")
        self.assertEqual(self.submit(survey, client=other).status_code, 410)
        survey = self.publish()
        self.db.surveys.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"settings.expires_at": utcnow() - timedelta(seconds=1)}})
        self.assertEqual(self.submit(survey).status_code, 410)
        self.assertEqual(self.count(survey), 0)

    def test_statistics_and_records_require_author(self):
        survey = self.publish()
        for suffix in ["statistics", "statistics/q1", "responses"]:
            self.assertEqual(self.person.get(f"/api/surveys/{survey['id']}/{suffix}").status_code, 404)
        anonymous_client = self.enterContext(TestClient(create_app(self.settings)))
        self.assertEqual(self.submit(survey, client=anonymous_client).status_code, 401)

    def test_empty_statistics_zero_options_and_null_average(self):
        survey = self.publish()
        stats = self.author.get(f"/api/surveys/{survey['id']}/statistics").json()
        self.assertEqual(stats["response_count"], 0)
        self.assertEqual(stats["participant_count"], 0)
        self.assertEqual([o["count"] for o in stats["questions"][0]["options"]], [0, 0])
        self.assertIsNone(stats["questions"][3]["average"])
        self.assertEqual(self.author.get(f"/api/surveys/{survey['id']}/statistics/missing").status_code, 404)

    def test_live_statistics_people_counts_choices_text_and_average(self):
        other, other_user = self.new_client("anonymous_other_")
        content = self.form(multiple=True)
        content["questions"][0]["options"].append({"id": "other", "label": "其他"})
        survey = self.publish(content)
        for client, body in [
            (self.person, self.payload(numeric=0, multi=["a", "b"], text="第一份建议", anonymous=True)),
            (self.person, self.payload(numeric=20, choice="no", text="第二份建议")),
            (other, self.payload(numeric=40, multi=["b"], text=None, anonymous=True)),
        ]:
            self.assertEqual(self.submit(survey, body, client).status_code, 200)
        stats = self.author.get(f"/api/surveys/{survey['id']}/statistics").json()
        self.assertEqual((stats["response_count"], stats["participant_count"]), (3, 2))
        single, multi, text, numeric = stats["questions"]
        self.assertEqual(single["answered_count"], 3)
        self.assertEqual([(o["count"], o["people_count"]) for o in single["options"]], [(2, 2), (1, 1), (0, 0)])
        self.assertEqual([o["count"] for o in multi["options"]], [2, 2])
        self.assertEqual(text["answered_count"], 2)
        self.assertEqual({a["value"] for a in text["answers"]}, {"第一份建议", "第二份建议"})
        self.assertEqual(numeric["average"], 20)
        records = self.author.get(f"/api/surveys/{survey['id']}/responses").json()
        self.assertEqual(records["total"], 3)
        self.assertNotIn(other_user["username"], str(records))
        named = [r for r in records["items"] if not r["is_anonymous"]]
        self.assertEqual(named[0]["respondent_name"], self.person_user["username"])
        question = self.author.get(f"/api/surveys/{survey['id']}/statistics/q4").json()
        self.assertEqual(question["average"], numeric["average"])
        self.submit(survey, self.payload(numeric=60))
        self.assertEqual(self.author.get(f"/api/surveys/{survey['id']}/statistics").json()["response_count"], 4)

    def test_skipped_questions_excluded_from_denominators(self):
        survey = self.publish(self.form(jumps=True))
        body = self.payload(choice="no")
        body["answers"] = [a for a in body["answers"] if a["question_id"] != "q2"]
        self.assertEqual(self.submit(survey, body).status_code, 200)
        q2 = self.author.get(f"/api/surveys/{survey['id']}/statistics/q2").json()
        self.assertEqual(q2["answered_count"], 0)
        self.assertEqual([o["count"] for o in q2["options"]], [0, 0])

    def test_all_text_contents_and_record_pagination(self):
        survey = self.publish(self.form(multiple=True))
        for index in range(23):
            self.assertEqual(self.submit(survey, self.payload(text=f"测试内容 {index:02}")).status_code, 200)
        values = []
        for offset in [0, 10, 20]:
            data = self.author.get(f"/api/surveys/{survey['id']}/statistics/q3?offset={offset}&limit=10").json()
            self.assertEqual(data["answered_count"], 23)
            values.extend(a["value"] for a in data["answers"])
        self.assertEqual(len(set(values)), 23)
        records = self.author.get(f"/api/surveys/{survey['id']}/responses?offset=20&limit=10").json()
        self.assertEqual((records["total"], len(records["items"])), (23, 3))


if __name__ == "__main__":
    unittest.main()
