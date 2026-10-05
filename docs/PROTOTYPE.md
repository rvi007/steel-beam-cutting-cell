# The 1:10 working prototype - what to buy and how to build it

A **desk-top version of the cell at 1:10** that really moves: two gantry bridges, two small
servo arms, cameras with YOLO, and a real hard-wired E-stop. It proves the software, the motion
planning, the vision and the safety circuit before anything full size is built.

- **Size:** about 1.1 m x 0.4 m x 0.45 m with the control box - it fits on a desk.
- **Shopping list:** `docs/Prototype_Shopping_List.pdf` (print it, tick as you buy) or
  `docs/prototype_bom.csv` (Excel / Google Sheets). Every line has a **part number** P01 ...
- **Assembly drawing:** `docs/Prototype_Assembly.pdf` - views with part-number balloons, an exploded
  view, every position, the parts list and the position list. In the app: the **Prototype** tab
  (3D, click any part, explode slider). Positions P11-1, P11-2 ... are the copies of a part (also in
  `cad/prototype_positions.csv` and the CAD tree).
- **CAD:** `cad/prototype_1to10.step` (Fusion 360 / SolidWorks / FreeCAD / Onshape).
- **Cut list:** `cad/prototype_cut_list.csv` - every aluminium length, from the CAD.

Rebuild after changing the design: `python3 -m beamcell.cad prototype` (on a PC), then
`python3 tools/make_bom_pdf.py` and `python3 tools/make_assembly_pdf.py`.

![The 1:10 prototype with part numbers](images/assembly_iso.png)

## What it is (honestly)

| | Full size | 1:10 prototype |
|---|---|---|
| Bed | 12 m (6 m bars) | 600 mm (a 6 m bar at 1:10) - set `PROTO_LENGTH = 1200` in `beamcell/cad.py` for the full 12 m |
| Width between rails / rail height | 3 m / 3.4 m | 300 mm / 340 mm |
| Frame | steel runways on columns | 20x20 aluminium V-slot only |
| Bridges | steel box girders, servo drives | 20x20 on mini V-wheels, NEMA 17 + GT2 belts |
| Lift (Z) | 2 m mast | 200 mm 20x20 on a T8 lead screw |
| Arms | 6-axis industrial arms | MeArm-type arms: 4 MG90S micro servos each, about 150 mm reach |
| Cutter | 130 A plasma torch | **a fine-liner pen** in a sprung holder: it marks every cut line |
| Handler | 500 kg lifting magnet | 5 V 20 mm electromagnet |
| Steel | UK sections | 3D-printed UK sections at 1:10 (UB 305 = 30 x 16 mm) with steel tape on top |

**No real cutting on the prototype.** A plasma torch, a laser over Class 2 or a spindle would make a
desk model dangerous (UV, fumes, fire, eyes). The pen proves what the software has to prove: where
each hole, notch and cut-off is, in what order, and that the paths are right.

**Know before you build:**
1. The small arms have **4 servos** (base, shoulder, elbow, wrist), not 6 like the simulated arms.
   They point the pen straight down well; marking the web from the side needs the wrist tilted,
   which they can do in a narrower range. The arm maths for them has to be added (stage 5b).
2. The arms are driven by a **PCA9685 servo board** wired straight to the Jetson's 40-pin header
   (I2C, pins 3 and 5) - no extra controller. The stepper motors need the **FluidNC board**: Linux
   can't make exact step pulses; the Jetson sends it G-code over USB. It's flashed once from a web
   page - no Arduino programming.
3. At 1:10 the model beams are small and light: print them in PETG and put steel tape on the top
   flange so the magnet can lift them.

## Total cost

About **£1,150** for everything, about **£1,260** with 10% spare for postage and
price changes (October 2026 prices; check before you buy). The safety relay is the biggest single
item (~£180 new, ~£75 used) - **don't skip it or the E-stop**; wiring them properly is part of the point.
To get the gantry moving first (stages 1-2): about £430.

## Wiring the safety circuit - build it FIRST, before motors move

