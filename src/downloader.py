from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CHUNK_SIZE = 1024 * 1024

CONNECT_TIMEOUT = 20
READ_TIMEOUT = 60

MAX_HTML_HOPS = 3

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".avi",
    ".mov",
    ".m4v",
    ".ts",
}

VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/x-matroska",
    "video/webm",
    "video/x-msvideo",
    "video/quicktime",
    "video/mpeg",
    "application/octet-stream",
}

HTML_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}

BLOCKED_MARKERS = (
    b"verify that you are human",
    b"please verify that you are human",
    b"captcha",
    b"recaptcha",
    b"hcaptcha",
    b"cloudflare",
    b"cf-chl-",
    b"challenge-platform",
    b"access denied",
    b"checking your browser",
    b"security check",
)


def create_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=2,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=[
            "GET",
            "HEAD",
        ],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry
    )

    session.mount(
        "http://",
        adapter,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/130.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    return session


def looks_like_blocked_page(data: bytes) -> bool:
    sample = data[:65536].lower()

    return any(
        marker in sample
        for marker in BLOCKED_MARKERS
    )


def looks_like_html(data: bytes) -> bool:
    sample = data[:8192].lstrip().lower()

    html_markers = (
        b"<!doctype html",
        b"<html",
        b"<head",
        b"<body",
        b"<script",
    )

    return any(
        marker in sample
        for marker in html_markers
    )


def get_content_type(
    response: requests.Response,
) -> str:
    return (
        response.headers
        .get("Content-Type", "")
        .split(";")[0]
        .strip()
        .lower()
    )


def has_video_extension(url: str) -> bool:
    path = urlparse(url).path.lower()

    return any(
        path.endswith(extension)
        for extension in VIDEO_EXTENSIONS
    )


def is_probable_file_response(
    response: requests.Response,
) -> bool:

    content_type = get_content_type(
        response
    )

    if content_type in VIDEO_CONTENT_TYPES:
        return True

    if content_type.startswith("video/"):
        return True

    if has_video_extension(response.url):
        return True

    return False


def find_download_links(
    html: bytes,
    page_url: str,
) -> list[str]:

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = anchor.get("href")

        if not href:
            continue

        href = href.strip()

        if href.startswith(
            (
                "javascript:",
                "data:",
                "mailto:",
                "#",
            )
        ):
            continue

        absolute_url = urljoin(
            page_url,
            href,
        )

        parsed = urlparse(
            absolute_url
        )

        if parsed.scheme not in (
            "http",
            "https",
        ):
            continue

        text = anchor.get_text(
            " ",
            strip=True,
        ).lower()

        href_lower = absolute_url.lower()

        score = 0

        # Strong indicators.
        if any(
            href_lower.endswith(ext)
            for ext in VIDEO_EXTENSIONS
        ):
            score += 100

        if any(
            word in text
            for word in (
                "download",
                "direct",
                "video",
                "1080p",
                "1080",
            )
        ):
            score += 20

        if any(
            word in href_lower
            for word in (
                "download",
                "/dl/",
                "direct",
                "file",
            )
        ):
            score += 10

        if score > 0:
            links.append(
                (
                    score,
                    absolute_url,
                )
            )

    # Highest-scoring links first.
    links.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    result = []

    for _, url in links:
        if url not in result:
            result.append(url)

    return result


def resolve_download_url(
    url: str,
    session: requests.Session,
) -> str:

    current_url = url

    for hop in range(
        MAX_HTML_HOPS + 1
    ):

        print(
            f"Resolving URL "
            f"(step {hop + 1}): "
            f"{current_url}"
        )

        with session.get(
            current_url,
            stream=True,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
            allow_redirects=True,
        ) as response:

            response.raise_for_status()

            final_url = response.url

            content_type = get_content_type(
                response
            )

            print(
                f"Final URL: {final_url}"
            )

            print(
                f"Content-Type: {content_type}"
            )

            # A real video/file response.
            if is_probable_file_response(
                response
            ):
                return final_url

            # HTML page needs inspection.
            if content_type in HTML_CONTENT_TYPES:
                first_chunk = next(
                    response.iter_content(
                        chunk_size=8192
                    ),
                    b"",
                )

                if looks_like_blocked_page(
                    first_chunk
                ):
                    raise RuntimeError(
                        "The download service returned "
                        "a CAPTCHA/human-verification or "
                        "anti-bot page. "
                        "Automatic bypass is not supported."
                    )

                if not looks_like_html(
                    first_chunk
                ):
                    raise RuntimeError(
                        "The server returned an "
                        "unexpected response instead "
                        "of a video file."
                    )

                # Read enough HTML to find normal links.
                html_parts = [
                    first_chunk
                ]

                total_html = len(
                    first_chunk
                )

                for chunk in response.iter_content(
                    chunk_size=64 * 1024
                ):
                    html_parts.append(chunk)

                    total_html += len(chunk)

                    if total_html >= 2 * 1024 * 1024:
                        break

                html = b"".join(
                    html_parts
                )

                if looks_like_blocked_page(
                    html
                ):
                    raise RuntimeError(
                        "The download service returned "
                        "a CAPTCHA/human-verification or "
                        "anti-bot page. "
                        "Automatic bypass is not supported."
                    )

                links = find_download_links(
                    html,
                    final_url,
                )

                if not links:
                    raise RuntimeError(
                        "The download page did not expose "
                        "a normal accessible file/download link."
                    )

                print(
                    f"Found {len(links)} possible "
                    f"download link(s)."
                )

                # Try candidates in order.
                for candidate in links:

                    print(
                        f"Trying download candidate: "
                        f"{candidate}"
                    )

                    try:
                        resolved = resolve_download_url(
                            candidate,
                            session,
                        )

                        return resolved

                    except Exception as exc:
                        print(
                            f"Candidate rejected: {exc}"
                        )

                raise RuntimeError(
                    "No accessible video file was found "
                    "among the normal download links."
                )

            # Unknown/non-video response.
            raise RuntimeError(
                "Download URL returned an unsupported "
                f"content type: {content_type}"
            )

    raise RuntimeError(
        "Too many normal download-page redirects."
    )


def download_file(
    url: str,
    output_path: str,
    timeout: int = READ_TIMEOUT,
) -> Path:

    output = Path(
        output_path
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = output.with_suffix(
        output.suffix + ".part"
    )

    session = create_session()

    try:

        # Resolve normal download pages first.
        direct_url = resolve_download_url(
            url,
            session,
        )

        print(
            f"Resolved video URL: {direct_url}"
        )

        with session.get(
            direct_url,
            stream=True,
            timeout=(
                CONNECT_TIMEOUT,
                timeout,
            ),
            allow_redirects=True,
        ) as response:

            response.raise_for_status()

            content_type = get_content_type(
                response
            )

            print(
                f"Video response URL: "
                f"{response.url}"
            )

            print(
                f"Video Content-Type: "
                f"{content_type}"
            )

            if not is_probable_file_response(
                response
            ):
                raise RuntimeError(
                    "Resolved URL did not return "
                    "a recognizable video/file response."
                )

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            expected_size = None

            if (
                content_length
                and content_length.isdigit()
            ):
                expected_size = int(
                    content_length
                )

            downloaded = 0
            first_chunk = True

            with open(
                temp_file,
                "wb",
            ) as file:

                for chunk in response.iter_content(
                    chunk_size=CHUNK_SIZE
                ):

                    if not chunk:
                        continue

                    if first_chunk:

                        first_chunk = False

                        if looks_like_html(
                            chunk
                        ):
                            raise RuntimeError(
                                "The supposed video response "
                                "actually contains HTML."
                            )

                        if looks_like_blocked_page(
                            chunk
                        ):
                            raise RuntimeError(
                                "The supposed video response "
                                "contains a CAPTCHA or "
                                "human-verification page."
                            )

                    file.write(chunk)

                    downloaded += len(
                        chunk
                    )

            if downloaded <= 0:
                raise RuntimeError(
                    "Downloaded file is empty."
                )

            if (
                expected_size is not None
                and downloaded != expected_size
            ):
                raise RuntimeError(
                    "Incomplete download: "
                    f"{downloaded} / "
                    f"{expected_size} bytes"
                )

        temp_file.replace(
            output
        )

        print(
            f"Download completed: "
            f"{downloaded} bytes"
        )

        return output

    except Exception:

        if temp_file.exists():
            temp_file.unlink()

        raise
