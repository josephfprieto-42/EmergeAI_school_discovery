import unittest

from app.schemas import Child, Household, PreferencePatch, Preferences
from app.services import discovery

ORIGIN = (25.72, -80.27)


def _results(categories=("public", "charter"), fl_grade="A", max_distance=8.0):
    return [
        {"category": c, "fl_grade": fl_grade, "distance_miles": max_distance - i}
        for i, c in enumerate(categories)
    ]


class StageTests(unittest.TestCase):
    def test_nothing_known_is_discovering(self):
        self.assertEqual(discovery.stage_for(Preferences(), None), "discovering")

    def test_one_of_children_or_place_is_preliminary(self):
        self.assertEqual(discovery.stage_for(Preferences(children=[Child(grade=0)]), None), "preliminary")
        self.assertEqual(discovery.stage_for(Preferences(location_text="Kendall"), None), "preliminary")
        self.assertEqual(discovery.stage_for(Preferences(), ORIGIN), "preliminary")

    def test_children_and_place_is_refined(self):
        self.assertEqual(discovery.stage_for(Preferences(children=[Child(grade=0)], location_text="Kendall"), None), "refined")
        self.assertEqual(discovery.stage_for(Preferences(children=[Child(grade=0)]), ORIGIN), "refined")


class NextQuestionTests(unittest.TestCase):
    def test_children_first_then_location(self):
        first = discovery.next_question(Preferences(), None, None, [], [])
        self.assertEqual(first.topic, "children")
        self.assertTrue(first.options)
        self.assertTrue(all(o.label and o.message for o in first.options))

        second = discovery.next_question(Preferences(children=[Child(grade=0)]), None, None, ["children"], [])
        self.assertEqual(second.topic, "location")
        self.assertEqual(second.options, [])

    def test_known_topics_are_skipped_even_if_never_asked(self):
        prefs = Preferences(children=[Child(grade=0)], location_text="Kendall", categories=["public"])
        q = discovery.next_question(prefs, None, ORIGIN, [], _results())
        self.assertEqual(q.topic, "priorities")

    def test_a_topic_is_never_asked_twice(self):
        prefs = Preferences(children=[Child(grade=0)], location_text="Kendall")
        asked = []
        seen = []
        for _ in range(10):
            q = discovery.next_question(prefs, None, ORIGIN, asked, _results())
            if q is None:
                break
            self.assertNotIn(q.topic, seen)
            seen.append(q.topic)
            asked.append(q.topic)
        self.assertEqual(seen, ["categories", "priorities", "radius", "min_fl_grade"])
        self.assertIsNone(discovery.next_question(prefs, None, ORIGIN, asked, _results()))

    def test_categories_only_asked_when_results_span_types(self):
        prefs = Preferences(children=[Child(grade=0)], location_text="Kendall")
        q = discovery.next_question(prefs, None, ORIGIN, [], _results(categories=("public", "public")))
        self.assertEqual(q.topic, "priorities")

    def test_radius_needs_an_origin_and_far_results(self):
        prefs = Preferences(children=[Child(grade=0)], location_text="Kendall", priorities=["academics"])
        asked = ["categories"]
        self.assertEqual(discovery.next_question(prefs, None, None, asked, _results()).topic, "min_fl_grade")
        self.assertEqual(discovery.next_question(prefs, None, ORIGIN, asked, _results(max_distance=3.0)).topic, "min_fl_grade")
        self.assertEqual(discovery.next_question(prefs, None, ORIGIN, asked, _results(max_distance=9.0)).topic, "radius")

    def test_work_is_asked_only_when_care_or_schedule_matters(self):
        prefs = Preferences(children=[Child(grade=0)], location_text="Kendall", priorities=["academics"], radius_miles=5)
        asked = ["categories"]
        quiet = discovery.next_question(prefs, Household(), ORIGIN, asked, _results(fl_grade=None))
        self.assertIsNone(quiet)
        busy = discovery.next_question(prefs, Household(needs_after_school_care=True), ORIGIN, asked, _results(fl_grade=None))
        self.assertEqual(busy.topic, "work")

    def test_min_fl_grade_needs_graded_results(self):
        prefs = Preferences(children=[Child(grade=-2)], location_text="Kendall", priorities=["academics"], radius_miles=5)
        self.assertIsNone(discovery.next_question(prefs, None, ORIGIN, ["categories"], _results(fl_grade=None)))