```
 mains -> IEC inlet (switch + fuse) -> 24 V supply (motors, controller) and 5 V supply (servos, magnet)
                                          |                      |
                       PNOZ s3 output contacts, opened by:
                         - E-stop (NC contact 1 -> channel 1, NC contact 2 -> channel 2)
                         - door interlock switch (in series with the E-stop)
                         - reset: blue button (manual, monitored)
                                          |                      |
                              24 V to the motor drivers     5 V to the servos + magnet
 The Jetson and the FluidNC logic stay powered: they REPORT the stop, they don't make it.
 A spare NC contact on the E-stop -> Jetson GPIO (docs/SAFETY.md section 6) -> the app shows E-STOP.
```

## Build stages

| Stage | What you build | Done when |
|---|---|---|
| 0 | Software on the Jetson (`./start.sh`), `python3 -m beamcell.doctor --save` | the app runs, the doctor is green |
| 1 | Frame, bed, outfeed table, scrap tray (cut list + printed parts) | square and level |
| 5 | **Safety circuit and enclosure next** - E-stop, safety relay, door switch, reset | E-stop and door cut motor and servo power (measure it) |
| 2 | Bridges, carriages, Z axes, motors, FluidNC, limit switches | every axis homes and jogs from the FluidNC web page |
| 4 | Cameras on the Jetson, YOLO zones on the Camera tab | a hand in the danger zone stops the app |
| 3 | Build the two arms, PCA9685 on the Jetson, mount the arms under the Z axes | each servo moves from a test script |
| 5b | Software: send the planned moves to FluidNC (G-code) and the arms (PCA9685) | the prototype marks a B1 beam like the 3D view |
| 6 | Magnet on the Handler: lift a marked part to the outfeed table | part lands flat on the table |

## The shopping list

Same as `docs/prototype_bom.csv` and the PDF. Prices approximate (GBP, incl. VAT where known).


