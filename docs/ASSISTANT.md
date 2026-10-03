# "What's happening" and the optional AI advisor

## Is an LLM / VLM worth it here?

Short answer: **yes as an advisor, never as part of the safety system.**

| Job | Use AI? | Why |
|---|---|---|
| Stopping the machine, zones, interlocks | **No** | must be deterministic, fast (milliseconds) and certifiable. An AI model is none of these. The safety controller (`beamcell/safety.py`) is plain rules, and real machines put these functions in safety hardware. |
| Seeing people in the zones | YOLO (small vision model) | it's fast and good at "is there a person and where" - used as an **extra** layer (slow down / stop), never instead of the fence, gate and E-stops |
| "What's happening right now?" | **No AI needed** | the cell already knows exactly what each hand is doing, which part and face, and why it stopped. `situation()` turns those facts into plain sentences instantly - it's on the Machine tab. |
| Answering questions: "why did it stop?", "is this notch OK on a UB 457?", "what's on the camera?", "what should I check before reset?" | **Yes - this is where an LLM/VLM helps** | it explains in plain English from the same facts (and a camera picture). It's advisory: it can't move, start or reset anything. |

### Run it on the Jetson or in the cloud?
Your Orin Nano has **4 GB** of RAM shared by CPU and GPU, and the cell, the browser and YOLO
already use most of it. A vision-language model that can describe a camera picture usefully
needs several GB on its own, so running one **on the Jetson** would push everything else into
swap. The practical choice is to call a hosted model over the internet only when the operator
asks a question - nothing runs in the background, and nothing changes if the internet is down.

The advisor uses **Claude** (`claude-opus-5-5`, Anthropic's current default model) through the
official `anthropic` Python SDK, with low effort for quick answers. You can change the model and
effort in `config/cell.toml`.

## Switch it on

1. Install the SDK (once): `pip install --user anthropic`
2. Get an API key from the Anthropic Console and give it to the app:
   `export ANTHROPIC_API_KEY=sk-ant-...` (for the start-at-boot service, add
   `Environment=ANTHROPIC_API_KEY=...` to `deploy/beamcell.service`, or use an `EnvironmentFile`).
   Never commit the key to git.
3. In `config/cell.toml`: `[assistant]` `enabled = true`
4. Restart (`./start.sh`), then ask on the **Safety** tab. `python3 -m beamcell.doctor` checks the setup.

Each question sends: the live facts (safety state, stops, inputs, what each hand is doing,
the bar, camera zone status) and - if `send_camera = true` - the latest camera picture. Turn
`send_camera` off if pictures of people must not leave the site. Costs are per question
(a picture plus a short answer is a small amount - see Anthropic's pricing page).

## What it is told

The advisor's instructions (in `beamcell/assistant.py`) say: answer briefly from the facts,
say when it can't tell, and **never** advise bypassing, muting or defeating a stop, guard,
interlock, light curtain or E-stop, or entering the cell while it can move - if something
looks unsafe, press the E-stop and tell the supervisor.

## Later ideas (only if they earn their place)

- A YOLO model **trained on your own pictures** to find the beam's end and position on the
  bed, so the Cutter corrects for where the bar really lies (this is real value; it's vision,
  not an LLM).
- PPE detection (hi-vis, helmet) at the gate - needs a custom-trained YOLO.
- Reading drawings (PDF) to cross-check NC1 files - a good advisor task.
