# mac-maintain: maintenance manual

`mac-maintain.sh` is one command that checks your Mac, backs it up, cleans it, updates it and pushes your dotfiles. It is built to be **safe first**: by default it only *shows* what it would do.

- [1. Quick start](#1-quick-start)
- [2. The ten steps](#2-the-ten-steps)
- [3. Why it is safe](#3-why-it-is-safe)
- [4. Browser cache, logs and junk: the criteria](#4-browser-cache-logs-and-junk-the-criteria)
- [5. Backups: what the script does and what it does not](#5-backups-what-the-script-does-and-what-it-does-not)
- [6. Python: is "update everything" a good idea?](#6-python-is-update-everything-a-good-idea)
- [7. Updating macOS and apps from the terminal](#7-updating-macos-and-apps-from-the-terminal)
- [8. Git and your public dotfiles repository](#8-git-and-your-public-dotfiles-repository)
- [9. Permissions macOS will ask for](#9-permissions-macos-will-ask-for)
- [10. Configuration](#10-configuration)
- [11. Running it on a schedule](#11-running-it-on-a-schedule)
- [12. Manual tasks no script should do for you](#12-manual-tasks-no-script-should-do-for-you)
- [13. Troubleshooting](#13-troubleshooting)
- [14. What was tested, and what was not](#14-what-was-tested-and-what-was-not)
- [15. Ideas to improve it](#15-ideas-to-improve-it)

---

## 1. Quick start

1. **Put the script in your dotfiles** so it is versioned with everything else. Your repo has a stow package called `bin`; put the file where that package links its files (for example `~/macOS/bin/.local/bin/mac-maintain.sh`, adapt it to your layout) and run `stow bin`. Any folder works; stow is optional.
2. Make it executable: `chmod +x mac-maintain.sh`.
3. **Install the one tool that matters** (see section 5): `brew install rsync`.
4. **First run is a dry run** (this is the default, nothing changes):

   ```bash
   mac-maintain.sh
   ```

   Read the output top to bottom. The last block is a summary: every step is `OK`, `SKIP`, `WARN` or `FAIL`.
5. **Try the steps one by one for real**, starting with the harmless ones:

   ```bash
   mac-maintain.sh --run --only check
   mac-maintain.sh --run --only downloads      # asks before moving anything
   mac-maintain.sh --run --only cleanup        # close your browsers first
   mac-maintain.sh --run --only brew
   mac-maintain.sh --run --only backup
   mac-maintain.sh --run --only pip
   mac-maintain.sh --run --only git
   ```

6. When you trust it: `mac-maintain.sh --run` (it asks before each destructive action).

Command line:

| Option | Meaning |
|---|---|
| *(none)* / `--dry-run`, `-n` | Show what would happen. Changes nothing. **Default.** |
| `--run`, `-r` | Really do it. Asks before every destructive action. |
| `--yes`, `-y` | With `--run`: do not ask. For unattended use only. |
| `--only a,b` / `--skip a,b` | Run only / everything except these steps. |
| `--macos-install` | Allow installing macOS updates (asks first). |
| `--list-steps`, `--help`, `--version` | Information. |

Exit code: `0` all fine (warnings allowed), `1` at least one step failed, `2` wrong usage or another copy is already running.

Every run is logged in `~/Library/Logs/mac-maintain/` (the last 30 are kept). The logs contain colour codes: read them with `less -R`.

> **Never run it with `sudo`.** It refuses to start as root (it would use root's home folder). It asks for your password itself, once, only for the commands that need it.

---

## 2. The ten steps

They run in this order, and the order is deliberate: **look first, make a restore point, then change things, and publish last.**

| # | Step | What it does | Needs |
|---|---|---|---|
| 1 | `check` | macOS version, uptime, load, **disk space** of the Mac and both external drives, **memory** (available, swap, top 5 processes), battery, FileVault, SIP, Gatekeeper, firewall, date of the last Time Machine backup, whether the drives are mounted. Warns below 15 % free disk or 10 % free memory. | nothing |
| 2 | `timemachine` | `sudo tmutil startbackup --auto`: asks Time Machine for a backup now, using its existing settings and destination. Returns immediately (the backup runs in the background); `TM_BLOCK=1` waits for it. Skips if none is configured or one is already running. | sudo |
| 3 | `backup` | `rsync` mirror of `~/macOS` and `/Volumes/MacDatosMaster` to `/Volumes/MacDatosSlave/Backups/`. Details in section 5. | both drives mounted |
| 4 | `trash` | Empties the Trash through Finder (it handles locked items and every drive's trash). | Automation permission |
| 5 | `downloads` | Moves **old** items of `~/Downloads` to the **Trash**. Rules below. | nothing |
| 6 | `cleanup` | Browser caches and old user logs. Criteria in section 4. | nothing |
| 7 | `brew` | `brew update`, upgrade everything, fix missing dependencies, remove unneeded ones, clean old downloads, `brew doctor`, compare with your Brewfile. | Homebrew |
| 8 | `macos` | Lists macOS updates and App Store updates. Installs only if you ask. | nothing |
| 9 | `pip` | Updates pip and the pinned packages of `~/macOS/myPython`, runs the tests, **rolls back if anything fails**. Section 6. | the `.venv` |
| 10 | `git` | Secrets scan, then `git add -A`, `git commit -m "<date>"`, `git pull --rebase` if needed, `git push` for `~/macOS`. Section 8. | SSH key / network |

Why this order:

- **Time Machine and the rsync backup come before the cleaning and updating**, so you always have a restore point from just before the changes.
- **The Trash is emptied *before* Downloads is cleaned.** Whatever Downloads sends to the Trash stays recoverable until your *next* run: a two-stage deletion.
- **`brew` before `pip`**, because Homebrew can upgrade Python, and the script then tells you if your `.venv` needs rebuilding.
- **`git` last**, so the commit includes what `pip` and `brew` changed (a new `requirements.txt`, for instance).

### Downloads rules (`downloads`)

An item (file or folder, **top level only**) is moved to the Trash when it has not been touched for more than **30 days** (**7 days** for `.dmg`, `.pkg`, `.mpkg`, `.iso`, because installers are useless after installation).

"Touched" is the *newer* of the creation date and the modification date. A file you downloaded today but that was created years ago (an old PDF) is **not** old: the creation date on your disk is today.

Never moved:
- hidden files (`.something`);
- unfinished downloads: `.crdownload`, `.download`, `.part`, `.partial`, `.opdownload`, `.aria2`, `.tmp`;
- a folder named `_Keep` (put there anything you want to protect);
- a folder that contains **any** file modified within the limit, even if the folder itself looks old.

You can read the list (name, size, age) before confirming. Change the limits with `DOWNLOADS_DAYS` and `DOWNLOADS_INSTALLER_DAYS`.

---

## 3. Why it is safe

| Protection | How |
|---|---|
| **Dry run by default** | You must type `--run` to change anything. |
| **Asks before deleting** | Emptying the Trash, moving Downloads, emptying caches, deleting logs, removing packages and upgrading packages each ask `[y/N]`. Without a terminal and without `--yes` they are **skipped**, never assumed. |
| **Recoverable first** | Downloads go to the Trash, not into the void. |
| **A safety net for the mirror** | A file deleted or overwritten on `MacDatosMaster` is not erased from the backup: it is *moved* to `Backups/_deleted/<date>/`. Those folders are offered for removal only after 60 days. |
| **Drive guards** | The backup refuses to run if a drive is not mounted, if source and destination are the same device, if the source looks empty (the classic way to wipe a backup), or if the destination is read-only. |
| **Pip rollback** | A failed install, a failed `pip check` or a failed test restores the previous `requirements.txt` and packages. |
| **Secrets scan before every commit** | Private keys, `.env` files, API-key patterns and files larger than 50 MB stop the commit and unstage everything. The secret is never printed. |
| **No `set -e` surprises** | One failing step does not stop the others; it is reported in the summary. |
| **One copy at a time** | A lock prevents two simultaneous runs. |
| **Never as root** | It refuses to start with `sudo`. |

What a dry run does touch: only git's own bookkeeping (`git fetch` updates `.git/FETCH_HEAD`, and git refreshes its index). No file of yours is changed.

---

## 4. Browser cache, logs and junk: the criteria

You asked for the criteria that keep this safe. Here they are, as rules the script obeys.

### What is cleaned

| Item | Where | Why it is safe |
|---|---|---|
| **Chrome, Brave, Edge** caches | `~/Library/Caches/<vendor>/…` and, inside each profile (`Default`, `Profile 1`…): `Cache`, `Code Cache`, `GPUCache`, `Service Worker/CacheStorage`, `Service Worker/ScriptCache`, `DawnCache`; plus `GrShaderCache`, `ShaderCache`, `GraphiteDawnCache` | The browser rebuilds all of them. The only cost is that the next page loads a little slower once. |
| **Safari** cache | `~/Library/Caches/com.apple.Safari` (and its container cache) | Same. Needs Full Disk Access for Terminal; otherwise the script says so and goes on. |
| **Firefox** cache | `~/Library/Caches/Firefox/Profiles/*/cache2` | Same. |
| **Old logs** | files in `~/Library/Logs` older than **30 days** (including old crash reports) | Logs are only useful while you are debugging something recent. |
| **Homebrew** | `brew cleanup --prune=30` (old downloads and old versions) | Homebrew's own tool. |
| **pip cache** | only if `PIP_CACHE_PURGE=1` | Wheels get downloaded again when needed. |

### The rules that play safe

1. **Only caches, never data.** Cookies, saved logins, history, bookmarks, extensions, Local Storage, IndexedDB, sessions and sync data are never touched. (The test suite checks that `Cookies`, `Login Data` and `History` survive.)
2. **The browser must be closed.** A running browser is skipped and the summary says so. Deleting the cache of a running browser can corrupt it or make it crash.
3. **Empty the folder, keep the folder.** The cache directories themselves stay, so the browser does not trip over a missing path.
4. **Named folders only.** The script has a fixed list of paths. It never says "delete everything under `~/Library/Caches`", because that folder also holds things that are *not* safe to remove (some apps keep state there).
5. **Age limit for logs.** Recent logs stay, so you can still see what just went wrong.
6. **Show first, then ask.** You see the size per folder before confirming.
7. **User space only.** No `/System`, no `/Library`, no `/var`, no `sudo` for cleaning.

### What is deliberately **not** cleaned

- `~/Library/Caches` as a whole;
- `~/Library/Application Support`, Keychains, Mail, Messages, iCloud, Containers (except the Safari cache);
- `~/.ollama` (your models: gigabytes, but you chose them), Hugo site folders and their `resources/_gen`;
- `.DS_Store` files (harmless, and deleting them resets Finder window layouts);
- Xcode's `DerivedData`, Docker images, npm caches (add them yourself if you use them; they are safe but this is a personal choice).

### macOS "junk" worth knowing about

The Mac's own "Storage" view (*System Settings > General > Storage*) shows what takes space, with recommendations. For a deeper look use `du -sh ~/Library/* | sort -h | tail` or a tool such as OmniDiskSweeper (free) or `ncdu` (`brew install ncdu`). Do these by hand; deleting "System Data" blindly is the most common way to break an installation.

---

## 5. Backups: what the script does and what it does not

### What it does

- **Time Machine**: asks for a backup now (`sudo tmutil startbackup --auto`). `--auto` makes it behave as an automatic backup, honouring your settings (exclusions, destination, power conditions). Time Machine also runs by itself about once an hour, so this call matters mostly to get a **fresh restore point before the maintenance**.
- **Mirror to the second drive** with `rsync`:

  | Source | Destination |
  |---|---|
  | `~/macOS` | `/Volumes/MacDatosSlave/Backups/macOS-dotfiles/` |
  | `/Volumes/MacDatosMaster` | `/Volumes/MacDatosSlave/Backups/MacDatosMaster/` |

  Options with Homebrew's rsync 3: `-aHX` (permissions, times, hard links, extended attributes such as Finder tags), `--partial`, `--delete` combined with `--backup --backup-dir=…/_deleted/<date>/…`.
  Excluded: `.Spotlight-V100`, `.fseventsd`, `.Trashes`, `.TemporaryItems`, `.DocumentRevisions-V100` (macOS volume junk), and for `~/macOS`: `.venv`, `__pycache__`, `.pytest_cache` (rebuildable).

### Why Homebrew's rsync matters

Since macOS 15, Apple replaced the old `rsync` 2.6.9 with **openrsync**, a smaller implementation that accepts only a subset of options; since 15.4 the old one is gone, and users reported scripts breaking, including problems with `--backup-dir` ([Michael Tsai's summary](https://mjtsai.com/blog/2025/06/06/sequoias-new-rsync/)). The script therefore:

- uses Homebrew's rsync 3 when it finds it (`brew install rsync`), with the safe-delete mirror;
- otherwise falls back to **add-only** mode: it copies new and changed files but **never deletes** anything on the backup drive, and tells you to install the real rsync.

### What it does not do (read this)

1. **A mirror is not a history.** If you overwrite a file on `MacDatosMaster` today, yesterday's version is kept in `_deleted/` (that is what `--backup` does), but only the *previous* version of each sync, and only for 60 days. For real versions use Time Machine, or a tool such as `restic` or Arq.
2. **Two copies on drives next to the Mac are not a full backup strategy.** Fire, theft, a power surge or ransomware affect all of them. The common rule is **3-2-1**: 3 copies, on 2 kinds of media, 1 of them off-site (a cloud service such as Backblaze B2 with `restic`, or a third drive at another place). Your `~/macOS` is safe because it is also on GitHub; `MacDatosMaster` has no off-site copy.
3. **It does not check that a backup can be restored.** Once a month restore one random file from each backup (section 12).
4. **It does not verify with checksums** (`rsync -c`, slow). Run it by hand occasionally: `rsync -rcn --itemize-changes /Volumes/MacDatosMaster/ /Volumes/MacDatosSlave/Backups/MacDatosMaster/ | head`.
5. **Time Machine as a destination.** If one of your two external drives is also your Time Machine disk, `Backups/` is just another folder on it; make sure that does not fill the drive (the script warns below 15 % free).

### Restoring

- A file from the mirror: copy it from `/Volumes/MacDatosSlave/Backups/MacDatosMaster/…`.
- A deleted or overwritten file: look in `/Volumes/MacDatosSlave/Backups/_deleted/<date>/MacDatosMaster/…`.
- Your dotfiles: `git clone git@github.com:nmaximo7/macOS.git`, or copy from `Backups/macOS-dotfiles/`.

---

## 6. Python: is "update everything" a good idea?

**The naive way is not a good idea:**

```bash
pip install -U $(pip list --outdated ...)     # upgrade everything
pip freeze > requirements.txt                 # and save whatever came out
```

It upgrades every package at once to versions nobody tested together, `pip freeze` then freezes *accidental* transitive pins, and if something breaks you have no way back. It also fills `requirements.txt` with packages you do not import.

**What the script does instead** (and it fits how your project is already organised: `requirements.in` lists the 12 packages you import, `requirements.txt` is the pinned result):

1. Works **only inside `myPython/.venv`**. If there is no virtual environment it stops: it never touches the system or Homebrew Python (which is "externally managed" and refuses `pip install` anyway).
2. Saves the current `requirements.txt`.
3. Upgrades `pip`.
4. Installs **pip-tools** in the venv if missing, then runs
   `pip-compile --upgrade requirements.in -o requirements.txt`: the newest *compatible* versions of your 12 packages and their dependencies, resolved together.
5. `pip install -r requirements.txt`, then `pip check` (are all dependencies compatible?).
6. Runs `pytest`.
7. **If any of 4, 5 or 6 fails, it restores the old `requirements.txt` and reinstalls the old versions.** It shows which pins changed when it succeeds.

Because the tests are the gate, this is only as good as your tests; with your 130 tests it is a sound routine. The commit that follows (the `git` step) then contains a reviewed `requirements.txt`, and GitHub Actions re-runs the tests on Linux.

Things to know:

- `pip-compile` rewrites `requirements.txt` with `# via …` comments instead of the hand-written ones.
- **After a Homebrew Python upgrade** (the `brew` step warns you) the `.venv` can break because it points to the old interpreter. The `pip` step detects it and prints the rebuild command: `cd ~/macOS/myPython && rm -rf .venv && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`.
- **Alternative:** [`uv`](https://docs.astral.sh/uv/) (`brew install uv`) does the same job (`uv pip compile --upgrade`, `uv pip sync`) much faster. Worth a look later; the logic of this step would stay the same.
- A middle road if you want less automation: run only `pip list --outdated` (the dry run already shows it) and upgrade deliberately once a month.

---

## 7. Updating macOS and apps from the terminal

You asked whether there is something like **System Settings > General > Software Update** in the terminal. Yes:

| What | Command | Notes |
|---|---|---|
| List macOS updates | `softwareupdate --list` | No sudo. Items recommended for your Mac start with `*`. |
| Install the recommended ones | `sudo softwareupdate --install --recommended` | Add `--restart` to let it reboot when required. |
| Install everything | `sudo softwareupdate --install --all` | Includes non-recommended items. |
| Show whether macOS checks for updates automatically | `softwareupdate --schedule` | The other automatic-update options are in *System Settings > General > Software Update > (i)*. |
| App Store apps | `mas outdated`, `mas upgrade` | Needs `brew install mas`; you must be signed in to the App Store. Check that your version of `mas` works with your macOS release, since Apple changes the App Store internals often. |
| Homebrew formulae and casks | `brew update && brew upgrade` | Done by the `brew` step. |
| Casks that update themselves (Chrome, VS Code…) | `brew upgrade --greedy` | Off by default (`BREW_GREEDY=0`), because the app updates itself anyway. |
| Command Line Tools | listed by `softwareupdate --list` | Or `xcode-select --install` the first time. |

Source for the `softwareupdate` options: [DSSW reference](https://dssw.co.uk/reference/softwareupdate/) (all of them need admin rights except `--list`).

The `macos` step **lists** updates and, if you pass `--macos-install`, installs the recommended ones after asking (it may restart the Mac only with `MACOS_RESTART=1`). I would **not** install macOS updates unattended: do it when you can afford a restart, with a fresh Time Machine backup (which this script just made).

What the terminal does **not** replace: **major macOS upgrades** (for example from 26 to the next version) and some firmware updates are best done from System Settings, with the Mac plugged in.

---

## 8. Git and your public dotfiles repository

`github.com/nmaximo7/macOS` is **public**: everything committed is readable by everyone, forever (history included). So this step does more than `git add . && git commit && git push`:

1. Shows what changed (`git status`).
2. **Scans what would be committed** and refuses to commit if it finds:
   - a file named like a secret: `.env` (but `.env.example` is allowed), `id_rsa`, `id_ed25519` and friends, `*.pem`, `*.p12`, `*.key`, `*.keychain*`, `.netrc`, `.git-credentials`, `credentials.json`, `secrets.*`;
   - a **private key block**, an AWS key, a GitHub token, an OpenRouter/Anthropic/OpenAI key, a Slack token, a `TOR_CONTROL_PASS=…` value, or a quoted 16+ character value assigned to `password`, `secret`, `api_key`, `access_token`;
   - a staged file larger than 50 MB (GitHub refuses files over 100 MB).

   The message says **which file and what kind of secret**, never the value. Everything is unstaged again.
3. `git add -A` (this is what `git add .` means in a modern git: new, changed *and deleted* files), then `git commit -m "2026-10-30 11:44:38"` (the date, as you asked).
4. If the remote has newer commits (for example you edited a file on github.com): `git pull --rebase --autostash`. On a conflict it **aborts the rebase**, pushes nothing and tells you to resolve it by hand.
5. `git push`. If the network or the SSH key is unavailable it warns and keeps the commit locally for next time.

A false alarm (for example a documentation file that contains an example key) is solved by renaming the example, or once with `GIT_SCAN=0 mac-maintain.sh --run --only git`.

Two repo hygiene items I noticed on GitHub: a **`.DS_Store`** is committed at the top of your repo. The step warns about it and prints the fix: add `.DS_Store` to `.gitignore` and run `git rm -r --cached --ignore-unmatch '*.DS_Store'`. And remember what I said earlier about `ssh/.ssh`: the `config` file is fine; **never** commit `id_ed25519`.

---

## 9. Permissions macOS will ask for

| Permission | Needed for | How to grant |
|---|---|---|
| **sudo password** | `tmutil startbackup`, `softwareupdate --install` | Typed once per run, when needed. |
| **Automation: Terminal controls Finder** | Emptying the Trash and moving Downloads to it | A prompt appears the first time. If you clicked "Don't Allow": *System Settings > Privacy & Security > Automation*. |
| **Full Disk Access for Terminal** | Reading `~/.Trash` size, the Safari cache, `tmutil latestbackup` | *System Settings > Privacy & Security > Full Disk Access* > add Terminal (or iTerm). Optional: without it you only lose a size readout and the Safari cache clean-up. |
| **Removable volumes** | rsync on `/Volumes/…` | macOS may ask once to let Terminal access removable volumes. |

---

## 10. Configuration

Defaults are inside the script. To change them, copy `mac-maintain.conf.example` to `~/.config/mac-maintain/config` and keep only the lines you want, or set an environment variable for one run (`DOWNLOADS_DAYS=60 mac-maintain.sh --run --only downloads`). The file is read as shell code, so only put `NAME="value"` lines in it.

| Variable | Default | Meaning |
|---|---|---|
| `DOTFILES_DIR` | `~/macOS` | Your dotfiles repository. |
| `PYTHON_DIR`, `VENV_DIR` | `$DOTFILES_DIR/myPython`, `…/.venv` | Where the `pip` step works. |
| `SRC_MASTER`, `DST_SLAVE` | `/Volumes/MacDatosMaster`, `/Volumes/MacDatosSlave` | The two external drives. |
| `BACKUP_ROOT` | `$DST_SLAVE/Backups` | Where the mirror lives. |
| `MIRROR_DELETE` | `1` | `1`: deleted files are moved to `_deleted/` on the backup. `0`: add-only. |
| `KEEP_DELETED_DAYS` | `60` | Age after which `_deleted/` folders are offered for removal. |
| `DOWNLOADS_DIR`, `DOWNLOADS_DAYS`, `DOWNLOADS_INSTALLER_DAYS` | `~/Downloads`, `30`, `7` | Download rules. |
| `LOGS_DAYS` | `30` | Age of the logs to delete. |
| `BROWSERS` | `chrome safari firefox brave edge` | Browsers to clean. Remove the ones you do not use. |
| `PIP_CACHE_PURGE` | `0` | Also purge pip's download cache. |
| `BREW_GREEDY`, `BREWFILE_UPDATE`, `MAS_UPGRADE` | `0` | See section 7. `BREWFILE_UPDATE=1` rewrites your Brewfile (comments are lost; review the diff in git). |
| `MACOS_INSTALL`, `MACOS_RESTART` | `0` | Install macOS updates / allow a restart. |
| `TM_BLOCK` | `0` | Wait for Time Machine to finish. |
| `GIT_SCAN`, `GIT_MAX_FILE_MB` | `1`, `50` | Secrets scan on/off, size limit. |
| `MIN_FREE_PERCENT`, `SWAP_WARN_MB` | `15`, `4096` | Warning thresholds. |
| `KEEP_LOGS` | `30` | How many logs to keep. |

---

## 11. Running it on a schedule

Do **not** schedule the whole script unattended. Several steps need you (a sudo password, a Finder permission, a restart), and `--yes` removes every question.

What is reasonable:

- **Manually, about once a week**: `mac-maintain.sh --run`. Takes minutes, and you see what happens.
- **Automatically, only the read-only and low-risk steps**, with `launchd`. Example: every Sunday at 10:00 run the health check and push the dotfiles. Save this as `~/Library/LaunchAgents/com.nmaximo7.mac-maintain.plist` (change the path):

  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
    <key>Label</key><string>com.nmaximo7.mac-maintain</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/nmaximo7/macOS/bin/.local/bin/mac-maintain.sh</string>
      <string>--run</string><string>--yes</string>
      <string>--only</string><string>check,git</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>/tmp/mac-maintain.out</string>
    <key>StandardErrorPath</key><string>/tmp/mac-maintain.err</string>
  </dict>
  </plist>
  ```

  Load it with `launchctl load ~/Library/LaunchAgents/com.nmaximo7.mac-maintain.plist`. Unattended `git` needs the SSH key in the agent/Keychain (your `~/.ssh/config` already has `UseKeychain yes`). macOS may ask for permissions the first time.
- `brew upgrade`, `pip` and `macos` are better with you watching: an upgrade that breaks something at 3 a.m. is no fun.

---

## 12. Manual tasks no script should do for you

| When | Task |
|---|---|
| **Monthly** | **Test a restore**: copy one random file back from each backup (Time Machine, `Backups/MacDatosMaster`). A backup you never restored is a hope, not a backup. |
| Monthly | Check drive health: *Disk Utility > First Aid* on each volume. For SMART data of external drives install `smartmontools` (`brew install smartmontools`, then `sudo smartctl -a /dev/diskN`); not every USB enclosure passes SMART through. |
| Monthly | Restart the Mac. It clears memory and applies pending updates. |
| When a major macOS release appears | Upgrade from System Settings, after a fresh backup and after checking that your key tools support it (Homebrew, Python, Ollama, Hugo). |
| When prompted | Updates of apps that update themselves (Chrome, Office, Adobe, Docker Desktop…) and firmware. |
| Every few months | Review **Login Items** (*System Settings > General > Login Items & Extensions*), installed apps you no longer use (`brew list --cask`, `/Applications`), browser extensions, and what takes space (*Settings > General > Storage*). |
| Every few months | Update your Ollama models: `ollama list`, then `ollama pull <model>` for those you use. Remove unused ones with `ollama rm <model>` (they are several GB each). |
| Every few months | Rotate secrets that were ever shared or pasted anywhere (you pasted `TOR_CONTROL_PASS` in chat earlier; change it). Review the SSH keys in GitHub *Settings > SSH keys*. |
| Before travelling or selling the Mac | Full backup, then *System Settings > General > Transfer or Reset*. |
| Yearly | Review the 3-2-1 plan: is there an off-site copy? |
| Always | Keep a bootable/recovery plan: know your Apple Account, FileVault recovery key and where they are stored. |

---

## 13. Troubleshooting

| You see | Meaning and fix |
|---|---|
| `Do not run this script with sudo` | Run it as yourself. |
| `Another mac-maintain.sh is already running` | A second copy, or a stale lock after a crash: it removes stale locks by itself; if it persists run `rm -rf "${TMPDIR:-/tmp}/mac-maintain.lock"`. |
| `… is not mounted: backup skipped` | Plug in and unlock the drive. Check the exact name in `/Volumes` and set `SRC_MASTER`/`DST_SLAVE` if it differs. |
| `looks EMPTY: refusing to mirror an empty source` | The drive shows up but has no files (wrong volume, or not unlocked). Nothing was changed. |
| `same device` | Both paths are on the same disk. Fix the paths. |
| `only Apple's limited rsync was found` | `brew install rsync` (then the script uses `/opt/homebrew/bin/rsync`). |
| rsync code 23 or 24 | Some files could not be read or vanished during the copy (open files, permissions). Usually harmless; check the log. |
| `Finder could not empty the Trash` | Allow Terminal to control Finder (section 9). |
| `no Time Machine backup found (or Terminal lacks Full Disk Access)` | Either you have none, or Terminal cannot read the backup list. |
| `firefox is running: its cache is skipped` | Close the browser and run `--only cleanup` again. |
| `brew upgrade reported errors` | Read the log, then run `brew doctor` and the failing command by hand. |
| `Python is among them: your virtual environment may need rebuilding` | Expected after a Python upgrade; the `pip` step prints the rebuild command. |
| `pip-compile failed` | A dependency conflict among the new versions. The old `requirements.txt` is untouched. Pin the culprit in `requirements.in` (e.g. `package<2`). |
| `tests FAILED with the new versions … rolled back` | An upgrade broke something. Look at the log, then upgrade packages one by one to find which. |
| `secrets scan blocked the commit` | Read which file and kind of secret it names. Remove the file or add it to `.gitignore`; `git status` shows the state (everything is unstaged). |
| `pull --rebase failed (conflict?)` | The same file changed locally and on GitHub. Resolve it in `~/macOS` by hand. |
| `cannot reach the remote` | Offline, or the SSH key is not unlocked. Run `ssh -T git@github.com` to see. |

---

## 14. What was tested, and what was not

I wrote and tested the script in a Linux sandbox with a fake home folder, fake drives, a local "remote" repository and **stand-in versions of the macOS commands** (`tmutil`, `osascript`, `brew`, `softwareupdate`, `rsync`, `sysctl`, `vm_stat`…). 47 automated checks pass, among them:

- a dry run changes no file and calls no command that changes anything;
- without a terminal and without `--yes`, nothing destructive happens; with a terminal, `n` skips and `y` proceeds;
- Downloads: only the right items move (hidden, `_Keep`, unfinished downloads, recent items and folders with recent content stay; names with spaces work);
- caches are emptied but `Cookies`, `Login Data` and `History` survive; a running browser is skipped; recent logs stay;
- backup guards (unmounted, same device, empty source), rsync exit codes 23 and 12, the openrsync add-only mode;
- pip: success, compile failure, `pip check` failure and test failure each restore the old `requirements.txt`;
- git: commit and push with a date message, `.env`, a private key, an OpenRouter-style key and an oversized file are blocked and not echoed, `.env.example` is allowed, rebase on a newer remote, conflict aborts, unreachable remote;
- bad options, `--skip`, lock handling, refusal to run as root.

**Not tested (I had no Mac and no internet beyond my sandbox):**

- the real macOS tools: the `osascript` Finder calls, `tmutil`, `softwareupdate`, `mas`, real Homebrew and the real rsync 3 flags (they are standard rsync 3 flags, but I could not run them);
- `bash` 3.2 itself (the one macOS ships); I avoided the newer-bash features I know of, but **ShellCheck** was not available either;
- a real Time Machine or external drive.

So: **start with the dry run, then try one step at a time with `--run --only …`**, as in section 1. If something fails, send me the log (`less -R ~/Library/Logs/mac-maintain/<latest>.log`) and I will fix it.

---

## 15. Ideas to improve it

Ordered by how much they would help you:

1. **An off-site backup.** `restic` to Backblaze B2 (or any S3 storage) for `MacDatosMaster` and `~/macOS`: encrypted, versioned, deduplicated. This closes the biggest hole (section 5).
2. **Notifications.** Finish with `osascript -e 'display notification "Maintenance done: 2 warnings" with title "mac-maintain"'` so a scheduled run tells you the result.
3. **`brew bundle` as the source of truth.** Keep the Brewfile current (`BREWFILE_UPDATE=1`, review the git diff) so a new Mac is `brew bundle` away from your setup.
4. **`uv` instead of pip-tools** for much faster Python updates.
5. **Pre-commit hook for secrets.** Install `gitleaks` (`brew install gitleaks`) as a hook in `~/macOS`, so even manual commits are scanned. The script's scan would remain a second net.
6. **Real SMART monitoring** with `smartmontools` for the internal and external drives, and a warning in `check`.
7. **Disk-usage report**: top 10 folders under `$HOME` (`du`) in the `check` step, to see where space goes.
8. **Hugo/Ollama housekeeping**: `ollama list` sizes in the report; `hugo --gc` for the site cache.
9. **Dev caches** (Xcode `DerivedData`, `npm cache clean`, Docker `system prune`) as opt-in steps if you use those tools.
10. **A `--report` mode** that writes a one-page Markdown summary (disk before/after, what changed in Homebrew and pip) you can keep in `~/macOS/docs/`.
11. **GitHub Actions** (you already have it for `myPython`) could also run `shellcheck` on this script on every push: add a step `shellcheck bin/.local/bin/mac-maintain.sh` to a workflow.
12. **Rotate the backup layout** (`Backups/MacDatosMaster` plus weekly snapshots using `rsync --link-dest`) to get real versions without extra tools: more complex, and a good reason to look at restic instead.

---

*Sources used for this manual: [`tmutil` options (Eclectic Light Company)](https://eclecticlight.co/2017/05/27/taking-charge-of-time-machine-backups-backing-up-on-demand/), [the rsync change in macOS 15 (Michael Tsai)](https://mjtsai.com/blog/2025/06/06/sequoias-new-rsync/), [`softwareupdate` reference (DSSW)](https://dssw.co.uk/reference/softwareupdate/).*
