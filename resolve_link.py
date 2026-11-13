"""
Standalone Linkvertise / AWS S3 Paste Link Resolver
===================================================
A lightweight, zero-dependency Python utility designed to resolve Linkvertise,
AWS S3 pre-signed .txt pastes, and shortener links to extract the final destination
URL (prioritizing Telegram channel/group/bot links).

Key Features:
-------------
1. Fixes AWS S3 403 AccessDenied Signature Bug: Automatically sanitizes HTML-encoded
   `&amp;` entities to plain `&` so pre-signed query strings remain valid.
2. Zero External Dependencies: Built strictly using Python standard libraries
   (`urllib.request`, `re`, `html`, `asyncio`). Requires nothing in requirements.txt.
3. Dual Sync + Async Support:
   - `extract_final_link(url)`: Synchronous blocking call.
   - `extract_final_link_async(url)`: Non-blocking coroutine safe for aiogram, pyrogram,
     telethon, FastAPI, or any asyncio event loop.
4. Robust Parsing: Handles raw text, HTML `<a href="...">`, and follows HTTP redirects.
5. Interactive CLI & Argument Parsing:
   `python resolve_link.py "<URL>"` or run interactively `python resolve_link.py`.

Safety:
-------
This file is completely decoupled from main.py and existing bot workflows.
"""

from __future__ import annotations

import sys
import re
import html
import ssl
import asyncio
import urllib.request
import urllib.error
from typing import Optional, List

# Standard desktop browser user-agent to avoid anti-scraping 403 blocks
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Comprehensive regex to match Telegram links (channels, private invites, bots, joinchat)
TELEGRAM_URL_PATTERN = re.compile(
    r"https?://(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+/)?[a-zA-Z0-9_\-]+[^\s<>'\"()]*",
    re.IGNORECASE
)

# General URL fallback regex
GENERAL_URL_PATTERN = re.compile(
    r"https?://[^\s<>'\"()]+",
    re.IGNORECASE
)

# HTML href attribute regex
HREF_PATTERN = re.compile(
    r"""href\s*=\s*["'](https?://[^"']+)["']""",
    re.IGNORECASE
)


def sanitize_s3_url(raw_url: str) -> str:
    """
    Sanitizes AWS S3 pre-signed URLs copied from web pages or APIs.
    
    Fixes the critical AccessDenied XML error where `&amp;` corrupts
    query parameters (such as &AWSAccessKeyId=, &Signature=, &Expires=).
    """
    if not raw_url:
        return ""
    
    # Strip whitespace, newlines, and enclosing quotes
    cleaned = raw_url.strip().strip("\"'").strip()
    
    # Unescape HTML entities (e.g. &amp; -> &, &quot; -> ", etc.)
    cleaned = html.unescape(cleaned)
    
    # Secondary check in case of multiple or partial escaping
    cleaned = cleaned.replace("&amp;", "&")
    
    return cleaned


def _clean_trailing_punctuation(link: str) -> str:
    """Strips common trailing punctuation attached to URLs in prose/HTML."""
    return link.rstrip(".,;:!?'\")>]}")


def extract_links_from_text(text: str) -> List[str]:
    """
    Parses plain text or HTML content to extract links.
    Returns links with Telegram URLs prioritized at the top.
    """
    if not text:
        return []

    # 1. First priority: Extract direct Telegram URLs
    tg_links = [
        _clean_trailing_punctuation(match.group(0))
        for match in TELEGRAM_URL_PATTERN.finditer(text)
    ]
    if tg_links:
        # Deduplicate while preserving order
        return list(dict.fromkeys(tg_links))

    # 2. Second priority: Look for href links in HTML
    href_links = [
        _clean_trailing_punctuation(match.group(1))
        for match in HREF_PATTERN.finditer(text)
    ]
    # Check if any href is a Telegram link
    tg_hrefs = [l for l in href_links if any(d in l.lower() for d in ("t.me", "telegram.me", "telegram.dog"))]
    if tg_hrefs:
        return list(dict.fromkeys(tg_hrefs))
    if href_links:
        return list(dict.fromkeys(href_links))

    # 3. Third priority: Any generic HTTP/HTTPS link
    all_links = [
        _clean_trailing_punctuation(match.group(0))
        for match in GENERAL_URL_PATTERN.finditer(text)
    ]
    return list(dict.fromkeys(all_links))


