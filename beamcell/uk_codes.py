"""
UK rules used when checking parts (all sizes in mm).

Codes and guidance applied:
    BS EN 1090-2       Execution of steel structures (UK: via the NSSS). Hole sizes for bolts
                       (normal round, oversize and slotted holes), holes may be thermally cut,
                       re-entrant corners must be rounded.
    BS EN 1993-1-8     Eurocode 3 joints, with the UK National Annex: minimum end/edge
                       distances and spacings of bolt holes (Table 3.3).
    BS EN 10025-2      Steel grades (S275, S355).
    BS 4-1, BS EN 10056-1, BS EN 10210-2, BS EN 10219-2   Section sizes (see sections.py).
    SCI P358 / Blue Book  UK detailing practice: M20 8.8 bolts in 22 mm holes as standard,
                       notch (cope) sizes N x n to clear a supporting beam's flange.

Rules marked MACHINE are limits of this plasma cell, not code requirements.
"""

# Standard UK bolt sizes and the extra hole size (clearance) for each, BS EN 1090-2 Table 11
BOLTS = ["M12", "M16", "M20", "M22", "M24", "M27", "M30", "M36"]
STANDARD_BOLT = "M20"                 # UK default: M20 grade 8.8 in 22 mm holes
CLEARANCE = {                         # normal round, oversize, short slot extra length
    "M12": (1, 3, 4), "M14": (1, 4, 4), "M16": (2, 4, 6), "M18": (2, 4, 6), "M20": (2, 4, 6),
    "M22": (2, 4, 6), "M24": (2, 6, 8), "M27": (3, 8, 10), "M30": (3, 8, 10), "M36": (3, 8, 10),
}
HOLE_TYPES = ["normal", "oversize", "short slot", "long slot"]

GRADES = ["S275JR", "S275J0", "S275J2", "S355JR", "S355J0", "S355J2", "S355K2"]   # BS EN 10025-2
DEFAULT_GRADE = "S355J2"
STOCK_LENGTHS_M = [6, 8, 10, 12]     # common UK stockholder lengths that fit the 12 m cell
DEFAULT_STOCK_M = 12

MIN_CORNER_RADIUS = 5.0               # BS EN 1090-2: re-entrant corners rounded off
DEFAULT_COPE_RADIUS = 10.0            # usual UK detailing radius for a notch
MIN_HOLE_MACHINE = 10.0               # MACHINE: smallest plasma hole
MIN_PART_LENGTH = 150.0               # MACHINE: shortest part the Handler can hold
TRIM = 10.0                           # MACHINE: trimmed off the rough mill end of a bar
GAP = 20.0                            # MACHINE: gap between parts when they can't share a cut


def bolt_number(bolt):
    return int(bolt.lstrip("M"))


def hole_size(bolt, kind="normal"):
    """Hole diameter (and slot length) for a bolt, BS EN 1090-2 Table 11.
    Returns (diameter, slot_length) - slot_length 0 for round holes."""
    d = bolt_number(bolt)
    normal, oversize, short = CLEARANCE[bolt]
    if kind == "normal":
        return d + normal, 0.0
    if kind == "oversize":
        return d + oversize, 0.0
    if kind == "short slot":
        return d + normal, d + normal + short
    if kind == "long slot":
        return d + normal, d + normal + 1.5 * d
    raise ValueError(kind)


def min_distances(d0):
    """Minimum distances for a hole of diameter d0, BS EN 1993-1-8 Table 3.3 (UK NA):
    end e1, edge e2, pitch along p1, gauge across p2."""
    return {"e1": 1.2 * d0, "e2": 1.2 * d0, "p1": 2.2 * d0, "p2": 2.4 * d0}


def cope_advice(section, depth, length):
    """SCI P358 guidance on notches: small notches are fine; deep or long ones need the
    notched section checked by the engineer. Returns a warning string or ''."""
    h = section["h"]
    if depth > 0.5 * h:
        return f"notch deeper than half the beam ({depth:.0f} > {0.5 * h:.0f} mm) - engineer to check (SCI P358)"
    if length > h:
        return f"notch longer than the beam depth ({length:.0f} > {h:.0f} mm) - engineer to check (SCI P358)"
    return ""


def cope_to_clear(supporting):
    """Notch length N and depth n (mm) so a beam clears the flange of the supporting
    member - the Blue Book detailing values for that section."""
    return float(supporting.get("N", supporting["b"] / 2 + 10)), float(supporting.get("n", supporting["tf"] + supporting["r"]))
