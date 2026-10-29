"""注册登录与问卷管理的真实 MongoDB + HTTP 接口测试。"""

from copy import deepcopy
from datetime import timedelta
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from Backend.config import DatabaseSettings
from Backend.database import check_connection, create_client
from Backend.main import create_app
from Backend.security import COOKIE_NAME, token_hash, utcnow
from test_mongodb import make_survey


PASSWORD = "test-password-123"


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mongo = create_client()
        cls.addClassCleanup(cls.mongo.close)
        check_connection(cls.mongo)
        name = f"survey_system_api_test_{uuid4().hex}"
        if name in cls.mongo.list_database_names():
            raise RuntimeError("临时数据库已存在，停止测试")
        cls.addClassCleanup(cls.mongo.drop_database, name)
        cls.settings = DatabaseSettings(database_name=name)
        cls.db = cls.mongo[name]

    def setUp(self):
        self.client = self.enterContext(TestClient(create_app(self.settings)))
        self.other = self.enterContext(TestClient(create_app(self.settings)))
        self.username = "User_" + uuid4().hex[:12]
        response = self.client.post("/api/auth/register", json={"username": self.username, "password": PASSWORD})
        self.assertEqual(response.status_code, 201, response.text)
        self.user = response.json()

    def create_survey(self, content=None):
        response = self.client.post("/api/surveys", json=content or {})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def complete_content(self):
        fixture = make_survey(None)
        return {key: fixture[key] for key in ("title", "description", "settings", "questions")}

    def test_registration_hash_cookie_and_private_fields(self):
        self.assertNotIn("password", self.user)
        self.assertNotIn("password_hash", self.user)
        stored = self.db.users.find_one({"username_key": self.username.casefold()})
        self.assertTrue(stored["password_hash"].startswith("$argon2"))
        token = self.client.cookies.get(COOKIE_NAME)
        session = self.db.sessions.find_one({"token_hash": token_hash(token)})
        self.assertIsNotNone(session)
        self.assertNotIn("token", session)
        self.assertEqual(self.client.get("/api/auth/me").json()["id"], self.user["id"])
        result = self.other.post("/api/auth/login", json={"username": self.username, "password": PASSWORD})
        cookie = result.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_username_normalization_duplicate_and_login(self):
        duplicate = self.other.post("/api/auth/register", json={"username": "  " + self.username.upper() + "  ", "password": PASSWORD})
        self.assertEqual(duplicate.status_code, 409)
        login = self.other.post("/api/auth/login", json={"username": self.username.upper(), "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["id"], self.user["id"])

    def test_bad_credentials_and_invalid_registration(self):
        for username, password in [(self.username, "wrong-password"), ("missing_" + uuid4().hex, PASSWORD)]:
            with self.subTest(username=username):
                response = self.other.post("/api/auth/login", json={"username": username, "password": password})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "用户名或密码错误")
        for username, password in [("   ", PASSWORD), ("new-user", "short"), ("a\u0000b", PASSWORD)]:
            with self.subTest(username=username):
                self.assertEqual(self.other.post("/api/auth/register", json={"username": username, "password": password}).status_code, 422)

    def test_logout_revokes_copied_cookie(self):
        copied = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.other.cookies.set(COOKIE_NAME, copied)
        self.assertEqual(self.other.get("/api/auth/me").status_code, 401)

    def test_expired_session_rejected_before_ttl_cleanup(self):
        token = self.client.cookies.get(COOKIE_NAME)
        self.db.sessions.update_one({"token_hash": token_hash(token)}, {"$set": {"expires_at": utcnow() - timedelta(seconds=1)}})
        self.assertEqual(self.client.get("/api/surveys").status_code, 401)

    def test_unauthenticated_access_and_cross_site_writes(self):
        self.assertEqual(self.other.get("/api/surveys").status_code, 401)
        self.assertEqual(self.other.post("/api/surveys", json={}).status_code, 401)
        response = self.client.post("/api/surveys", json={}, headers={"Origin": "https://another.example"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_create_list_and_owner_isolation(self):
        survey = self.create_survey()
        listing = self.client.get("/api/surveys").json()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["counts"]["draft"], 1)
        self.assertEqual(listing["items"][0]["id"], survey["id"])
        self.other.post("/api/auth/register", json={"username": "Other_" + uuid4().hex, "password": PASSWORD})
        self.assertEqual(self.other.get("/api/surveys").json()["total"], 0)
        for method, path, body in [
            ("GET", "", None), ("PUT", "", {**self.complete_content(), "draft_revision": 1}),
            ("POST", "/publish", {"draft_revision": 1}), ("POST", "/close", None),
            ("PATCH", "/deadline", {"expires_at": None}),
        ]:
            with self.subTest(method=method, path=path):
                result = self.other.request(method, f"/api/surveys/{survey['id']}{path}", json=body)
                self.assertEqual(result.status_code, 404)

    def test_save_and_stale_revision_protection(self):
        survey = self.create_survey()
        body = {**self.complete_content(), "draft_revision": 1}
        result = self.client.put(f"/api/surveys/{survey['id']}", json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["draft_revision"], 2)
        self.assertEqual(result.json()["questions"][0]["id"], "q1")
        body["title"] = "来自旧页面的覆盖"
        self.assertEqual(self.client.put(f"/api/surveys/{survey['id']}", json=body).status_code, 409)
        self.assertNotEqual(self.client.get(f"/api/surveys/{survey['id']}").json()["title"], body["title"])
        self.assertEqual(self.client.post(f"/api/surveys/{survey['id']}/publish", json={"draft_revision": 1}).status_code, 409)

    def test_publish_requires_title_questions_and_complete_options(self):
        for mutation in ["title", "questions", "question_title", "options", "labels"]:
            with self.subTest(mutation=mutation):
                body = self.complete_content()
                if mutation == "title": body["title"] = "   "
                if mutation == "questions": body["questions"] = []
                if mutation == "question_title": body["questions"][0]["title"] = ""
                if mutation == "options": body["questions"][0]["options"] = body["questions"][0]["options"][:1]; body["questions"][0]["logic"]["rules"] = []
                if mutation == "labels": body["questions"][0]["options"][0]["label"] = " "
                survey = self.create_survey(body)
                response = self.client.post(f"/api/surveys/{survey['id']}/publish", json={"draft_revision": 1})
                self.assertEqual(response.status_code, 422, response.text)

    def test_bad_ids_ranges_and_references_rejected_without_write(self):
        for mutation in ["duplicate_question", "duplicate_option", "backward", "unknown_target", "unknown_option", "reversed_range", "bad_between", "repeated_rule", "huge_number"]:
            with self.subTest(mutation=mutation):
                body = self.complete_content()
                if mutation == "duplicate_question": body["questions"][1]["id"] = "q1"
                if mutation == "duplicate_option": body["questions"][0]["options"][1]["id"] = "yes"
                if mutation == "backward": body["questions"][3]["logic"]["default_target"] = "q1"
                if mutation == "unknown_target": body["questions"][0]["logic"]["rules"][0]["target"] = "missing"
                if mutation == "unknown_option": body["questions"][0]["logic"]["rules"][0]["condition"]["value"] = "missing"
                if mutation == "reversed_range": body["questions"][1]["validation"] = {"min_choices": 3, "max_choices": 1}
                if mutation == "bad_between": body["questions"][3]["logic"]["rules"][1]["condition"]["value"] = [60, 18]
                if mutation == "repeated_rule": body["questions"][3]["logic"]["rules"][1]["id"] = "r3"
                if mutation == "huge_number": body["questions"][3]["validation"]["max_value"] = 10 ** 100
                response = self.client.post("/api/surveys", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/surveys").json()["total"], 0)

    def test_publish_rejects_impossible_validation(self):
        for mutation in ["too_many", "zero_required", "no_integer", "past_deadline"]:
            with self.subTest(mutation=mutation):
                body = self.complete_content()
                if mutation == "too_many": body["questions"][1]["validation"] = {"max_choices": 3}
                if mutation == "zero_required": body["questions"][1]["validation"] = {"max_choices": 0}
                if mutation == "no_integer": body["questions"][3]["validation"] = {"integer_only": True, "min_value": 0.1, "max_value": 0.9}
                if mutation == "past_deadline": body["settings"]["expires_at"] = (utcnow() - timedelta(days=1)).isoformat()
                survey = self.create_survey(body)
                self.assertEqual(self.client.post(f"/api/surveys/{survey['id']}/publish", json={"draft_revision": 1}).status_code, 422)

    def test_publish_freeze_preview_and_close(self):
        content = self.complete_content()
        survey = self.create_survey(content)
        path = f"/api/surveys/{survey['id']}"
        self.assertEqual(self.client.get(f"/api/public/surveys/{survey['share_code']}").status_code, 404)
        published = self.client.post(path + "/publish", json={"draft_revision": 1})
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "published")
        self.assertEqual(self.client.put(path, json={**content, "draft_revision": 1}).status_code, 409)
        self.assertEqual(self.client.post(path + "/publish", json={"draft_revision": 1}).status_code, 409)
        public = f"/api/public/surveys/{survey['share_code']}"
        self.assertEqual(self.other.get(public).status_code, 401)
        preview = self.client.get(public)
        self.assertEqual(preview.status_code, 200)
        self.assertNotIn("owner_id", preview.json())
        self.assertEqual(len(preview.json()["questions"]), 4)
        self.assertEqual(self.client.post(path + "/close").json()["status"], "closed")
        self.assertEqual(self.client.get(public).status_code, 410)
        self.assertEqual(self.client.post(path + "/close").status_code, 200)
        self.assertEqual(self.client.patch(path + "/deadline", json={"expires_at": None}).status_code, 409)

    def test_deadline_change_expiry_and_timezone(self):
        survey = self.create_survey(self.complete_content())
        path = f"/api/surveys/{survey['id']}"
        self.client.post(path + "/publish", json={"draft_revision": 1})
        future = (utcnow() + timedelta(days=1)).isoformat()
        self.assertEqual(self.client.patch(path + "/deadline", json={"expires_at": future}).status_code, 200)
        self.assertEqual(self.client.patch(path + "/deadline", json={"expires_at": "2030-01-01T12:00:00"}).status_code, 422)
        from bson import ObjectId
        self.db.surveys.update_one({"_id": ObjectId(survey["id"])}, {"$set": {"settings.expires_at": utcnow() - timedelta(seconds=1)}})
        self.assertEqual(self.client.get(f"/api/public/surveys/{survey['share_code']}").status_code, 410)
        result = self.client.get("/api/surveys?status=expired").json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["effective_status"], "expired")
        self.assertEqual(self.client.patch(path + "/deadline", json={"expires_at": None}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/public/surveys/{survey['share_code']}").status_code, 200)

    def test_extra_fields_invalid_id_and_draft_close(self):
        self.assertEqual(self.client.post("/api/surveys", json={"owner_id": self.user["id"]}).status_code, 422)
        self.assertEqual(self.client.get("/api/surveys/not-an-id").status_code, 404)
        survey = self.create_survey()
        self.assertEqual(self.client.post(f"/api/surveys/{survey['id']}/close").status_code, 409)

    def test_frontend_and_health_are_served(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        for path in ["/", "/survey/example", "/assets/app.js", "/assets/styles.css"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertIn("no-store", self.client.get("/api/auth/me").headers["cache-control"])


if __name__ == "__main__":
    unittest.main()
