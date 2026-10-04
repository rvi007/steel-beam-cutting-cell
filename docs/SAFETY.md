# Safety - stops, rules and regulations (UK)

**Read this first.** The cell's software has the stops a real machine needs, and they behave
the way the standards require (latching, reset, separate start, watchdogs, reduced speed,
hold-to-run). That makes the prototype safe to *demonstrate* and teaches the right
procedures. But a Jetson, Python and a web browser are **not safety-rated**. On any machine
that can hurt someone, every safety function below must be done in **hard-wired safety
hardware** (a safety relay or safety PLC, certified components), designed and validated by a
competent person. The software then only *reports* the safety state; it never *is* the
safety system. A camera with AI (YOLO) is never a safety device.

## 1. UK law that applies

| Law | What it means for this cell |
|---|---|
| Health and Safety at Work etc. Act 1974 | the general duty to keep people safe |
| Management of Health and Safety at Work Regulations 1999 (reg 3) | a written **risk assessment** |
| **PUWER 1998** (Provision and Use of Work Equipment) | reg 11 guard dangerous parts; reg 14 start controls; reg 15 stop controls; **reg 16 emergency stops**; reg 17-18 controls and control systems; reg 19 isolation; reg 24 warnings; reg 9 training |
| Supply of Machinery (Safety) Regulations 2008 | if the machine is supplied/put into service: essential requirements, technical file, conformity assessment, Declaration of Conformity, **UKCA** marking |
| **LOLER 1998** | the Handler's magnet lifts loads: lifting equipment - thorough examination (at least every 6 months for lifting accessories), safe working load marked |
| **COSHH 2002** + HSE guidance | plasma cutting fume from steel is a **carcinogen**: local exhaust ventilation (LEV), LEV thoroughly examined at least every 14 months, RPE where needed |
| Control of Noise at Work Regulations 2005 | plasma is loud: assess, hearing protection zone if over 85 dB(A) |
| Control of Artificial Optical Radiation at Work Regulations 2010 | the plasma arc's UV: screens, eye protection |
| Electricity at Work Regulations 1989 (and BS 7671 wiring) | electrical safety of the installation |
| Personal Protective Equipment at Work Regulations 1992 (amended 2022) | PPE as the last line |
| Regulatory Reform (Fire Safety) Order 2005 | sparks and hot work: fire risk assessment, extinguisher |
| Workplace (Health, Safety and Welfare) Regulations 1992 | marked walkways, lighting |
| RIDDOR 2013 | reporting serious incidents |

## 2. Standards used for the design

| Standard | Used for |
|---|---|
| BS EN ISO 12100 | risk assessment method (find hazards, estimate, reduce) |
| BS EN ISO 13849-1 / -2 | safety-related control systems: Performance Level (PL) and validation |
| BS EN 60204-1 | electrical equipment of machines: **stop categories 0/1/2**, E-stop, reset |
| BS EN ISO 13850 | emergency stop design (red mushroom on yellow, latching, twist to release) |
| BS EN ISO 10218-1 / -2 | industrial robots and robot cells: modes, **reduced speed 250 mm/s**, enabling device |
| BS EN ISO 14119 | interlocks on guards (the gate) |
| BS EN ISO 14120 | fixed and movable guards (the fence) |
| BS EN ISO 13857 | safety distances so people can't reach in |
| BS EN ISO 13855 | **where to mount a light curtain** (S = K x T + C) |
| BS EN IEC 61496-1/-2 | light curtains (Type 4) |
| BS EN ISO 17916 | **safety of thermal cutting machines** (the plasma cell) |
| BS EN 60974-1 | plasma cutting power sources |
| BS EN 13155 | non-fixed load lifting attachments (the magnet) |

## 3. Safety functions - in the software now, and what the real machine needs

| # | Function | In this prototype (software) | Real machine (hardware) - target |
|---|---|---|---|
| SF1 | **Emergency stop** | red E-STOP button on every screen + **Esc** key + optional wired button; latches; category 0 (or 1); release does not restart; Reset then Start | E-stops at the desk, the gate and each end; safety relay/PLC cuts drive power; **PL d, Cat 3** |
| SF2 | **Gate interlock** | gate open in Auto = protective stop (cat 1), latched until closed + Reset | coded interlock switch with guard locking until motion has stopped; **PL d** |
| SF3 | **Light curtain** (infeed) | beam broken in Auto = protective stop, latched | Type 4 curtain mounted at the BS EN ISO 13855 distance (shown on the Safety tab); **PL d/e** |
| SF4 | **Manual mode** | speed limited to 250 mm/s, **hold-to-run** (moves only while held) | safe-limited speed in the drives + 3-position enabling device; **PL d** |
| SF5 | **Maintenance / isolation** | Maintenance mode = isolated, nothing moves; needs Lock Out Tag Out confirmed; checklist again afterwards | lockable main isolator, personal padlocks (LOTO procedure), stored energy released |
| SF6 | **Fume extraction interlock** | no start without extraction; extraction stops = protective stop | airflow switch on the LEV wired to the plasma enable |
| SF7 | **Reset** | only works when every cause is gone; never starts the machine | blue reset button outside the cell with a view of the cell, monitored (falling edge) |
| SF8 | **Watchdogs** | operator screen silent > 2 s, or a required camera silent > 1.5 s = stop | safety PLC monitors its own I/O and communications |
| SF9 | **Bridge separation** | planner keeps bridges >= 1 m apart at all times; collision check | safe position monitoring / mechanical buffers on the rails |
| SF10 | **Camera zones (YOLO)** | warning zone slows to 25%; danger zone = protective stop | **extra layer only** - not safety-rated, never replaces SF1-SF4 |
| SF11 | **Magnet load loss** | Handler lifts max 500 kg; heavier parts left for the crane | battery-backed or permanent electro-magnet (no drop on power loss), BS EN 13155, LOLER |

