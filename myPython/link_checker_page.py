#!/usr/bin/env python3
"""
link_checker_page.py - check the links and images of ONE page of the BUILT Hugo site.

It reads the HTML that Hugo wrote in HUGO_ROOT/public (run `hugo` first; `hugo server`
keeps everything in memory) and checks every <a href> and <img src>:

  * links to your own site  -> the file must exist in public/ (capitals must match,
                               as on a Linux server). Nothing is requested.
  * links to other sites    -> a real HTTP request (HEAD, then GET if refused).

    python3 link_checker_page.py /complex/chainrule/
    python3 link_checker_page.py complex/chainrule --live    # ask the Hugo server about
                                                             # your own links too

Exit code: 0 nothing critical, 1 broken links or missing files, 2 page/config problem.
(content_links.py / content_images.py are the newer checkers: they start from the
Markdown and the running server.)
"""
import os
import time
import requests
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from bs4 import BeautifulSoup


def check_url(url, headers, timeout=10):
    """Check URL with proper handling of different status codes"""
    try:
        # Try HEAD first (faster)
        response = requests.head(
            url, headers=headers, timeout=timeout, allow_redirects=True
        )

        # Some servers don't support HEAD, try GET
        if response.status_code == 405 or response.status_code == 403:
            time.sleep(0.5)  # Be polite
            response = requests.get(
                url, headers=headers, timeout=timeout, allow_redirects=True
            )

        return {
            "status": response.status_code,
            "url": url,
            "final_url": response.url,
            "error": None,
        }

    except requests.exceptions.Timeout:
        return {"status": None, "url": url, "final_url": None, "error": "Timeout"}
    except requests.exceptions.ConnectionError:
        return {
            "status": None,
            "url": url,
            "final_url": None,
            "error": "Connection Error",
        }
    except requests.exceptions.TooManyRedirects:
        return {
            "status": None,
            "url": url,
            "final_url": None,
            "error": "Too Many Redirects",
        }
    except Exception as e:
        return {"status": None, "url": url, "final_url": None, "error": str(e)}


def _exact_file(root, parts):
    """True if root/part1/part2/... is a file, with the capitals written exactly.

    macOS ignores upper/lower case but a Linux web server does not, so every part
    is compared with the real names on disk.
    """
    current = Path(root)
    for part in parts:
        try:
            if part not in os.listdir(current):
                return False
        except OSError:
            return False
        current = current / part
    return current.is_file()


def local_file_for(public_dir, url_path):
    """The file in public/ that serves `url_path` (the path of an internal URL), or None.

    "/a/b/"  -> a/b/index.html          "/a/b"  -> a/b, a/b/index.html or a/b.html
    "/"      -> index.html              "/img/x.png%20y" is URL-decoded first.
    """
    rel = unquote(url_path).lstrip("/")
    parts = [p for p in rel.split("/") if p]
    if ".." in parts or "." in parts:  # never leave public/
        return None
    candidates = [parts + ["index.html"]]
    if rel and not rel.endswith("/"):
        candidates = [parts, parts + ["index.html"], parts[:-1] + [parts[-1] + ".html"]]
    for candidate in candidates:
        if _exact_file(public_dir, candidate):
            return Path(public_dir).joinpath(*candidate)
    return None


