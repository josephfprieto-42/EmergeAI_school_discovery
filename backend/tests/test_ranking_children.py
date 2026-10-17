import unittest

from app import db
from app.schemas import Child, Household, Preferences
from app.services.ranking import (
    ActivityPoint,
    RouteContext,
    annotate_route,
    build_context,
    cost_label,
    retrieve_and_rank,
    score_school,
    weights_for,
)


class RankingChildrenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = db.connect()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_nearby_grades_share_one_list(self):
        prefs = Preferences(children=[Child(grade=0, label="kindergartner"), Child(grade=3, label="3rd grader")])
        results, considered, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNone(groups)
        self.assertGreater(considered, 0)
        self.assertTrue(results)
        self.assertLessEqual(len(results), 6)
        for school in results:
            self.assertLessEqual(school["grade_low"], 0)
            self.assertGreaterEqual(school["grade_high"], 3)
            self.assertEqual(school["serves_grades"], [0, 3])

    def test_disjoint_grades_return_a_group_per_child(self):
        # Public and charter schools do not span infant care through high school.
        # Some private schools do, after their licensed infant program is merged in.
        prefs = Preferences(
            categories=["public", "charter"],
            children=[Child(grade=-2, label="infant"), Child(grade=10, label="10th grader")],
        )
        results, considered, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNotNone(groups)
        assert groups is not None
        self.assertEqual([g["grade"] for g in groups], [-2, 10])
        self.assertGreater(considered, 0)
        seen = set()
        for group in groups:
            self.assertTrue(group["results"])
            self.assertGreater(group["candidates_considered"], 0)
            self.assertLessEqual(len(group["results"]), 6)
            for school in group["results"]:
                self.assertLessEqual(school["grade_low"], group["grade"])
                self.assertGreaterEqual(school["grade_high"], group["grade"])
                self.assertIn(group["grade"], school["serves_grades"])
                seen.add(school["id"])
        self.assertEqual({s["id"] for s in results}, seen)

    def test_minimum_grade_does_not_hide_infant_care(self):
        prefs = Preferences(
            min_fl_grade="A",
            children=[Child(grade=-2, label="infant"), Child(grade=10, label="10th grader")],
        )
        _, _, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNotNone(groups)
        assert groups is not None
        infant = next(g for g in groups if g["grade"] == -2)
        teen = next(g for g in groups if g["grade"] == 10)
        self.assertTrue(infant["results"])
        self.assertTrue(any(s.get("fl_grade") is None for s in infant["results"]))
        self.assertTrue(teen["results"])
        self.assertTrue(all(s.get("fl_grade") == "A" for s in teen["results"]))

    def test_one_child_stays_a_single_list(self):
        prefs = Preferences(children=[Child(grade=9, label="high school")])
        results, _, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNone(groups)
        self.assertTrue(results)
        for school in results:
            self.assertLessEqual(school["grade_low"], 9)
            self.assertGreaterEqual(school["grade_high"], 9)
            self.assertEqual(school["serves_grades"], [9])

    def test_affordability_drops_private_k12(self):
        prefs = Preferences(priorities=["affordability"], children=[Child(grade=9, label="high school")])
        results, _, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNone(groups)
        self.assertTrue(results)
        for school in results:
            self.assertNotEqual(school["category"], "private")
            self.assertEqual(school["cost"], "tuition-free")
            self.assertIn("tuition-free", school["ranking"]["reasons"])

    def test_affordability_keeps_private_when_asked(self):
        prefs = Preferences(
            priorities=["affordability", "religious"],
            keywords=["Catholic"],
            children=[Child(grade=0, label="kindergartner")],
        )
        results, _, _ = retrieve_and_rank(self.con, prefs, None, limit=12)
        self.assertTrue(any(s["category"] == "private" for s in results))
        for school in results:
            self.assertIn(school["cost"], ("tuition-free", "not reported"))
        self.assertNotIn("cost", weights_for(prefs))

    def test_affordability_keeps_child_care_and_ranks_free_programs_first(self):
        prefs = Preferences(priorities=["affordability"], children=[Child(grade=-2, label="infant")])
        results, _, groups = retrieve_and_rank(self.con, prefs, None, limit=6)
        self.assertIsNone(groups)
        self.assertTrue(any(s["category"] == "early_childhood" for s in results))
        self.assertTrue(results)
        self.assertTrue(all(s["cost"] == "tuition-free" for s in results))
        self.assertTrue(all(s["category"] != "private" for s in results))

    def test_cost_score_prefers_tuition_free_over_unpriced_care(self):
        prefs = Preferences(priorities=["affordability"])
        weights = weights_for(prefs)
        free = {"category": "early_childhood", "subtype": "early_head_start", "name": "Early Head Start"}
        priced = {"category": "early_childhood", "subtype": "daycare", "name": "Daycare"}
        free_score = score_school(free, prefs, weights)
        priced_score = score_school(priced, prefs, weights)
        self.assertGreater(free_score["score"], priced_score["score"])
        self.assertEqual(cost_label(free), "tuition-free")
        self.assertEqual(cost_label(priced), "not reported")
        self.assertIn("price not reported", priced_score["reasons"])


