# Sensors: finding the beam, watching the cell, and what the hands decide

The cell has two cameras and a set of sensors. On the prototype most of them are **placeholders**:
the software already has a place for each one and **simulates** it, so the planner, the safety
controller and the screens work today. When a sensor is wired in, it replaces the simulation.
All of them are listed on the **Sensors** tab, with what each does, where it goes and what to buy.

## 1. How a beam is found and measured (what happens in real life)

A rolled steel beam is never exactly its catalogue size, and never exactly where the crane put it:

- **BS EN 10034** lets an I or H section be a few mm deeper or wider than its catalogue size, slightly out of square,
  and bowed by up to 0.1-0.3 % of its length. That is **18 mm over 12 m** for a UB 305.
- The crane puts the bar down **somewhere near** the end stop, not exactly at x = 0.

A cut that is 10 mm out is a scrapped part, so every production line **measures first, then cuts**:

| Step | What happens | Sensor | On the prototype |
|---|---|---|---|
| 1. Is there a bar? | A light beam across the bed is broken by the bar | **Bar-present photo-eye** | IR break-beam pair |
| 2. Where does it start? | A laser on the end stop measures the distance to the bar's end. That distance is the **x offset** every cut moves by | **Datum laser** | VL53L1X time-of-flight sensor |
| 3. What shape is it really? | The Cutter runs along the bar with a **laser profile scanner**: real depth, flange width, out-of-square, bow, and where the far end is | **Profile scanner + gantry encoders** | Camera 2 + a line laser |
| 4. Where is the surface, right here? | Before every cut the torch touches the steel (**ohmic touch-off**). That is the true surface, so the cut height is right | **Torch touch-off** | Micro-switch on the sprung pen holder |
| 5. Check | Every reading is compared with the BS EN 10034 tolerances. Out of tolerance means the machine doesn't start (wrong section, bent bar, bar not seated) | - | the same check, in software |

The result is the **bar check**. It appears under every plan on the Machine tab, and you can try it
on the Sensors tab. Today its readings are simulated: small, realistic and repeatable.

### How the big suppliers do it

| Machine | How it measures the beam |
|---|---|
| **Ficep NOZOMI** (robotic plasma coping) | a **non-contact laser scanner** on the robot surveys the real profile in seconds, so the torch doesn't have to probe every start point |
| **Voortman V808** (robotic thermal cutting) | a **measuring sensor on the torch nozzle** measures the exact profile; the difference from the theoretical size is compensated during cutting; roller-feed measuring and clamping |
| **Lincoln Electric PythonX STRUCTURAL** | a **measuring stand** measures the exact length of the beam at the start; guaranteed accuracy of 1 mm over 12 m |
| **Hypertherm** torch height controllers (used on most plasma machines) | **initial height sensing by ohmic contact** (or stall detection), then **arc-voltage** height control during the cut |

BEAM CELL follows the same pattern: a laser scanner on the Cutter (like Ficep), touch-off at the
torch (like Voortman and every plasma height controller), and a datum and length check (like PythonX).

## 2. The two cameras

| | Camera 1: cell overview | Camera 2: close-up on the torch |
|---|---|---|
| Where | high on the infeed-end column, looking down the cell | on the Cutter, beside the torch, behind a spatter shield |
| Sees | **people** in the warning and danger zones (YOLO); **objects** left on the bed; a part **hanging or slipping**; offcuts stuck in the rollers; smoke | the **bar edge** and the real cut line; the kerf and **hole quality**; **nozzle wear**; the pen mark on the prototype |
| Prototype | USB wide-angle (P29) | Arducam IMX219 (P30) + line laser (P53) |
| Full size | IP67 industrial camera | welding camera with auto-darkening |

**A camera with AI is never the safety device.** Detecting people for *safety* needs certified
protective equipment: light curtains (BS EN IEC 61496-2), safety laser scanners, or a *certified*
vision-based protective device (IEC TS 61496-4-2 / 4-3). In this cell the cameras are an **extra**
layer on top of those: they can slow the machine down or stop it, but nothing relies on them alone.

## 3. Hazards: what is detected, and what each hand decides

Every stop has a **fixed decision**: what the Cutter does, what the Handler does, and what you
must do. The rules are written in advance and checked in the risk assessment; **an AI never
decides them on the spot**. The AI advisor can only explain what happened. The same table is on
the Sensors tab, and you can **simulate** the new hazards there and on the Safety tab.

