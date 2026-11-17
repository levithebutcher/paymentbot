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
from urllib.parse import urlparse
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
    Also cleans enclosing quotes and trailing punctuation from prose.
    """
    if not raw_url:
        return ""
    
    # Strip whitespace, newlines, and enclosing quotes/brackets
    cleaned = raw_url.strip().strip("\"'<>").strip()
    
    # Unescape HTML entities (e.g. &amp; -> &, &quot; -> ", etc.)
    cleaned = html.unescape(cleaned)
    
    # Secondary check in case of multiple or partial escaping
    cleaned = cleaned.replace("&amp;", "&")
    
    # Clean trailing punctuation from prose (e.g., periods, commas, closing parens)
    cleaned = _clean_trailing_punctuation(cleaned)
    
    return cleaned


def _clean_trailing_punctuation(link: str) -> str:
    """Strips common trailing punctuation attached to URLs in prose/HTML."""
    return link.rstrip(".,;:!?'\")>]}")


# Domains and extensions to ignore when scraping HTML paste pages
IGNORED_DOMAINS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "code.jquery.com",
    "cdn.jsdelivr.net",
    "www.w3.org",
    "facebook.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "pinterest.com",
    "whatsapp.com",
    "nordvpn.net",
    "doubleclick.net",
    "googleads",
    "googletagmanager.com",
    "google-analytics.com",
)

IGNORED_EXTENSIONS = (
    ".css", ".js", ".ico", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".woff", ".woff2", ".ttf"
)


def normalize_paste_url(url: str) -> str:
    """
    Normalizes pastebin URLs to their raw text endpoints where available.
    Supports Pastebin, Rentry, Paste.ee, Dpaste, and Hastebin.
    """
    if "pastebin.com/" in url and "/raw/" not in url:
        url = re.sub(r"pastebin\.com/([a-zA-Z0-9]+)$", r"pastebin.com/raw/\1", url)
    elif ("rentry.co/" in url or "rentry.org/" in url) and not url.endswith("/raw"):
        url = re.sub(r"rentry\.(co|org)/([a-zA-Z0-9]+)$", r"rentry.\1/\2/raw", url)
    elif "paste.ee/p/" in url:
        url = url.replace("paste.ee/p/", "paste.ee/r/")
    elif "dpaste.org/" in url and not url.endswith("/raw"):
        url = re.sub(r"dpaste\.org/([a-zA-Z0-9]+)$", r"dpaste.org/\1/raw", url)
    elif "hastebin.com/" in url and "/raw/" not in url:
        url = re.sub(r"hastebin\.com/([a-zA-Z0-9]+)$", r"hastebin.com/raw/\1", url)
    return url


def is_valid_destination_link(link: str, source_host: str = "") -> bool:
    """Validates if an extracted link is a legitimate external destination link."""
    if not link.startswith(("http://", "https://")):
        return False
    parsed = urlparse(link)
    host = parsed.netloc.lower()
    if not host:
        return False
    # Ignore same-host / self-references (e.g. pastelink.net internal links on pastelink.net)
    if source_host:
        sh = source_host.lower()
        if host == sh or host.endswith("." + sh):
            return False
        if "pastelink.net" in sh and ("pslk.net" in host or "pastelink.net" in host):
            return False
        if "justpaste.it" in sh and "justpaste.it" in host:
            return False
        if "controlc.com" in sh and "controlc.com" in host:
            return False
    # Ignore CDN, social share, ads
    if any(d in host or d in link.lower() for d in IGNORED_DOMAINS):
        return False
    # Ignore static files
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in IGNORED_EXTENSIONS):
        return False
    return True


def extract_links_from_text(text: str, source_url: Optional[str] = None) -> List[str]:
    """
    Parses plain text or HTML content to extract destination links.
    Returns links with Telegram URLs prioritized at the top.
    """
    if not text:
        return []

    source_host = ""
    if source_url:
        try:
            source_host = urlparse(source_url).netloc.lower()
        except Exception:
            pass

    # 1. First priority: Extract direct Telegram URLs
    tg_links = [
        _clean_trailing_punctuation(match.group(0))
        for match in TELEGRAM_URL_PATTERN.finditer(text)
    ]
    if tg_links:
        return list(dict.fromkeys(tg_links))

    # 2. Second priority: Look for href links in HTML
    href_links = [
        _clean_trailing_punctuation(match.group(1))
        for match in HREF_PATTERN.finditer(text)
    ]
    valid_hrefs = [l for l in href_links if is_valid_destination_link(l, source_host)]
    # Prioritize any Telegram links in hrefs
    tg_hrefs = [l for l in valid_hrefs if any(d in l.lower() for d in ("t.me", "telegram.me", "telegram.dog"))]
    if tg_hrefs:
        return list(dict.fromkeys(tg_hrefs))
    if valid_hrefs:
        return list(dict.fromkeys(valid_hrefs))

    # 3. Third priority: Any generic HTTP/HTTPS link in raw text
    all_links = [
        _clean_trailing_punctuation(match.group(0))
        for match in GENERAL_URL_PATTERN.finditer(text)
    ]
    valid_all = [l for l in all_links if is_valid_destination_link(l, source_host)]
    return list(dict.fromkeys(valid_all))


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

    # Normalize known pastebin sites to their raw endpoints for cleaner/faster parsing
    fetch_url = normalize_paste_url(cleaned_url)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(fetch_url, headers=headers)

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

    # Parse content to extract destination links (filtering out paste site self-references)
    links = extract_links_from_text(content, source_url=cleaned_url)
    if links:
        target_link = links[0]
        # If the destination link is a known shortlink, follow redirect to check for Telegram
        if not any(d in target_link.lower() for d in ("t.me", "telegram.me", "telegram.dog")):
            if any(short in target_link.lower() for short in ("t.co/", "bit.ly/", "tinyurl.com/", "cutt.ly/", "is.gd/", "rb.gy/")):
                try:
                    s_req = urllib.request.Request(target_link, headers=headers)
                    redir_url, _ = _fetch_url_content(s_req, timeout=5)
                    if any(d in redir_url.lower() for d in ("t.me", "telegram.me", "telegram.dog")):
                        return redir_url
                    target_link = redir_url
                except Exception:
                    pass
        return target_link

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
