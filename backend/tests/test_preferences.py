import unittest

from app.schemas import ActivityPlace, ActivityUpdate, Child, ChildUpdate, Household, HouseholdPatch, ListUpdate, PreferencePatch, Preferences
from app.services.llm import _fallback_patch
from app.services.preferences import merge, merge_household


def _family() -> Preferences:
    return Preferences(
        location_text="Coral Gables",
        radius_miles=3,
        categories=["public"],
        priorities=["academics"],
        keywords=["Bilingual"],
        min_fl_grade="A",
        children=[Child(grade=2, label="7-year-old")],
    )


class MergeTests(unittest.TestCase):
    def test_unspecified_fields_survive(self):
        got = merge(_family(), PreferencePatch(radius_miles=5))
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual(got.radius_miles, 5)
        self.assertEqual(got.categories, ["public"])
        self.assertEqual(got.priorities, ["academics"])
        self.assertEqual(got.keywords, ["Bilingual"])
        self.assertEqual(got.min_fl_grade, "A")
        self.assertEqual([c.grade for c in got.children], [2])
        self.assertEqual(got.child_grade, 2)
        self.assertEqual(got.child_grades, [2])

    def test_add_child_keeps_the_first(self):
        patch = PreferencePatch(children=ChildUpdate(op="add", children=[Child(grade=0, label="kindergartner")]))
        got = merge(_family(), patch)
        self.assertEqual([(c.grade, c.label) for c in got.children], [(0, "kindergartner"), (2, "7-year-old")])
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual(got.child_grades, [0, 2])

    def test_replace_remove_and_clear(self):
        replaced = merge(_family(), PreferencePatch(categories=ListUpdate(op="replace", values=["charter"])))
        self.assertEqual(replaced.categories, ["charter"])

        removed = merge(_family(), PreferencePatch(keywords=ListUpdate(op="remove", values=["bilingual"])))
        self.assertEqual(removed.keywords, [])
        self.assertEqual(removed.categories, ["public"])

        cleared = merge(_family(), PreferencePatch(clear_fields=["min_fl_grade", "children"]))
        self.assertIsNone(cleared.min_fl_grade)
        self.assertEqual(cleared.children, [])
        self.assertIsNone(cleared.child_grade)
        self.assertEqual(cleared.location_text, "Coral Gables")

    def test_reset_then_applies_new_constraints(self):
        patch = PreferencePatch(
            reset=True,
            location_text="33156",
            children=ChildUpdate(op="add", children=[Child(grade=-2, label="18-month-old")]),
        )
        got = merge(_family(), patch)
        self.assertEqual(got.location_text, "33156")
        self.assertIsNone(got.min_fl_grade)
        self.assertEqual(got.categories, [])
        self.assertEqual(got.keywords, [])
        self.assertEqual([c.grade for c in got.children], [-2])

    def test_explicit_clear_wins_over_a_repeated_value(self):
        got = merge(_family(), PreferencePatch(location_text="Coral Gables", clear_fields=["location_text"]))
        self.assertIsNone(got.location_text)
        self.assertEqual(got.radius_miles, 3)


