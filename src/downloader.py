import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


MAX_HTML_HOPS = 3
MAX_RETRIES = 3

VIDEO_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".webm",
    ".avi",
    ".mov",
    ".m4v",
)

DOWNLOAD_EXTENSIONS = VIDEO_EXTENSIONS + (
    ".zip",
    ".rar",
)

CAPTCHA_MARKERS = (
    "verify that you are human",
    "verification required",
    "captcha",
    "cloudflare",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "access denied",
    "bot verification",
    "human verification",
)


def _looks_like_captcha(text: str) -> bool:
    lowered = text.lower()

    return any(
        marker in lowered
        for marker in CAPTCHA_MARKERS
    )


def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)

        return parsed.scheme in (
            "http",
            "https",
        )

    except Exception:
        return False


def _looks_like_file_url(url: str) -> bool:
    path = urlparse(url).path.lower()

    return path.endswith(
        DOWNLOAD_EXTENSIONS
    )


def _looks_like_video_response(
    response: requests.Response,
) -> bool:

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    if content_type.startswith("video/"):
        return True

    if (
        "application/octet-stream"
        in content_type
    ):
        return True

    if _looks_like_file_url(
        response.url
    ):
        return True

    return False


def _extract_public_links(
    html: str,
    current_url: str,
) -> list[str]:

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links: list[str] = []

    def add_link(value: str | None):

        if not value:
            return

        value = value.strip()

        if not value:
            return

        absolute = urljoin(
            current_url,
            value,
        )

        if not _is_http_url(absolute):
            return

        if absolute not in links:
            links.append(absolute)

    # --------------------------------------------------
    # 1. Normal <a href="">
    # --------------------------------------------------

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        add_link(
            anchor.get("href")
        )

    # --------------------------------------------------
    # 2. <source src="">
    # --------------------------------------------------

    for source in soup.find_all(
        "source",
        src=True,
    ):
        add_link(
            source.get("src")
        )

    # --------------------------------------------------
    # 3. <video src="">
    # --------------------------------------------------

    for video in soup.find_all(
        "video",
        src=True,
    ):
        add_link(
            video.get("src")
        )

    # --------------------------------------------------
    # 4. Common JS assignments
    #
    # Only extract URLs that are already exposed
    # in the returned page.
    # --------------------------------------------------

    url_patterns = (
        r'''["'](https?://[^"' ]+)["']''',
        r'''(?:file|url|download|src)\s*[:=]\s*["']([^"']+)["']''',
        r'''window\.location(?:\.href)?\s*=\s*["']([^"']+)["']''',
    )

    for script in soup.find_all("script"):

        script_text = script.string or script.get_text(
            " ",
            strip=False,
        )

        if not script_text:
            continue

        for pattern in url_patterns:

            for match in re.finditer(
                pattern,
                script_text,
                flags=re.IGNORECASE,
            ):
                add_link(
                    match.group(1)
                )

    return links


def _score_link(
    url: str,
) -> int:

    score = 0

    lowered = url.lower()

    # Direct media/file URLs are best.
    if _looks_like_file_url(url):
        score += 100

    if any(
        token in lowered
        for token in (
            "download",
            "direct",
            "dl",
            "file",
            "stream",
            "video",
        )
    ):
        score += 20

    if any(
        token in lowered
        for token in (
            "captcha",
            "verify",
            "challenge",
            "cloudflare",
        )
    ):
        score -= 1000

    return score


def _choose_public_link(
    links: list[str],
) -> str | None:

    if not links:
        return None

    ranked = sorted(
        links,
        key=_score_link,
        reverse=True,
    )

    for link in ranked:

        lowered = link.lower()

        # Never intentionally follow obvious
        # challenge/CAPTCHA URLs.
        if any(
            marker in lowered
            for marker in (
                "captcha",
                "challenge",
                "verify",
                "cloudflare",
            )
        ):
            continue

        return link

    return None


