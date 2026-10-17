import sys
import unittest
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

import identity  # noqa: E402


def rec(**kwargs) -> identity.Record:
    base = dict(
        source="mdc_gis_private",
        source_id="1",
        name="Example School",
        category="private",
        subtype="private",
        program_kind="school",
        lat=25.76,
        lon=-80.20,
        address="100 Main St",
        city="Miami",
    )
    base.update(kwargs)
    return identity.Record(**base)


class ClassifyTests(unittest.TestCase):
    def test_private_and_daycare_with_the_same_name_merge(self):
        school = rec(name="Atala Montessori", address="240 N Krome Ave", source_id="p")
        daycare = rec(
            source="mdc_gis_daycare", source_id="d", name="Atala Montessori",
            category="early_childhood", subtype="daycare", program_kind="daycare",
            address="240 N Krome Ave", grade_low=-2, grade_high=-1, license_number="C11MD0001",
        )
        hit = identity.classify(school, daycare)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "same_school")
        clusters = identity.cluster_same_school(2, identity.link_records([school, daycare]))
        self.assertEqual(len(clusters), 1)

    def test_shared_address_alone_does_not_merge(self):
        school = rec(source="mdc_gis_public", category="public", subtype="traditional", name="Edison Park K-8", mdcps_id="1234", address="500 NW 67th St")
        daycare = rec(
            source="mdc_gis_daycare", category="early_childhood", subtype="daycare", program_kind="daycare",
            name="Happy Hearts Day Care", address="500 NW 67th St", grade_low=-2, grade_high=-1,
        )
        hit = identity.classify(school, daycare)
        self.assertEqual(hit[0], "same_campus_different_program")
        clusters = identity.cluster_same_school(2, identity.link_records([school, daycare]))
        self.assertEqual(sorted(len(c) for c in clusters), [1, 1])

    def test_same_school_number_at_two_addresses_stays_two_campuses(self):
        main = rec(source="mdc_gis_charter", category="charter", subtype="charter", name="Miami Arts Charter", mdcps_id="7059", address="95 NW 23rd St", lat=25.80, lon=-80.20, campus_label="Wynwood")
        other = rec(source="mdc_gis_charter", source_id="2", category="charter", subtype="charter", name="Miami Arts Charter", mdcps_id="7059", address="3000 SE 9th St", lat=25.46, lon=-80.43, campus_label="Homestead")
        hit = identity.classify(main, other)
        self.assertEqual(hit[0], "same_identity_different_campus")
        clusters = identity.cluster_same_school(2, identity.link_records([main, other]))
        self.assertEqual(len(clusters), 2)

    def test_learning_center_is_not_merged_into_the_school(self):
        school = rec(source="mdc_gis_public", category="public", subtype="traditional", name="John I. Smith K-8 Center", mdcps_id="5101", address="10415 NW 52nd St", grade_low=-1, grade_high=8)
        plc = rec(
            source="mdc_gis_public", source_id="2", category="public", subtype="primary_learning_center", program_kind="plc",
            name="John I. Smith Elementary PLC-A1", mdcps_id="5101", address="10415 NW 52nd St",
        )
        hit = identity.classify(school, plc)
        self.assertNotEqual(hit[0], "same_school")

    def test_head_start_at_a_school_address_stays_separate(self):
        school = rec(source="mdc_gis_public", category="public", subtype="traditional", name="South Pointe Elementary", mdcps_id="4001", address="1050 4th St")
        head = rec(
            source="mdc_gis_headstart", category="early_childhood", subtype="head_start", program_kind="headstart",
            name="South Pointe Elementary", address="1050 4th St", grade_low=-1, grade_high=-1,
        )
        self.assertEqual(identity.classify(school, head)[0], "same_campus_different_program")

    def test_nearby_coordinates_without_a_name_match_do_not_merge(self):
        left = rec(name="Chabad Grove", address="3713 Main Hwy", lat=25.72, lon=-80.24)
        right = rec(source="mdc_gis_daycare", source_id="2", name="Miami Jewish Montessori", category="early_childhood", subtype="daycare", program_kind="daycare", address="3715 Main Hwy", lat=25.7202, lon=-80.2402)
        hit = identity.classify(left, right)
        self.assertNotEqual(hit[0] if hit else None, "same_school")

    def test_merge_keeps_license_and_provenance(self):
        school = rec(name="Atala Montessori", address="240 N Krome Ave", grade_low=-1, grade_high=5, enrollment=40)
        daycare = rec(
            source="mdc_gis_daycare", source_id="9", name="Atala Montessori", category="early_childhood",
            subtype="daycare", program_kind="daycare", address="240 N Krome Ave",
            grade_low=-2, grade_high=-1, license_number="C11MD9999", capacity=30,
        )
        row, provenance = identity.merge_records([school, daycare], "240 n krome ave")
        self.assertEqual(row["license_number"], "C11MD9999")
        self.assertEqual(row["capacity"], 30)
        self.assertEqual(row["enrollment"], 40)
        self.assertEqual(row["grade_low"], -2)
        self.assertEqual(row["grade_high"], 5)
        self.assertEqual(row["category"], "private")
        self.assertEqual({item["source"] for item in provenance}, {"mdc_gis_private", "mdc_gis_daycare"})


class RealDataInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_db

        cls.schools, cls.excluded, raw = build_db.collect_mdc()
        cls.attrs, attr_counts = build_db.collect_attributes()
        raw.update(attr_counts)
        cls.links = identity.link_records(cls.schools)
        cls.attr_links = identity.link_attributes(cls.schools, cls.attrs)
        cls.report = identity.build_report(cls.schools, cls.links, cls.attrs, cls.attr_links, cls.excluded, raw)

    def _count(self, left: str, right: str, relation: str) -> int:
        key = "|".join(sorted((left, right)))
        return self.report["overlap_by_pair"].get(key, {}).get(relation, 0)

    def test_programs_that_only_share_a_campus_are_not_merged(self):
        self.assertEqual(self._count("mdc_gis_public", "mdc_gis_headstart", "same_school"), 0)
        self.assertEqual(self._count("mdc_gis_public", "mdc_gis_daycare", "same_school"), 0)
        self.assertEqual(self._count("mdc_gis_charter", "mdc_gis_daycare", "same_school"), 0)
        self.assertGreater(self._count("mdc_gis_public", "mdc_gis_daycare", "same_campus_different_program"), 0)

    def test_private_daycare_overlap_merges_and_flags_the_rest(self):
        self.assertGreater(self._count("mdc_gis_private", "mdc_gis_daycare", "same_school"), 50)
        self.assertGreater(self.report["ambiguous_count"], 0)

    def test_nces_and_fldoe_enrich_by_school_number(self):
        self.assertGreater(self._count("mdc_gis_public", "nces", "enriched"), 0)
        self.assertGreater(self._count("mdc_gis_public", "fldoe", "enriched"), 0)

    def test_a_merged_group_never_mixes_school_numbers(self):
        for group in identity.cluster_same_school(len(self.schools), self.links):
            ids = {self.schools[i].mdcps_id for i in group if self.schools[i].mdcps_id}
            self.assertLessEqual(len(ids), 1)
            kinds = {self.schools[i].program_kind for i in group}
            self.assertFalse("plc" in kinds and "school" in kinds)


if __name__ == "__main__":
    unittest.main()
