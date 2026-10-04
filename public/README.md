# BEAM CELL

### Robotic cutting of UK structural steel

**Two robot arms on an overhead gantry that cut beams to size: bolt holes, slots, notches,
mitres and cut-to-length. Drawings in, finished beams out.**

Designed and built by **Ravi Mahadeva** · UK codes · runs on an NVIDIA Jetson Orin Nano

![BEAM CELL cutting a beam](docs/images/beam_cell.gif)

▶ **[Watch the 30-second video](docs/video/beam_cell_30s.mp4)**

> **The source code is private.** You can read everything on this page and in the `docs`
> folder. To get the code, **[request access](https://github.com/rvi007/beam-cell/issues/new?template=request-access.yml)**
> (it takes a minute). See [How to get the code](#how-to-get-the-code).

---

## The idea in one minute

Steel fabricators cut hundreds of beams a week. Each one needs holes for the bolts, notches
where it meets another beam, and the ends cut square or at an angle. Today that is done
on large, expensive machines or by hand.

BEAM CELL does the same work with **two robot arms hanging from an overhead gantry** above a
12-metre roller bed:

| | The **Cutter** (orange) | The **Handler** (blue) |
|---|---|---|
| Tool | plasma torch | electromagnet |
| Job | bolt holes, slots, openings, notches (copes), mitres, cut-to-length | holds each part while it is cut free, then carries it to the outfeed table |

You give it the parts, straight from the drawing office as **NC1 files** (from Tekla
Structures, Advance Steel or SDS2), or you draw them on screen. It then:

1. **Checks every part against the UK codes**, for example edge distances and hole sizes, and tells you what is wrong and why.
2. **Fits the parts onto stock bars** so as little steel as possible is wasted.
3. **Plans every move of both arms** and checks they never hit each other or the steel.
4. **Shows the whole job in 3D** before any steel is cut.
5. **Runs the job** with the safety system watching all the time: today in the 3D simulation, next on the 1:10 prototype.

There is also a **manual mode**: click on the beam to put a hole or a cut exactly there.

## See it

| | |
|---|---|
| ![The cell](docs/images/machine.png) **The whole cell**: the Handler carries a finished beam to the outfeed table while the Cutter works. | ![The Cutter](docs/images/cutter.png) **Following the Cutter** as it cuts a notch and bolt holes. |
| ![Parts](docs/images/parts.png) **Parts from the drawing office**: every face drawn, every UK check shown. | ![Manual cut](docs/images/manual_cut.png) **Manual cutting**: click on the steel to put a hole or a cut there. |

## Safety comes first

A cutting machine with moving arms can hurt people, so safety is designed in the way a real
machine does it, following UK law and standards (PUWER, BS EN ISO 13849, BS EN 60204-1,
BS EN ISO 13850, BS EN ISO 10218):

- **Emergency stop** on every screen and as a real red button; it stops everything at once.
- **Interlocked gate and light curtain**: open the gate or reach in and the machine stops.
- **Camera with AI person detection**: the machine slows down when someone comes close and stops when they come too close.
- **Reset and Start are separate**, and a **pre-start checklist** has to be signed for every job.
- **Auto, Manual (slow, hold-to-run) and Maintenance (locked off)** modes.
- **Watchdogs and a full event log** of every stop and start.

The full details are in **[docs/SAFETY.md](docs/SAFETY.md)**: the law, the standards, the risk assessment
and what certified hardware a real machine needs.

## The 1:10 desk-top prototype

The next step is a **working model at 1:10 scale**, about 1.1 m long, built from parts you
can buy in the UK: aluminium frame, stepper motors, two small robot arms, a pen that marks
the cut lines and a small magnet, all with the same safety system.

![The 1:10 prototype with part numbers](docs/images/assembly_iso.png)

- **Cost: about £1,100** for everything (stages 1–2, the moving frame, are about £430).
- **[Shopping list (PDF)](docs/Prototype_Shopping_List.pdf)**: every part, its price and a link to buy it.
- **[Assembly drawing (PDF)](docs/Prototype_Assembly.pdf)**: every part numbered and shown where it goes.
- **[How to build it](docs/PROTOTYPE.md)**: build stages, safety wiring and honest notes.

## Where it is now

| Done | Next |
|---|---|
| Complete software: UK checks, NC1 import, nesting, motion planning for both arms, collision checks, 3D simulation | Build the 1:10 prototype |
| Safety system in software, with a camera | Drive real motors from the planner |
| Full 3D CAD of the cell and the prototype | Test on real steel with a fabrication partner |
| Shopping list, assembly drawing and build plan | Safety hardware certified for a full-size cell |

## Looking for sponsors and partners

I am looking for **sponsors, steel fabricators and engineering partners** to help build the
prototype and then a full-size cell. If you can help with parts, workshop space, steel,
expertise or funding, **[open a message here](https://github.com/rvi007/beam-cell/issues/new?template=sponsor.yml)**.

## How to get the code

The source code, the CAD files (STEP) and the build tools are in a **private** repository.

1. **[Fill in the access request](https://github.com/rvi007/beam-cell/issues/new?template=request-access.yml)**:
   who you are, your GitHub username and what you would like to use it for.
2. I read every request. If it is approved, GitHub sends you an invitation to the private repository.
3. Accept the invitation. You can then read and clone the code.

Please don't put private details (phone, address) in the request: requests can be seen by
everyone who visits this page.

## Read more

| Document | What's in it |
|---|---|
| [How the machine works](docs/MACHINE.md) | the layout, how a beam lies on the bed, how a bar is cut step by step |
| [Safety](docs/SAFETY.md) | stops, UK law and standards, risk assessment, E-stop wiring |
| [UK codes](docs/UK_CODES.md) | every UK rule the cell checks, and where it comes from |
| [NC1 files](docs/NC1_FILES.md) | how parts come in from Tekla and other detailing software |
| [The 1:10 prototype](docs/PROTOTYPE.md) | what to buy, how to build it, how to wire the safety circuit |
| [A scale model](docs/SCALE_MODEL.md) | a static display model at 1:20 or 1:100 |
| [The AI advisor](docs/ASSISTANT.md) | "what's happening" in plain English, and where AI helps (and where it must not) |

## Copyright

© 2026 Ravi Mahadeva. All rights reserved. See [LICENSE](LICENSE).
You may read and share links to this page. You may not copy, build or sell the design without written permission.