class FallbackPatchTests(unittest.TestCase):
    def test_follow_up_adds_a_child_without_dropping_constraints(self):
        got = merge(_family(), _fallback_patch("also a kindergartner"))
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual(got.radius_miles, 3)
        self.assertEqual(got.categories, ["public"])
        self.assertEqual(got.keywords, ["Bilingual"])
        self.assertEqual(sorted(c.grade for c in got.children), [0, 2])

    def test_only_charters_replaces_categories(self):
        got = merge(_family(), _fallback_patch("only charters"))
        self.assertEqual(got.categories, ["charter"])
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual([c.grade for c in got.children], [2])

    def test_forget_keyword_and_clear_minimum_grade(self):
        dropped = merge(_family(), _fallback_patch("forget the bilingual requirement"))
        self.assertEqual(dropped.keywords, [])
        self.assertNotIn("language", dropped.priorities)
        self.assertEqual(dropped.location_text, "Coral Gables")

        cleared = merge(_family(), _fallback_patch("no minimum grade"))
        self.assertIsNone(cleared.min_fl_grade)
        self.assertEqual(cleared.radius_miles, 3)

    def test_reset_message_keeps_only_the_new_request(self):
        got = merge(_family(), _fallback_patch("start over, daycare near 33156 for my 18-month-old"))
        self.assertEqual(got.location_text, "33156")
        self.assertIsNone(got.min_fl_grade)
        self.assertEqual(got.keywords, [])
        self.assertIn("early_childhood", got.categories)
        self.assertEqual([c.grade for c in got.children], [-2])

    def test_grade_correction_replaces_the_only_child(self):
        got = merge(_family(), _fallback_patch("she's actually in 3rd grade now", _family()))
        self.assertEqual([c.grade for c in got.children], [3])
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual(got.keywords, ["Bilingual"])

    def test_radius_change_leaves_location(self):
        got = merge(_family(), _fallback_patch("make it 5 miles"))
        self.assertEqual(got.radius_miles, 5)
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual([c.grade for c in got.children], [2])

    def test_prefer_near_is_set_and_cleared(self):
        near_work = merge(_family(), _fallback_patch("something closer to my work"))
        self.assertEqual(near_work.prefer_near, "work")
        back = merge(near_work, _fallback_patch("actually closer to home"))
        self.assertEqual(back.prefer_near, "home")
        self.assertEqual(back.location_text, "Coral Gables")

    def test_bare_answers_parse_without_context(self):
        self.assertEqual(_fallback_patch("5 miles").radius_miles, 5)
        self.assertEqual(_fallback_patch("within 2 miles").radius_miles, 2)
        self.assertEqual(sorted(_fallback_patch("public or charter").categories.values), ["charter", "public"])
        self.assertEqual([c.grade for c in _fallback_patch("2nd grade").children.children], [2])
        self.assertEqual([c.grade for c in _fallback_patch("kindergarten").children.children], [0])
        self.assertEqual(_fallback_patch("strong academics").priorities.values, ["academics"])
        self.assertEqual(_fallback_patch("only A-rated schools").min_fl_grade, "A")

    def test_bare_answers_use_the_pending_question(self):
        place = _fallback_patch("Coral Gables", None, pending="location")
        self.assertEqual(place.location_text, "coral gables")
        self.assertIsNone(place.children)
        self.assertFalse(place.reset)
        self.assertIsNone(_fallback_patch("Coral Gables", None, pending=None).location_text)

        grade = _fallback_patch("3", None, pending="children")
        self.assertEqual([c.grade for c in grade.children.children], [3])
        self.assertIsNone(_fallback_patch("3", None, pending="radius").children)

    def test_declining_a_question_clears_rather_than_sets(self):
        for text, field in [
            ("any school type is fine", "categories"),
            ("distance doesn't matter", "radius_miles"),
            ("any state grade is fine", "min_fl_grade"),
        ]:
            patch = _fallback_patch(text, _family(), pending=None)
            self.assertIn(field, patch.clear_fields, text)
            self.assertFalse(patch.reset, text)
        got = merge(_family(), _fallback_patch("any school type is fine", _family()))
        self.assertEqual(got.categories, [])
        self.assertEqual(got.location_text, "Coral Gables")
        self.assertEqual([c.grade for c in got.children], [2])


def _household() -> Household:
    return Household(
        work_location_text="Brickell",
        work_schedule_text="work until 6",
        needs_after_school_care=True,
        activities=[ActivityPlace(label="ballet", location_text="Coconut Grove")],
        activity_interests=["arts"],
    )