| Hazard | Detected by | Stop | Cutter | Handler | You |
|---|---|---|---|---|---|
| Emergency stop | E-stop buttons | 0 | torch off at once; stops dead | stops dead; **magnet stays on** (battery backup) | find the cause, release, Reset, Start |
| Gate opened / light curtain | interlock, light curtain | 1 | torch off; controlled stop | stops; keeps holding its part | leave the cell, close the gate, Reset |
| Person in the danger zone | camera 1 / area scanner | 1 | torch off; controlled stop | stops; **never lowers a load towards a person** | everyone out, Reset |
| **Object on the bed** in the hands' path | camera 1 (object detection) | 2 | torch off; **holds where it is**; won't move into that area | holds; won't set a part down on it | remove the object, Reset |
| **Load slipping / wrong weight** | magnet current, load cell, camera 1 | 2 | stops | stops moving sideways at once; **magnet stays on**; if the floor and bed below are clear, **lowers the part slowly straight down** onto the bed or table, otherwise holds it and sounds the alarm | keep everyone from under the load; check magnet, weight, that it was cut free; Reset |
| **Torch collision** | breakaway switch | 1 | torch off at once; stops; lifts 50 mm | stops; keeps holding | check torch and nozzle, re-seat the mount, re-measure the bar, Reset |
| **Fire / smoke** | flame / smoke detector, camera 1 | 1 | torch off at once; stops and lifts clear | stops; keeps holding | fire procedure; extraction keeps running; Reset only when it's out |
| Fume extraction off | airflow switch | 1 | torch off at once | stops | get extraction running, Reset |
| Screen / camera / wiring fault | watchdogs | 1 | torch off; stops | stops; keeps holding | fix it, Reset |

**Stop categories** (BS EN 60204-1): **0** means the power is cut at once. **1** means a controlled
stop, then the power goes off. **2** means a controlled stop with the power kept on, so the hands
hold their position and the magnet keeps its grip. Category 2 is used for an object on the bed and
a slipping load, because cutting the power then would drop the load or let the arm sag.

Two rules run through all of these:

- **The magnet never lets go on a stop.** It follows BS EN 13155 (lifting magnets need a backup so a power failure doesn't drop the load) and LOLER.
- **Nothing moves over a person.** The Handler only lowers a load if the area under it is clear.

## 4. Standards that apply

| Standard | What it covers here |
|---|---|
| **BS EN ISO 17916** | safety of thermal cutting machines (gantry plasma machines) - the machine standard for this cell |
| BS EN ISO 12100 | risk assessment |
| BS EN ISO 13849-1 | safety-related control systems (performance level) |
| BS EN 60204-1 | electrical equipment; stop categories 0, 1, 2 |
| BS EN ISO 13850 | emergency stop |
| BS EN ISO 13855 | where to put a light curtain or scanner (safety distance) |
| BS EN ISO 14119 / 14120 | gate interlocks / guards |
| BS EN IEC 61496 (-2, -3, TS -4) | light curtains, laser scanners, vision-based protective devices |
| BS EN ISO 10218-1/-2 | the robot arms |
| **BS EN 13155** + LOLER | the lifting magnet: backup if the power fails, safety factor |
| **BS EN 10034** | rolling tolerances of I and H sections (the bar check) |
| **BS EN ISO 9013** | thermal cut quality (squareness, roughness) |
| **BS EN 1090-2** | execution of steel structures: thermal cutting and holes must meet the cut-quality and hardness requirements |
| COSHH + HSG258 | fume extraction (LEV) |
| Regulatory Reform (Fire Safety) Order 2005 | fire risk |
| PUWER 1998 | the machine as work equipment |

## 5. Wiring a sensor in

1. Fit it and wire it as the Sensors tab says (I2C, GPIO, USB...).
2. Safety devices (E-stops, gate, light curtain, scanner, torch breakaway) go to the **safety relay**,
   and an auxiliary contact goes to the Jetson's GPIO (see `docs/SAFETY.md`, wiring).
3. Process sensors (datum, scanner, load cell, current, flame) feed the software. Their reading
   replaces the simulation in `beamcell/sensors.py`. Set `[sensors] simulate = false` in
   `config/cell.toml` when all of them are real.
4. The second camera: `[sensors] torch_camera = "csi"` (or "0" / "1" for USB).

Sources for the supplier and standard details above: Voortman V808 product page, Ficep NOZOMI
601 RAZ, Lincoln Electric PythonX, Hypertherm (torch height control, True Hole), BSI (EN ISO 17916),
HSE (magnetic lifting devices), the Blue Book (BS EN 10034 tolerances).
