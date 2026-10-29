"""
content_images.py - check_images(Path(page)): are all the images of a page really visible?

    from content_images import check_images
    check_images(Path("/Volumes/MacDatosMaster/justtothepoint/content/calculus/lineintegralspace.md"))

An image counts as "visible" when the server answers 200 AND what comes back really is a
picture: an image/* content type, not empty, and not a web page in disguise (Hugo or a
proxy answering an error page with status 200). Only the first bytes of each file are read.

Where images are looked for (nothing is written; fenced code, `inline code`, comments ignored)
  * ![alt](/code/images/x.jpg)  and  [![alt](/img/x.png)](link)
  * <img src="...">  and  {{< figure src="..." >}}
  * the front matter:  featured_image / image / thumbnail / cover / banner / header_image / images
  * ALSO the images your THEME adds (header logo, footer icons, favicon, og:image, srcset variants):
    they are not in the Markdown, so the page is read as Hugo serves it. They are listed after the
    Markdown ones, under a "from the theme" line, with their place (head, nav, main, aside, foot, meta)
    instead of a line number. check_images(page, include_theme=False) checks only the Markdown.

Because your site is synchronised with Syncthing and served by another computer, a missing
image is explained when possible:
  * "exists in static/ but the server answers 404" -> not synced yet, or Hugo has not rebuilt
  * "upper/lower case differs"  -> macOS ignores capitals, the server does not (Foo.JPG vs foo.jpg)
  * "found in assets/" or "in content/" -> Hugo does not serve those folders as they are
Also reported in yellow (the image still works): missing alt text, and files above 1 MB.

      9  ✓ 200  /code/images/ok.png  [diagram]  image/png, 84 KB
     14  ✗ 404  /code/images/typo.png  [chart]  HTTP 404 Not Found: the file exists in static/ but ...
     20  ✓ 200  /code/images/big.jpg  [photo]  image/jpeg, 3.2 MB  large file (3.2 MB) may slow the page
     26  ✓ 200  /code/images/a.png  []  image/png, 4 KB  no alt text

check_images() returns the number of broken images (-1 if the check could not run).
Pass show_ok=False to print only the problems.
"""

from __future__ import annotations

from content_urls import (
    LARGE_IMAGE_BYTES,
    STATIC_DIR,
    UNSURE_STATUS,
    Verdict,
    moved_note,
    reason,
    run_check,
)

# ---- recognising what the first bytes of a file are --------------------------------

_MAGIC = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a",
    b"GIF89a",
    b"BM",
    b"II*\x00",
    b"MM\x00*",
    b"\x00\x00\x01\x00",
    b"<svg",
)


def _looks_like_image(head: bytes) -> bool:
    """JPEG, PNG, GIF, WebP, AVIF/HEIC, BMP, TIFF, ICO or SVG?"""
    if head.startswith(_MAGIC):
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    if head[4:8] == b"ftyp":  # AVIF, HEIC
        return True
    return b"<svg" in head[:512].lower()


def _looks_like_html(head: bytes) -> bool:
    start = head.lstrip()[:20].lower()
    return (
        start.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))
        and b"<svg" not in head[:512].lower()
    )


def _size(n: int) -> str:
    return (
        f"{n / 1_000_000:.1f} MB" if n >= 1_000_000 else f"{max(1, round(n / 1000))} KB"
    )


def _problem(probe):
    """Why a 200 answer is NOT a visible image (None when it looks fine)."""
    if probe.length == 0 or (probe.length is None and not probe.head):
        return "the file is empty (0 bytes)"
    if _looks_like_html(probe.head):
        return "the server answered with a web page, not an image"
    kind = probe.content_type
    if kind.startswith("image/"):
        return None
    if kind in (
        "application/octet-stream",
        "binary/octet-stream",
        "",
    ) and _looks_like_image(probe.head):
        return None
    return f"not an image (Content-Type: {kind or 'missing'})"


def _missing_hint(ref, target, ctx) -> str:
    """After a 404 on YOUR server: look for the file on this computer and say what is wrong."""
    matches = ctx.local_matches(target.url)
    exact = [m for m in matches if m[2]]
    if exact:
        folder = exact[0][0]
        if folder == STATIC_DIR:
            return "the file exists in static/ but the server does not serve it: not synced yet, or Hugo has not rebuilt"
        if folder == "assets":
            return "the file is in assets/, which Hugo does not serve as it is (move it to static/)"
        return "the file is in content/: it is only served for page bundles (index.md)"
    if matches:
        folder, path, _ = matches[0]
        return (
            f"upper/lower case differs: the file is {folder}/{path.relative_to(ctx.root / folder)} "
            "(macOS ignores capitals, the server does not)"
        )
    hint = "no such file in static/, assets/ or content/ (wrong path or file missing)"
    written = ref.target.strip()
    if ref.source != "frontmatter" and not written.startswith(
        ("/", "http", "data:", "//")
    ):
        hint += "; relative paths only work inside page bundles, start with / to use static/"
    return hint


def judge_image(ref, target, probe, ctx) -> Verdict:
    """Turn what the server answered into a verdict for one image."""
    extra = []
    if ref.source in ("markdown", "html", "shortcode") and not ref.label.strip():
        extra.append("no alt text")
    if probe.error:
        level = "warn" if (probe.timeout and not target.internal) else "bad"
        return Verdict(level, "ERR", probe.error)
    status = probe.status
    if 200 <= status < 300:
        code = (
            "200" if status == 206 else str(status)
        )  # 206 = "here are the first bytes": a success
        problem = _problem(probe)
        if problem:
            return Verdict("bad", code, problem)
        info = probe.content_type or "image"
        if probe.length:
            info += f", {_size(probe.length)}"
            if probe.length > LARGE_IMAGE_BYTES:
                extra.append(f"large file ({_size(probe.length)}) may slow the page")
        note = " ".join(x for x in (info, moved_note(probe)) if x)
        return Verdict("ok", code, note, "; ".join(extra))
    if status in UNSURE_STATUS and not target.internal:
        return Verdict(
            "warn",
            str(status),
            f"{reason(status)} - the site may block hotlinking or robots; open it by hand",
        )
    note = reason(status)
    if target.internal and status == 404:
        note += ": " + _missing_hint(ref, target, ctx)
    return Verdict("bad", str(status), note)


def check_images(page, show_ok: bool = True, include_theme: bool = True) -> int:
    """Print whether every image of `page` is visible. Returns the number of broken images.

    page:    path of the .md file inside HUGO_ROOT/content (Path or str).
    show_ok: False = print only the problems.
    include_theme: True = also check what the theme adds (menu, header logo, footer, icons),
                   read from the page as the Hugo server renders it. False = only the Markdown.
    """
    return run_check(
        page,
        noun="image",
        kinds=("image",),
        probe_mode=lambda ref, target: "image",
        judge=judge_image,
        show_ok=show_ok,
        include_theme=include_theme,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: python3 content_images.py page.md")
    check_images(sys.argv[1])
