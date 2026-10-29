"""
content_links.py - check_links(Path(page)): do all the links of a page work?

    from content_links import check_links
    check_links(Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/lineintegralspace.md"))

What it checks (nothing is written or changed; it only reads the page and asks servers)
--------------------------------------------------------------------------------------
  * links to other pages of your site  ("/calculus/other/", "../other/", {{< relref "x.md" >}})
        -> asked to YOUR Hugo server (HUGO_SERVER in .env), never to the internet
  * #anchors  ("#section-two", "/calculus/other/#intro")
        -> the page is read and the id must exist
  * links to other websites  (https://...), autolinks <https://...>, bare addresses in the
    text, <a href="...">, and the link= of {{< figure >}}
  * reference definitions  [label]: https://...
  * not checked: mailto:, tel:, javascript: ... (shown as "skipped")
  * ignored: fenced code, `inline code`, <!-- comments -->, front matter
  * ALSO the links your THEME adds (menu, header logo, sidebar, footer, social icons): they are not
    in the Markdown, so the page is read as Hugo serves it. They are listed after the Markdown ones,
    under a "from the theme" line, with their place on the page (head, nav, main, aside, foot) instead
    of a line number. A link repeated in several places is shown once ("x3"); same-page #links
    (table of contents), mailto: and javascript: are left out. check_links(page, include_theme=False)
    checks only the Markdown. Links written as http://localhost:1313/... (what `hugo server` writes
    unless it has --baseURL) are read as YOUR server, not as this computer.

The report (Rich), one line per link, in page order:

      12  ✓ 200  /calculus/other/  [next lesson]
      15  ✗ 404  /calculus/missing/  [oops]  HTTP 404 Not Found (is the target a draft, or not synced yet?)
      18  ! 403  https://www.linkedin.com/in/xxx  [me]  HTTP 403 Forbidden - the site may block automatic checks
      21  – -    mailto:me@example.com  mailto: links are not checked

  ✓ works   ✗ broken   ! cannot be verified (the site refuses robots, or is slow): open it by hand   – skipped

check_links() returns the number of broken links (-1 if the check could not run at all,
for example because the Hugo server is not reachable). Pass show_ok=False to print only problems.
"""

from __future__ import annotations

from content_urls import UNSURE_STATUS, Verdict, moved_note, reason, run_check


def _probe_mode(ref, target) -> str:
    """Read the whole page only when an #anchor of YOUR site has to be verified."""
    return "body" if (target.fragment and target.internal) else "head"


def judge_link(ref, target, probe, ctx) -> Verdict:
    """Turn what the server answered into a verdict for one link."""
    if probe.error:
        # A slow external site is "cannot tell"; anything else that fails is broken.
        level = "warn" if (probe.timeout and not target.internal) else "bad"
        return Verdict(level, "ERR", probe.error)
    status = probe.status
    if 200 <= status < 300:
        if (
            target.fragment
            and target.internal
            and probe.ids is not None
            and target.fragment not in probe.ids
        ):
            return Verdict(
                "bad",
                str(status),
                f"the page exists but has no #{target.fragment} anchor",
            )
        return Verdict("ok", str(status), moved_note(probe))
    if status in UNSURE_STATUS and not target.internal:
        return Verdict(
            "warn",
            str(status),
            f"{reason(status)} - the site may block automatic checks; open it by hand",
        )
    note = reason(status)
    if target.internal and status == 404:
        note += " (is the target a draft, or not synced yet?)"
    return Verdict("bad", str(status), note)


def check_links(page, show_ok: bool = True, include_theme: bool = True) -> int:
    """Print whether every link of `page` works. Returns the number of broken links.

    page:    path of the .md file inside HUGO_ROOT/content (Path or str).
    show_ok: False = print only the problems.
    include_theme: True = also check what the theme adds (menu, header logo, footer, icons),
                   read from the page as the Hugo server renders it. False = only the Markdown.
    """
    return run_check(
        page,
        noun="link",
        kinds=("link",),
        probe_mode=_probe_mode,
        judge=judge_link,
        show_ok=show_ok,
        include_theme=include_theme,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python3 content_links.py page.md")
    check_links(sys.argv[1])
