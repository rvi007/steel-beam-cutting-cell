"""IFC export of the steel frame: the files open, every member is real UK steel in S355, the numbers add up,
and no steel is where the bridges and arms move."""
import os
import unittest

from beamcell import ifc_export as X
from beamcell import machine as M
from beamcell import sections as S

try:
    import ifcopenshell
    import ifcopenshell.util.element
except ImportError:
    ifcopenshell = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {12: os.path.join(ROOT, "cad", "beam_cell_steel_12m.ifc"), 20: os.path.join(ROOT, "cad", "beam_cell_steel_20m.ifc")}
TYPES = ("IfcBeam", "IfcColumn", "IfcPlate", "IfcMember")


class Members(unittest.TestCase):
    """The member list (no ifcopenshell needed)."""

    def test_columns_and_mass(self):
        for length, cols, (lo, hi) in ((12, 10, (5000, 7000)), (20, 14, (7500, 10000))):
            ms = X.members(length)
            columns = [m for m in ms if m["profile"] == "UC254*254*73"]
            self.assertEqual(len(columns), cols)
            self.assertTrue(lo <= sum(m["mass_kg"] for m in ms) <= hi, length)
            # both runways: rail ends 300 mm past the end columns, so (X range + 0.6 m) each
            runway = sum(m["length_mm"] for m in ms if m["profile"] == "UB457*191*67")
            self.assertEqual(runway, 2 * round((length + 2.6 + 0.6) * 1000))
            self.assertTrue(all(m["length_mm"] <= X.RUNWAY_STOCK_MAX for m in ms if m["profile"] == "UB457*191*67"))
            self.assertEqual(len({m["mark"] for m in ms}), len(ms), "marks are unique")
            self.assertEqual(M.WORK_LENGTH, 12.0, "the machine size is put back")

    def test_outside_moving_envelope(self):
        for length in (12, 20):
            for m in X.members(length):
                self.assertFalse(X.in_envelope(m), f"{length} m: {m['mark']} is in the machine's moving envelope")

    def test_tekla_names(self):
        self.assertEqual(X.tekla_name("UB 457x191x67"), "UB457*191*67")
        self.assertEqual(X.tekla_name("UC 254x254x73"), "UC254*254*73")
        self.assertEqual(X.tekla_name("RHS 120x80x5.0"), "RHS120*80*5")
        self.assertEqual(X.tekla_name("SHS 100x100x6.3"), "SHS100*100*6.3")
        self.assertEqual(X.tekla_name("EA 70x70x7.0"), "L70*70*7")


@unittest.skipIf(ifcopenshell is None, "ifcopenshell not installed")
class Files(unittest.TestCase):

    def test_open_and_count(self):
        for length, path in FILES.items():
            f = ifcopenshell.open(path)
            ms = X.members(length)
            want = {t: 0 for t in TYPES}
            for m in ms:
                want[{"beam": "IfcBeam", "column": "IfcColumn", "plate": "IfcPlate", "member": "IfcMember"}[m["kind"]]] += 1
            for t in TYPES:
                self.assertEqual(len(f.by_type(t)), want[t], f"{length} m {t}")
            self.assertEqual(f.schema, "IFC2X3")
            cols = [c for c in f.by_type("IfcColumn") if c.ObjectType == "UC254*254*73"]
            self.assertEqual(len(cols), 10 if length == 12 else 14)

    def test_material_profile_pset(self):
        for path in FILES.values():
            f = ifcopenshell.open(path)
            for t in TYPES:
                for el in f.by_type(t):
                    mat = ifcopenshell.util.element.get_material(el)
                    self.assertEqual(mat.Name, "S355", el.Name)
                    solid = el.Representation.Representations[0].Items[0]
                    self.assertEqual(solid.SweptArea.ProfileName, el.ObjectType)
                    ps = ifcopenshell.util.element.get_psets(el)["Pset_BeamCellSteel"]
                    for k in ("Profile", "Grade", "Length", "Mark", "Assembly"):
                        self.assertIn(k, ps)
                    self.assertEqual(ps["Mark"], el.Name)
                    self.assertEqual(ps["Profile"], el.ObjectType)
                    if t != "IfcPlate":                 # plates are extruded through their thickness
                        self.assertAlmostEqual(solid.Depth, ps["Length"], delta=1.0)
                    self.assertTrue(el.Decomposes, f"{el.Name} is in an assembly")

    def test_i_profiles_match_sections(self):
        f = ifcopenshell.open(FILES[12])
        seen = set()
        for p in f.by_type("IfcIShapeProfileDef"):
            title = {"UB457*191*67": "UB 457x191x67", "UC254*254*73": "UC 254x254x73"}[p.ProfileName]
            s = S.get(title)
            self.assertAlmostEqual(p.OverallDepth, s["h"])
            self.assertAlmostEqual(p.OverallWidth, s["b"])
            self.assertAlmostEqual(p.WebThickness, s["tw"])
            self.assertAlmostEqual(p.FlangeThickness, s["tf"])
            self.assertAlmostEqual(p.FilletRadius, s["r"])
            seen.add(p.ProfileName)
        self.assertEqual(seen, {"UB457*191*67", "UC254*254*73"})

    def test_column_geometry(self):
        try:
            import ifcopenshell.geom
            import numpy as np
        except ImportError:
            self.skipTest("ifcopenshell.geom not available")
        f = ifcopenshell.open(FILES[12])
        st = ifcopenshell.geom.settings()
        st.set("use-world-coords", True)
        c1 = [c for c in f.by_type("IfcColumn") if c.Name == "C1"][0]
        v = np.array(ifcopenshell.geom.create_shape(st, c1).geometry.verts).reshape(-1, 3) * 1000   # m -> mm
        uc = S.get("UC 254x254x73")
        x, y = M.X_LIMITS[0] * 1000, -M.WIDTH * 500
        np.testing.assert_allclose(v.min(0), (x - uc["h"] / 2, y - uc["b"] / 2, 25), atol=1.0)
        np.testing.assert_allclose(v.max(0), (x + uc["h"] / 2, y + uc["b"] / 2, X.runway_z() - 20), atol=1.0)


if __name__ == "__main__":
    unittest.main()