class SettledTests(unittest.TestCase):
    def test_clear_fields_settle_their_topics(self):
        patch = PreferencePatch(clear_fields=["categories", "radius_miles", "keywords"])
        self.assertEqual(discovery.settled_by_patch(patch), ["categories", "radius"])

    def test_acknowledge_settled_adds_a_phrase_once(self):
        out = discovery.acknowledge_settled(["Within 2 miles"], ["categories", "categories"])
        self.assertEqual(out, ["Within 2 miles", "Any school type"])
        self.assertEqual(discovery.acknowledge_settled(["Any school type"], ["categories"]), ["Any school type"])


class ChangesTests(unittest.TestCase):
    def test_added_child_and_location(self):
        prior = Preferences()
        prefs = Preferences(children=[Child(grade=0)], location_text="coral gables")
        self.assertEqual(discovery.changes(prior, prefs, None, None), ["Added a kindergartner", "Searching near Coral Gables"])

    def test_grade_correction_reads_as_a_change(self):
        prior = Preferences(children=[Child(grade=0)])
        prefs = Preferences(children=[Child(grade=3)])
        self.assertEqual(discovery.changes(prior, prefs, None, None), ["Grade changed to 3rd grader"])

    def test_second_child_is_an_addition_not_a_correction(self):
        prior = Preferences(children=[Child(grade=0)])
        prefs = Preferences(children=[Child(grade=0), Child(grade=5)])
        self.assertEqual(discovery.changes(prior, prefs, None, None), ["Added a 5th grader"])

    def test_category_replace_add_drop_and_clear(self):
        base = Preferences(children=[Child(grade=2)])
        self.assertEqual(
            discovery.changes(base, base.model_copy(update={"categories": ["charter"]}), None, None),
            ["Limited to charter schools"],
        )
        self.assertEqual(
            discovery.changes(base.model_copy(update={"categories": ["public"]}), base.model_copy(update={"categories": ["charter"]}), None, None),
            ["Switched to charter only"],
        )
        self.assertEqual(
            discovery.changes(base.model_copy(update={"categories": ["public"]}), base.model_copy(update={"categories": ["public", "charter"]}), None, None),
            ["Added charter schools"],
        )
        self.assertEqual(
            discovery.changes(base.model_copy(update={"categories": ["public", "charter"]}), base.model_copy(update={"categories": ["public"]}), None, None),
            ["Dropped charter schools"],
        )
        self.assertEqual(
            discovery.changes(base.model_copy(update={"categories": ["public"]}), base, None, None),
            ["Any school type"],
        )

    def test_priorities_radius_and_grade_floor(self):
        prior = Preferences(radius_miles=5, min_fl_grade="A", priorities=["academics"])
        prefs = Preferences(radius_miles=2, priorities=["small_school"])
        got = discovery.changes(prior, prefs, None, None)
        self.assertIn("Prioritizing a small school", got)
        self.assertIn("No longer weighting strong academics", got)
        self.assertIn("Within 2 miles", got)
        self.assertIn("No minimum state grade", got)

    def test_no_change_is_empty(self):
        prefs = Preferences(children=[Child(grade=1)], location_text="Kendall")
        self.assertEqual(discovery.changes(prefs, prefs.model_copy(), None, None), [])

    def test_household_changes(self):
        got = discovery.changes(Preferences(), Preferences(), Household(), Household(work_location_text="Brickell", needs_after_school_care=True))
        self.assertEqual(got, ["Remembered: you work in Brickell", "Noted: late pickup needed"])


class CopyTests(unittest.TestCase):
    def test_intro_restates_changes(self):
        self.assertEqual(discovery.intro(["Added a kindergartner"], Preferences(), None), "Got it: added a kindergartner.")
        self.assertIn("Miami-Dade", discovery.intro([], Preferences(), None))

    def test_preliminary_note_names_what_is_missing(self):
        note = discovery.preliminary_note(Preferences(children=[Child(grade=0)]), None, None)
        self.assertIn("your child's grade", note)
        self.assertIn("Tell me where you live", note)
        other = discovery.preliminary_note(Preferences(location_text="Kendall"), None, None)
        self.assertIn("Tell me your child's grade", other)


if __name__ == "__main__":
    unittest.main()
