import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.payloads: list[str] = []

    def create(self, **kwargs):
        self.payloads.append(kwargs["messages"][-1]["content"])
        return _FakeResponse(self.content)


class _FakeClient:
    def __init__(self, content: str):
        self.completions = _FakeCompletions(content)
        self.chat = self


class SchoolBriefTests(unittest.TestCase):
    def setUp(self):
        self.llm = patch.object(llm, "_get_client", return_value=None)
        self.llm.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.llm.stop()

    def _graded_school(self) -> dict:
        listed = self.client.get("/api/schools", params={"category": "public", "fl_grade": "A", "limit": 1})
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertTrue(items)
        return items[0]

    def test_ask_describes_the_school_without_a_model(self):
        school = self._graded_school()
        response = self.client.post(f"/api/schools/{school['id']}/ask", json={"lat": 25.76, "lon": -80.25})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["school_id"], school["id"])
        self.assertFalse(body["llm_used"])
        self.assertIn(school["name"], body["answer"])
        self.assertIn(school["fl_grade"], body["answer"])
        self.assertIn("miles from your location", body["answer"])
        self.assertIn("tuition-free", body["answer"])

    def test_missing_school_is_not_found(self):
        response = self.client.post("/api/schools/999999999/ask", json={})
        self.assertEqual(response.status_code, 404, response.text)

    def test_ask_uses_the_model_when_it_returns_a_profile(self):
        school = self._graded_school()
        fake = _FakeClient('{"answer": "Coral Reef is a public high school in Miami with a published A grade."}')
        with patch.object(llm, "_get_client", return_value=fake):
            response = self.client.post(f"/api/schools/{school['id']}/ask", json={})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["llm_used"])
        self.assertIn("Coral Reef", body["answer"])
        self.assertIn(school["name"], fake.completions.payloads[0])
        self.assertNotIn("Tell me about", body["answer"])
