import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import sessions
from app.main import app
from app.services import llm
from app.services.geocode import _offline


class RecommendSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(sessions, "SESSIONS_PATH", Path(self.tmp.name) / "sessions.db"),
            patch.object(llm, "_get_client", return_value=None),
            patch("app.routers.recommend.geocode", side_effect=_offline),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_turn_merges_prefs_and_restores_session(self):
        first = self.client.post(
            "/api/recommend",
            json={"message": "We live in Coral Gables and have a 7-year-old. Looking for a small school with strong academics, ideally bilingual, within 3 miles."},
        )
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        sid = body["session_id"]
        self.assertEqual(body["preferences"]["location_text"], "coral gables")
        self.assertEqual(body["preferences"]["child_grades"], [2])
        self.assertEqual(body["preferences"]["radius_miles"], 3)
        self.assertIn("Bilingual", body["preferences"]["keywords"])
        self.assertIsNone(body["groups"])
        self.assertTrue(body["results"])
        self.assertTrue(all(2 in (s.get("serves_grades") or []) for s in body["results"]))

        second = self.client.post(
            "/api/recommend",
            json={"session_id": sid, "message": "also a kindergartner"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        follow = second.json()
        self.assertEqual(follow["session_id"], sid)
        self.assertEqual(follow["preferences"]["child_grades"], [0, 2])
        self.assertEqual(follow["preferences"]["location_text"], "coral gables")
        self.assertEqual(follow["preferences"]["radius_miles"], 3)
        self.assertIn("Bilingual", follow["preferences"]["keywords"])
        self.assertIsNone(follow["groups"])
        for school in follow["results"]:
            self.assertLessEqual(school["grade_low"], 0)
            self.assertGreaterEqual(school["grade_high"], 2)

        stored = self.client.get(f"/api/sessions/{sid}")
        self.assertEqual(stored.status_code, 200, stored.text)
        state = stored.json()
        self.assertEqual([m["content"] for m in state["messages"]], [
            "We live in Coral Gables and have a 7-year-old. Looking for a small school with strong academics, ideally bilingual, within 3 miles.",
            body["summary"] + (f"\n\n{body['follow_up']}" if body["follow_up"] else ""),
            "also a kindergartner",
            follow["summary"] + (f"\n\n{follow['follow_up']}" if follow["follow_up"] else ""),
        ])
        self.assertEqual(state["preferences"]["child_grades"], [0, 2])
        self.assertIsNotNone(state["recommendation"])
        self.assertIsNotNone(body["origin"])
        self.assertEqual(len(body["origin"]), 2)
        self.assertEqual(body["origin_label"], "Coral Gables")
        self.assertIsNone(state["origin"])
        self.assertIsNone(state["origin_label"])
        self.assertIsNone(state["recommendation"]["origin"])

        gone = self.client.delete(f"/api/sessions/{sid}")
        self.assertEqual(gone.status_code, 204)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").status_code, 404)

    def test_disjoint_children_come_back_as_groups(self):
        res = self.client.post(
            "/api/recommend",
            json={"message": "My 18-month-old and a 10th grader, public or charter, near 33156"},
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual([c["grade"] for c in body["preferences"]["children"]], [-2, 10])
        self.assertEqual([g["grade"] for g in body["groups"]], [-2, 10])
        self.assertTrue(body["groups"][0]["results"])
        self.assertTrue(body["groups"][1]["results"])
        self.assertTrue(body["results"])

    def test_origin_persists_only_with_consent(self):
        remembered = self.client.post(
            "/api/recommend",
            json={
                "message": "a small public school",
                "origin": [25.75, -80.26],
                "origin_label": "Current location",
                "remember_location": True,
            },
        )
        self.assertEqual(remembered.status_code, 200, remembered.text)
        body = remembered.json()
        sid = body["session_id"]
        self.assertEqual(body["origin"], [25.75, -80.26])
        self.assertEqual(body["origin_label"], "Current location")
        self.assertIsNone(body["preferences"].get("radius_miles"))
        stored = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(stored["origin"], [25.75, -80.26])
        self.assertEqual(stored["origin_label"], "Current location")

        ranked = self.client.post(
            "/api/recommend",
            json={
                "session_id": sid,
                "message": "with strong academics",
                "origin": [25.75, -80.26],
                "origin_label": "Current location",
                "radius_miles": 5,
            },
        )
        self.assertEqual(ranked.status_code, 200, ranked.text)
        follow = ranked.json()
        self.assertEqual(follow["origin"], [25.75, -80.26])
        self.assertIsNone(follow["preferences"].get("radius_miles"))
        self.assertTrue(follow["results"])
        self.assertTrue(all(school["distance_miles"] is not None and school["distance_miles"] <= 5 for school in follow["results"]))
        cleared = self.client.get(f"/api/sessions/{sid}").json()
        self.assertIsNone(cleared["origin"])
        self.assertIsNone(cleared["origin_label"])
        self.assertIsNone(cleared["recommendation"]["origin"])

        again = self.client.post(
            "/api/recommend",
            json={
                "session_id": sid,
                "message": "still looking",
                "origin": [25.72, -80.27],
                "origin_label": "Coral Gables",
                "remember_location": True,
                "radius_miles": 5,
            },
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertIsNone(again.json()["preferences"].get("radius_miles"))
        kept = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(kept["origin"], [25.72, -80.27])
        self.assertEqual(kept["origin_label"], "Coral Gables")
        self.assertEqual(kept["recommendation"]["origin"], [25.72, -80.27])

        forgotten = self.client.delete(f"/api/sessions/{sid}/origin")
        self.assertEqual(forgotten.status_code, 204)
        after = self.client.get(f"/api/sessions/{sid}").json()
        self.assertIsNone(after["origin"])
        self.assertIsNone(after["origin_label"])
        self.assertIsNone(after["recommendation"]["origin"])

    def test_household_outlives_the_session(self):
        first = self.client.post(
            "/api/recommend",
            json={"message": "We both work downtown until 6, 2nd grader near Coral Gables, she does ballet in Coconut Grove."},
        )
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        sid, hid = body["session_id"], body["household_id"]
        self.assertTrue(hid)
        household = body["household"]
        self.assertEqual(household["work_location_text"], "downtown Miami")
        self.assertTrue(household["needs_after_school_care"])
        self.assertEqual([a["label"] for a in household["activities"]], ["ballet"])
        self.assertEqual(household["activities"][0]["location_text"], "coconut grove")
        self.assertEqual(body["preferences"]["location_text"], "coral gables")
        self.assertEqual(body["preferences"]["child_grades"], [2])
        # Work was geocoded for this turn and the commute shows up on the ranked rows.
        self.assertIsNotNone(body["work"])
        self.assertTrue(body["results"])
        self.assertTrue(all(s["detour_miles"] is not None for s in body["results"]))
        self.assertTrue(all("care" in s["ranking"]["components"] for s in body["results"]))
        self.assertEqual([p["label"] for p in body["activity_points"]], ["ballet"])

        # The session exposes the household id; the household endpoint returns it on its own.
        state = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(state["household_id"], hid)
        self.assertEqual(state["household"]["work_location_text"], "downtown Miami")
        own = self.client.get(f"/api/households/{hid}")
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(own.json()["household"]["work_location_text"], "downtown Miami")
        # Work coordinates are only stored with consent (mirrors the home origin rule).
        self.assertIsNone(own.json()["work"])
        self.assertIsNone(state["recommendation"]["work"])
        self.assertEqual(state["recommendation"]["activity_points"], [])

        # "Start over" deletes the session but the household survives and seeds the next one.
        self.assertEqual(self.client.delete(f"/api/sessions/{sid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/households/{hid}").status_code, 200)
        fresh = self.client.post("/api/recommend", json={"message": "kindergartner near Kendall", "household_id": hid})
        self.assertEqual(fresh.status_code, 200, fresh.text)
        again = fresh.json()
        self.assertNotEqual(again["session_id"], sid)
        self.assertEqual(again["household_id"], hid)
        self.assertEqual(again["household"]["work_location_text"], "downtown Miami")
        self.assertEqual([a["label"] for a in again["household"]["activities"]], ["ballet"])
        self.assertEqual(again["preferences"]["location_text"], "kendall")
        self.assertEqual(again["preferences"]["child_grades"], [0])
        self.assertTrue(all(s["detour_miles"] is not None for s in again["results"]))

        # A household-level correction updates the shared record.
        changed = self.client.post("/api/recommend", json={"session_id": again["session_id"], "message": "forget my work"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertIsNone(changed.json()["household"]["work_location_text"])
        self.assertEqual([a["label"] for a in changed.json()["household"]["activities"]], ["ballet"])
        self.assertIsNone(changed.json()["work"])
        self.assertIsNone(self.client.get(f"/api/households/{hid}").json()["household"]["work_location_text"])

        # Forgetting the household removes it entirely.
        self.assertEqual(self.client.delete(f"/api/households/{hid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/households/{hid}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/households/{hid}").status_code, 404)
        # A stale id on the next turn is tolerated: a new household is minted.
        stale = self.client.post("/api/recommend", json={"message": "I work in Doral", "household_id": hid})
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertTrue(stale.json()["household_id"])
        self.assertEqual(stale.json()["household"]["work_location_text"], "doral")

    def test_guided_discovery_asks_one_thing_at_a_time(self):
        def turn(message, sid=None):
            payload = {"message": message}
            if sid:
                payload["session_id"] = sid
            res = self.client.post("/api/recommend", json=payload)
            self.assertEqual(res.status_code, 200, res.text)
            return res.json()

        # Nothing known yet: no ranking, ask about the children first.
        hi = turn("hi")
        sid = hi["session_id"]
        self.assertEqual(hi["stage"], "discovering")
        self.assertEqual(hi["results"], [])
        self.assertEqual(hi["changes"], [])
        self.assertEqual(hi["question"]["topic"], "children")
        self.assertTrue(hi["question"]["options"])
        self.assertEqual(hi["follow_up"], hi["question"]["text"])

        # A bare answer to the pending question is parsed as that answer.
        kinder = turn("kindergarten", sid)
        self.assertEqual(kinder["stage"], "preliminary")
        self.assertEqual(kinder["preferences"]["child_grades"], [0])
        self.assertEqual(kinder["changes"], ["Added a kindergartner"])
        self.assertTrue(kinder["results"])
        self.assertTrue(all(0 in (s.get("serves_grades") or []) for s in kinder["results"]))
        self.assertEqual(kinder["question"]["topic"], "location")
        self.assertIn("first matches", kinder["summary"])

        # A bare place name answers the location question and does not touch anything else.
        gables = turn("Coral Gables", sid)
        self.assertEqual(gables["stage"], "refined")
        self.assertEqual(gables["preferences"]["location_text"], "coral gables")
        self.assertEqual(gables["preferences"]["child_grades"], [0])
        self.assertEqual(gables["preferences"]["categories"], [])
        self.assertEqual(gables["changes"], ["Searching near Coral Gables"])
        self.assertIsNotNone(gables["origin"])
        self.assertEqual(gables["question"]["topic"], "categories")
        self.assertEqual([o["label"] for o in gables["question"]["options"]], ["Public", "Charter", "Private", "Any type is fine"])

        # Declining a topic settles it: the next question moves on and it is never re-asked.
        any_type = turn("any school type is fine", sid)
        self.assertEqual(any_type["preferences"]["categories"], [])
        self.assertEqual(any_type["changes"], ["Any school type"])
        self.assertEqual(any_type["question"]["topic"], "priorities")

        academics = turn("strong academics", sid)
        self.assertEqual(academics["preferences"]["priorities"], ["academics"])
        self.assertEqual(academics["changes"], ["Prioritizing strong academics"])
        self.assertNotEqual(academics["question"]["topic"], "categories")

        # A natural correction replaces the only child and re-ranks.
        third = turn("actually 3rd grade", sid)
        self.assertEqual(third["preferences"]["child_grades"], [3])
        self.assertIn("Grade changed to 3rd grader", third["changes"])
        self.assertTrue(third["results"])
        self.assertTrue(all(3 in (s.get("serves_grades") or []) for s in third["results"]))
        self.assertEqual(third["preferences"]["location_text"], "coral gables")

        # Asked topics persist with the session and are never repeated.
        state = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(state["asked"][:4], ["children", "location", "categories", "priorities"])
        self.assertEqual(len(state["asked"]), len(set(state["asked"])))
        self.assertEqual(state["recommendation"]["stage"], "refined")

        # Start over clears the asked list and goes back to discovery.
        reset = turn("start over", sid)
        self.assertEqual(reset["stage"], "discovering")
        self.assertEqual(reset["results"], [])
        self.assertEqual(reset["question"]["topic"], "children")
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").json()["asked"], ["children"])

    def test_one_message_with_enough_detail_skips_discovery(self):
        res = self.client.post("/api/recommend", json={"message": "2nd grader near Kendall, charter only"})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["stage"], "refined")
        self.assertTrue(body["results"])
        self.assertEqual(body["preferences"]["categories"], ["charter"])
        self.assertIn("Added a 2nd grader", body["changes"])
        self.assertIn("Searching near Kendall", body["changes"])
        self.assertIn("Limited to charter schools", body["changes"])
        # Children, location and type are known, so the first question is about priorities.
        self.assertEqual(body["question"]["topic"], "priorities")

    def test_work_coordinates_persist_only_with_consent(self):
        remembered = self.client.post(
            "/api/recommend",
            json={"message": "I work in Brickell and we live in Kendall, 3rd grader", "remember_location": True},
        )
        self.assertEqual(remembered.status_code, 200, remembered.text)
        body = remembered.json()
        hid = body["household_id"]
        self.assertEqual(body["household"]["work_location_text"], "brickell")
        self.assertEqual(body["preferences"]["location_text"], "kendall")
        self.assertIsNotNone(body["work"])
        stored = self.client.get(f"/api/households/{hid}").json()
        self.assertEqual(stored["work"], body["work"])
        self.assertEqual(stored["work_label"], body["work_label"])
        state = self.client.get(f"/api/sessions/{body['session_id']}").json()
        self.assertEqual(state["recommendation"]["work"], body["work"])

        # A later turn without consent clears the stored coordinates but keeps the place text.
        quiet = self.client.post("/api/recommend", json={"session_id": body["session_id"], "message": "small schools please"})
        self.assertEqual(quiet.status_code, 200, quiet.text)
        self.assertIsNotNone(quiet.json()["work"])
        after = self.client.get(f"/api/households/{hid}").json()
        self.assertIsNone(after["work"])
        self.assertEqual(after["household"]["work_location_text"], "brickell")


if __name__ == "__main__":
    unittest.main()
