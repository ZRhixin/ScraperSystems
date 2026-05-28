#!/bin/bash
set -e

# Start virtual display (needed for Playwright captcha browser)
Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99

# Wait for Xvfb to be ready before launching x11vnc.
# Previously this was `sleep 1`, which lost the race on restart and exited
# the whole script under `set -e`.
for i in $(seq 1 60); do
  [ -S /tmp/.X11-unix/X99 ] && break
  sleep 0.5
done
if ! [ -S /tmp/.X11-unix/X99 ]; then
  echo "ERROR: Xvfb did not become ready within 30s" >&2
  exit 1
fi

# Start VNC server on the virtual display (port 5900)
x11vnc -display :99 -nopw -forever -shared -quiet -bg

# Start noVNC websocket proxy (port 6080 → localhost:5900)
websockify --web=/usr/share/novnc 6080 localhost:5900 &

echo "[Scraper] Virtual display :99 ready"
echo "[Scraper] noVNC accessible on port 6080"

# Start scraper server
exec python server.py