class MergeHouseholdTests(unittest.TestCase):
    def test_none_patch_keeps_everything(self):
        got = merge_household(_household(), None)
        self.assertEqual(got, _household())

    def test_add_activity_keeps_the_first(self):
        patch = HouseholdPatch(
            activities=ActivityUpdate(op="add", activities=[ActivityPlace(label="soccer", location_text="Tropical Park")]),
            activity_interests=ListUpdate(op="add", values=["sports"]),
        )
        got = merge_household(_household(), patch)
        self.assertEqual([(a.label, a.location_text) for a in got.activities], [("ballet", "Coconut Grove"), ("soccer", "Tropical Park")])
        self.assertEqual(got.activity_interests, ["arts", "sports"])
        self.assertEqual(got.work_location_text, "Brickell")
        self.assertTrue(got.needs_after_school_care)

    def test_add_updates_the_place_of_an_existing_activity(self):
        patch = HouseholdPatch(activities=ActivityUpdate(op="add", activities=[ActivityPlace(label="Ballet", location_text="Pinecrest")]))
        got = merge_household(_household(), patch)
        self.assertEqual([(a.label, a.location_text) for a in got.activities], [("ballet", "Pinecrest")])

    def test_remove_activity(self):
        patch = HouseholdPatch(activities=ActivityUpdate(op="remove", activities=[ActivityPlace(label="ballet")]))
        got = merge_household(_household(), patch)
        self.assertEqual(got.activities, [])
        self.assertEqual(got.work_location_text, "Brickell")

    def test_clear_fields(self):
        got = merge_household(_household(), HouseholdPatch(clear_fields=["work_location_text", "needs_after_school_care", "activities"]))
        self.assertIsNone(got.work_location_text)
        self.assertIsNone(got.needs_after_school_care)
        self.assertEqual(got.activities, [])
        self.assertEqual(got.work_schedule_text, "work until 6")
        self.assertEqual(got.activity_interests, ["arts"])

    def test_reset_drops_the_prior_household(self):
        got = merge_household(_household(), HouseholdPatch(work_location_text="Doral"), reset=True)
        self.assertEqual(got.work_location_text, "Doral")
        self.assertIsNone(got.work_schedule_text)
        self.assertEqual(got.activities, [])
        self.assertFalse(merge_household(_household(), None, reset=True).activities)
        self.assertTrue(merge_household(_household(), None, reset=True).is_empty())

    def test_blank_strings_do_not_overwrite(self):
        got = merge_household(_household(), HouseholdPatch(work_location_text="  ", work_schedule_text=""))
        self.assertEqual(got.work_location_text, "Brickell")
        self.assertEqual(got.work_schedule_text, "work until 6")

    def test_fallback_extraction_feeds_the_merge(self):
        patch = _fallback_patch("We both work downtown until 6, 2nd grader near Coral Gables, she does ballet in Coconut Grove.")
        self.assertIsNotNone(patch.household)
        got = merge_household(None, patch.household)
        self.assertEqual(got.work_location_text, "downtown Miami")
        self.assertIn("until 6", got.work_schedule_text or "")
        self.assertTrue(got.needs_after_school_care)
        self.assertEqual([(a.label, a.location_text) for a in got.activities], [("ballet", "coconut grove")])
        self.assertEqual(got.activity_interests, ["arts"])
        prefs = merge(Preferences(), patch)
        self.assertEqual(prefs.location_text, "coral gables")
        self.assertEqual(prefs.child_grades, [2])

        forgot = _fallback_patch("forget my work")
        self.assertIn("work_location_text", forgot.household.clear_fields)
        after = merge_household(got, forgot.household)
        self.assertIsNone(after.work_location_text)
        self.assertEqual(after.activities, got.activities)

        wiped = _fallback_patch("forget my household")
        self.assertIn("household", wiped.clear_fields)
        self.assertTrue(merge_household(got, wiped.household, reset=True).is_empty())


if __name__ == "__main__":
    unittest.main()
