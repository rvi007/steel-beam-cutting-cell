"""CAD: the files in the repo are there and complete; with CadQuery installed, the solids are right."""
import glob
import json
import math
import os
import struct
import unittest

from beamcell import cad, nc1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def glb_json(path):
    with open(path, "rb") as fh:
        data = fh.read()
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


class Files(unittest.TestCase):
    """These run everywhere (the Jetson too): the 3D view and the downloads need these files."""

    def test_step_files(self):
        for rel in ("cad/beam_cell.step", "cad/prototype_1to10.step", "cad/parts/B1.step"):
            with open(os.path.join(ROOT, rel)) as fh:
                head = fh.read(200)
            self.assertTrue(head.startswith("ISO-10303-21"), rel)

    def test_web_models(self):
        moving = glb_json(os.path.join(ROOT, "web", "models", "moving.glb"))
        names = {n.get("name") for n in moving["nodes"]}
        for key in ("cutter", "handler"):
            for body in ["bridge", "carriage", "mast"] + [f"link{k}" for k in range(7)]:
                self.assertIn(f"{key}_{body}", names)
        self.assertIn("gate", names)
        cell = glb_json(os.path.join(ROOT, "web", "models", "cell.glb"))
        with open(os.path.join(ROOT, "web", "models", "labels.json")) as fh:
            labels = json.load(fh)["labels"]
        meshes = [n["name"] for n in cell["nodes"] + moving["nodes"] if "mesh" in n]
        self.assertGreater(len(meshes), 100)
        self.assertEqual([m for m in meshes if m not in labels], [])          # every solid says what it is
        for lamp in ("red", "amber", "green", "blue"):
            self.assertIn(f"lamp_{lamp}", meshes)

    def test_prototype_assembly_numbers(self):
        """Every solid of the prototype carries its part number and position, and every part number
        is a line of the shopping list."""
        import csv
        glb = glb_json(os.path.join(ROOT, "web", "models", "prototype.glb"))
        tags = [n["name"].split()[0] for n in glb["nodes"] if n.get("name", "").startswith("P")]
        with open(os.path.join(ROOT, "web", "models", "prototype_positions.json")) as fh:
            positions = json.load(fh)
        with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
            pns = {r["part_no"] for r in csv.DictReader(fh)}
        self.assertEqual(sorted(tags), sorted(p["tag"] for p in positions))
        self.assertEqual(len(set(tags)), len(tags))                      # no position twice
        self.assertTrue(all(p["pn"] in pns for p in positions))

    def test_cut_list(self):
        with open(os.path.join(ROOT, "cad", "prototype_cut_list.csv")) as fh:
            rows = fh.read().splitlines()
        self.assertEqual(rows[0], "profile,length_mm,use,quantity")
        self.assertTrue(any(r.startswith("20x20,900,top rail,2") for r in rows))


@unittest.skipIf(cad.cq is None, "CadQuery not installed (it's for a PC)")
class Solids(unittest.TestCase):
    def test_parts_have_the_right_volume(self):
        """Each example part's solid = section area x length, less the holes and notches."""
        for f in sorted(glob.glob(os.path.join(ROOT, "examples", "nc1", "*.nc1"))):
            with open(f) as fh:
                part = nc1.read(fh.read(), f)[0]
            solid = cad.part_solid(part).val()
            self.assertTrue(solid.isValid(), part.mark)
            s = part.sec
            plain = s["m"] / 7850 * 1e6 * part.length
            holes = sum(math.pi * (h["d"] / 2) ** 2 * (s["tf"] if part.hole_face(h) in ("o", "u") else s["tw"]) for h in part.holes)
            removed = plain - holes - solid.Volume()
            self.assertGreater(removed, -0.004 * plain, part.mark)              # section tables round the mass
            limit = 0.02 * plain if part.copes or part.outlines else 0.004 * plain
            self.assertLess(removed, limit, part.mark)

    def test_cell_model(self):
        m = cad.build_cell()
        groups = {it[0] for it in m.items if it[0]}
        self.assertIn("cutter.link6", groups)
        self.assertTrue(all(label for _, _, label, _, _ in m.items))


if __name__ == "__main__":
    unittest.main()


class ShoppingList(unittest.TestCase):
    def test_extrusion_metres_match_the_cad(self):
        """docs/prototype_bom.csv buys enough of each extrusion for cad/prototype_cut_list.csv."""
        import csv
        with open(os.path.join(ROOT, "cad", "prototype_cut_list.csv")) as fh:
            need, pieces = {}, {}
            for r in csv.DictReader(fh):
                need[r["profile"]] = need.get(r["profile"], 0) + int(r["length_mm"]) * int(r["quantity"])
                pieces[r["profile"]] = pieces.get(r["profile"], 0) + int(r["quantity"])
        with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(all(len(r) == 10 and r["approx_gbp_each"] and r["part_no"] for r in rows))
        for profile, mm in need.items():
            qty = next(r for r in rows if f"V-slot {profile}" in r["item"])["qty"]
            if qty.endswith(" m"):                   # bought by the metre
                self.assertGreaterEqual(float(qty.split()[0]) * 1000 + 50, mm, profile)
            else:                                    # bought as cut pieces
                self.assertEqual(int(qty), pieces[profile], profile)


@unittest.skipIf(cad.cq is None, "CadQuery not installed (it's for a PC)")
class Continuity(unittest.TestCase):
    """Nothing in the cell floats: every fixed part touches another one or stands on the floor, and every
    roller is mounted - a shaft through it and a bolted pillow-block bearing at each end."""

    def solids(self, length):
        from beamcell import cad, machine as M
        M.set_length(length)
        try:
            m = cad.build_cell()
        finally:
            M.set_length(12)
        out = []
        for group, name, label, shape, colour in m.items:
            if group is None:
                bb = (shape.val() if hasattr(shape, "val") else shape).BoundingBox()
                out.append((label, (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)))
        return out

    def test_nothing_floats(self):
        touch = lambda a, b: all(a[2 * i] <= b[2 * i + 1] + 2 and b[2 * i] <= a[2 * i + 1] + 2 for i in range(3))
        for length in (12, 20):
            parts = self.solids(length)
            floating = [lab for i, (lab, a) in enumerate(parts)
                        if a[4] > 5 and not any(touch(a, b) for j, (_, b) in enumerate(parts) if j != i)]
            self.assertEqual(floating, [], f"{length} m: not attached to anything")

    def test_every_roller_is_mounted(self):
        for length in (12, 20):
            parts = self.solids(length)
            tubes = [a for lab, a in parts if "roller" in lab.lower() and "tube" not in lab.lower() and lab.startswith(("Bed roller", "Driven infeed", "Bridging"))]
            shafts = [a for lab, a in parts if lab.startswith("Roller shaft")]
            housings = [a for lab, a in parts if lab.startswith("Pillow-block bearing UCP205 - housing")]
            self.assertGreater(len(tubes), 10)
            for t in tubes:
                x = (t[0] + t[1]) / 2
                shaft = [s for s in shafts if s[0] <= x <= s[1]]
                self.assertEqual(len(shaft), 1, f"roller at x={x:.0f} has no shaft")
                s = shaft[0]
                held = [h for h in housings if h[0] <= x <= h[1] and s[2] <= h[2] and h[3] <= s[3]]
                self.assertEqual(len(held), 2, f"roller at x={x:.0f} isn't held by two bearings")
