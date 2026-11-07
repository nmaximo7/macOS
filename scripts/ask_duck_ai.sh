#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Ask Duck.ai about a word
# @raycast.mode silent
# @raycast.argument1 {"type":"text","placeholder":"Enter a word or topic"}

printf 'Explain this word or topic: %s' "$1" | /usr/bin/pbcopy
open "https://duck.ai"

