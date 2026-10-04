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
        for rel in ("cad/beam_cell.step", "cad/prototype_1to5.step", "cad/parts/B1.step"):
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

    def test_cut_list(self):
        with open(os.path.join(ROOT, "cad", "prototype_cut_list.csv")) as fh:
            rows = fh.read().splitlines()
        self.assertEqual(rows[0], "profile,length_mm,use,quantity")
        self.assertTrue(any(r.startswith("20x40,1500,top rail,2") for r in rows))


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
