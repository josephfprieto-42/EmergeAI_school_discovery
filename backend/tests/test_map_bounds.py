import unittest

from app.db import connect, haversine_miles
from app.services.map_bounds import MAP_BUFFER_MILES, dataset_map_bounds, expand_bounds


class ExpandBoundsTests(unittest.TestCase):
    def test_each_side_grows_by_the_requested_miles(self):
        south, west, north, east = 25.41439, -80.80311, 25.97383, -80.12283
        mid_lat = (south + north) / 2
        mid_lon = (west + east) / 2
        s, w, n, e = expand_bounds(south, west, north, east, 10)

        self.assertAlmostEqual(haversine_miles(north, mid_lon, n, mid_lon), 10, delta=0.05)
        self.assertAlmostEqual(haversine_miles(south, mid_lon, s, mid_lon), 10, delta=0.05)
        self.assertAlmostEqual(haversine_miles(mid_lat, east, mid_lat, e), 10, delta=0.05)
        self.assertAlmostEqual(haversine_miles(mid_lat, west, mid_lat, w), 10, delta=0.05)
        self.assertLess(s, south)
        self.assertGreater(n, north)
        self.assertLess(w, west)
        self.assertGreater(e, east)


class DatasetMapBoundsTests(unittest.TestCase):
    def test_buffer_contains_every_school(self):
        bounds = dataset_map_bounds()
        con = connect()
        try:
            row = con.execute(
                """SELECT MIN(lat) AS south, MAX(lat) AS north,
                          MIN(lon) AS west, MAX(lon) AS east
                   FROM schools WHERE lat IS NOT NULL AND lon IS NOT NULL"""
            ).fetchone()
        finally:
            con.close()

        self.assertLess(bounds["south"], row["south"])
        self.assertGreater(bounds["north"], row["north"])
        self.assertLess(bounds["west"], row["west"])
        self.assertGreater(bounds["east"], row["east"])

        mid_lon = (row["west"] + row["east"]) / 2
        mid_lat = (row["south"] + row["north"]) / 2
        self.assertAlmostEqual(
            haversine_miles(row["north"], mid_lon, bounds["north"], mid_lon), MAP_BUFFER_MILES, delta=0.05
        )
        self.assertAlmostEqual(
            haversine_miles(mid_lat, row["east"], mid_lat, bounds["east"]), MAP_BUFFER_MILES, delta=0.05
        )
