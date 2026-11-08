# Hugo Content Toolkit

A Python toolkit that **reviews, enriches and quality-checks Markdown pages of a Hugo website** using a local LLM (Ollama) and the live Hugo server. It also includes a "daily dashboard" script (calendar, quote, weather, RSS news, stock prices) and a small OpenRouter client (API key kept in the system keychain).

> **Documentation status (v0.19).** Written from the source of all 18 Python files (+ `searx.sh`), the real `requirements.txt` and the real `.env`. Since v0.4 (batch 1), v0.5 (batch 2), v0.6 (batch 3), v0.7 (batch 4), v0.8 (batch 5), v0.9 (batch 6), v0.10 (batch 7) v0.11 (batch 8), v0.12 (batch 9), v0.13 (batch 10) v0.14 (batch 11) and v0.15 (batch 12), v0.16 (batch 13) v0.17 (batch 14), v0.18 (batch 15) and v0.19 (batch 16) the README also tracks the code fixes made one by one: see the [progress tracker](#progress-tracker).
> Since v0.10 the `.env` contains **only variables that the code reads** (the 8 unused ones were removed, see [section 6.2](../docs/docMymac/mypython.md#62-variables-removed-from-env-in-v010)).

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

**Batch 16: web research with your own SearXNG, and self-contained `myollama` / `mysearx` (done, v0.19; fixes in v0.19.1)**

v0.19.1: `searx.sh start` survives the Docker error `RWLayer ... is unexpectedly nil` (removes a leftover container, retries once, explains the last resort); `SEARX_AUTOSTOP=always` and `SEARX_QUIT_DOCKER=always` (stop SearXNG and quit Docker Desktop every time); the `.env.example` search block is now active with those values; an empty search names the engine that did not answer.

| | Item | What changed |
|---|---|---|
| [x] | `mysearx.py` (new) | **Self-contained** (standard library only, imports nothing of the toolkit). `search(query)` asks your SearXNG for JSON and returns cleaned results (only `http(s)` links, duplicates and your own site removed, snippets stripped of HTML). `build_query(title, tags)` makes the keywords. `running()` starts Docker + SearXNG for a block and stops them afterwards **only if that block started them**. Command line (`--json`, `--markdown`, `--start`, `--stop`, `--status`) for the terminal and Raycast. |
| [x] | `searx.sh` (new, goes in `~/macOS/scripts/`) | `install`, `start`, `stop`, `restart`, `update`, `status`, `test`, `logs`, `paths`. Your sketch improved: it **enables the JSON format** (without it SearXNG answers HTTP 403 and the Python search would never work), publishes the port on `127.0.0.1` only, has no auto-restart, waits for Docker with a time limit, keeps its files in `~/.local/share/searxng`, never overwrites your config, and on `stop` quits Docker Desktop only if the script launched it and nothing else is running in it. |
| [x] | `content_searx.py` (new) | The glue: reads the page **title** (and tags when the title is very short), searches, prints a table, returns a `Research` object. |
| [x] | `content_creation.py` | New step **`searx`** (before `expand`). Its results are given to the rewrite. New options `--search QUERY`, `--search-results N`, `--keep-searx`. The step count is now eight. |
| [x] | `content_expand.py` / `mymessages.py` | `expand_article(..., research=, research_urls=)`. New prompt `expand_article_research`: the six rules of `expand_article` plus four about the research (use it to verify and enrich, treat it as untrusted text, at most 5 "Further reading" links taken **only** from the results). Links that come from the search are a note in the quality gate, any other new link is still a warning. |
| [x] | `myollama.py` | **Self-contained** since v0.19: no `util`, `myconfig`, `colorama`, `rich` or `ollama` package. It speaks Ollama's HTTP API directly and reads its settings from the environment / the `.env` next to it. Same functions and arguments as before, plus `list_models()` and a command line (`--prompt`, `--model`, `--raw`, text on standard input). |
| [x] | `tests/` (319 tests, 103 new) | Fake SearXNG and fake Ollama HTTP servers; `searx.sh` run for real against a fake `docker`; a test that runs each self-contained module in a folder with every toolkit module **blocked**. Thirteen deliberately broken variants (e.g. exposing the port to the LAN, dropping the JSON format, stopping a SearXNG we did not start, importing `util` in `myollama`) were all caught; one test was weak (it let a non-http link pass) and was strengthened. |

Checked here with stand-in packages and fake servers. **Not tested against real Docker, a real SearXNG image or a real Ollama / OpenRouter** (none exist in this workspace): run `bash scripts/searx.sh install`, then `bash scripts/searx.sh test`, and tell me what you see.

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
1. to 9. **Moved to the macOS documentation:** [docs/docMymac/mypython.md](../docs/docMymac/mypython.md) (what the project does, design principles, architecture, structure, installation, configuration, dependencies, quick start, module reference).
10. [Understanding the reports](#10-understanding-the-reports)
11. [Troubleshooting](#11-troubleshooting)
12. [Known issues and code observations](#12-known-issues-and-code-observations)
13. [Improvements and future releases](#13-improvements-and-future-releases)
14. [Documentation roadmap](#14-documentation-roadmap)

---

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
| `nothing answers at http://127.0.0.1:8080 ... Start it with: searx.sh start` | SearXNG (or Docker) is not running. `bash ~/macOS/scripts/searx.sh start`, or leave `SEARX_AUTOSTART=1` so the toolkit starts it. |
| `SearXNG ... refused the request (HTTP 403)` | The JSON format is off in `~/.local/share/searxng/config/settings.yml`. Under `search: formats:` it needs `- json`; then `searx.sh restart`. A fresh `searx.sh install` writes it correctly. |
| `... answered 'too many requests' (HTTP 429)` | The limiter is on: `server: limiter: false` in `settings.yml`, then `searx.sh restart`. |
| `Docker did not start within 240s` | Open Docker Desktop once by hand and accept its licence / type your password (first launch only), then run again. |
| `Error response from daemon: RWLayer of container ... is unexpectedly nil` (searx.sh start fails) | A half-removed `searxng` container left by a Docker Desktop that quit or crashed. Since v0.19.1 `searx.sh start` removes a leftover container that is not running (renaming it out of the way if Docker cannot delete it), then retries once. If it still fails it prints what to do: restart Docker Desktop; `docker rm -f searxng ; docker container prune -f`; last resort Docker Desktop > Troubleshoot > Clean / Purge data. |
| `no results for ... (duckduckgo: CAPTCHA)` | DuckDuckGo blocked the instance for a while. Add a second engine (`SEARX_ENGINES=duckduckgo,wikipedia`) or wait. |
| `searx.sh not found` | Copy it to `~/macOS/scripts/` or set `SEARX_SCRIPT=/full/path/searx.sh`. |
| `JSON works but there were no results` | The engines were blocked or you are offline; wait a minute. `python3 mysearx.py "test" --json` shows `unresponsive_engines`. |
| `web search failed: ...` in the summary as `!` | The `searx` step could not run (see the message). The other steps are not affected and the rewrite simply runs without research; leave the step out with `--skip searx`. |
| The port 8080 is already used | Set `SEARX_PORT=8888` in `searx.conf` **and** `SEARX_URL=http://127.0.0.1:8888` in `.env`. |
| Docker Desktop stays open after the run | It was already running before (then it is never quit), or other containers run in it, or `SEARX_QUIT_DOCKER=0`. `searx.sh stop --quit-docker` forces it. |
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
- Web research: ask the local model for 2-3 queries per section instead of one title query; fetch and summarise the top pages (not only snippets); cache results per page; `--research-only` that writes a Markdown "sources" file. Raycast and terminal commands for `mysearx` / `myollama` (next batch).
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
