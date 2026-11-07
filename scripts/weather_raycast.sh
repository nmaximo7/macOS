#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Weather
# @raycast.mode inline
# @raycast.refreshTime 30m
# @raycast.icon ☁️

curl -s "wttr.in/?format=%c+%t"