**Stop categories (BS EN 60204-1):** 0 = power removed at once; 1 = controlled stop, then power
removed; 2 = controlled stop, power kept (normal Pause). The Safety tab shows which one
happened.

## 4. Operating procedure (what the screens enforce)

1. **Pre-start checklist** - tick every item and confirm (fence/gate, walk-round, extraction,
   E-stop test, screens + PPE, extinguisher, magnet inspection).
2. **Reset** (blue lamp blinking = reset needed). Refused until every cause is gone.
3. **Start** (or Run on the Machine tab). Green lamp = running at full speed; amber = reduced
   speed or paused; red = stopped.
4. Any stop latches. Find the cause, clear it, **Reset**, then **Start**.
5. Teaching or checking inside the fence: **Manual** mode - 250 mm/s and hold-to-run.
6. Maintenance: **Maintenance** mode + isolate + padlock (LOTO). After maintenance, the
   checklist must be confirmed again.

Every event is written with a time stamp to `logs/safety_log.jsonl` (and shown on the Safety tab).

## 5. Starter risk assessment (BS EN ISO 12100 style - complete it for your own cell)

| Hazard | Who | Measures in the design | Still to do on a real machine |
|---|---|---|---|
| Crushing / impact by gantry and arms | operator, maintenance | fence, interlocked gate, light curtain, E-stops, manual reduced speed, hold-to-run | safety PLC, validated PL, guard locking, stopping-time measurement |
| Plasma arc - burns, UV, noise | operator | torch only cuts while extraction runs; cell fenced | arc screens, PPE, noise assessment |
| Fume (carcinogenic) | everyone nearby | extraction interlock | LEV design, testing, 14-month examination, air monitoring |
| Falling part from the magnet | operator | 500 kg limit, part lifted only 250 mm, nobody in the cell in Auto | fail-safe magnet, LOLER examination, exclusion zone |
| Sharp edges, hot steel, sparks, fire | operator | offcuts drop into the skip; kerf shown hot in the 3D view | gloves, cooling time, fire extinguisher, no combustibles |
| Electric shock | maintenance | isolation in Maintenance mode | LOTO, BS 7671 installation, panel interlocks |
| Software fault | everyone | watchdogs, latching, separate reset/start, fail-safe wiring | **safety functions in certified hardware, independent of the software** |

## 6. Wiring the prototype's E-stop to the Jetson (optional)

For a physical demo you can wire a real E-stop so pressing it stops the 3D machine. This
**reports** the button to the software; it is not a safety circuit.

```
3.3 V (pin 1) ---[10 kOhm]---+--- GPIO pin (e.g. pin 11) on the Orin's 40-pin header
                             |
                     E-stop AUXILIARY NC contact
                             |
GND (pin 6) -----------------+
```
- Contact closed (button released) = pin reads 0 = healthy. Button pressed, wire cut or plug
  pulled = pin reads 1 = **E-STOP**. A broken wire can never hide a stop.
- Do the same for a gate switch (NC, closed when shut) and a light curtain's status relay.
- Reset button: normally-open push-button from the pin to GND (+ the same pull-up).
- Set the pins in `config/cell.toml` under `[gpio]`, `enabled = true`, and install
  `sudo apt install python3-jetson-gpio`. Check with `python3 -m beamcell.doctor`.
- On a real machine the E-stop's **main** contacts go to a safety relay that cuts motor
  power; only the auxiliary contact goes to the Jetson.

## 7. What is honestly still missing before anything real moves

- A safety PLC / safety relay design, with the PL calculated (e.g. with SISTEMA) and validated.
- Measured stopping times (they set the light curtain distance and the fence distances).
- A full risk assessment signed off by a competent person, and operator training records.
- If supplied or put into service as a machine: technical file, conformity assessment,
  Declaration of Conformity and UKCA marking.
