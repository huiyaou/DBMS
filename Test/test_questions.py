"""题目复用、权限、版本及统计的真实数据库测试。"""
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from Backend.config import DatabaseSettings
from Backend.database import create_client, check_connection
from Backend.main import create_app


class QuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mongo = create_client()
        cls.addClassCleanup(cls.mongo.close)
        check_connection(cls.mongo)
        cls.name = 'survey_questions_test_' + uuid4().hex
        cls.addClassCleanup(cls.mongo.drop_database, cls.name)
        cls.settings = DatabaseSettings(database_name=cls.name)

    def setUp(self):
        self.a = self.enterContext(TestClient(create_app(self.settings)))
        self.b = self.enterContext(TestClient(create_app(self.settings)))
        self.aname, self.bname = 'a' + uuid4().hex, 'b' + uuid4().hex
        for client, name in [(self.a, self.aname), (self.b, self.bname)]:
            self.assertEqual(client.post('/api/auth/register', json={'username': name, 'password': 'password123'}).status_code, 201)
        self.content = {'id':'q1', 'type':'number', 'title':'年龄', 'required':True, 'validation': {'min_value':0, 'max_value':120, 'integer_only':True}, 'logic': {'rules':[], 'default_target':'NEXT'}}

    def new_question(self, title='年龄'):
        response = self.a.post('/api/questions', json={'content': {**self.content, 'title': title}})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def new_survey(self, title='目标问卷'):
        response = self.a.post('/api/surveys', json={'title': title})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def append(self, survey, version, client=None):
        return (client or self.a).post(f"/api/surveys/{survey['id']}/questions", json={'question_id':version['question_id'], 'version_id':version['id'], 'draft_revision':survey['draft_revision']})

    def test_append_to_draft_and_published_keeps_old_questions_and_answers(self):
        v1 = self.new_question()
        survey = self.append(self.new_survey(), v1).json()
        published = self.a.post(f"/api/surveys/{survey['id']}/publish", json={'draft_revision':survey['draft_revision']}).json()
        old = deepcopy(published['questions'])
        submitted = self.b.post(f"/api/public/surveys/{survey['share_code']}/responses", json={'attempt_id':str(uuid4()), 'is_anonymous':False, 'answers':[{'question_id':old[0]['id'], 'value':20}]})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        v2 = self.new_question('身高')
        appended = self.append(published, v2)
        self.assertEqual(appended.status_code, 200, appended.text)
        self.assertEqual(appended.json()['status'], 'published')
        self.assertEqual(appended.json()['questions'][:-1], old)
        self.assertEqual(len(appended.json()['questions']), 2)
        self.assertFalse(appended.json()['questions'][-1]['required'])
        original_answers = self.a.get(f"/api/surveys/{survey['id']}/statistics").json()
        self.assertEqual(original_answers['response_count'], 1)
        self.assertEqual(original_answers['questions'][0]['average'], 20)
        self.assertEqual(original_answers['questions'][1]['answered_count'], 0)
        # 普通保存接口不能绕过发布后的原题保护。
        changed = appended.json()
        changed['questions'][0]['title'] = '篡改'
        body = {k:changed[k] for k in ('title','description','settings','questions','draft_revision')}
        self.assertIn(self.a.put(f"/api/surveys/{survey['id']}", json=body).status_code, (409,422))

    def test_append_rejects_duplicate_family_closed_foreign_and_stale(self):
        v1=self.new_question()
        survey=self.append(self.new_survey(),v1).json()
        v2=self.a.post(f"/api/questions/{v1['question_id']}/versions",json={'parent_id':v1['id'],'content':{**self.content,'validation':{'min_value':0,'max_value':150,'integer_only':True}}}).json()
        self.assertEqual(self.append(survey,v2).status_code,409)
        fresh=self.new_question('收入')
        self.assertEqual(self.append(survey,fresh,self.b).status_code,404)
        stale={**survey,'draft_revision':1}
        self.assertEqual(self.append(stale,fresh).status_code,409)
        self.a.post(f"/api/surveys/{survey['id']}/publish",json={'draft_revision':survey['draft_revision']})
        closed=self.a.post(f"/api/surveys/{survey['id']}/close").json()
        self.assertEqual(self.append(closed,fresh).status_code,409)

    def test_edit_any_version_and_delete_preserves_published_snapshot(self):
        v1=self.new_question()
        survey=self.append(self.new_survey(),v1).json()
        self.a.post(f"/api/surveys/{survey['id']}/publish",json={'draft_revision':survey['draft_revision']})
        qid=v1['question_id']
        v2=self.a.post(f'/api/questions/{qid}/versions',json={'parent_id':v1['id'],'content':{**self.content,'validation':{'min_value':0,'max_value':100,'integer_only':True}}}).json()
        v3=self.a.post(f'/api/questions/{qid}/versions',json={'parent_id':v1['id'],'content':{**self.content,'validation':{'min_value':0,'max_value':80,'integer_only':True}}}).json()
        self.assertEqual(v3['parent_id'],v1['id'])
        self.assertNotEqual(v3['id'],v2['id'])
        self.assertEqual(self.b.delete(f"/api/questions/{qid}/versions/{v1['id']}").status_code,404)
        self.assertEqual(self.a.delete(f"/api/questions/{qid}/versions/{v1['id']}").status_code,204)
        listed=self.a.get('/api/questions').json()[0]['versions']
        self.assertTrue(listed[0]['archived'])
        self.assertEqual([v['number'] for v in listed],[0,1,2])
        self.assertEqual(self.a.get(f"/api/surveys/{survey['id']}").json()['questions'][0]['title'],'年龄')
        self.assertEqual(self.append(self.new_survey(),v1).status_code,404)
        self.assertEqual(self.a.delete(f'/api/questions/{qid}').status_code,204)
        self.assertEqual(self.a.get('/api/questions').json(),[])
        self.assertEqual(self.a.get(f"/api/public/surveys/{survey['share_code']}").status_code,200)

    def test_concurrent_append_uses_revision_without_overwriting(self):
        survey=self.new_survey()
        versions=[self.new_question('题目一'),self.new_question('题目二')]
        # 两个同账号客户端携带相同修订号，同时追加不同题目。
        self.b.post('/api/auth/login',json={'username':self.aname,'password':'password123'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.append,survey,versions[0],self.a),pool.submit(self.append,survey,versions[1],self.b)]
            codes=sorted(f.result().status_code for f in futures)
        self.assertEqual(codes,[200,409])
        self.assertEqual(len(self.a.get(f"/api/surveys/{survey['id']}").json()['questions']),1)

    def test_delete_library_question_and_version_only_removes_bank_entries(self):
        original=self.new_question()
        qid=original['question_id']
        next_version=self.a.post(f'/api/questions/{qid}/versions',json={'parent_id':original['id'],'content':{**self.content,'validation':{'min_value':0,'max_value':150,'integer_only':True}}}).json()
        draft=self.append(self.new_survey('保留的草稿'),original).json()
        published=self.append(self.new_survey('保留的发布问卷'),next_version).json()
        published=self.a.post(f"/api/surveys/{published['id']}/publish",json={'draft_revision':published['draft_revision']}).json()
        submitted=self.b.post(f"/api/public/surveys/{published['share_code']}/responses",json={'attempt_id':str(uuid4()),'is_anonymous':False,'answers':[{'question_id':published['questions'][0]['id'],'value':25}]})
        self.assertEqual(submitted.status_code,200,submitted.text)
        bank_ids=[]
        for v in (original,next_version):
            bank=self.a.post('/api/banks',json={'name':'版本题库'}).json()
            bank_ids.append(bank['id'])
            self.assertEqual(self.a.put(f"/api/banks/{bank['id']}/items",json={'question_id':qid,'version_id':v['id']}).status_code,200)
        # 仅移除指定版本及题库中的该版本，其他版本仍可用。
        for _ in range(2):
            self.assertEqual(self.a.delete(f"/api/questions/{qid}/versions/{original['id']}").status_code,204)
        banks={b['id']:b for b in self.a.get('/api/banks').json()}
        self.assertEqual(banks[bank_ids[0]]['items'],[])
        self.assertEqual(banks[bank_ids[1]]['items'][0]['version_id'],next_version['id'])
        self.assertEqual(self.a.get(f"/api/surveys/{draft['id']}").json()['questions'],draft['questions'])
        # 整题删除及重复请求均成功，不删除任一问卷中的复用快照。
        for _ in range(2):
            self.assertEqual(self.a.delete(f'/api/questions/{qid}').status_code,204)
        self.assertEqual(self.a.get('/api/questions').json(),[])
        self.assertTrue(all(not b['items'] for b in self.a.get('/api/banks').json()))
        for survey in (draft,published):
            self.assertEqual(self.a.get(f"/api/surveys/{survey['id']}").json()['questions'],survey['questions'])
        stats=self.a.get(f"/api/surveys/{published['id']}/statistics").json()
        self.assertEqual(stats['response_count'],1)
        self.assertEqual(stats['questions'][0]['average'],25)

    def test_new_version_keeps_title_and_allows_type_options_changes(self):
        original=self.new_question()
        path=f"/api/questions/{original['question_id']}/versions"
        renamed=self.a.post(path,json={'parent_id':original['id'],'content':{**self.content,'title':'其他标题'}})
        self.assertEqual(renamed.status_code,422)
        changed={**self.content,'type':'single_choice','options':[{'id':'young','label':'18 岁以下'},{'id':'adult','label':'18 岁及以上'}],'validation':{}}
        saved=self.a.post(path,json={'parent_id':original['id'],'content':changed})
        self.assertEqual(saved.status_code,201,saved.text)
        self.assertEqual(saved.json()['content']['title'],original['content']['title'])
        self.assertEqual(saved.json()['content']['type'],'single_choice')
        listing=self.a.get('/api/questions').json()[0]['versions']
        self.assertEqual([v['number'] for v in listing],[0,1])
        self.assertEqual(listing[0]['content']['type'],'number')
        self.assertEqual(len(listing),2)  # 标题篡改请求没有创建版本。

    def test_versions_sharing_banks_snapshot_and_statistics(self):
        response = self.a.post('/api/questions', json={'content':self.content})
        self.assertEqual(response.status_code, 201, response.text)
        v1 = response.json(); qid, vid = v1['question_id'], v1['id']
        self.assertEqual(self.b.get('/api/questions').json(), [])
        self.assertEqual(self.a.post(f'/api/questions/{qid}/share', json={'username':self.bname}).status_code, 204)
        self.assertEqual(len(self.b.get('/api/questions').json()), 1)
        updated = {**self.content, 'validation':{'min_value':0,'max_value':150,'integer_only':True}}
        v2 = self.b.post(f'/api/questions/{qid}/versions', json={'parent_id':vid, 'content':updated})
        self.assertEqual(v2.status_code, 201, v2.text)
        self.assertEqual(v2.json()['parent_id'], vid)
        bank = self.b.post('/api/banks', json={'name':'常用题'}).json()
        self.assertEqual(self.b.put(f"/api/banks/{bank['id']}/items", json={'question_id':qid,'version_id':vid}).status_code, 200)
        self.assertEqual(self.b.get('/api/banks').json()[0]['items'][0]['version_id'], vid)
        q = {**v1['content'], 'id':'age', 'required':True, 'source_question_id':qid, 'source_version_id':vid}
        survey = self.a.post('/api/surveys', json={'title':'测试', 'questions':[q]} )
        self.assertEqual(survey.status_code, 201, survey.text)
        s = survey.json()
        self.assertEqual(self.a.post(f"/api/surveys/{s['id']}/publish", json={'draft_revision':1}).status_code, 200)
        forged = {**q, 'title':'篡改题目'}
        self.assertEqual(self.a.post('/api/surveys', json={'title':'错误', 'questions':[forged]}).status_code, 422)
        result = self.b.post(f"/api/public/surveys/{s['share_code']}/responses", json={'attempt_id':str(uuid4()), 'is_anonymous':False, 'answers':[{'question_id':'age','value':0}]})
        self.assertIn(result.status_code, (200,201), result.text)
        stats = self.a.get(f'/api/questions/{qid}/versions/{vid}/statistics').json()
        self.assertEqual((stats['survey_count'],stats['answered_count'],stats['average']), (1,1,0))
        self.assertEqual(self.b.get(f'/api/questions/{qid}/versions/{vid}/statistics').json()['answered_count'], 0)
        self.assertEqual(self.a.get(f'/api/surveys/{s["id"]}').json()['questions'][0]['title'], '年龄')


if __name__ == '__main__':
    unittest.main()
