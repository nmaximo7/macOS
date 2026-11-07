# Hugo Content Toolkit

A Python toolkit that **reviews, enriches and quality-checks Markdown pages of a Hugo website** using a local LLM (Ollama) and the live Hugo server. It also includes a "daily dashboard" script (calendar, quote, weather, RSS news, stock prices) and a small OpenRouter client (API key kept in the system keychain).

> **Documentation status (v0.18).** Written from the source of all 16 files, the real `requirements.txt` and the real `.env`. Since v0.4 (batch 1), v0.5 (batch 2), v0.6 (batch 3), v0.7 (batch 4), v0.8 (batch 5), v0.9 (batch 6), v0.10 (batch 7) v0.11 (batch 8), v0.12 (batch 9), v0.13 (batch 10) v0.14 (batch 11) and v0.15 (batch 12), v0.16 (batch 13) v0.17 (batch 14) and v0.18 (batch 15) the README also tracks the code fixes made one by one: see the [progress tracker](#progress-tracker).
> Since v0.10 the `.env` contains **only variables that the code reads** (the 8 unused ones were removed, see [section 6.2](#62-variables-removed-from-env-in-v010)).

![Tests](https://github.com/nmaximo7/macOS/actions/workflows/tests.yml/badge.svg)

---

## Progress tracker

Fixes are applied little by little. This table is updated after every batch (`[x]` done, `[ ]` pending). Items refer to [section 12](#12-known-issues-and-code-observations).

**Batch 1: `util.py` (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `normalize_string` raised `NameError` | Added `import re`. |
| [x] | `quote` and `yfinance` imported at the top | Now imported **inside** `select_quote()` and `stocks()`. If a package is missing, a yellow notice is printed and the function returns `None`; nothing else breaks. `util`, `myollama` and the front-matter check no longer need those two packages. |
| [x] | `display_alarm_color` defined twice | Duplicate removed (one definition left). |
| [x] | `display_message` silently wrote `my_output.md` | Now writes **only** with `display_message(text, save_to_file=True)`; new optional `filename` argument and constant `OUTPUT_MARKDOWN`; `clear_output_markdown(filename=...)` uses the same constant. No other file in the project called `display_message`, so nothing else changes. |

Checked by compiling the file, importing it with `quote` and `yfinance` blocked, and calling each changed function.

**Batch 2: corrupted emoji `�` (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `util.py` | Default emoji of `display_alarm_color` is now `⚠️`. |
| [x] | `greetings.py` | 4 emoji restored (RSS feeds 📡, feed title 📰, link 🔗, weather 🌤️). |
| [x] | `link_checker_page.py` | 21 emoji restored (progress 🔍 📄 🌐 🔗 🖼️, summary 📊, issue types 🤖 bot blocked, 🔥 server error, 🔌 connection error, 📁 missing file, 🎉 all passed). |

The original emoji were lost when the files were saved with the wrong encoding, so the new ones are chosen from the surrounding text; change them freely. All three files are UTF-8, contain no `U+FFFD` any more and compile. Tip: set your editor to **UTF-8** and never re-save these files in another encoding.

**Batch 3: `greetings.py` cleanup (done)**

| | Item | What was changed |
|---|---|---|
| [x] | Bare `except:` in `get_weather` | Now `except requests.RequestException:` (no network, timeout, DNS...). Other errors are no longer hidden. |
| [x] | `.env` loaded inside `news()` | `news()` now uses `get_settings().rss_feed_urls` from `myconfig.py`. `greetings.py` no longer imports `os` or `dotenv`. `myconfig.Settings` has a new field `rss_feed_urls` (tuple, split on whitespace like before). An invalid number elsewhere in `.env` is reported as a red message instead of crashing the dashboard. |
| [x] | `Fore.BLACK` unreadable on dark terminals | Replaced by `Fore.LIGHTBLACK_EX` (grey) in `greetings.py` (3), `util.py` (2) and `myollama.py` (1). |

Checked by compiling and running `news()`, `get_weather()` and `get_settings()` with stand-in packages (no network): feeds parsed correctly including an inline `# comment`, offline weather prints the yellow notice and returns `False`, missing feeds and an invalid `OLLAMA_TIMEOUT` give friendly messages.

**Batch 4: `content_creation.py` rewrite (done)**

| | Item | What was changed |
|---|---|---|
| [x] | Hard-coded page path | The page is now a command-line argument: `python3 content_creation.py PAGE.md`. Without it you get a usage message (exit code 2). |
| [x] | Results ignored, "All checks passed!" always printed | Every check's result is collected. `check_links`, `check_images` and `check_render` return a count (`0` fine, `>0` problems, `-1` could not run); `frontmatter`, `latex` and `quotes` only make proposals. A summary table and an honest verdict are printed at the end. |
| [x] | No exit code | `0` = clean, `1` = something needs attention (problems, a check that could not run, or a crash), `2` = wrong usage. Useful for scripts and git hooks. |
| [x] | One failure stopped everything | Each check is isolated: if one raises an exception (e.g. Ollama not running) it is shown in the summary and the others still run. Modules are imported only when their check runs. |
| [x] | Pointless call | The `page_frontmatter(...)` call whose result was discarded was removed. |
| [x] | Relative paths (added in v0.7.1) | `python3 content_creation.py content/calculus/maxwellfaraday.md` failed when run from another folder (`page not found`). The page is now looked up as written, then in `HUGO_ROOT/<path>`, then in `HUGO_ROOT/content/<path>`, so `content/calculus/page.md` and `calculus/page.md` both work from anywhere. If nothing is found, the message lists every place tried. |
| [x] | New options | `--only CHECK...`, `--skip CHECK...` and `--hide-ok`. Check names: `frontmatter latex links images quotes render`. |

Checked with stand-in versions of the six check modules: all fine (exit 0), links with 2 problems + render that cannot run + a crashing LaTeX check (exit 1, remaining checks still ran), `--only`/`--skip`/`--hide-ok`, missing file and unknown check name (exit 2). It has **not** yet been run against your real Hugo server.

**Batch 5: `openrouter.py` and the API key in the keychain (done)**

| | Item | What was changed |
|---|---|---|
| [x] | Key written in the source | The key is saved with `python3 openrouter.py --set-key` (hidden prompt) in the system keychain through `keyring`; read with `get_api_key()`. Fallback: environment variable `OPENROUTER_API_KEY`. Remove it with `--delete-key`. |
| [x] | Request made on import | Everything is inside functions; `ask_openrouter()` returns `(text, model_used)`; `cli()` is called only from `__main__`. |
| [x] | No timeout, no error handling | 60 s timeout; clear messages for no key, bad key (401), no credits (402), rate limit (429), timeout, no connection, unexpected answer; exit code `1` on error. The key never appears in any message. |
| [x] | New dependency | `keyring` added to `requirements.txt` (pinned to `keyring==25.7.0` in batch 10). |

Checked with stand-in `keyring` and `requests` packages (no real network, no real Keychain): import makes no request; no key, env fallback, `--set-key` (spaces stripped), success, 401, 429, timeout, no connection, odd answer, HTML error page, broken keychain and `--delete-key` twice all behave as described; the secret never appeared in any output. It has **not** yet been tried against the real OpenRouter or the real macOS Keychain.

**Batch 6: `.env.example` and `.gitignore` (done)**

| | Item | What was changed |
|---|---|---|
| [x] | No template | `.env.example` created: every variable read by the code (`HUGO_SERVER`, `HUGO_ROOT`, `BASE_URL`, `MYMODEL_QUERY`, `MODELS_NEWCONTENT`, `OLLAMA_TIMEOUT`, `OLLAMA_NUM_CTX`, `TOPIC`, `NUMBER_QUOTES`, `FORTUNES_PATH`, `QUOTE_SOURCES`, `RSS_FEED_URLS`) with default, meaning and format rules; the 8 variables nobody reads are listed commented out and clearly separated. No secrets. |
| [x] | Nothing protected `.env` | `.gitignore` created: `.env`, `.env.*` (except `.env.example`), caches, virtual environments, `my_output.md`, editor files. |
| [x] | Passwords and keys | The template says the OpenRouter key belongs in the keychain and that `TOR_CONTROL_PASS` would also be safer there. |
| [x] | Your real `.env` | Cleaned in batch 7 (below). |

**Batch 7: your real `.env` cleaned (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `NUMBER_QUOTES=30` | Now `7`, as you decided. |
| [x] | Unused variables | Deleted: `REQUEST_TIMEOUT`, `MODEL`, `MYMODEL_FRONTMATTER`, `MYMODEL_SUMMARIZE`, `SEARX_URL`, `MAX_RESULTS`, `MAX_RETRIES`, `TOR_CONTROL_PASS`. The new `.env` was built from your file: every other line, value and comment is unchanged, and the Tor password is not in it. |
| [x] | Template | The "not read" block was removed from `.env.example`. |
| [x] | Your pasted values (v0.10.1) | The real `.env` is now built on the documented template, with your values: `HUGO_ROOT`, `MYMODEL_QUERY=qwen3.8:27b`, `FORTUNES_PATH` and the new news feeds (`RSS_FEED_URLS`: TechCrunch and BBC; the New York Times feed is gone). `.env.example` stays generic (placeholders) so it is safe to commit. |
| [ ] | **To confirm** | Three values in your pasted text differed from what you had chosen before; I kept your earlier choices: `NUMBER_QUOTES=7` (pasted: 3, the template default), `MODELS_NEWCONTENT="qwen3.8:27b qwen2.5-coder:1.5b"` (pasted: `qwen3:32b gemma3:27b`, which may not be installed) and `QUOTE_SOURCES="file fortune library zenquotes dummyjson"` (pasted: `file fortune`). Edit those three lines if you meant the pasted ones. |

Checked by loading the new `.env` through `myconfig.load_settings()`: `number_quotes` is 7, both models, the three feeds and the five quote sources parse correctly. **Keep your old `.env` until you have tried the new one**, then delete it.

**Batch 8: personal values moved to `.env` (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `AUTHOR`, default featured image (`content_frontmatter.py`) | Now `AUTHOR` and `FEATURED_IMAGE` in `.env` (read through `myconfig`). If `AUTHOR` is not set, the page's own `author:` is kept in place; if `FEATURED_IMAGE` is not set, none is proposed. |
| [x] | Default fortunes path (`myconfig.py`) | The personal default was removed; no `FORTUNES_PATH` means the `file` source is skipped with a clear note. Docstrings updated. |
| [x] | Weather city "Malaga" and Spanish (`greetings.py`) | `WEATHER_CITY` and `WEATHER_LANG` (default `en`); no city = wttr.in guesses from your IP; spaces in city names are encoded. |
| [x] | Ten stock tickers (`util.py`) | `STOCK_TICKERS` in `.env`; `stocks(tickers=None)` also accepts a list; `util.py` still does not need `myconfig` to import. |
| [x] | `hugo_root` / `base_url` in `link_checker_page.py` | Default to `HUGO_ROOT` / `HUGO_SERVER`; friendly message if they are not set. |
| [x] | Your `.env` and the template | Your real `.env` now has `AUTHOR`, `FEATURED_IMAGE`, `WEATHER_CITY=Malaga`, `WEATHER_LANG=es`, `STOCK_TICKERS` with your previous values, so **nothing changes for you**. `.env.example` has placeholders. |

Checked with stand-in packages (no network): defaults with an empty `.env`, values from `.env` (accents, comma in the author, lower-case tickers, `San Francisco`), 8 front-matter cases (author/featured image set, unset, page's own, different author), quotes without `FORTUNES_PATH`, the exact weather URL for four cases, stocks from `.env` / default / argument, and the link checker with and without `HUGO_ROOT`: all 26 checks pass. Not yet run against your real Hugo, Ollama, wttr.in or Yahoo Finance.

**Batch 9: prompts and requirements (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `mymessages.py` | Reduced to the two prompts that make sense: `query_expand` (default) and `check_proof`. Removed `assistant_msg`, `myuser_msg`, `query_frontmatter`, `query_msg`, `query_summarize`; fixed the stray `"\n."`; added a docstring on how to add prompts. The text of the kept prompts is unchanged (checked). |
| [x] | `myollama.py` docs | The examples mentioned a `query_definition` prompt that never existed; they now use `check_proof`. No code change. |
| [x] | `requirements.txt` | Removed the deprecated `dotenv==0.9.9` shim (`python-dotenv` provides `import dotenv`). `gazpacho` was kept then (since removed in v0.16): I checked, and `quote` is "powered by gazpacho" without declaring it, so removing it would probably break `util.select_quote`. |
| [x] | `requirements.in` | New: the 12 packages the project imports, each with who uses it, plus how to rebuild the pinned list with `pip-compile`. Cross-checked: every one of them is in `requirements.txt`. |
| [x] | `lxml` | Resolved in batch 10: `pip show lxml` says `Required-by: yfinance`, so it stays. |
| [x] | `keyring` pin | Pinned to `keyring==25.7.0` in batch 10. |

Checked by importing `mymessages`/`myollama` with stand-in packages: `available_prompts()` returns exactly `check_proof` and `query_expand`, the default prompt resolves, and asking for a removed name (`query_msg`) gives the friendly "unknown prompt... Available prompts: check_proof, query_expand" message. Package metadata could not be read from PyPI directly from my sandbox; the `quote`/`gazpacho` conclusion comes from the package's PyPI page.

**Batch 10: your answers, `.env` audit and `link_checker_page.py` (done)**

| | Item | What was changed |
|---|---|---|
| [x] | `keyring` | Pinned: `keyring==25.7.0` in `requirements.txt` (the version you reported). |
| [x] | `lxml` | You ran `pip show lxml`: `Required-by: yfinance`. It stays; the README no longer calls it unused. |
| [x] | `.env` audit | Compared the 17 variables the code reads with the 15 active keys of your `.env`: nothing missing, nothing stale, and `.env` and `.env.example` have exactly the same keys. The only two variables not present, `OLLAMA_TIMEOUT` and `OLLAMA_NUM_CTX`, are optional (defaults 600 s and Ollama's own) and appear commented out in both files, so **no change to `.env` was needed**. If you meant a specific edit, tell me which. |
| [x] | Internal links | Links to your own site are now looked up as files in `public/` (exact capitals, `index.html`, `.html`, URL-decoding, no escaping `public/`). Before, they were turned into `http://` URLs and fetched like external sites, and the file branch was only reached by `data:`/`ftp:` URLs, which it wrongly reported as missing. New `--live` option keeps the old "ask the server" behaviour. |
| [x] | Usage text and exit codes | `python3 link_checker_page.py <path>` (it said `check_page.py`); exit code 0 / 1 / 2. |
| [x] | Issue list | Broken images and unusual statuses were counted in the summary but not listed; now they are. |

Checked with stand-in `requests`/`bs4` and a fake built site: own links (absolute, relative, with `#fragment`, without trailing slash, absolute with your own host) found; wrong capitals, missing pages and a `%2e%2e` traversal reported missing; `mailto:`, `#x` and `data:` skipped; external links requested (4 requests only in default mode, all 12 with `--live`); exit codes 1 and 2. Not yet run against your real `public/` folder.

**Batch 11: shared helpers made public, docstring fixed (done)**

| | Item | What was changed |
|---|---|---|
| [x] | Private helpers imported across modules | `_read_lines`, `_front_len` and `_make_ssl_context` of `content_urls.py` were imported by `content_render.py` and `content_quotes.py`. They are now public: `read_lines`, `front_len`, `make_ssl_context`, and the three files use the new names. `_unquote_value` and `_fields_of` are used only inside `content_urls.py`, so they stay private. |
| [x] | Old names | Kept as one-line aliases at the end of `content_urls.py` in case another script of yours imports them (`_read_lines = read_lines`...). They are the very same objects. |
| [x] | `check_browser_results` docstring | An assignment came before the docstring, so Python did not treat it as one. Swapped the two lines; no change in behaviour. |

Checked by loading the old and the new `content_urls.py` side by side: `read_lines` / `front_len` return exactly the same on four test pages (normal, BOM + Windows line endings, no front matter, unclosed front matter), `scan_page` finds the same 3 references, `_fields_of` returns the same fields, the SSL context is built, the aliases are the same objects, and `content_quotes` and `content_render` import correctly. Pure renaming: no behaviour change expected.

**Batch 15: AI rewrite with OpenRouter, and "latest page" by default (done, v0.18)**

| | Item | What changed |
|---|---|---|
| [x] | `content_expand.py` (new, 16th file) | `expand_article(page)`: sends the article **without front matter** to a model with the `expand_article` prompt, cleans the answer, runs a **quality gate** (placeholders, shorter than the original, lost or invented links/images, changed shortcodes, wrong math delimiters), saves a copy **outside `content/`** and prints the Markdown to copy. Optional `--copy` (clipboard). |
| [x] | `mymessages.py` | New prompt `expand_article` (your wording: "fully rewritten, highly expanded, and polished ... copy and paste directly ... no placeholders ... every single step"). The prompt lookup (`available_prompts`, `resolve_prompt`) moved here so `myollama` and `openrouter` share it; `myollama` keeps the same two functions as wrappers. |
| [x] | `openrouter.py` | New `call_openrouter(content, prompt="...")`, the OpenRouter twin of `call_ollama`; `ask_openrouter` accepts `temperature` and `max_tokens`; `--system NAME` on the command line. |
| [x] | `myconfig.py` / `.env.example` | New variables `OPENROUTER_MODEL`, `OPENROUTER_TIMEOUT`, `OPENROUTER_MAX_TOKENS`, `EXPAND_PROVIDER`, `EXPAND_OUTPUT_DIR`. |
| [x] | `content_creation.py` | The page is **optional**: `python3 content_creation.py` picks the most recently modified Markdown file of `HUGO_ROOT/content` and tells you which. New last step `expand`; new options `--provider`, `--model`, `--temperature`, `--copy`, `--no-save`, `--include-index`. |
| [x] | `tests/` (216 tests, 86 new) | Cleaning, quality gate, output folder safety, provider wiring, OpenRouter payload, latest-page search, CLI options, settings. Deliberately broken code was caught by the tests in 12 of 12 trials (two weak tests were first found and strengthened). |

Checked end to end with a stand-in OpenRouter: `content_creation.py --only expand` with no page chose the newest of two pages, sent only the body, removed the "Here is the rewritten article:" line and saved the file. **Not tested against the real OpenRouter** (no key or network here): first run it on a short page.

**Batch 14: CI and your `.env` values (done, v0.17)**

| | Item | What changed |
|---|---|---|
| [x] | CI | `.github/workflows/tests.yml` (at the **root** of the `macOS` repo, not inside `myPython`) runs `python -m pytest` on Ubuntu with Python 3.12 whenever `myPython/**` changes. First run: green, 34 s. Your Mac: 130 passed. |
| [x] | `.env.example` | Your confirmed values: `NUMBER_QUOTES=7`, `MODELS_NEWCONTENT="qwen3.8:27b qwen2.5-coder:1.5b"`, `QUOTE_SOURCES="file fortune library zenquotes dummyjson"`. |
| [x] | `ssh/.ssh` check | Only `config` is versioned (host entries and the *path* of the key, no key). |

**Batch 13: one quote engine (done, v0.16)**

| | Item | What changed |
|---|---|---|
| [x] | `content_quotes.py` | New `pick_daily_quote()` / `daily_quote()`: one random quote without a page, from the same `QUOTE_SOURCES`, any topic, same length/author filter; a failing source only produces a note. |
| [x] | `util.select_quote` | Uses it (lazy import) and prints text + author in cyan, or a yellow "No quote today" notice. |
| [x] | Dependencies | `quote` and `gazpacho` removed from `requirements.in`, `requirements.txt` and `pyproject.toml` (12 packages). You can run `pip uninstall quote gazpacho`. |
| [x] | `tests/` | +7 tests (130): daily quote, failing/unknown sources, `util` no longer imports `quote`. |

**Batch 12: tests and `pyproject.toml` (done)**

| | Item | What was added |
|---|---|---|
| [x] | `tests/` (130 tests) | `unittest`-style classes, so they run with `python3 -m pytest` **and** with plain `python3 -m unittest discover -s tests -t .`. No network, no Ollama, no Hugo: each test builds a throw-away site in a temporary folder or sets environment variables. Your `.env` is never read. |
| [x] | What is covered | `test_latex.py` (`fix_math`, `_convert_line`), `test_quotes.py` (`parse_fortunes`, `Quote.as_fortune`, `resolve_topic`), `test_urls.py` (`_content_url_path`, `page_url`, `scan_page`, `front_len`, URL encoding), `test_frontmatter.py` (`_clean_*`, YAML quoting, `_build_blocks` with and without `AUTHOR` / `FEATURED_IMAGE`), `test_config.py` (`load_settings`: defaults, values, invalid numbers), `test_paths.py` (`find_page`, exit codes and summary of `content_creation`, `local_file_for`). |
| [x] | `pyproject.toml` | Metadata, Python >= 3.11, the 12 dependencies, a `dev` extra with `pytest`, and the pytest settings. Running the scripts from the folder works exactly as before. |

Checked here with stand-in packages (`rich`, `ollama`...) and `unittest` (**pytest itself could not be installed here**): all 130 pass, and deliberately breaking `_urlize` and the fortune separator made 2 and 4 tests fail. **Not yet run on your machine** with the real packages (`content_latex.py` must be in the project folder, the tests import it): run `python3 -m pytest` and tell me if anything fails; it would be either a test assumption or a real bug.

**Still pending (suggested order)**

| | Item | Section 12 |
|---|---|---|
| | *Nothing pending.* Ideas for later: expand very long articles section by section, a diff/apply mode, retries, tests for the network parts with a fake local server, async link checking. | |

---

## Table of contents

0. [Progress tracker](#progress-tracker)
1. [What the project does](#1-what-the-project-does)
2. [Key design principles](#2-key-design-principles)
3. [Architecture](#3-architecture)
4. [Project structure](#4-project-structure)
5. [Installation, step by step](#5-installation-step-by-step)
6. [Configuration: the `.env` file](#6-configuration-the-env-file)
7. [Dependencies and why each one is needed](#7-dependencies-and-why-each-one-is-needed)
8. [Quick start and usage](#8-quick-start-and-usage)
9. [Module reference (every file, every function)](#9-module-reference)
10. [Understanding the reports](#10-understanding-the-reports)
11. [Troubleshooting](#11-troubleshooting)
12. [Known issues and code observations](#12-known-issues-and-code-observations)
13. [Improvements and future releases](#13-improvements-and-future-releases)
14. [Documentation roadmap](#14-documentation-roadmap)

---

## 1. What the project does

You write articles as Markdown files in a Hugo site (the author's site is *justtothepoint*: calculus, programming, technology tutorials). Before publishing a page, you run the toolkit on it. It:

| Step | Function | What it tells you |
|---|---|---|
| 1 | `check_hugo_frontmatter` | Proposes a complete front matter (title, keywords, categories, description, date...) generated by an LLM; changed values are shown in red. |
| 2 | `check_latex` | Shows which lines contain math that should be wrapped or repaired in LaTeX (`x²` → `$x^2$`, `sin(x)` → `$\sin(x)$`, `<sup>`/`<sub>` → `^`/`_`, ...). |
| 3 | `check_links` | Checks every link (internal, external, `#anchors`, Hugo `ref`/`relref`, and links added by the theme). |
| 4 | `check_images` | Checks every image is really served and really an image (not an HTML error page), size, alt text, case-sensitivity and sync problems. |
| 5 | `provide_quotes` | Proposes fresh, on-topic quotes (with authors) from your fortunes file, the `fortune` command, a Python library or online APIs. |
| 6 | `check_render` | Looks at the **final page** served by Hugo (HTTP + optionally a real headless Chromium): math engine, formulas intact/typeset/fitting, console errors, leftovers, HTML structure. |

**Everything is read-only.** The tools only print proposals and reports; they never modify your Markdown (the only optional files written are a screenshot you explicitly ask for and, if you call `util.display_message(..., save_to_file=True)`, `my_output.md`).

Extras: `myollama.py` (one question to one or many Ollama models), `greetings.py` (daily dashboard), `link_checker_page.py` (older standalone checker for the built `public/` folder), `openrouter.py` (hosted-LLM client; key in the keychain), `util.py` (terminal helpers, quotes, stocks).

## 2. Key design principles

- **One configuration point**: `myconfig.py` reads `.env` once (cached singleton) and builds the shared Ollama client. Importing it never fails; errors appear only when settings are first requested.
- **Read-only and safe**: results are printed with [Rich](https://github.com/Textualize/rich); you copy what you like.
- **Your real environment, not guesses**: pages are checked against the *running Hugo server* (possibly another computer, kept in sync with Syncthing), so you see what visitors see.
- **Friendly failures**: missing settings, unreachable servers or missing models produce explanatory messages, often with the command to fix them.
- **Each module is also a script**: every `content_*.py` can be run directly with a page path.

## 3. Architecture

```
                         .env  ──►  myconfig.py  (Settings + Ollama client, cached)
                                        │
        ┌───────────────────────────────┼─────────────────────────────┐
        ▼                               ▼                             ▼
  myollama.py  ◄── mymessages.py   content_urls.py  (shared engine)   content_quotes.py
  (LLM calls)      (system prompts)   │  PageContext · Checker · scan_page · run_check
     │    ▲                           ├──► content_links.py   check_links()
     │    │                           ├──► content_images.py  check_images()
     ▼    │                           └──► content_render.py  check_render()
  util.py ┘  (terminal helpers,
   │          quotes, stocks)
   │  content_frontmatter.py  check_hugo_frontmatter()  ──► myollama.py
   │
   └──► greetings.py  today()

  content_latex.py  check_latex()      (standalone: only Rich)
  content_expand.py   expand_article()  ──► openrouter.py (hosted) or myollama.py (local), prompt from mymessages.py
  content_creation.py  main(page)      runs the seven steps, prints a summary, returns an exit code
  link_checker_page.py                 (standalone, legacy)
  openrouter.py                        (standalone; key from the system keychain via keyring)
```

**Import chain:** `content_frontmatter` → `myollama` → `util`. Since v0.4, `util.py` imports `content_quotes` and `yfinance` only inside `select_quote()` and `stocks()` (the daily dashboard), so the content checks run without them.

**Typical flow of `check_links` / `check_images`:** `scan_page` (find refs in Markdown, skipping code and comments) → `PageContext.resolve` (turn each into an absolute URL or "skip") → read the page as the server renders it to add theme links/images → `Checker.run` (parallel HTTP, cached) → a `judge_*` function turns each response into a `Verdict` → `print_evaluation` prints the report.

## 4. Project structure

```
.
├── content_creation.py      # Runs the seven steps on one page (or the latest modified one): summary + exit code
├── content_expand.py        # expand_article(): AI rewrite of the article, quality gate, saved outside content/
├── content_frontmatter.py   # LLM-proposed front matter (title, keywords, categories, description)
├── content_images.py        # Are all images really visible? (judge + check_images)
├── content_latex.py         # Detects/repairs LaTeX candidates in prose and math
├── content_links.py         # Do all links work? (judge + check_links)
├── content_quotes.py        # Proposes fresh quotes (fortunes, fortune cmd, library, online APIs)
├── content_render.py        # Checks the final served page (HTTP + optional browser)
├── content_urls.py          # Shared engine: scanning, URL resolution, HTTP checker, report
├── greetings.py             # Daily dashboard: calendar, quote, weather, RSS news, stocks
├── link_checker_page.py     # Legacy checker for built Hugo "public/" HTML
├── myconfig.py              # .env → Settings object + shared Ollama client
├── mymessages.py            # System prompts (dicts with role/content)
├── myollama.py              # call_ollama / call_ollamas
├── openrouter.py            # OpenRouter client: ask_openrouter(), call_openrouter(), key in the keychain
├── util.py                  # Colour/print helpers, random quote, stock prices
├── requirements.txt         # Pinned dependencies (direct + transitive)
├── requirements.in          # Only the 12 packages the project imports (source of the pinned list)
├── .env                     # Local configuration (never commit)
├── .env.example             # Safe template with every variable (commit this one)
├── pyproject.toml           # Metadata and pytest settings
├── tests/                   # 216 unit tests (no network needed)
├── .gitignore               # Keeps .env, caches and my_output.md out of git
└── my_output.md             # Only created if util.display_message(..., save_to_file=True) is used
```

## 5. Installation, step by step

### 5.1 Prerequisites

| Requirement | Why |
|---|---|
| **Python 3.11+** | `quotes_library` needs 3.11 and the pinned `pandas 3.x` / `numpy 2.x` are recent; the code itself uses `from __future__ import annotations`. |
| **Ollama** (https://ollama.com), running | LLM for front matter and `myollama`. |
| A pulled model matching `.env`, e.g. `ollama pull <MYMODEL_QUERY>` | The default model if none is configured is `qwen3:32b`. |
| A **Hugo site** with `content/`, `static/` and a running `hugo server` | Needed by links/images/render checks. |
| *(optional)* `fortune` command (macOS: `brew install fortune`) | One quote source. |
| *(optional)* Chromium for Playwright | Browser-based render checks (`playwright` is already in `requirements.txt`, the browser binary is a separate download). |
| *(optional)* OpenRouter account and API key | Only for `openrouter.py`. The key is saved once in the system keychain: `python3 openrouter.py --set-key`. |

### 5.2 Install

```bash
# 1. Get the code
git clone <your-repository-url> hugo-content-toolkit
cd hugo-content-toolkit

# 2. Virtual environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 3. Dependencies
python3 -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Download the browser used by content_render (optional but recommended)
playwright install chromium

# 5. Configuration
#    Create .env next to myconfig.py from the template (see section 6)
cp .env.example .env && open -e .env      # macOS; or use any editor
#    (optional) save your OpenRouter key in the keychain; the prompt hides what you type
python3 openrouter.py --set-key

# 6. Ollama
ollama serve                         # if not already running
ollama pull <your-model>             # the name you put in MYMODEL_QUERY

# 7. Hugo: make it reachable from the machine running the toolkit
hugo server --bind 0.0.0.0           # add --baseURL http://<server-ip>:1313 if needed

# 8. Verify the configuration
python3 myconfig.py
```

`python3 myconfig.py` prints the path of the `.env` it found and every resolved setting, so you can confirm what the project will use.

## 6. Configuration: the `.env` file

The `.env` file must be **next to `myconfig.py`** (since v0.6 `greetings.py` no longer loads it itself). Values in `.env` override variables already set in the shell (`override=True`). Spaces around `=`, quotes, and trailing `# comments` on unquoted values are accepted by python-dotenv (your `BASE_URL = "..."` and `RSS_FEED_URLS=... # comment` lines work).

### 6.1 Variables read by the reviewed code

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `HUGO_SERVER` | `content_urls` and everything built on it | none (**required** for links/images/render) | Where Hugo answers, e.g. `192.168.1.46:1313`. `http://` is added if missing; trailing `/` removed. |
| `HUGO_ROOT` | `content_urls`, `content_quotes` | none (**required**) | Folder of the site **on this computer** (must contain `content/` and `static/`). `~` is expanded. |
| `BASE_URL` | `myconfig` | `http://localhost:11434` | Address of the Ollama server. |
| `MYMODEL_QUERY` | `myconfig`, `myollama`, `content_frontmatter` | `qwen3:32b` | Default model for every `call_ollama` that does not name one (this includes front matter). |
| `MODELS_NEWCONTENT` | `myconfig`, `myollama.call_ollamas` | none | Models (separated by spaces **or** commas) used to expand content with several models. |
| `OLLAMA_TIMEOUT` | `myconfig` | `600` | Seconds to wait for Ollama. Must be a number. *Not in your `.env`: the default applies.* |
| `OLLAMA_NUM_CTX` | `myollama` | Ollama default | Context window in tokens (e.g. `32768`). Must be an integer. *Not in your `.env`.* |
| `TOPIC` | `content_quotes` | empty = any | Quote subject: `technology`, `maths`, `science`, `humor`, `wisdom`, `education`, any custom word, or `auto` (deduced from the page front matter). |
| `NUMBER_QUOTES` | `content_quotes` | `3` | How many quotes to propose (minimum 1). Your `.env` has `30`, which prints 30 quotes per page. |
| `FORTUNES_PATH` | `content_quotes` | none (no personal path in the code since v0.11) | A fortunes file or a folder of them (`%` between quotes, `    -- Author` as the last line). Without it the `file` quote source is skipped with a yellow note. |
| `QUOTE_SOURCES` | `content_quotes` | `file fortune` | Order of preference among `file`, `fortune`, `library`, `zenquotes`, `dummyjson`. Online sources are opt-in. |
| `OPENROUTER_MODEL` | `openrouter.call_openrouter`, `content_expand` | `openrouter/free` | Hosted model for the rewrite. `openrouter/free` lets OpenRouter pick a free one; for long, careful rewrites choose a specific model with a large context window. *(new in v0.18)* |
| `OPENROUTER_TIMEOUT` | same | `300` | Seconds to wait for OpenRouter. A rewrite of a long article takes minutes. Must be a number. *(new in v0.18)* |
| `OPENROUTER_MAX_TOKENS` | same | none (the model's own limit) | Cap on the length of the answer. Set it if a model complains that the request is too large. Must be an integer. *(new in v0.18)* |
| `EXPAND_PROVIDER` | `content_expand`, `content_creation` | `openrouter` | Who rewrites the article: `openrouter` (hosted) or `ollama` (your local `MYMODEL_QUERY`). Anything else is an error that names the variable. *(new in v0.18)* |
| `EXPAND_OUTPUT_DIR` | `content_expand` | `~/hugo-expanded` | Folder where the rewrite is saved. It is **refused if it is inside `HUGO_ROOT/content`**, because Hugo would publish the file as a page. *(new in v0.18)* |
| `AUTHOR` | `content_frontmatter` | none | `author:` proposed for every page. Not set = each page's own author is left alone. *(new in v0.11)* |
| `FEATURED_IMAGE` | `content_frontmatter` | none | `featured_image:` proposed for pages that have none. Not set = none is proposed. *(new in v0.11)* |
| `WEATHER_CITY` | `greetings.get_weather` | none | City of the weather line. Not set = wttr.in guesses it from your IP. *(new in v0.11)* |
| `WEATHER_LANG` | `greetings.get_weather` | `en` | Language of the weather line (`en`, `es`, `fr`...). *(new in v0.11)* |
| `STOCK_TICKERS` | `util.stocks` | `AAPL MSFT GOOGL AMZN TSLA BRK-B NVDA META JPM V` | Stocks shown by the dashboard, spaces or commas. *(new in v0.11)* |
| `RSS_FEED_URLS` | `myconfig` → `greetings.news` | none | Feed URLs separated by whitespace (since v0.6 read by `myconfig.Settings.rss_feed_urls`). |

### 6.2 Variables removed from `.env` in v0.10

No file of this repository read these eight variables, so they were deleted from your `.env` (you confirmed). If a script I have not seen needs one of them, add it back.

| Removed variable | What it was probably for |
|---|---|
| `REQUEST_TIMEOUT` | HTTP timeout of another script (`myconfig` uses `OLLAMA_TIMEOUT`). |
| `MODEL` | Generic model name. |
| `MYMODEL_FRONTMATTER`, `MYMODEL_SUMMARIZE` | Per-task models; front matter actually uses `MYMODEL_QUERY`. |
| `SEARX_URL`, `MAX_RESULTS`, `MAX_RETRIES` | A SearXNG web-search pipeline (matching the `query_msg` and `query_summarize` prompts removed in v0.12). |
| `TOR_CONTROL_PASS` | Password of the Tor control port. It had been pasted in a chat, so **change it** if you still use Tor. |

Also changed: `NUMBER_QUOTES` 30 → **7**.

> **The OpenRouter API key is not in `.env`.** Since v0.8 it lives in the system keychain (`python3 openrouter.py --set-key`); `OPENROUTER_API_KEY` as an environment variable is only a fallback for servers/CI. Do not add the key to `.env`.

> **Security.** `.env` no longer holds any secret, but keep it out of git (`.gitignore` does that) and do not paste it into chats anyway. Never add passwords or API keys to it: use the keychain.

### 6.3 `.env.example` (safe template to commit)

The real file `.env.example` is now part of the project (since v0.9; the block of unused variables was removed in v0.10). It documents every variable with its default, which file reads it, the format rules of `.env`, and a note about secrets. It contains **no secrets** and uses placeholder paths: copy it with `cp .env.example .env` and edit the values. `.gitignore` excludes `.env` (and any `.env.*`) but keeps `.env.example`.

Checked by loading both the template and the shape of your real `.env` (without the password) through `myconfig.load_settings()`: all values parse correctly (for example `MODELS_NEWCONTENT` becomes a tuple of two models and `HUGO_SERVER` gains `http://`).

## 7. Dependencies and why each one is needed

Since v0.12 there are two files: **`requirements.in`** lists only the 12 packages the project imports (each with a comment saying who uses it), and **`requirements.txt`** is the full pinned list (direct + transitive) used by `pip install -r requirements.txt`. To rebuild the pinned list from the short one: `pip install pip-tools && pip-compile requirements.in -o requirements.txt`.

`pip install -r requirements.txt` installs everything pinned. Packages are grouped by role:

**Imported directly by the reviewed code**

| Package | Used in | Purpose |
|---|---|---|
| `ollama` | `myconfig`, `myollama` | Official Python client for the Ollama server (chat calls, error classes). |
| `python-dotenv` | `myconfig` | Loads `.env` into environment variables. (The deprecated `dotenv` shim that was also pinned was removed in v0.12: `python-dotenv` alone provides `import dotenv`.) |
| `rich` | most modules | Coloured, structured terminal reports, spinners, progress bars. |
| `colorama` | `util`, `greetings`, `myollama` | ANSI colours (`Fore`, `Style`), cross-platform. |
| `requests` | `greetings`, `link_checker_page`, `openrouter` | Weather request (wttr.in), link checks in the legacy checker, OpenRouter call. |
| `keyring` *(only for `openrouter.py`, new in v0.8)* | `openrouter` (lazy import) | Stores and reads the OpenRouter API key in the system keychain (macOS Keychain, Windows Credential Locker, Linux Secret Service) instead of in source code, `.env` or shell history. If it is missing, `openrouter.py` falls back to the `OPENROUTER_API_KEY` environment variable. |
| `beautifulsoup4` (+ `soupsieve`) | `link_checker_page` | Parses built HTML to find `<a>` and `<img>`. |
| `feedparser` (+ `feedparser-sgmllib`) | `greetings` | Reads RSS/Atom feeds. |
| `certifi` | `content_urls`, `content_quotes` (via `make_ssl_context`) | Up-to-date CA certificates for HTTPS. |
| `playwright` (+ `greenlet`, `pyee`) | `content_render` | Headless Chromium to see how formulas are really drawn. Needs `playwright install chromium`. |
| `quotes_library` | `content_quotes` (source `library`) | Offline quote database (Python 3.11+). |
| `yfinance` *(only for the dashboard)* | `util.stocks` (lazy import) | Yahoo Finance prices (research/educational use). If missing, a notice is printed and prices are skipped. |

**Transitive dependencies (installed automatically by the above)**
`httpx`, `httpcore`, `h11`, `anyio`, `idna`, `urllib3`, `charset-normalizer` (HTTP stacks of `ollama`/`requests`); `pydantic`, `pydantic_core`, `annotated-types`, `typing-inspection`, `typing_extensions` (`ollama` models); `markdown-it-py`, `mdurl`, `Pygments` (`rich`); `pandas`, `numpy`, `python-dateutil`, `pytz`, `six`, `curl_cffi`, `cffi`, `pycparser`, `peewee`, `platformdirs`, `protobuf`, `websockets`, `multitasking` (`yfinance`). parser`) but it is **required by `yfinance`** (`pip show lxml` → `Required-by: yfinance`, checked on your machine in v0.13), so it stays in `requirements.txt`; it is not in `requirements.in` because the project does not import it.

**Standard library only** (deliberately, for the network engine): `urllib`, `http.client`, `ssl`, `html.parser`, `concurrent.futures`, `dataclasses`, `re`, `difflib`, `subprocess`, `json`.

## 8. Quick start and usage

Every example uses a page **inside `HUGO_ROOT/content`**.

```bash
# Run all seven steps on one page and get a summary (exit code 0 = clean, 1 = needs attention)
python3 content_creation.py /path/to/justtothepoint/content/calculus/stoketheorem.md
python3 content_creation.py content/calculus/stoketheorem.md   # relative to HUGO_ROOT works from any folder
python3 content_creation.py PAGE.md --only links images      # just these checks
python3 content_creation.py PAGE.md --skip render quotes     # everything but these
python3 content_creation.py PAGE.md --hide-ok                # only show problems

# NEW in v0.18: no page = the Markdown file you edited LAST in HUGO_ROOT/content
python3 content_creation.py                                  # latest modified page, all seven steps
python3 content_creation.py --include-index                  # ... also consider section pages (_index.md)

# NEW in v0.18: the AI rewrite (step "expand"), ready to paste into the site
python3 content_creation.py PAGE.md --only expand            # just the rewrite
python3 content_creation.py PAGE.md --skip expand            # the checks without the rewrite
python3 content_creation.py PAGE.md --only expand --provider ollama      # local model, nothing leaves your Mac
python3 content_creation.py PAGE.md --only expand --model vendor/model --copy   # choose the model, copy to the clipboard
python3 content_expand.py  PAGE.md                           # the same, without the other steps

# Run one check on one page
python3 content_frontmatter.py /path/to/justtothepoint/content/calculus/stoketheorem.md
python3 content_latex.py       /path/to/.../stoketheorem.md
python3 content_links.py       /path/to/.../stoketheorem.md
python3 content_images.py      /path/to/.../stoketheorem.md
python3 content_quotes.py      /path/to/.../stoketheorem.md
python3 content_render.py      /path/to/.../stoketheorem.md [--no-browser]

# Daily dashboard
python3 greetings.py

# Legacy checker for built HTML in public/
python3 link_checker_page.py /calculus/chainrule/          # own links: files in public/ (run `hugo` first)
python3 link_checker_page.py calculus/chainrule --live     # own links: asked from the Hugo server

# Quick LLM test (all models of MODELS_NEWCONTENT)
python3 myollama.py

# OpenRouter (save the key once with --set-key; it is stored in the system keychain, not in .env)
python3 openrouter.py --set-key
python3 openrouter.py "Explain Stokes' theorem in two sentences" --model openrouter/free
python3 openrouter.py --delete-key
```

From Python:

```python
from pathlib import Path
from content_links import check_links
from content_render import check_render
from content_quotes import provide_quotes
from myollama import call_ollama, call_ollamas

page = Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/stoketheorem.md")
broken = check_links(page, show_ok=False)                # number of broken links (-1 = could not check)
problems = check_render(page, screenshot_dir="~/shots")  # number of problems
quotes = provide_quotes(page, count=3, topic="maths", sources=("file", "zenquotes"))
text = call_ollama("Raycast Launcher", prompt="query_expand", show=False)
```

## 9. Module reference

Legend: `_name` = private helper (not meant for outside use).

### 9.1 `myconfig.py`: configuration singleton
Reads `.env` (path = folder of this file) and exposes an immutable `Settings` object plus the shared Ollama client. Nothing is read at import time.

| Item | Description |
|---|---|
| `ENV_PATH`, `DEFAULT_*` | Constants: `.env` location and default model, host, timeout (600 s), fortunes path, number of quotes (3), quote sources (`file`, `fortune`), weather language (`en`), default stock tickers. (v0.11: the personal default fortunes path was removed.) |
| `Settings` (frozen dataclass) | `model_query`, `models_newcontent` (tuple), `base_url`, `timeout`, `num_ctx`, `hugo_server`, `hugo_root`, `topic`, `number_quotes`, `fortunes_path` (`None` when not set), `quote_sources`, `rss_feed_urls` (v0.6), `weather_city`, `weather_lang`, `stock_tickers`, `author`, `featured_image` (v0.11). New helper `_read_text(name)`. |
| `_split_list(raw)` | `'a b,c'` → `('a','b','c')`. |
| `_read_number(name, default, cast)` | Reads a numeric env var; clear `ValueError` naming the variable if invalid. |
| `_normalize_server(raw)` | Adds `http://` if missing, strips quotes and final `/`. |
| `_read_path(name)` | Reads a path env var, expands `~`; `None` if missing. |
| `load_settings()` | Builds `Settings` from the *current* environment (easy to test). |
| `get_settings()` | Cached; loads `.env` (override) then `load_settings()`. |
| `get_client()` | Cached `ollama.Client(host, timeout)`. |
| `reload_settings()` | Clears both caches and re-reads `.env`. |
| `python3 myconfig.py` | Prints the effective configuration. |

### 9.2 `mymessages.py`: system prompts
Prompts as data, plus (since v0.18) the lookup functions `available_prompts()` and `resolve_prompt(prompt)` that `myollama.py` and `openrouter.py` both use, so the same prompt names work with a local and with a hosted model. Each public variable that is a dict `{"role", "content"}` is a prompt; `available_prompts()` discovers them automatically, so adding a new prompt needs no code change. Keep only real **system** prompts here, because every such dict is offered as a selectable prompt. Cleaned in v0.12: it now has two prompts.

| Prompt | Purpose |
|---|---|
| `query_expand` | **Default prompt** of `myollama`: clarify, proofread, explain and expand a text. |
| `expand_article` | *(new in v0.18)* Used by `content_expand.py`: "provide a fully rewritten, highly expanded, and polished version of the article that I can copy and paste directly into my website", with six numbered rules: no placeholders (write every step), keep structure and voice, never drop information, keep links/images/shortcodes/code exactly and invent no URLs, math with `$...$` / `$$...$$`, and no front matter, preamble or code fence around the answer. |
| `check_proof` | Academic proofreading report ignoring front matter (use it with `call_ollama(text, prompt="check_proof")`). Not used by any other file: kept as the ready-made alternative; delete it if you do not proofread with it. |

Removed in v0.12 (not referenced by any file): `assistant_msg` and `myuser_msg` (role `assistant`/`user`, not system prompts, so they were wrongly offered as selectable prompts), `query_frontmatter` (replaced long ago by `FRONTMATTER_PROMPT` in `content_frontmatter.py`), and `query_msg` / `query_summarize` (DuckDuckGo query generator and web-page summariser of the SearXNG pipeline whose variables were removed from `.env`). The stray `"\n."` at the end of `check_proof` was fixed. The module now starts with a docstring explaining how to add a prompt.

### 9.3 `myollama.py`: talking to Ollama

| Function | Description |
|---|---|
| `available_prompts()` | Since v0.18 a one-line wrapper of `mymessages.available_prompts()` (kept so existing code works). |
| `resolve_prompt(prompt)` | Wrapper of `mymessages.resolve_prompt()`: accepts a prompt name or a ready dict; friendly `ValueError` listing valid names otherwise. |
| `_validate_call(...)` | Validates content (non-empty, ≤ 100 000 chars), model name, temperature (0-2), `max_tokens` (> 0). |
| `_strip_thinking(text)` | Removes `<think>…</think>` blocks (qwen3, deepseek-r1). |
| `_clear_terminal()` | Clears the screen only when output is a real terminal. |
| `_ask_model(...)` | Calls `client.chat` with `temperature`, `num_predict` (+ `num_ctx` if set); converts errors into `RuntimeError` with hints (`ollama pull <model>` on 404, `ollama serve` when unreachable). |
| `call_ollama(content, prompt="query_expand", model_name=None, role="user", temperature=0.7, max_tokens=10000, clear_screen=True, strip_thinking=True, show=True, *, system_prompt=None)` | Sends `[system prompt, user content]` to **one** model with a spinner; returns the answer. `show=False` is used by other modules that only need the text. `system_prompt` is the legacy alias of `prompt`. |
| `_problem_with_input(content, models)` | Returns a message describing invalid input or `None`. |
| `call_ollamas(content, prompt="query_expand", models=None)` | Same question to **every** model (default `MODELS_NEWCONTENT`); a failing model is reported in red and skipped; returns `{model: answer}`. Uses temperature 0.7 and `max_tokens=20000`. |

### 9.4 `content_creation.py`: the orchestrator
Runs the seven steps (six checks and the AI rewrite) on one page, prints a summary and returns an exit code (rewritten in v0.7; optional page and `expand` step added in v0.18). Each check is imported only when it runs and is isolated: an exception in one is recorded and the next still runs.

| Item | Description |
|---|---|
| `OK`, `PROPOSAL`, `PROBLEMS`, `UNCHECKED`, `ERROR` | Possible status of a check. `PROPOSAL` (front matter, LaTeX, quotes) never changes the exit code. |
| `StepResult` | Dataclass: `key`, `title`, `status`, `detail`; property `needs_attention` (problems, unchecked or error). |
| `_counted(count, noun)` | Converts the number returned by links/images/render: `>0` problems, `0` fine, `-1` could not run. |
| `_step_frontmatter`, `_step_latex`, `_step_links`, `_step_images`, `_step_quotes`, `_step_render`, `_step_expand` | One wrapper per step; each returns `(status, detail)`. `_step_expand` returns `PROPOSAL` (rewrite saved), `PROBLEMS` (the quality gate found issues) or `UNCHECKED` (no API key, no network...). |
| `EXPAND_PROVIDERS`, `_expand_options` | The `--provider` choices (kept equal to `myconfig.EXPAND_PROVIDERS` by a test, because this file must not import `myconfig` at start-up) and the options of the expand step, reset at the beginning of every `main()` call. |
| `find_latest_page(content_root, include_index=False)` | **New in v0.18.** Walks `content/` and returns `(path, mtime)` of the newest `.md`/`.markdown` file. Ignores hidden folders and files, editor leftovers (`name~`, `.#name`) and `_index.md` (unless asked); ties are broken by path so the answer is stable. |
| `_choose_latest(include_index)` | Uses `find_latest_page` with `HUGO_ROOT/content`, tells you which page it chose and when it was saved ("3 hours ago"), or explains why it cannot (no `HUGO_ROOT`, no `content/`, no Markdown). |
| `STEPS`, `STEP_KEYS` | Ordered list `(key, title, function)` and the valid names for `--only` / `--skip`. |
| `run_checks(page, only=None, skip=None, show_ok=True)` | Runs the selected checks, returns a list of `StepResult`. |
| `print_summary(results)` | Prints one line per check and the verdict; returns `0` or `1`. |
| `find_page(raw)` | Locates the page: as written, then `HUGO_ROOT/<path>`, then `HUGO_ROOT/content/<path>` (`HUGO_ROOT` from `.env` via `myconfig`). Returns `(path or None, places tried)`. |
| `main(page=None, only=None, skip=None, show_ok=True, include_index=False, expand_options=None)` | `page=None` means "the most recently modified page". Locates the file with `find_page` (`2` and a list of places tried if missing), runs and summarises; returns the exit code. |
| `cli(argv=None)` | `argparse` entry point: `[PAGE.md] [--only STEP...] [--skip STEP...] [--hide-ok] [--include-index] [--provider P] [--model M] [--temperature T] [--copy] [--no-save]`. |

Exit codes: `0` clean, `1` something needs attention, `2` wrong usage.

### 9.5 `content_frontmatter.py`: LLM-proposed front matter
One single question is sent to the model; it must answer with JSON (`title`, `keywords`, `categories`, `description`). `language` is always `en`, `author` is the `AUTHOR` constant, `date` is today, `featured_image`/`weight` are kept or defaulted, any unknown field (e.g. `firstarticle`) is kept verbatim. New/changed values print in red.

| Function | Description |
|---|---|
| `_read(page)` | Reads UTF-8 with `\n` line endings. |
| `_split_page(text)` | `(front_matter, body)`; empty front matter if absent or unclosed. |
| `page_frontmatter(page)` | **Public.** Text between the two `---` lines. |
| `_parse_blocks(front)` | `{key: [lines]}` without a YAML library. |
| `_unquote`, `_block_value` | Normalise scalar/list values for comparison. |
| `_site_categories(content_root)` | Cached: categories used across the site (up to 5 000 pages), most frequent first (top 40). |
| `_known_categories(page)` | Finds the `content/` ancestor and returns site categories. |
| `_article_digest(...)` | Builds the model input: current title, known categories, headings (≤ 60), first 10 000 chars + last 2 000. |
| `_extract_json(answer)` | Extracts a JSON object tolerating code fences and chatter. |
| `_ask_model(digest)` | Calls `call_ollama(show=False)`, temperature 0.3 then 0.1 on retry (one retry if JSON invalid). |
| `_clean_text/_as_list/_clean_keywords/_clean_categories/_clean_title/_clean_description` | Sanitise model output: lowercase, deduplicate, ≤ 30 keywords, ≤ 4 categories (spelled as the site spells them), description trimmed to ~320 chars. |
| `_quote`, `_scalar` | YAML-safe output (quote only when necessary). |
| `_comparable(value)` | Normalises values so equal values are not painted red. |
| `_build_blocks(existing, ai, known)` | Builds ordered `(key, lines, changed)` blocks. |
| `_print_block(lines, changed)` | Prints one field (bold key; red when changed). |
| `check_hugo_frontmatter(page)` | **Public.** Prints the proposed front matter. |

Settings at the top: `LANGUAGE`, `DEFAULT_WEIGHT`, `KEEP_EXISTING_DATE`, limits. Since v0.11 the author and the default featured image are **not** constants any more: they come from `AUTHOR` and `FEATURED_IMAGE` in `.env` (`get_settings()`); when `AUTHOR` is not set the page's own `author:` stays where it is, and when `FEATURED_IMAGE` is not set none is proposed.

### 9.6 `content_latex.py`: LaTeX detector/repairer
Pure text processing (only needs Rich). Ignores front matter, fenced code, inline code, link targets, URLs, shortcodes and HTML tags. Prints each line that needs a fix with new/corrected expressions in red; lines with an unpaired `$` are shown in yellow with `?` and not converted.

Recognises: Greek letters and symbols (`π`, `∇·F`, `∫`, `≤`, `ℝ³`...), fractions (`½`, `<sup>1</sup>&frasl;<sub>2</sub>`), super/subscripts (`u²`, `x₁`, `3<sup>2`, `x^10` → `x^{10}`), function names (`sin(x)` → `$\sin(x)$`, `ysin(z)` → `y\sin(z)`), and `\vert\begin{smallmatrix}…` → `vmatrix`.

| Function | Description |
|---|---|
| `_m`, `_strip`, `_split_marked` | Mark/unmark/split "new" text (private-use characters `\ue000`/`\ue001`, nestable). |
| `_vmatrix_sub(m)` | Bars + `smallmatrix` → `vmatrix`. |
| `_unicode_to_latex(s)` | Unicode symbols, scripts and `√` → LaTeX with correct spacing for binary operators. |
| `fix_math(s)` | Repairs the *content* of a math span (tags, matrices, Unicode, exponents, function names) while protecting `\text{}`-style commands. |
| `_script(mark)`, `_rewrite_tags(text)` | `<sup>/<sub>/<u>` and entity fractions → `^`/`_`/`\frac` (ordinals like `1<sup>st</sup>` are left). |
| `_split_token(tok)` | Separates leading/trailing punctuation from a word. |
| `_Item` | Small token container (text / whitespace / math). |
| `_mathy(core)` | Does this word look like math? |
| `_convert_token(tok)` | Converts one word or returns `None` (skips real Greek text, ambiguous words). |
| `_merge_items(items)` | Joins `cos θ` and `x² + y² = 1` into one `$…$` span. |
| `_calls(marked)` | Wraps `sin(x)`, `ln(2)`... in plain text. |
| `_prose(text, in_table)` | Converts a plain-text segment (table-aware). |
| `_convert_line(line, in_display)` / `_convert_line_ex(...)` | Converts one line, tracking multi-line `$$` blocks and stray `$`. |
| `_frontmatter_end(lines, text)` | Front-matter length (`---`, `+++`, or JSON). |
| `check_latex(page)` | **Public.** Prints lines to fix and a summary. |

### 9.7 `content_urls.py`: the shared engine
Used by links, images, render and quotes.

| Item | Description |
|---|---|
| Constants | `CONTENT_DIR`, `STATIC_DIR`, `ASSETS_DIR`, `TIMEOUT` (12 s), `MAX_WORKERS` (8), `MAX_REDIRECTS` (8), `MAX_BODY_BYTES`, `LARGE_IMAGE_BYTES` (1 MB), `USER_AGENT`, `FRONTMATTER_IMAGE_KEYS`, colour styles. |
| `HugoConfigError` | Raised when `HUGO_SERVER`/`HUGO_ROOT` are missing. |
| `_hugo_settings()` | Returns `(server, root)` or raises with the exact line to add to `.env`. |
| `read_lines`, `front_len` | **Public since v0.14** (were `_read_lines` / `_front_len`): read a page as lines and count the lines of its front matter; used by `content_render` and `content_quotes` too. |
| `_unquote_value`, `_fields_of` | Small front-matter helpers used only inside this module. |
| `_quote_path`, `_safe_url`, `_urlize` | URL encoding (non-ASCII, IDNA), Hugo-style lowercase/hyphen slugs. |
| `_content_url_path(path, root)` | `content/a/b.md` → `/a/b/` honouring `url:`, `slug:`, `_index.md`, bundles. |
| `page_url(page, include_scheme=True)` | **Public.** Address where Hugo serves the page. |
| `Ref` | One found link/image: line, kind, target, label, source (`markdown`, `html`, `shortcode`, `autolink`, `bare`, `definition`, `frontmatter`, `theme`), region. |
| `_mask_line`, `_attrs`, `_find_open`, `_parse_dest`, `_scan_line`, `_scan_front` | Hand-written Markdown scanner: inline/reference links, images, `<a>`, `<img>`, `{{< figure >}}`, `ref`/`relref`, autolinks, bare URLs, front-matter images; skips code and comments. |
| `scan_page(page)` | **Public.** All `Ref`s of a page in order. |
| `Target` | Resolved reference: `fetch` / `skip` / `bad`, URL, fragment, internal?, note. |
| `_locate(base, rel)` | Case-exact file lookup (detects macOS case-insensitivity problems). |
| `PageContext` | `resolve(raw, root_relative)`, `_as_server` (maps `localhost:1313` to your server), `_resolve_shortcode`, `local_matches(url)` (find a file in `static/`, `content/`, `assets/`). |
| `Probe` | Server answer: status, final URL, content type, length, first bytes, anchors (`ids`), HTML, error, timeout. |
| `_NoRedirect`, `_IdCollector`, `_RenderedScanner`, `_srcset`, `_theme_targets` | Manual redirect following; collects `id`s; reads the *served* HTML to find theme links/images (menu, footer, icons, `og:image`). Duplicates shown once as `×N`. |
| `make_ssl_context` | **Public since v0.14** (was `_make_ssl_context`): HTTPS context with the `certifi` certificates; used by `content_quotes` too. |
| `_decode`, `_length` | Charset decoding, size from `Content-Range`/`Content-Length`. |
| `Checker` | `probe(url, mode)` (modes `head`, `body`, `page`, `image`; cached, thread-safe, one retry on transient errors), `run(jobs)` (thread pool), internals `_probe`, `_attempt`, `_request`, `_describe` (human-readable network errors). Your own server bypasses proxies. |
| `Verdict`, `UNSURE_STATUS` | Level `ok/warn/bad/skip`; external 401/403/429/451/503/999 are "cannot tell", not "broken". |
| `reason(status)`, `moved_note(probe)` | `HTTP 404 Not Found`, `→ final address`. |
| `Evaluation`, `evaluate(...)` | Scan + resolve + probe + judge, with a progress bar. |
| `_render_row`, `print_evaluation`, `run_check(...)` | Printing and the one-call entry used by `check_links`/`check_images`. |

### 9.8 `content_links.py`

| Function | Description |
|---|---|
| `_probe_mode(ref, target)` | Reads the whole page only when an `#anchor` of your own site must be verified. |
| `judge_link(ref, target, probe, ctx)` | Verdict: network errors, missing anchors, redirects, "may block robots" (warn) vs 404 (broken, with draft/sync hint). |
| `check_links(page, show_ok=True, include_theme=True)` | **Public.** Prints report; returns the number of broken links (`-1` if nothing could be checked). |

### 9.9 `content_images.py`

| Function | Description |
|---|---|
| `_looks_like_image(head)`, `_looks_like_html(head)` | Magic-byte detection (JPEG, PNG, GIF, WebP, AVIF/HEIC, BMP, TIFF, ICO, SVG). |
| `_size(n)` | `84 KB` / `3.2 MB`. |
| `_problem(probe)` | Why a 200 is not a visible image (empty, HTML page in disguise, wrong content type). |
| `_missing_hint(ref, target, ctx)` | After a 404 on your server: not synced/Hugo not rebuilt, wrong capitals, file in `assets/` or `content/`, relative-path advice. |
| `judge_image(...)` | Verdict plus yellow remarks: no alt text, file > 1 MB. |
| `check_images(page, show_ok=True, include_theme=True)` | **Public.** Returns the number of broken images. |

### 9.10 `content_render.py`: checks the final page

| Check key | Meaning |
|---|---|
| `page` | The page loads (HTTP). |
| `engine` | KaTeX/MathJax really loaded (or pre-rendered); detects a missing engine or CSS. |
| `resources` | Every script and stylesheet answers. |
| `intact` | Formulas in the HTML match your Markdown (detects Markdown/typographer damage: `_` → italics, lost `\\`, `\{`...). |
| `typeset` *(browser)* | Formulas that fail to draw, remain raw `$…$`, missing fonts. |
| `fit` *(browser)* | Formulas wider than the window at 1280 px (problem) and 390 px (warning); page scrolling sideways; CSS hints (`display: inline-block`, `min-width: 0`). |
| `console` *(browser)* | JS errors and failed requests. |
| `leftovers` | Unprocessed shortcodes, Hugo template errors, literal Markdown. |
| `structure` | Unclosed tags, duplicate ids, missing/multiple `<h1>`, empty headings/links/title. |

| Function / class | Description |
|---|---|
| `Finding`, `Report` (`add`) | Data containers for results, notes, skips and hints. |
| `_squash`, `_alnum` | Normalisation for comparisons. |
| `SourceIndex` | Reads your `.md` once: formulas, and `find_line`, `find_tag`, `find_heading`, `closest` to point to your Markdown line. |
| `PageScan` | HTML parser collecting scripts, styles, ids, headings, text, structural issues. |
| `math_spans(html)` | Formulas still written with delimiters. |
| `_short`, `_version`, `detect_engine`, `check_engine`, `check_resources` | Engine/resource checks. |
| `_explain_difference`, `check_formulas_intact` | Explain what Markdown changed in a formula. |
| `check_leftovers`, `check_structure` | Text leftovers and HTML structure. |
| `COLLECT_JS`, `OVERFLOW_JS` | JavaScript executed in the page (read-only). |
| `BrowserResult`, `run_browser(url, screenshot_dir, phone)` | Headless Chromium via Playwright; optional full-page PNG. |
| `check_browser_results(...)` | Converts browser data into findings (its docstring was in the wrong place until v0.14). |
| `_row`, `print_report` | Printing. |
| `check_render(page, show_ok=True, browser="auto", screenshot_dir=None, phone=True)` | **Public.** Returns number of problems (`-1` if not checkable). |

### 9.11 `content_quotes.py`

| Function / class | Description |
|---|---|
| `Quote` (`as_fortune()`) | Text, author, source, on-topic flag, hits, score; export in fortunes format. |
| `TOPICS`, `Topic`, `resolve_topic(raw, page_text)` | Topic definitions (aliases, file names, key words); `auto` infers from the page. |
| `parse_fortunes(raw, source)` | Splits fortune-format text (`%` separators, `-- Author`). |
| `_read_fortune_file`, `_fortune_files`, `_quotes_from_files` | Read files/folders; if file names match the topic, only those are used. |
| `_source_file`, `_source_fortune`, `_source_library`, `_source_zenquotes`, `_source_dummyjson` | The five sources (`SOURCES` registry). Failures only add a yellow note (`file` says "FORTUNES_PATH is not set" when it is missing). |
| `_find_fortune_command`, `_run`, `_fortune_directory` | Locate and query the system `fortune`. |
| `_http_json`, `_online_quote`, `_coerce` | Online/library helpers. |
| `_stem`, `_words`, `page_profile(page)` | Weighted vocabulary of the page (title/keywords ×3, headings ×2, body ×1). |
| `_fingerprint`, `_site_text`, `_already_used` | Avoid quotes already present anywhere in `content/`. |
| `acceptable(quote)` | Has author, 25-420 chars, ≤ 6 lines, no URLs. |
| `rank(quotes, weights, rng)` | Score = 10 (on-topic) + relevance (≤ 6) + small randomness. |
| `choose(ranked, count, site)` | Best `count`: not used, no duplicates, one per author when possible. |
| `provide_quotes(page, count=None, topic=None, sources=None, rng=None)` | **Public.** Prints and returns quotes. |

### 9.12 `greetings.py`: daily dashboard

| Function | Description |
|---|---|
| `show_calendar()` | Prints the current month with today highlighted (reverse video). |
| `news(max_entries_per_feed=3)` | Gets the feeds from `get_settings().rss_feed_urls` (`RSS_FEED_URLS` in `.env`), prints title/link/200-char summary per entry; shows a red message if none are set or `.env` is invalid. |
| `get_weather(city=None, lang=None)` | `wttr.in` one-line weather (5 s timeout). City and language default to `WEATHER_CITY` / `WEATHER_LANG` of `.env` (no city = wttr.in guesses from your IP); the city is URL-encoded (`San Francisco`); only network errors (`requests.RequestException`) are caught. |
| `today()` | Ruler with timestamp, calendar, random quote (`util.select_quote`), weather, news, stocks (`util.stocks`). |

### 9.13 `link_checker_page.py`: legacy checker for the built site
Reads `HUGO_ROOT/public/<page>/index.html` (run `hugo` first: `hugo server` keeps everything in memory) and checks every `<a href>` and `<img src>`. Reworked in v0.13: links to **your own site** are now checked as files in `public/` (nothing is requested, no waiting), links to **other sites** by HTTP, `data:`/`ftp:` and similar are skipped. Exit code: `0` nothing critical, `1` broken links or missing files, `2` page or configuration problem.

| Function | Description |
|---|---|
| `check_url(url, headers, timeout=10)` | HEAD then GET fallback on 403/405; returns status/final URL/error. |
| `_exact_file(root, parts)` | `root/part1/part2` is a file **with the capitals written exactly** (macOS ignores case, a Linux server does not). *(new)* |
| `local_file_for(public_dir, url_path)` | The file in `public/` that serves an internal URL path: `/a/b/` → `a/b/index.html`; `/a/b` → `a/b`, `a/b/index.html` or `a/b.html`; URL-decoded; never leaves `public/` (`..` is refused). *(new)* |
| `check_page(local_path, hugo_root=None, base_url=None, live=False)` | `hugo_root` / `base_url` default to `HUGO_ROOT` / `HUGO_SERVER` of `.env`. Parses the page with BeautifulSoup, checks links and images (internal = same host as `HUGO_SERVER`; `live=True` asks the server about them too), prints a categorised summary and the list of issues (now including broken images and unusual statuses), returns a result dict (`None` if the page or the configuration is missing). |
| `cli(argv=None)` | `local_path [--live]`; returns the exit code. *(new)* |

Superseded by `content_links.py`/`content_images.py`, which work from the Markdown source and the live server.

### 9.14 `util.py`: terminal helpers, quotes, stocks
Imports `colorama` (initialised with `autoreset=True`), `rich` and `re` at import time. `content_quotes` and `yfinance` are imported lazily inside `select_quote()` and `stocks()` (changed in v0.4 and v0.16). Constant: `OUTPUT_MARKDOWN = "my_output.md"`.

| Function | Description |
|---|---|
| `normalize_string(s)` | Collapses whitespace and lowercases (for tolerant comparisons). *(Fixed in v0.4: `import re` was missing.)* |
| `display_message(text, save_to_file=False, filename=OUTPUT_MARKDOWN)` | Prints `text` between magenta rulers. Only when `save_to_file=True` it also appends the text to `filename` (default `my_output.md`, relative to the current directory) as a yellow `<span>`. *(Before v0.4 it always wrote the file.)* |
| `print_color(color, text)` | Prints with a raw ANSI code (`"\033[<color>m"`). |
| `clear_output_markdown(filename=OUTPUT_MARKDOWN)` | Empties the markdown output file. |
| `display_text_color(text, color=Fore.GREEN, newline=True)` | Coloured print; `newline=False` ends with a space (used to list stocks inline). |
| `display_alarm_color(text, color=Fore.RED, emoji="⚠️")` | Coloured message with a leading emoji (the duplicate definition was removed in v0.4; the default emoji is `⚠️` since v0.5). |
| `text_horizontalRuler(text)` | Rich: magenta text followed by a rule. |
| `select_quote()` | Prints one random quote with its author, taken from `content_quotes.pick_daily_quote()` (same sources as the page tools: `QUOTE_SOURCES`; any topic). Prints a yellow notice if no source gives a quote. Since v0.16 it no longer needs the `quote` package. |
| `stocks(tickers=None)` | Prints the closing price of each ticker via `yfinance`, one request per ticker. Tickers: the argument, else `STOCK_TICKERS` of `.env`, else `DEFAULT_TICKERS` (AAPL, MSFT, GOOGL, AMZN, TSLA, BRK-B, NVDA, META, JPM, V). Imports `yfinance` lazily; prints a yellow notice and returns `None` if it is not installed. |
| `display_log_color(text, color=Fore.GREEN, level="INFO")` | Timestamped log line. |
| `display_chunck(text, color=Fore.GREEN)` | Prints without newline and flushes (streaming output). |

### 9.15 `openrouter.py`: OpenRouter client (rewritten in v0.8)
A module you can import and a command-line tool. **Importing it does nothing**; a request is made only when a function is called. The API key is never written in the source, in `.env` or in error messages: it is read from the system keychain with the `keyring` package (service `justtothepoint-toolkit`, user `OPENROUTER_API_KEY`), with the environment variable `OPENROUTER_API_KEY` as a fallback. On macOS the first access may ask you to allow Python: choose "Always Allow".

| Item | Description |
|---|---|
| `API_URL`, `DEFAULT_MODEL` (`openrouter/free`), `DEFAULT_TIMEOUT` (60 s), `KEYRING_SERVICE`, `KEYRING_USER`, `ENV_VARIABLE` | Constants. |
| `OpenRouterError` | The only exception raised for expected problems; its message is for humans and never contains the key. |
| `_keyring()` | Imports `keyring` lazily (`None` if not installed). |
| `get_api_key()` | Key from the keychain, else from `OPENROUTER_API_KEY`; otherwise an error that tells you to run `--set-key` (and why the keychain failed, if it did). |
| `set_api_key(key=None)` | Saves the key in the keychain; without an argument it asks with a hidden prompt (`getpass`). Rejects an empty key. |
| `delete_api_key()` | Removes the key; returns `False` if none was saved. |
| `_error_text(response)` | Short explanation of an HTTP error, with hints for 401/403 (bad key), 402 (no credits), 429 (rate limit). |
| `ask_openrouter(prompt, model="openrouter/free", timeout=60, system=None, temperature=None, max_tokens=None)` | Sends the question; returns `(answer, model that answered)`. `temperature` and `max_tokens` are sent only when given. Handles timeout, no connection, HTTP errors and unexpected answers. |
| `call_openrouter(content, prompt="query_expand", model=None, timeout=None, temperature=0.7, max_tokens=None, show=False, strip_thinking=True)` | **New in v0.18.** The OpenRouter twin of `myollama.call_ollama`: you choose WHAT to do by prompt **name** from `mymessages.py` (`query_expand`, `check_proof`, `expand_article`...). Model, timeout and `max_tokens` default to `OPENROUTER_MODEL`, `OPENROUTER_TIMEOUT` and `OPENROUTER_MAX_TOKENS`. Returns `(answer, model used)`; validates content (non-empty, at most 100 000 characters) and raises `ValueError` for a bad argument or unknown prompt name. |
| `_strip_thinking(text)` | Removes `<think>...</think>` blocks. |
| `cli(argv=None)` | `python3 openrouter.py ["prompt"] [--system NAME] [--model M] [--timeout S] [--set-key] [--delete-key]`; `--system` uses a prompt of `mymessages.py`. Exit code `0` ok, `1` error. |

Since v0.18 it is connected to the check pipeline through `call_openrouter()` and `content_expand.py` (section 9.16). It still imports only `requests` (and `keyring` when it needs the key) at start-up: `mymessages` and `myconfig` are imported inside `call_openrouter`, so `python3 openrouter.py "Hello!"` keeps working with nothing else configured.

### 9.16 `content_expand.py`: AI rewrite of an article, ready to paste *(new in v0.18)*
`expand_article(page)` takes the **body** of a page (the front matter is removed and never sent), asks a model for "a fully rewritten, highly expanded, and polished version ... that I can copy and paste directly into my website" (prompt `expand_article` in `mymessages.py`), checks the answer, saves it and prints it. It never writes inside `content/` and never changes the page.

| Item | Description |
|---|---|
| `ExpandError` | The only exception for expected problems (empty page, page too long, no API key, no network, unusable output folder). Messages are for humans and never contain the key. |
| `Expansion` | Dataclass returned by `expand_article`: `text`, `provider`, `model`, `words_before`, `words_after`, `seconds`, `saved_to`, `copied`, `warnings` (read before pasting), `notes` (information); property `serious` = there are warnings. |
| `article_body(page)` | The Markdown without its front matter (uses `read_lines` / `front_len` of `content_urls`, so BOM and Windows line endings are handled). |
| `clean_answer(answer)` | Returns `(text, notes)`. Removes a `<think>` block, a fence around the whole answer (only when the inside has balanced fences, so an article made of code is safe), a front matter block, and a chatty first line ("Here is the article:") followed by a blank line. |
| `compare_texts(original, expanded)` | **The quality gate.** Returns `(warnings, notes)`. Warnings: empty answer; **shorter** than the original; **less than 15% longer**; **placeholders** (`insert ... here`, `TODO`, `TBD`, "to be completed", `[...]`, "proof omitted", a line with only `...`), counted only when there are more than in the original; **links/images of the original that vanished**; **new links/images** (models invent URLs); changed **Hugo shortcodes**; math written with `\( \)` / `\[ \]`. Notes: renamed headings and the growth factor. |
| `output_dir()` | `EXPAND_OUTPUT_DIR` or `~/hugo-expanded`; raises `ExpandError` if it is inside `HUGO_ROOT/content`. Checked **before** the model is asked, so no time or credit is wasted. |
| `save_expansion(text, page)` | Writes `<page>-expanded-YYYYmmdd-HHMMSS.md` (UTF-8, `\n`). For `index.md` bundles the folder name is used. |
| `copy_to_clipboard(text)` | `pbcopy` on macOS; `False` if it is not available (reported as a note, not an error). |
| `_ask_openrouter`, `_ask_ollama` | The two providers, with a spinner (OpenRouter) or the one of `call_ollama`. Provider errors become `ExpandError`. |
| `expand_article(page, provider=None, model=None, temperature=None, save=True, copy=False, show=True)` | The public function; returns an `Expansion`. |
| `cli(argv=None)` | `python3 content_expand.py PAGE.md [--provider P] [--model M] [--temperature T] [--copy] [--no-save]`. Exit code `0` clean, `1` error or warnings, `2` page not found. |

**Privacy.** With `openrouter` the article is sent to OpenRouter and to the company that runs the model; free models may keep prompts. Fine for text you are about to publish; for private drafts use `--provider ollama`.

**Limits.** An article longer than 100 000 characters is refused with a message (split it, or expand one section at a time). A model with a small context window may cut or refuse a long article: choose another `OPENROUTER_MODEL` or set `OPENROUTER_MAX_TOKENS`.

## 10. Understanding the reports

Links/images (one line per item):

```
   12  ✓ 200  /calculus/other/  [next lesson]
   15  ✗ 404  /calculus/missing/  [oops]  HTTP 404 Not Found (is the target a draft, or not synced yet?)
   18  ! 403  https://www.linkedin.com/in/xxx  [me]  HTTP 403 Forbidden - the site may block automatic checks
   21  – -    mailto:me@example.com  mailto: links are not checked
```

`✓` works, `✗` broken, `!` cannot be verified (open by hand), `–` skipped. Items from the theme show a region (`nav`, `foot`...) instead of a line number. Return value = number of broken items; `-1` = could not run.

`check_render`: `✓` check passed, `✗` problems (counted), `!` warnings (not counted). Red text in `check_hugo_frontmatter` = new/changed value.

## 11. Troubleshooting

| Message / symptom | Cause and fix |
|---|---|
| `The 'yfinance' package is not installed` (yellow notice from `greetings.py`) | Only the stock prices need it: `pip install yfinance` (or `pip install -r requirements.txt`). |
| `No quote today (...)` | No source in `QUOTE_SOURCES` returned a usable quote (check `FORTUNES_PATH`, or add `fortune`/`library`). |
| `my_output.md` not created | Intended since v0.4: call `display_message(text, save_to_file=True)` to write it. |
| `link_checker_page.py`: `Page not found: .../public/...` or `MISSING FILE` for a link that works in the browser | `public/` is missing or old: run `hugo` to build it (`hugo server` does not write it), or use `--live` to ask the running server. Capitals must match exactly (`/Images/` is not `/images/`). |
| `HUGO_SERVER is not set in .env` / `HUGO_ROOT is not set...` | Add both variables (section 6). |
| `... is not inside <root>/content (check HUGO_ROOT in .env)` | The page path is outside `HUGO_ROOT/content`. |
| `the Hugo server ... does not answer` | Start `hugo server --bind 0.0.0.0`; check IP/port and firewall. |
| `the server answers 404 for this page itself` | Draft, future date, not synced (Syncthing) or Hugo not rebuilt. |
| Image 404 but file exists in `static/` | Not synced yet, or Hugo hasn't rebuilt. |
| Image 404, "upper/lower case differs" | macOS ignores case, the Linux server does not; fix the capitals. |
| `Cannot reach Ollama at ... (try: ollama serve)` | Start Ollama or fix `BASE_URL`. |
| `Ollama rejected the request ... try: ollama pull <model>` | The model in `MYMODEL_QUERY` / `MODELS_NEWCONTENT` is not installed (check the exact tag with `ollama list`). |
| `must be a number, got ...` | Fix `OLLAMA_TIMEOUT` / `OLLAMA_NUM_CTX` / `NUMBER_QUOTES`. |
| `could not get valid JSON from the model` | Use a stronger model or lower temperature. |
| `Playwright is not installed` / `Chromium is not installed` | `playwright install chromium`, or `browser=False`. |
| `fortune: command not found` | `brew install fortune` or drop `fortune` from `QUOTE_SOURCES`. |
| `file: ... does not exist (FORTUNES_PATH in .env)` | Set `FORTUNES_PATH` to an existing file/folder. |
| `library: quotes-library is not installed` | `pip install quotes-library` (Python 3.11+). |
| `zenquotes: no quotes (rate limit...)` | Wait ~30 s. |
| SSL certificate errors on macOS | Make sure `certifi` is installed (it is in `requirements.txt`). |
| `expansion failed: ...` in the summary as `!` | The `expand` step could not run: usually no API key (`python3 openrouter.py --set-key`) or no network. The other steps are not affected; leave it out with `--skip expand`. |
| `! N placeholder(s) found` / `SHORTER than the original` / `link/image(s) ... missing` | The quality gate of `content_expand` found a bad rewrite. Do not paste it as it is: run it again, lower `--temperature`, or choose a stronger `--model`. |
| `EXPAND_OUTPUT_DIR (...) is inside your Hugo content folder` | Choose another folder in `.env`; a file inside `content/` would be published by Hugo. |
| `No page given ... HUGO_ROOT is not set` | Without an argument `content_creation.py` needs `HUGO_ROOT` in `.env` to find the latest page. |
| `No OpenRouter API key found` | Run `python3 openrouter.py --set-key` (and `pip install keyring`). If it adds "the keychain could not be read", unlock the keychain / allow Python access, or set `OPENROUTER_API_KEY` in the environment. |
| `OpenRouter answered HTTP 401` | The saved key is wrong or revoked: run `python3 openrouter.py --set-key` again. |
| `OpenRouter answered HTTP 402` / `429` | No credits for that model (use `--model openrouter/free`) / rate limit (wait and retry). |

## 12. Known issues and code observations

Factual notes from reading the code, not necessarily bugs:

1. ~~**`util.py` bug**: `normalize_string` uses `re` without importing it.~~ **Fixed in v0.4.**
2. ~~**`util.py` duplicates and side effects**~~ **Fixed in v0.4**: duplicate `display_alarm_color` removed; `display_message` writes `my_output.md` only with `save_to_file=True`; `quote` and `yfinance` are imported lazily.
3. ~~**`.env` contains a secret** and variables nobody reads; `NUMBER_QUOTES=30`.~~ **Fixed in v0.10**: the 8 unused variables (including `TOR_CONTROL_PASS`) were removed and `NUMBER_QUOTES` is 7.
4. ~~**`openrouter.py`** is a script with a placeholder key in the source, not integrated with `.env`.~~ **Fixed in v0.8**: key in the keychain, functions with timeout and error handling, `__main__` guard. Still open: it is not connected to `myollama`/the pipeline.
5. ~~**Duplicated quote logic**~~ **Fixed in v0.16**: `util.select_quote` now uses `content_quotes` (new `daily_quote`/`pick_daily_quote`); the `quote` and `gazpacho` packages were dropped.
6. ~~**Hard-coded personal values**~~ **Fixed in v0.11**: fortunes path, author, default featured image, weather city/language, stock tickers and the link checker's `hugo_root`/`base_url` now come from `.env`. Left on purpose: personal paths used only as *examples* in comments and docstrings (`content_urls.py`, `content_quotes.py`, `myconfig.py`...), and the `LANGUAGE`/`DEFAULT_WEIGHT` constants, which are not personal.
7. ~~**`content_creation.main`** ignores the return values and always prints "All checks passed!".~~ **Fixed in v0.7** (see tracker).
8. ~~**`mymessages`**: unused `query_frontmatter`, missing `query_definition`, stray `"\n."`, role-`assistant`/`user` dicts offered as prompts.~~ **Fixed in v0.12** (and the `myollama` docs now use `check_proof` as the second example).
9. ~~**`greetings.py`**: bare `except:`, `.env` loaded inside `news()`, `Fore.BLACK` unreadable.~~ **Fixed in v0.6.** Still open: the city (`"Malaga"`) is hard-coded.
10. ~~**Encoding**: emoji in `greetings.py`, `link_checker_page.py` and `util.py` appear corrupted (`�`).~~ **Fixed in v0.5** (see tracker).
11. ~~**`link_checker_page.py`**: internal links became HTTP URLs, the local-file branch was never reached, wrong usage text.~~ **Fixed in v0.13** (see tracker). It also used to flag `data:` images as missing files, and broken images / unusual statuses were counted but missing from the issue list.
12. ~~**`requirements.txt`**: redundant `dotenv` wrapper, direct vs transitive packages.~~ **Fixed in v0.12** (`dotenv` removed, `requirements.in` added). `gazpacho` was dropped in v0.16 together with `quote`; `lxml` stays because `lxml` because `yfinance` requires it (checked in v0.13). Nothing open here.
13. ~~**Private helpers imported across modules** (`_front_len`, `_read_lines`, `_make_ssl_context`).~~ **Fixed in v0.14**: renamed to `front_len`, `read_lines`, `make_ssl_context`; the old names remain as aliases at the end of `content_urls.py` (delete them once you are sure no other script uses them).
14. ~~**`content_render.check_browser_results`**: an assignment preceded the docstring.~~ **Fixed in v0.14**: the docstring is first, so `help()` and tools see it.
15. ~~No tests, no `pyproject.toml`.~~ **Added in v0.15** (see tracker). CI added in v0.17.

## 13. Improvements and future releases

**Short term**
- ~~Add `import re` to `util.py`; remove the duplicated `display_alarm_color`~~ (done, v0.4). Encoding/emoji fixed in v0.5. Bare `except:` replaced in v0.6.
- ~~Make `content_creation.main` take the page from the command line, collect each check's return value and print a real summary / exit code.~~ (done, v0.7)
- Move all personal defaults to `.env` (still open); ~~commit a `.env.example`~~ (done, v0.9); ~~delete or document unused variables~~ (done, v0.10).
- ~~Read the OpenRouter key from a safe place; wrap the call in a function with timeout and error handling; guard with `if __name__ == "__main__"`.~~ (done, v0.8: system keychain)
- ~~Make `util` import `quote`/`yfinance` lazily inside `select_quote`/`stocks`.~~ (done, v0.4)
- ~~Unify `.env` loading (`greetings.news` → `myconfig`), add `RSS_FEED_URLS` to `Settings`.~~ (done, v0.6) Still open: add the weather city to `Settings`.
- ~~Add the missing `query_definition` prompt or correct the docs.~~ (done, v0.12: docs corrected)

**Medium term**
- Convert to a package (`hugo_content_toolkit/`) with `pyproject.toml` and a single CLI: `hugo-check links|images|latex|render|frontmatter|quotes|all PAGE`.
- ~~Unit tests for the pure functions~~ (done, v0.15). CI done (v0.17). Next: tests for the network parts with a fake local server.
- `--apply` options (opt-in) to write front matter or LaTeX fixes, with backup/diff.
- Batch mode: check a whole section or all pages changed in git; JSON/HTML report output.
- Replace `link_checker_page.py` with a mode of `content_links` that reads `public/`.
- Retries (`MAX_RETRIES`) for OpenRouter and Ollama. *(The common interface is done in v0.18: the same prompt names work with `call_ollama` and `call_openrouter`, and `EXPAND_PROVIDER` chooses one.)*
- Expand very long articles **section by section** (split at `##` headings, expand each, join) so the 100 000-character limit and small context windows stop mattering.
- `--diff` view and `--apply` (opt-in, with backup) to merge the rewrite into the page after review; a second model pass that checks the first one's facts and math.
- ~~Stock watch-list and cities configurable in `.env`~~ (done, v0.11); parallel stock requests still open.

**Long term**
- Pre-commit / CI integration, caching of external-link results, async checking.
- Prompt templates in files, multilingual front matter, Docker image.

## 14. Documentation roadmap

All 15 listed files, `requirements.txt` and `.env` have now been documented. What is still unknown:

| Item | Why it matters |
|---|---|
| Any script that used the 8 variables removed in v0.10 (SearXNG, Tor...) | If it exists and is part of the project, share it: it would need its own README section and its variables restored in `.env.example`. |
| Where `check_proof` is used | Not used by any file; kept as a ready-made prompt. Tell me if you want it deleted. |
| ~~A real `.env.example`~~ | Done in v0.9. |
| The Hugo theme/CSS used for KaTeX | Would allow documenting the exact formula-fit fixes `check_render` suggests. |
| Tests, CI or deployment scripts, if any | Development guide. |