### Stage 1 - frame and bed (about £130)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P01 | V-slot 20x20 aluminium extrusion | cut to size - lengths in cad/prototype_cut_list.csv (frame, bed rails, bridges, Z axes, camera post) *(the whole frame is 20x20; lengths come from the CAD model)* | 9.5 m | 8 | [Ooznest (cut to size), Amazon UK](https://ooznest.co.uk/?s=20x20mm+V-Slot+cut+to+size&post_type=product) |
| P02 | Corner brackets + M5 T-nuts + M5 bolts | 30 cast 20-series corner brackets, 120 drop-in T-nuts, M5x8 button heads | 1 kit | 30 | [Ooznest, Amazon UK](https://ooznest.co.uk/?s=cast+corner+bracket+20+series&post_type=product) |
| P03 | Rubber feet | stick-on rubber feet 20 mm *(stops it sliding on the desk)* | 4 | 1 | [Amazon UK](https://www.amazon.co.uk/s?k=rubber+feet+20mm+self+adhesive) |
| P04 | Bed rollers | 10 mm printed sleeves on 3 mm silver steel rod (50 mm), 2 x 623ZZ bearings each *(print the sleeves; buy rod and bearings)* | 6 | 2 | [Amazon UK, Simply Bearings](https://www.amazon.co.uk/s?k=623ZZ+bearings+3mm) |
| P05 | Roller brackets (3D printed) | PETG, clip on the 20x20 bed rails *(filament counted under Consumables)* | 12 | 0 | print |
| P06 | Bed riser blocks (3D printed) | PETG blocks that hold the bed rails 60 mm above the base *(filament counted under Consumables)* | 6 | 0 | print |
| P07 | Outfeed table board | 3 mm plywood strip 700 x 90 mm | 1 | 4 | [builders' merchant, Amazon UK](https://www.amazon.co.uk/s?k=3mm+plywood+sheet) |
| P08 | Outfeed table risers (3D printed) | PETG *(filament counted under Consumables)* | 3 | 0 | print |
| P09 | Scrap tray (3D printed) | 700 x 44 mm tray under the bed *(filament counted under Consumables)* | 1 | 0 | print |

### Stage 2 - motion and controller (about £300)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P10 | Mini V-wheel gantry plate kits | 20-series mini gantry plate + 4 mini V-wheels (625 bearings) + eccentric spacers *(2 per bridge end x 2 bridges + 1 per carriage x 2)* | 6 | 12 | [Ooznest](https://ooznest.co.uk/?s=mini+V-wheel+gantry+plate&post_type=product) |
| P11 | NEMA 17 stepper motor | 1.5-2 A, 40 mm body, 5 mm shaft (a NEMA 14 is lighter if you prefer) *(X (one per bridge) and Y (one per carriage))* | 4 | 12 | [Ooznest, StepperOnline](https://www.omc-stepperonline.com/search?search=nema+17+stepper+motor+40mm) |
| P12 | NEMA 17 with integrated T8 lead screw | T8 x 2 mm lead, 150 mm screw, with brass nut *(Z axes)* | 2 | 22 | [StepperOnline, Amazon UK](https://www.omc-stepperonline.com/search?search=nema+17+lead+screw+T8+150mm) |
| P13 | Z motor bracket (3D printed) | PETG shelf on top of the carriage plate, holds the Z and Y motors *(filament counted under Consumables)* | 2 | 0 | print |
| P14 | Lead-screw nut block (3D printed) | PETG block with the brass T8 nut, fixed to the Z axis *(filament counted under Consumables)* | 2 | 0 | print |
| P15 | GT2 belt 6 mm | 5 m (2 per bridge along the rails, 1 per carriage) | 1 | 8 | [Ooznest](https://ooznest.co.uk/?s=GT2+belt+6mm&post_type=product) |
| P16 | GT2 16T pulleys + idlers | 4 x 16T 5 mm bore (cross shafts), 2 x 16T (Y), 8 idlers | 1 set | 20 | [Ooznest, Amazon UK](https://ooznest.co.uk/?s=GT2+pulley+16+tooth&post_type=product) |
| P17 | 5 mm cross shafts + bearings | 2 x 360 mm 5 mm silver steel, 4 x 625ZZ in printed blocks, 2 x 5-5 mm couplers *(one motor drives both rails of a bridge)* | 1 set | 12 | [Amazon UK, Simply Bearings](https://www.amazon.co.uk/s?k=5mm+linear+shaft+400mm) |
| P18 | Home / limit switches | mechanical microswitch with lever, NC wiring *(one per axis + 2 spare)* | 8 | 1.50 | [Amazon UK](https://www.amazon.co.uk/s?k=micro+limit+switch+lever+pack) |
| P19 | FluidNC 6-axis CNC controller (ESP32) | 6 driver sockets, USB to the Jetson (e.g. Elecrow / Bart Dring 6x CNC Controller) *(flash once from the web installer - no programming)* | 1 | 40 | [Elecrow, Tindie](https://www.elecrow.com/6x-cnc-controller-for-fluidnc.html) |
| P20 | TMC2209 stepper driver modules | StepStick format *(quiet; one per axis)* | 6 | 5 | [Amazon UK, Ooznest](https://www.amazon.co.uk/s?k=TMC2209+stepper+driver+stepstick) |
| P21 | Motor cable + drag chain | 5 m 4-core 0.25 mm2, 1 m 7x7 drag chain | 1 set | 15 | [Amazon UK](https://www.amazon.co.uk/s?k=4+core+cable+0.25mm+drag+chain+7x7) |

### Stage 3 - arms and tools (about £100)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P22 | MeArm-type 4-servo arm kit | small 4-servo arm with MG90S metal-gear micro servos (reach ~150 mm); swap the gripper for the pen / magnet *(about £37 each (MeArm pocket-sized kit))* | 2 | 37 | [Cool Components, Kitronik](https://coolcomponents.co.uk/collections/kits/robotic-arm) |
| P23 | Arm mount plate (3D printed) | PETG plate: bolts the arm base under the Z axis *(filament counted under Consumables)* | 2 | 0 | print |
| P24 | PCA9685 16-channel servo board | I2C - wired straight to the Jetson's 40-pin header (pins 3 / 5), drives all 8 servos *(no extra controller needed for the arms)* | 1 | 6 | [Amazon UK, kunkune](https://kunkune.co.uk/?p=11021) |
| P25 | 5 V power supply for the servos | Mean Well LRS-35-5 (5 V 7 A) - servos and magnet | 1 | 12 | [RS, Farnell](https://uk.rs-online.com/web/c/?searchTerm=Mean+Well+LRS-35-5) |
| P26 | Cutter 'torch' for the prototype (pen holder) | fine-liner pen in a sprung 3D-printed holder (marks every cut line on the model beam) *(no real cutting on the prototype: see docs/PROTOTYPE.md)* | 1 | 2 | print |
| P27 | Handler magnet | 5 V 20 mm lifting electromagnet (~2.5 kg hold) + MOSFET module + flyback diode *(switch it from a FluidNC output)* | 1 | 8 | [Amazon UK](https://www.amazon.co.uk/s?k=5V+electromagnet+20mm+lifting) |
| P28 | Model beams (3D printed) | UB 305x165 at 1:10 (30 x 16 mm), 500 mm long, with steel tape on the top flange *(the magnet needs steel to grip; filament counted under Consumables)* | 4 | 0 | print |

### Stage 4 - cameras and sensors (about £130)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P29 | USB wide-angle camera (safety zone) | 1080p UVC, 90-120 deg view (e.g. Logitech C920/C922 or an Arducam USB wide-angle) *(plug and play on the Jetson; YOLO watches the cell)* | 1 | 50 | [Amazon UK, Pimoroni](https://www.amazon.co.uk/s?k=Logitech+C920+webcam) |
| P30 | CSI camera (close-up of the Cutter) | Arducam IMX219 for Jetson Orin Nano (22-pin cable), wide-angle lens *(optional; checks the marked lines)* | 1 | 25 | [Arducam, RobotShop UK](https://www.arducam.com/arducam-imx219-pdaf-cdaf-autofocus-camera-module-with-case-for-raspberry-pi-nvidiar-jetson-orin-series.html) |
| P31 | Powered USB 3 hub | 4-port, own power supply *(controller + camera (+ spare))* | 1 | 20 | [Amazon UK](https://www.amazon.co.uk/s?k=powered+USB+3.0+hub+4+port) |
| P48 | VL53L1X time-of-flight distance sensor | I2C breakout, up to 4 m - the datum sensor: finds where the model beam starts *(on the Jetson's I2C with the PCA9685)* | 1 | 12 | [Pimoroni, The Pi Hut](https://shop.pimoroni.com/search?q=VL53L1X) |
| P49 | Pen touch-off micro-switch | micro-switch with roller lever, on the sprung pen holder - finds the beam surface (the prototype's initial height sensing) *(one spare)* | 2 | 1.5 | [Amazon UK, CPC](https://www.amazon.co.uk/s?k=micro+switch+roller+lever) |
| P50 | Load cell 1 kg + HX711 | bar load cell 1 kg with HX711 amplifier - between the Handler's wrist and magnet: weighs the part (slipping, wrong part, not cut free) | 1 | 7 | [Amazon UK, The Pi Hut](https://www.amazon.co.uk/s?k=load+cell+1kg+HX711) |
| P51 | INA219 current sensor | I2C current sensor in the magnet supply - checks the magnet is really on *(not drawn (wiring, inside the box))* | 1 | 5 | [Pimoroni, Amazon UK](https://www.amazon.co.uk/s?k=INA219+current+sensor) |
| P52 | IR flame sensor module | IR flame sensor with digital output - demonstrates the fire detector *(NOT a certified fire detector - demo only)* | 1 | 3 | [Amazon UK](https://www.amazon.co.uk/s?k=IR+flame+sensor+module) |
| P53 | Line laser module (Class 2) | 650 nm line laser, Class 1 or 2 (1 mW or less) - with camera 2 it shows the beam's real profile *(never look into the beam; Class 2 or below only)* | 1 | 6 | [Amazon UK](https://www.amazon.co.uk/s?k=line+laser+module+650nm+1mW) |

### Stage 5 - safety and enclosure (about £360)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P32 | Emergency stop station | yellow box, red 40 mm mushroom, turn to release, 2 NC contacts (e.g. Schneider Harmony XALK178 family) *(BS EN ISO 13850; NC contacts to the safety relay - add an NO/NC block for the Jetson)* | 1 | 42 | [RS, Farnell, TME](https://uk.rs-online.com/web/c/?searchTerm=XALK178) |
| P33 | Safety relay | Pilz PNOZ s3 24 V DC (dual channel, manual reset) or equivalent *(cuts the 24 V motor and 5 V servo supplies - this is how a real machine does it)* | 1 | 180 | [RS, Farnell (new) / ~£75 used](https://uk.farnell.com/search?st=PNOZ+s3+751103) |
| P34 | Door interlock switch | non-contact coded magnetic safety switch, NC (e.g. Pilz PSEN or Schmersal BNS) *(BS EN ISO 14119; wired into the safety relay)* | 1 | 60 | [RS, Farnell](https://uk.rs-online.com/web/c/?searchTerm=non+contact+safety+switch+coded) |
| P35 | Reset push button | 22 mm blue illuminated, 1 NO *(outside the enclosure with a view inside)* | 1 | 8 | [RS, Amazon UK](https://uk.rs-online.com/web/c/?searchTerm=22mm+blue+illuminated+push+button) |
| P36 | Stack light | 24 V mini LED tower, red / amber / green *(driven by the Jetson through a relay module)* | 1 | 15 | [Amazon UK](https://www.amazon.co.uk/s?k=24V+mini+LED+stack+light+3+colour) |
| P37 | 4-channel relay module (opto-isolated) | 3.3 V logic input, 24 V contacts *(stack light and magnet)* | 1 | 8 | [Amazon UK](https://www.amazon.co.uk/s?k=4+channel+relay+module+optocoupler+3.3V) |
| P38 | IR break-beam sensor pair | 5 mm IR break-beam (demonstrates the light-curtain input) *(one pair demonstrates the light curtain, one is the bar-present photo-eye - NOT a safety light curtain)* | 2 | 6 | [Pimoroni, The Pi Hut](https://thepihut.com/search?q=IR+break+beam+sensor) |
| P39 | Polycarbonate sheet 2 mm | front door, ends and lid (~0.6 m2) - polycarbonate, not acrylic (acrylic shatters) | 0.6 m2 | 35 | [plastics stockist, Amazon UK](https://www.amazon.co.uk/s?k=2mm+polycarbonate+sheet+clear) |
| P40 | Hinges + handle | 2 small hinges, 1 handle (20-series) | 1 set | 12 | [Ooznest, Amazon UK](https://ooznest.co.uk/?s=hinge+20+series&post_type=product) |

### Stage 6 - electrical (about £90)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P41 | 24 V power supply | Mean Well LRS-100-24 (24 V 4.5 A) - motors, controller, safety circuit | 1 | 14 | [RS, Farnell](https://uk.rs-online.com/web/c/?searchTerm=Mean+Well+LRS-100-24) |
| P42 | IEC mains inlet with switch and fuse | panel mount, 3 A fuse *(have the mains side checked by a competent person)* | 1 | 8 | [RS, Farnell](https://uk.rs-online.com/web/c/?searchTerm=IEC+inlet+switch+fuse) |
| P43 | DIN rail + terminals + fuse holders | short 35 mm DIN rail, 12 terminals, 3 x 5x20 fuse holders | 1 set | 20 | [RS, Farnell](https://uk.rs-online.com/web/c/?searchTerm=DIN+rail+terminal+block+fuse+holder) |
| P44 | Control box | ABS enclosure ~200 x 160 x 110 with cable glands *(holds the Jetson too)* | 1 | 20 | [RS, CPC](https://uk.rs-online.com/web/c/?searchTerm=ABS+enclosure+200x160) |
| P45 | Wire + ferrules + crimp tool | 0.5 and 0.75 mm2 flexible, ferrule kit | 1 set | 25 | [Amazon UK, CPC](https://www.amazon.co.uk/s?k=ferrule+crimp+tool+kit) |
| P46 | Jetson Orin Nano Super (4 GB) | you already have it - docs/JETSON_SPECS.md *(runs the app, YOLO, the planner and the arms)* | 1 | 0 | - |

### Consumables (about £40)

| Part | Item | What to look for | Qty | ~£ each | Where |
|---|---|---|---|---|---|
| P47 | PETG and PLA filament | 1 kg each *(brackets, risers, tray, model beams, arm parts)* | 2 | 20 | [Amazon UK, 3DJake](https://www.amazon.co.uk/s?k=PETG+filament+1kg+1.75mm) |

**Total: about £1,150.**


## Safety rules for the prototype (it's still a machine)

- Do the risk assessment in `docs/SAFETY.md` for the prototype too - belts, lead screws and servo
  arms can pinch fingers, and the mains side can kill.
- Have the mains wiring (IEC inlet to the power supplies) checked by a competent person.
- Keep the polycarbonate door closed while it runs (the door switch stops it if you don't).
- No lasers above Class 2, no plasma, no spindle on the prototype.
- If other people will use it at work, PUWER 1998 applies: training, the E-stop, guards.
