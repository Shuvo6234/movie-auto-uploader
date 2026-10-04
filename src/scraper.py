import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://vegamoviess.io/"
EXACT_QUALITY = "1080p x264"


@dataclass
class Movie:
    source_id: str
    title: str
    source_url: str
    download_url: str
    quality: str


def create_session() -> requests.Session:
    session = requests.Session()

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


def normalize_url(url: str) -> str:
    return urljoin(BASE_URL, url)


def get_source_id(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    filename = path.split("/")[-1]

    match = re.match(r"(\d+)", filename)

    if match:
        return match.group(1)

    return filename or url


def is_movie_url(url: str) -> bool:
    parsed = urlparse(url)

    base_domain = urlparse(BASE_URL).netloc

    if parsed.netloc != base_domain:
        return False

    return bool(
        re.search(
            r"-202[0-9]-.*\.html$",
            parsed.path,
            re.IGNORECASE,
        )
    )


def find_movie_links(
    session: requests.Session,
) -> list[str]:

    print(
        f"Opening source website: {BASE_URL}"
    )

    response = session.get(
        BASE_URL,
        timeout=(20, 60),
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
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

        url = normalize_url(href)

        if not is_movie_url(url):
            continue

        if url not in links:
            links.append(url)

    return links


def extract_title(
    soup: BeautifulSoup,
    source_id: str,
) -> str:

    # Prefer the main H1.
    heading = soup.find("h1")

    if heading:
        title = heading.get_text(
            " ",
            strip=True,
        )

        if title:
            return title

    # Fallback to <title>.
    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True,
        )

        if title:
            title = re.sub(
                r"\s*[-|]\s*Vegamovies.*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()

            title = re.sub(
                r"^Download\s+",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()

            return title

    return source_id


def _clean_text(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _is_valid_download_link(
    url: str,
    movie_url: str,
) -> bool:

    if not url:
        return False

    normalized = normalize_url(url).rstrip("/")

    base = BASE_URL.rstrip("/")

    movie = normalize_url(movie_url).rstrip("/")

    # Never accept homepage.
    if normalized == base:
        return False

    # Never accept the movie page itself.
    if normalized == movie:
        return False

    parsed = urlparse(normalized)

    if parsed.scheme not in (
        "http",
        "https",
    ):
        return False

    # Reject obvious non-web links.
    if normalized.lower().startswith(
        (
            "javascript:",
            "data:",
            "mailto:",
        )
    ):
        return False

    return True


def _find_link_after_quality_heading(
    quality_heading,
    movie_url: str,
) -> str | None:

    """
    The actual page structure is approximately:

        <h3>1080p x264</h3>
        <h3></h3>
        <a href="https://nexdrive.you/...">
            Click Here To Download [2.5GB]
        </a>

    So we inspect the nearby siblings rather than searching
    the entire remainder of the document.
    """

    # First inspect following siblings.
    sibling = quality_heading.next_sibling

    checked_nodes = 0

    while sibling is not None and checked_nodes < 12:

        checked_nodes += 1

        # If it is an element.
        if getattr(
            sibling,
            "name",
            None,
        ):

            # If sibling itself is an anchor.
            if sibling.name == "a":
                href = sibling.get("href")

                if href and _is_valid_download_link(
                    href,
                    movie_url,
                ):
                    return normalize_url(href)

            # Otherwise look for an anchor directly
            # inside this nearby sibling.
            anchor = sibling.find(
                "a",
                href=True,
            )

            if anchor:
                href = anchor.get("href")

                if href and _is_valid_download_link(
                    href,
                    movie_url,
                ):
                    return normalize_url(href)

        sibling = sibling.next_sibling

    return None


def find_quality_link(
    soup: BeautifulSoup,
    movie_url: str,
) -> str | None:

    """
    Find the exact movie download block.

    IMPORTANT:
    We require an element whose normalized text is exactly:

        1080p x264

    This prevents the navigation menu's many
    '1080p' strings from being selected.
    """

    quality_headings = []

    for element in soup.find_all(
        ["h2", "h3", "h4"],
    ):
        text = _clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if text.lower() == EXACT_QUALITY.lower():
            quality_headings.append(element)

    print(
        f"Found {len(quality_headings)} exact "
        f"'{EXACT_QUALITY}' heading(s)."
    )

    if not quality_headings:
        return None

    for heading in quality_headings:

        print(
            "Exact quality heading found:",
            _clean_text(
                heading.get_text(
                    " ",
                    strip=True,
                )
            ),
        )

        download_url = (
            _find_link_after_quality_heading(
                heading,
                movie_url,
            )
        )

        if download_url:

            print(
                "Correct download link found:",
                download_url,
            )

            return download_url

    return None


def extract_movie_info(
    session: requests.Session,
    movie_url: str,
) -> Movie | None:

    print(
        f"Reading movie page: {movie_url}"
    )

    response = session.get(
        movie_url,
        timeout=(20, 60),
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    source_id = get_source_id(
        movie_url
    )

    title = extract_title(
        soup,
        source_id,
    )

    download_url = find_quality_link(
        soup,
        movie_url,
    )

    if not download_url:

        print(
            f"No valid '{EXACT_QUALITY}' "
            f"download link found."
        )

        return None

    return Movie(
        source_id=source_id,
        title=title,
        source_url=movie_url,
        download_url=download_url,
        quality=EXACT_QUALITY,
    )


def find_latest_movie(
    session: requests.Session,
) -> Movie | None:

    movie_links = find_movie_links(
        session
    )

    print(
        f"Found {len(movie_links)} movie page(s)."
    )

    for movie_url in movie_links:

        print(
            f"Checking movie: {movie_url}"
        )

        try:

            movie = extract_movie_info(
                session,
                movie_url,
            )

        except requests.RequestException as exc:

            print(
                f"Could not read movie page: {exc}"
            )

            continue

        except Exception as exc:

            print(
                f"Unexpected scraper error: {exc}"
            )

            continue

        if movie is None:
            continue

        print(
            f"Exact quality found: "
            f"{EXACT_QUALITY}"
        )

        print(
            f"Movie title: {movie.title}"
        )

        print(
            f"Download URL: {movie.download_url}"
        )

        return movie

    return None
