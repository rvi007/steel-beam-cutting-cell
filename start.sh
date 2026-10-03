#!/bin/sh
# Start the Beam Cell app. Then open http://localhost:8080 in a browser
# (or http://<this computer's address>:8080 from another computer or a tablet).
#   ./start.sh                 normal start
#   ./start.sh --camera 0      start with the USB camera on
#   ./start.sh --port 8000     a different port
cd "$(dirname "$0")" && exec python3 -m beamcell.server "$@"
