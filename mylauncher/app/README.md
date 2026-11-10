# app/ - the window (not built yet)

This folder is empty on purpose. In **step 2** we will add the window here: a search box, a list of
suggestions and the keyboard handling. The window will contain **no logic**: for every key you type it
will run `cli/mylauncher.py search "<text>" --json` and draw the answer; when you press Enter it will
run `cli/mylauncher.py run --id <id>`.

See `docs/03-implementation.md`, section "Roadmap", for the decisions we still have to take (which
window toolkit to use) and `docs/04-journal.md` for the step-by-step log.