def _fetch_url_content(req: urllib.request.Request, timeout: int) -> tuple[str, str]:
    """
    Fetches raw HTTP content with automatic fallback to unverified SSL context
    if the host machine lacks local CA root certificate bundles.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            final_url = response.geturl()
            charset = response.headers.get_content_charset() or "utf-8"
            return final_url, response.read().decode(charset, errors="replace")
    except urllib.error.URLError as err:
        # Fallback for Windows/minimal containers lacking certifi/CA bundles
        err_str = str(err.reason) if hasattr(err, "reason") else str(err)
        if "CERTIFICATE_VERIFY_FAILED" in err_str:
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=unverified_ctx, timeout=timeout) as response:
                final_url = response.geturl()
                charset = response.headers.get_content_charset() or "utf-8"
                return final_url, response.read().decode(charset, errors="replace")
        raise


def extract_final_link(url: str, timeout: int = 15) -> str:
    """
    Synchronously fetches an AWS S3 / Linkvertise paste .txt URL and extracts
    the final destination link (e.g. Telegram link).

    Args:
        url: The raw URL or S3 pre-signed paste link.
        timeout: Network timeout in seconds (default: 15s).

    Returns:
        The extracted destination URL string.

    Raises:
        ValueError: If the URL is empty or no valid destination could be found.
        RuntimeError: If HTTP fetch fails (e.g. expired S3 signature 403, 404, network error).
    """
    cleaned_url = sanitize_s3_url(url)
    if not cleaned_url or not cleaned_url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid or empty URL provided: {url!r}")

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(cleaned_url, headers=headers)

    try:
        final_redirect_url, content = _fetch_url_content(req, timeout)

        # Check if HTTP redirection itself landed directly on Telegram
        if any(dom in final_redirect_url.lower() for dom in ("t.me/", "telegram.me/", "telegram.dog/")):
            return final_redirect_url

    except urllib.error.HTTPError as err:
        if err.code == 403:
            raise RuntimeError(
                "Access Denied (403): The AWS S3 pre-signed link has expired, or the signature "
                "was rejected. Please ensure the link is active and valid."
            ) from err
        if err.code == 404:
            raise RuntimeError("Resource Not Found (404): The requested paste link does not exist.") from err
        raise RuntimeError(f"HTTP Error {err.code}: {err.reason}") from err

    except urllib.error.URLError as err:
        raise RuntimeError(f"Network Connection Failed: {err.reason}") from err
    except TimeoutError as err:
        raise RuntimeError(f"Request timed out after {timeout} seconds.") from err
    except Exception as err:
        raise RuntimeError(f"Unexpected error while resolving link: {err}") from err

    # Parse content to extract destination links
    links = extract_links_from_text(content)
    if links:
        return links[0]

    # If no link found, but content is non-empty plain text, check if content itself is a target
    trimmed = content.strip()
    if trimmed and not trimmed.startswith("<") and len(trimmed) < 250:
        return trimmed

    raise ValueError("No destination URL or Telegram link could be extracted from the target content.")


async def extract_final_link_async(url: str, timeout: int = 15) -> str:
    """
    Asynchronously resolves the link in a background worker thread.
    
    Safe for non-blocking execution inside aiogram, pyrogram, telethon,
    or FastAPI without requiring extra third-party libraries (uses standard asyncio).

    Args:
        url: The raw URL or S3 pre-signed paste link.
        timeout: Network timeout in seconds (default: 15s).

    Returns:
        The extracted destination URL string.
    """
    loop = asyncio.get_running_loop()
    # Runs the standard library synchronous function in the default executor thread pool
    return await loop.run_in_executor(None, extract_final_link, url, timeout)


# CLI Execution Entrypoint
def main() -> None:
    """Command Line Interface for resolve_link.py"""
    if len(sys.argv) > 1:
        target_url = sys.argv[1].strip()
    else:
        print("\n" + "=" * 60)
        print("🔗  AWS S3 / LINKVERTISE PASTE RESOLVER (STANDALONE)")
        print("=" * 60)
        try:
            target_url = input("Enter S3 paste URL or .txt link: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

    if not target_url:
        print("❌ Error: No URL provided. Exiting.")
        sys.exit(1)

    print("\n⏳ Fetching and resolving destination link...")
    try:
        result = extract_final_link(target_url)
        print("\n" + "—" * 60)
        print(f"🎯 Final Target Link:\n👉 {result}")
        print("—" * 60 + "\n")
    except Exception as exc:
        print(f"\n❌ Resolution Failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
