# Plasma: how the torch finds the steel, holds its height, and changes for each cut

The Cutter's plasma settings come from a **cut chart** (`beamcell/plasma.py`). The planner uses
it for every cut, so the plan's timing is the real cutting speed. On the Machine tab, the Cutter's
card shows the settings of the cut it is doing: amps, speed, height, arc volts, and torch height control on or off.
The Sensors tab shows the whole chart.

> **The numbers are typical values for planning,** built from published cut charts for mild steel.
> Before cutting real steel, put in the cut chart of **your** plasma system and consumables, and
> qualify the process: BS EN ISO 9013 for cut quality, and BS EN 1090-2 for thermal-cut holes, which have hardness and quality requirements.

## 1. The nozzle-to-steel distance: how it is found and held

| Stage | What happens | Why |
|---|---|---|
| **Touch-off** (initial height sensing) | The torch moves down until the nozzle / shield touches the steel. A small voltage on the nozzle closes a circuit through the plate (**ohmic contact**). Or the Z axis feels the stall. | finds the **true surface**: beams are bowed, out of square and a few mm off their catalogue size |
| **Pierce height** | Lift to about 2x the cut height, fire the arc, wait the **pierce delay** | molten metal splashes up while piercing; height keeps it off the nozzle |
| **Edge start** | Cuts that start at a flange edge need **no pierce**: the arc starts on the edge | faster, and the nozzle lasts longer |
| **Cut height** | Drop to the cut height and move at the cut speed | the height sets the bevel and quality of the cut |
| **Torch height control (THC)** | The arc voltage rises when the torch is higher and falls when lower; the controller moves Z to hold the **target arc voltage** | holds the height over a bowed or uneven beam |
| **THC off** | On holes, in tight corners and near edges | there, the voltage jumps for other reasons, and the torch would dive into the steel |
| **Collision** | A magnetic **breakaway** mount lets the torch snap off if it hits something; its switch stops the machine | protects the torch and the arm |

On the 1:10 prototype the "torch" is a pen in a sprung holder. Z moves down until a **micro-switch
on the holder** closes. That is the same idea as touch-off, with no arc and no arc voltage.

## 2. The parameters and what changes them

| Parameter | Set by | Typical (O2 plasma, 10 mm) |
|---|---|---|
| **Current (amps)** | plate thickness: up to 12 mm at 130 A, up to 25 mm at 170 A, thicker at 300 A | 130 A |
| **Gas** | process: O2 plasma with an air shield for mild steel (best edges); air plasma on small machines | O2 / air |
| **Cut speed** | thickness and amps, then reduced for the kind of cut | 2,700 mm/min |
| **Arc voltage** (= height during the cut) | thickness and amps | 135 V |
| **Cut height** | consumables | 3.0 mm |
| **Pierce height** | about 2x cut height | 6.6 mm |
| **Pierce delay** | thickness (longer for thicker plate) | 0.5 s |
| **Kerf** (width of the cut) | amps and consumables; the path is offset by half of it | 2.5 mm |

On a UB 305x165x40 the web (6.0 mm) and the flanges (10.2 mm) get different settings, and the
planner uses the right one for each pass.

## 3. Cutting scenarios

| Scenario | Speed | Start | Torch height control | Notes |
|---|---|---|---|---|
| **Straight cut through the section** (cut-to-length, mitre) | 100 % | edge start | on, off near the edges | a mitre in plan is still a vertical cut: same thickness, longer path |
| **Notch (cope)** with a radius | 100 %, **50 % in the corners** | edge start | on along the straights, off in the corners and radius | minimum cope radius from the UK checks (Blue Book) |
| **Bolt hole** | **60 %** | pierce in the centre, **lead-in arc** | **off** | bolt-ready holes need diameter at least equal to the plate thickness (**d/t ≥ 1**); d/t from 1 to 1.5 needs the full hole recipe (Hypertherm "True Hole" type: gas, speed changes around the hole, arc off on time); **d/t < 1: drill it** |
| **Slotted hole** | 65 % | pierce in the centre | off | as holes |
| **Opening / cut-out** | 80 %, 50 % in corners | pierce inside the waste, lead-in | on along the straights | |
| **Very thick plate** (above the pierce limit, 50 mm at 300 A) | - | **edge start only** or drill a start hole | - | the planner warns |
| **Bevel** (weld prep, torch tilted) | slower: the steel is effectively thicker (t / cos angle) | - | - | not in the planner yet |

The planner reports these as warnings on the plan, for example a hole that must be drilled, or
plate too thick to pierce.

## 4. Choosing the chart

`config/cell.toml`:

```toml
[plasma]
process = "o2"     # "o2" production O2 plasma, "air" air plasma, "pen" the 1:10 prototype's pen
```

To use your own machine's numbers, edit the rows in `beamcell/plasma.py` (`CHARTS`). Each row is
thickness, speed, arc volts, cut height, pierce height, pierce delay and kerf. Then restart the app.

## 5. Saved settings: the numbers that worked on YOUR machine

A cut chart is only a starting point. Plasma behaves differently with every machine, set of
consumables, gas supply and batch of steel, so the right numbers have to be found by trying them.
The **Plasma** tab is for that:

1. **Start new settings**: pick the beam (for example UB 305x165x40), the grade and the plasma.
   The numbers are filled in from the cut chart. A beam has two thicknesses, so there is a column
   for the **web** and one for the **flange**.
2. Cut a test piece. Change the numbers until the cut is clean: square edges, little dross, holes
   the right size. Changed numbers are highlighted, with the chart's value in grey beside them.
3. Mark it **Works well** (or *Still trying* / *Doesn't work*), write what you saw in **Notes**,
   and **Save**. Each one is a file named after the beam, in `plasma_settings/` (for example
   `plasma_settings/UB 305x165x40 S355.json`).
4. Next time you cut that beam, the Machine tab picks its saved settings automatically (the ones
   marked *Works well* first). The **Plasma** list above **Plan** shows which are used, and you can
   choose others or the plain cut chart. A saved job remembers its plasma settings too.

What each saved setting holds, for the web and for the flange: thickness, current (A), cut speed,
hole speed, corner speed (% of the cut speed), arc voltage, cut height, pierce height, pierce delay,
kerf width, gas pressure and torch height control on/off. Holes always cut with height control off,
and edge starts skip the pierce delay.

`plasma_settings/` stays on the machine (it is not in git, so `git pull` never touches it).
**Back it up**: it holds what you learned.

Sources: Hypertherm, *Torch height control for plasma cutting* and *True Hole technology*; Hypertherm
XPR300 published cut speeds for mild steel; BS EN ISO 9013; BS EN 1090-2.
