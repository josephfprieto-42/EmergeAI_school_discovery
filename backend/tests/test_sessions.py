import tempfile
import unittest
from pathlib import Path

from app import sessions
from app.schemas import Child, Preferences


def _response(session_id: str, summary: str) -> dict:
    prefs = Preferences(location_text="Coral Gables", children=[Child(grade=2, label="7-year-old")])
    return {
        "session_id": session_id,
        "preferences": prefs.model_dump(mode="json"),
        "origin": [25.75, -80.26],
        "origin_label": "Coral Gables",
        "summary": summary,
        "follow_up": None,
        "results": [],
        "groups": None,
        "explanations": [],
        "candidates_considered": 0,
        "llm_used": False,
    }


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = sessions.connect(Path(self.tmp.name) / "sessions.db")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_roundtrip_and_delete(self):
        sid = sessions.create_session(self.con)
        prefs = Preferences(location_text="Coral Gables", children=[Child(grade=2, label="7-year-old")])
        sessions.save_turn(
            self.con,
            sid,
            prefs,
            (25.75, -80.26),
            "Coral Gables",
            "we live in Coral Gables",
            "Here are some schools.",
            _response(sid, "Here are some schools."),
        )
        stored = sessions.get_session(self.con, sid)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["preferences"].location_text, "Coral Gables")
        self.assertEqual([c.grade for c in stored["preferences"].children], [2])
        self.assertEqual([m.content for m in stored["messages"]], ["we live in Coral Gables", "Here are some schools."])
        self.assertEqual(stored["origin"], (25.75, -80.26))
        self.assertEqual(stored["recommendation"].summary, "Here are some schools.")

        sessions.delete_session(self.con, sid)
        self.assertIsNone(sessions.get_session(self.con, sid))
        self.assertIsNone(sessions.get_session(self.con, "missing"))

    def test_keeps_only_recent_messages(self):
        sid = sessions.create_session(self.con)
        prefs = Preferences()
        for i in range(25):
            sessions.save_turn(self.con, sid, prefs, None, None, f"user {i}", f"assistant {i}", _response(sid, f"assistant {i}"))
        stored = sessions.get_session(self.con, sid)
        assert stored is not None
        self.assertEqual(len(stored["messages"]), sessions.MESSAGE_CAP)
        self.assertEqual(stored["messages"][0].content, "user 5")
        self.assertEqual(stored["messages"][-1].content, "assistant 24")


if __name__ == "__main__":
    unittest.main()