HOME = (25.72, -80.27)  # Coral Gables
WORK = (25.77, -80.19)  # Brickell / downtown


def _school(name: str, lat: float, lon: float, **extra) -> dict:
    base = {
        "id": hash(name) % 100000,
        "name": name,
        "category": "public",
        "subtype": "school",
        "lat": lat,
        "lon": lon,
        "fl_grade": "B",
        "enrollment": 600,
        "after_school_care": False,
        "after_school_care_names": [],
    }
    base.update(extra)
    base["distance_miles"] = round(db.haversine_miles(HOME[0], HOME[1], lat, lon), 2)
    return base


class HouseholdRankingTests(unittest.TestCase):
    def test_route_mode_prefers_the_school_with_the_smaller_detour(self):
        # Halfway between home and work versus a school the same distance from home but off the line.
        on_route = _school("Midway", (HOME[0] + WORK[0]) / 2, (HOME[1] + WORK[1]) / 2)
        off_route = _school("Off Route", HOME[0] - 0.045, HOME[1] - 0.045)
        prefs = Preferences()
        ctx = build_context(prefs, HOME, Household(work_location_text="Brickell"), WORK, None)
        self.assertEqual(ctx.mode, "route")
        for s in (on_route, off_route):
            annotate_route(s, ctx)
        self.assertLess(on_route["detour_miles"], off_route["detour_miles"])
        self.assertIsNotNone(on_route["work_miles"])
        w = weights_for(prefs, ctx)
        a = score_school(on_route, prefs, w, ctx)
        b = score_school(off_route, prefs, w, ctx)
        self.assertGreater(a["components"]["distance"], b["components"]["distance"])
        self.assertGreater(a["score"], b["score"])
        self.assertIn("on the way to work", a["reasons"])
        self.assertTrue(any(r.startswith("adds ") and r.endswith("to your commute") for r in b["reasons"]))

    def test_prefer_near_work_uses_work_as_the_anchor(self):
        near_work = _school("Near Work", WORK[0] + 0.005, WORK[1])
        near_home = _school("Near Home", HOME[0] + 0.005, HOME[1])
        prefs = Preferences(prefer_near="work")
        ctx = build_context(prefs, HOME, None, WORK, None)
        self.assertEqual(ctx.mode, "work")
        for s in (near_work, near_home):
            annotate_route(s, ctx)
        w = weights_for(prefs, ctx)
        self.assertGreater(score_school(near_work, prefs, w, ctx)["score"], score_school(near_home, prefs, w, ctx)["score"])
        self.assertTrue(any(r.endswith("mi from work") for r in score_school(near_work, prefs, w, ctx)["reasons"]))

    def test_without_work_the_mode_falls_back_to_home(self):
        ctx = build_context(Preferences(prefer_near="route"), HOME, None, None, None)
        self.assertEqual(ctx.mode, "home")

    def test_campus_care_ranks_the_flagged_twin_higher(self):
        lat, lon = HOME[0] + 0.01, HOME[1] + 0.01
        plain = _school("Twin A", lat, lon)
        with_care = _school("Twin B", lat, lon, after_school_care=True, after_school_care_names=["YMCA Twin B"])
        prefs = Preferences()
        household = Household(work_schedule_text="until 6", needs_after_school_care=True)
        ctx = build_context(prefs, HOME, household, None, None)
        self.assertTrue(ctx.needs_care)
        w = weights_for(prefs, ctx)
        self.assertIn("care", w)
        for s in (plain, with_care):
            annotate_route(s, ctx)
        a = score_school(with_care, prefs, w, ctx)
        b = score_school(plain, prefs, w, ctx)
        self.assertGreater(a["score"], b["score"])
        self.assertIn("YMCA Twin B after-school care on campus", a["reasons"])
        self.assertIn("after-school care not reported", b["reasons"])

    def test_care_component_is_off_without_a_stated_need(self):
        prefs = Preferences()
        ctx = build_context(prefs, HOME, Household(work_location_text="Brickell"), WORK, None)
        self.assertNotIn("care", weights_for(prefs, ctx))
        s = _school("Any", HOME[0], HOME[1], after_school_care=True)
        annotate_route(s, ctx)
        self.assertFalse(any("after-school" in r for r in score_school(s, prefs, weights_for(prefs, ctx), ctx)["reasons"]))

    def test_sports_interest_uses_the_fhsaa_directory(self):
        plain = _school("Plain High", HOME[0] + 0.01, HOME[1], grade_high=12)
        soccer = _school(
            "Soccer High",
            HOME[0] + 0.01,
            HOME[1],
            grade_high=12,
            sports=[{"sport": "Soccer", "team": "Boys"}, {"sport": "Soccer", "team": "Girls"}],
        )
        prefs = Preferences()
        quiet = build_context(prefs, HOME, None, None, None)
        sporty = build_context(
            prefs,
            HOME,
            Household(activities=[{"label": "soccer"}], activity_interests=["sports"]),
            None,
            None,
        )
        self.assertEqual(sporty.sport_terms, ["soccer"])
        annotate_route(plain, quiet)
        quiet_score = score_school(plain, prefs, weights_for(prefs, quiet), quiet)
        self.assertNotIn("sports", quiet_score["components"])
        for school in (plain, soccer):
            annotate_route(school, sporty)
        missed = score_school(plain, prefs, weights_for(prefs, sporty), sporty)
        offered = score_school(soccer, prefs, weights_for(prefs, sporty), sporty)
        self.assertIn("not in the FHSAA sports directory", missed["reasons"])
        self.assertIn("FHSAA: soccer", offered["reasons"])
        self.assertGreater(offered["score"], missed["score"])

    def test_activity_place_adds_a_detour_reason(self):
        studio = ActivityPoint(label="ballet in Coconut Grove", lat=25.7279, lon=-80.2416)
        near_studio = _school("Grove", 25.728, -80.24)
        prefs = Preferences()
        ctx = build_context(prefs, HOME, Household(activities=[]), WORK, [studio])
        annotate_route(near_studio, ctx)
        self.assertEqual(len(near_studio["activity_detours"]), 1)
        self.assertEqual(near_studio["activity_detours"][0]["label"], "ballet in Coconut Grove")
        self.assertIsNotNone(near_studio["activity_miles"])
        reasons = score_school(near_studio, prefs, weights_for(prefs, ctx), ctx)["reasons"]
        self.assertTrue(any("ballet in Coconut Grove" in r for r in reasons))

    def test_retrieve_and_rank_annotates_route_fields_from_the_catalog(self):
        prefs = Preferences(children=[Child(grade=2)], radius_miles=5)
        household = Household(work_location_text="Brickell", needs_after_school_care=True)
        results, considered, groups = retrieve_and_rank(self.con, prefs, HOME, limit=6, household=household, work=WORK)
        self.assertIsNone(groups)
        self.assertGreater(considered, 0)
        self.assertTrue(results)
        for s in results:
            self.assertIsNotNone(s["detour_miles"])
            self.assertIsNotNone(s["work_miles"])
            self.assertIn("after_school_care", s)
            self.assertIn("care", s["ranking"]["components"])

    @classmethod
    def setUpClass(cls):
        cls.con = db.connect()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()


class CatalogCareTests(unittest.TestCase):
    def test_after_school_care_flag_is_populated_and_named(self):
        con = db.connect()
        try:
            flagged = con.execute("SELECT COUNT(*) FROM schools WHERE after_school_care = 1").fetchone()[0]
            self.assertGreater(flagged, 50)
            unnamed = con.execute(
                "SELECT COUNT(*) FROM schools WHERE after_school_care = 1 AND (after_school_care_names IS NULL OR after_school_care_names IN ('', '[]'))"
            ).fetchone()[0]
            self.assertEqual(unnamed, 0)
            row = con.execute("SELECT * FROM schools WHERE after_school_care = 1 LIMIT 1").fetchone()
            school = db.row_to_school(row)
            self.assertTrue(school["after_school_care"])
            self.assertTrue(school["after_school_care_names"])
            # Flags only land on K-12 campuses, never on the provider records themselves.
            cats = {r[0] for r in con.execute("SELECT DISTINCT category FROM schools WHERE after_school_care = 1")}
            self.assertTrue(cats <= {"public", "charter", "private"}, cats)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