def _request_with_retry(
    session: requests.Session,
    url: str,
) -> requests.Response:

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            print(
                f"Request attempt "
                f"{attempt}/{MAX_RETRIES}: "
                f"{url}"
            )

            response = session.get(
                url,
                timeout=(20, 90),
                allow_redirects=True,
                stream=True,
            )

            response.raise_for_status()

            return response

        except requests.RequestException as exc:

            last_error = exc

            print(
                f"Request failed: {exc}"
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    2 ** (attempt - 1)
                )

    raise RuntimeError(
        f"Could not access URL after "
        f"{MAX_RETRIES} attempts: "
        f"{last_error}"
    )


def _read_html(
    response: requests.Response,
) -> str:

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    if (
        "text/html" not in content_type
        and "application/xhtml" not in content_type
    ):
        return ""

    chunks = []

    total = 0

    max_html_size = 5 * 1024 * 1024

    for chunk in response.iter_content(
        chunk_size=64 * 1024,
        decode_unicode=True,
    ):

        if not chunk:
            continue

        chunks.append(chunk)

        total += len(chunk)

        if total >= max_html_size:
            break

    return "".join(chunks)


def _resolve_download_url(
    session: requests.Session,
    start_url: str,
) -> tuple[str, requests.Response]:

    current_url = start_url

    visited: set[str] = set()

    for hop in range(
        1,
        MAX_HTML_HOPS + 1,
    ):

        if current_url in visited:
            raise RuntimeError(
                "Download-page redirect loop detected."
            )

        visited.add(current_url)

        print(
            f"Resolving URL "
            f"(step {hop}): "
            f"{current_url}"
        )

        response = _request_with_retry(
            session,
            current_url,
        )

        final_url = response.url

        content_type = (
            response.headers
            .get("Content-Type", "")
            .lower()
        )

        print(
            f"Final URL: {final_url}"
        )

        print(
            f"Content-Type: {content_type}"
        )

        # ------------------------------------------
        # Direct video/file response
        # ------------------------------------------

        if _looks_like_video_response(
            response
        ):
            return final_url, response

        # ------------------------------------------
        # HTML response
        # ------------------------------------------

        html = _read_html(response)

        if not html:
            response.close()

            raise RuntimeError(
                "The server returned neither "
                "a recognized video/file response "
                "nor HTML."
            )

        if _looks_like_captcha(html):
            response.close()

            raise RuntimeError(
                "NexDrive/downstream page requires "
                "human verification/CAPTCHA. "
                "Automation will not bypass it."
            )

        links = _extract_public_links(
            html,
            final_url,
        )

        print(
            f"Found {len(links)} public URL(s) "
            f"in the HTML."
        )

        next_url = _choose_public_link(
            links
        )

        if not next_url:
            response.close()

            raise RuntimeError(
                "The download page did not expose "
                "a normal accessible file/download link."
            )

        print(
            f"Public download/redirect link found: "
            f"{next_url}"
        )

        response.close()

        current_url = next_url

    raise RuntimeError(
        "Too many download-page hops. "
        "Stopping safely."
    )


def download_file(
    url: str,
    output_path: str,
) -> Path:

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/130.0 Safari/537.36"
        ),
        "Accept": (
            "video/*,"
            "application/octet-stream,"
            "text/html,"
            "application/xhtml+xml,"
            "*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    partial = output.with_suffix(
        output.suffix + ".part"
    )

    if partial.exists():
        partial.unlink()

    final_url, response = _resolve_download_url(
        session,
        url,
    )

    print(
        f"Starting file transfer from: "
        f"{final_url}"
    )

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    if (
        "text/html" in content_type
        or "application/xhtml" in content_type
    ):
        response.close()

        raise RuntimeError(
            "Final response is HTML, not a media file."
        )

    total_bytes = 0

    try:

        with partial.open(
            "wb"
        ) as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                file.write(chunk)

                total_bytes += len(chunk)

        response.close()

        if total_bytes <= 0:

            if partial.exists():
                partial.unlink()

            raise RuntimeError(
                "Downloaded file is empty."
            )

        partial.replace(output)

    except Exception:

        response.close()

        if partial.exists():
            partial.unlink()

        raise

    print(
        f"Download completed: "
        f"{total_bytes} bytes"
    )

    print(
        f"Saved to: {output}"
    )

    return output