def check_page(local_path, hugo_root=None, base_url=None, live=False):
    """
    Check all links and images in a specific Hugo page.

    Args:
        local_path: Path relative to site root, e.g., '/complex/chainrule/'
        hugo_root: Root directory of Hugo installation (default: HUGO_ROOT of .env)
        base_url: Base URL of the running Hugo server (default: HUGO_SERVER of .env)
        live: False (default) = links/images of your own site are looked up as files in
              public/; True = they are requested from the Hugo server like external ones.

    Returns:
        dict: Summary of issues found
    """

    # Where the site is and where Hugo answers: from .env unless given explicitly
    if hugo_root is None or base_url is None:
        try:
            from myconfig import get_settings

            settings = get_settings()
        except Exception as e:  # myconfig missing or an invalid .env
            print(f"❌ Cannot read the configuration: {e}")
            return None
        hugo_root = hugo_root or settings.hugo_root
        base_url = base_url or settings.hugo_server
        if not hugo_root or not base_url:
            print("❌ HUGO_ROOT and HUGO_SERVER must be set in .env (or passed as arguments)")
            return None

    # Normalize local path
    local_path = local_path.strip("/")

    # Construct full file path
    public_dir = Path(hugo_root) / "public"
    page_path = public_dir / local_path / "index.html"

    # Check if page exists
    if not page_path.exists():
        # Try without /index.html
        page_path = public_dir / f"{local_path}.html"
        if not page_path.exists():
            print(f"❌ Page not found: {page_path}")
            return None

    print(f"🔍 Checking page: {local_path}")
    print(f"📄 File: {page_path}")
    print(f"🌐 URL: {base_url}/{local_path}/")
    print("=" * 80 + "\n")

    # User agent to mimic a real browser
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # Results counters
    results = {
        "success": 0,
        "redirect": 0,
        "bot_blocked": 0,
        "broken": 0,
        "server_error": 0,
        "timeout": 0,
        "connection_error": 0,
        "missing_file": 0,
        "issues": [],  # List of actual issues to report
    }

    checked_urls = set()

    # Parse HTML
    with open(page_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    page_url = urljoin(base_url, f"/{local_path}/")
    base_netloc = urlparse(base_url).netloc  # "192.168.1.46:1313": the host of YOUR site

    # Check links
    print("🔗 Checking links...")
    for link in soup.find_all("a", href=True):
        href = link["href"]

        # Skip anchors, mailto, tel, javascript
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        full_url = urljoin(page_url, href)

        # Skip if already checked
        if full_url in checked_urls:
            continue
        checked_urls.add(full_url)

        parsed = urlparse(full_url)
        # A link to your own site: checked as a file in public/ (unless --live)
        internal = (
            not live
            and parsed.scheme in ["http", "https"]
            and parsed.netloc == base_netloc
        )

        # External URL
        if parsed.scheme in ["http", "https"] and not internal:
            result = check_url(full_url, headers)
            status = result["status"]
            error = result["error"]

            if error:
                if error == "Timeout":
                    results["timeout"] += 1
                    results["issues"].append(
                        {"type": "timeout", "url": href, "full_url": full_url}
                    )
                    print(f"⏱️  TIMEOUT: {href}")
                elif "Connection" in error:
                    results["connection_error"] += 1
                    results["issues"].append(
                        {
                            "type": "connection_error",
                            "url": href,
                            "full_url": full_url,
                            "error": error,
                        }
                    )
                    print(f"🔌 CONNECTION ERROR: {href}")
                else:
                    results["connection_error"] += 1
                    results["issues"].append(
                        {
                            "type": "error",
                            "url": href,
                            "full_url": full_url,
                            "error": error,
                        }
                    )
                    print(f"❓ ERROR: {href} - {error}")

            elif 200 <= status < 300:
                results["success"] += 1
                print(f"✅ OK ({status}): {href}")

            elif 300 <= status < 400:
                results["redirect"] += 1
                print(f"↪️  REDIRECT ({status}): {href} → {result['final_url']}")

            elif status == 403 or status == 405:
                results["bot_blocked"] += 1
                results["issues"].append(
                    {"type": "bot_blocked", "url": href, "status": status}
                )
                print(f"🤖 BOT BLOCKED ({status}): {href} (likely working for humans)")

            elif status == 404 or status == 410:
                results["broken"] += 1
                results["issues"].append(
                    {"type": "broken", "url": href, "status": status}
                )
                print(f"❌ BROKEN ({status}): {href}")

            elif 500 <= status < 600:
                results["server_error"] += 1
                results["issues"].append(
                    {"type": "server_error", "url": href, "status": status}
                )
                print(f"🔥 SERVER ERROR ({status}): {href}")

            else:
                results["broken"] += 1
                results["issues"].append(
                    {"type": "unusual", "url": href, "status": status}
                )
                print(f"⚠️  UNUSUAL STATUS ({status}): {href}")

            # Be polite - don't hammer servers
            time.sleep(0.3)

        # Internal link: the file must exist in public/
        elif internal:
            if local_file_for(public_dir, parsed.path) is None:
                results["missing_file"] += 1
                results["issues"].append({"type": "missing_file", "url": href})
                print(f"📁 MISSING FILE: {href}")
            else:
                results["success"] += 1
                print(f"✅ LOCAL FILE OK: {href}")

        # ftp:, data:, ... : nothing to check

    # Check images
    print("\n🖼️  Checking images...")
    for img in soup.find_all("img", src=True):
        src = img["src"]
        full_url = urljoin(page_url, src)

        if full_url in checked_urls:
            continue
        checked_urls.add(full_url)

        parsed = urlparse(full_url)
        internal = (
            not live
            and parsed.scheme in ["http", "https"]
            and parsed.netloc == base_netloc
        )

        if parsed.scheme in ["http", "https"] and not internal:
            result = check_url(full_url, headers)
            status = result["status"]

            if result["error"]:
                results["connection_error"] += 1
                results["issues"].append(
                    {
                        "type": "image_error",
                        "url": src,
                        "full_url": full_url,
                        "error": result["error"],
                    }
                )
                print(f"🖼️  IMAGE ERROR: {src} - {result['error']}")
            elif status and 200 <= status < 300:
                results["success"] += 1
                print(f"✅ IMAGE OK ({status}): {src}")
            else:
                results["broken"] += 1
                results["issues"].append(
                    {"type": "image_broken", "url": src, "status": status}
                )
                print(f"🖼️  IMAGE BROKEN ({status}): {src}")

            time.sleep(0.3)
        elif internal:
            if local_file_for(public_dir, parsed.path) is None:
                results["missing_file"] += 1
                results["issues"].append({"type": "missing_image", "url": src})
                print(f"🖼️  MISSING IMAGE: {src}")
            else:
                results["success"] += 1
                print(f"✅ LOCAL IMAGE OK: {src}")

    # Print summary
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)

    print(f"\n✅ SUCCESS: {results['success']} links/images working")
    print(f"↪️  REDIRECTS: {results['redirect']} redirects (usually OK)")
    print(
        f"🤖 BOT BLOCKED: {results['bot_blocked']} (403/405 - likely working for real users)"
    )
    print(f"❌ BROKEN: {results['broken']} truly broken links")
    print(f"🔥 SERVER ERRORS: {results['server_error']} server-side issues")
    print(f"⏱️  TIMEOUTS: {results['timeout']} timeouts")
    print(f"🔌 CONNECTION ERRORS: {results['connection_error']} connection issues")
    print(f"📁 MISSING FILES: {results['missing_file']} missing local files")

    # Detail issues
    if results["issues"]:
        print("\n" + "=" * 80)
        print("⚠️  ISSUES FOUND:")
        print("=" * 80)

        for issue in results["issues"]:
            issue_type = issue["type"]
            url = issue["url"]

            if issue_type == "broken":
                print(f"  ❌ BROKEN ({issue['status']}): {url}")
            elif issue_type == "missing_file" or issue_type == "missing_image":
                print(f"  📁 MISSING: {url}")
            elif issue_type == "bot_blocked":
                print(f"  🤖 BOT BLOCKED ({issue['status']}): {url}")
            elif issue_type == "server_error":
                print(f"  🔥 SERVER ERROR ({issue['status']}): {url}")
            elif issue_type == "timeout":
                print(f"  ⏱️  TIMEOUT: {url}")
            elif issue_type == "image_broken":
                print(f"  🖼️  IMAGE BROKEN ({issue['status']}): {url}")
            elif issue_type == "unusual":
                print(f"  ⚠️  UNUSUAL STATUS ({issue['status']}): {url}")
            elif "error" in issue:
                print(f"  ❓ ERROR: {url} - {issue['error']}")

    # Return results
    critical_issues = results["broken"] + results["missing_file"]
    if critical_issues > 0:
        print(f"\n⚠️  Found {critical_issues} critical issues that need fixing!")
        return results
    else:
        print("\n🎉 All critical checks passed!")
        print("ℹ️  Bot-blocked links and timeouts may need manual verification.")
        return results


def cli(argv=None):
    """Command line: returns the exit code (0 ok, 1 critical issues, 2 page/config problem)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="link_checker_page.py",
        description="Check the links and images of one page of the built Hugo site (public/).",
    )
    parser.add_argument("local_path", help="page path in the site, e.g. /complex/chainrule/")
    parser.add_argument(
        "--live",
        action="store_true",
        help="request your own links from the Hugo server instead of looking for the files in public/",
    )
    args = parser.parse_args(argv)

    results = check_page(args.local_path, live=args.live)
    if results is None:
        return 2
    return 1 if results["broken"] + results["missing_file"] > 0 else 0


if __name__ == "__main__":
    import sys

    sys.exit(cli())
