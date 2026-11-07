#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Start MyMac 
# @raycast.mode silent
# @raycast.packageName Development
# @raycast.description Open Gemini in Zen

set -euo pipefail

SSH_TARGET="server"
GEMINI_URL="https://gemini.google.com"

# Launch Gemini in Zen. If Zen is closed, macOS will launch it;
# if it's already open, this sends the URL to Zen.
open -a "Zen" "$GEMINI_URL"
