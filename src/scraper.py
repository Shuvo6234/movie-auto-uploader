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
    """
    Create a requests session with normal browser-like headers.
    """

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
        "Connection": "keep-alive",
    })

    return session


def normalize_url(url: str) -> str:
    """
    Convert relative URLs into absolute URLs.
    """

    return urljoin(
        BASE_URL,
        url,
    )


def get_source_id(url: str) -> str:
    """
    Extract the numeric movie ID from the source URL.

    Example:
    /59193-digger-2026-...html
    -> 59193
    """

    parsed = urlparse(url)

    path = parsed.path.rstrip("/")

    filename = path.split("/")[-1]

    match = re.match(
        r"(\d+)",
        filename,
    )

    if match:
        return match.group(1)

    return filename or url


def is_movie_url(url: str) -> bool:
    """
    Check whether a URL looks like a Vegamovies
    movie page.
    """

    parsed = urlparse(url)

    base_domain = urlparse(
        BASE_URL
    ).netloc

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
    """
    Get movie page links from the homepage.
    """

    print(
        f"Opening source website: {BASE_URL}"
    )

    response = session.get(
        BASE_URL,
        timeout=(20, 60),
        allow_redirects=True,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    links: list[str] = []

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
    """
    Extract movie title from the movie page.
    """

    # First try H1.
    heading = soup.find("h1")

    if heading:

        title = heading.get_text(
            " ",
            strip=True,
        )

        if title:
            return title

    # Fallback to page title.
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

            if title:
                return title

    return source_id


def clean_text(text: str) -> str:
    """
    Normalize whitespace.
    """

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def is_valid_download_link(
    url: str,
    movie_url: str,
) -> bool:
    """
    Validate a candidate download URL.
    """

    if not url:
        return False

    normalized = normalize_url(
        url
    ).rstrip("/")

    base = BASE_URL.rstrip("/")

    movie = normalize_url(
        movie_url
    ).rstrip("/")

    # Do not return homepage.
    if normalized == base:
        return False

    # Do not return the same movie page.
    if normalized == movie:
        return False

    parsed = urlparse(
        normalized
    )

    if parsed.scheme not in (
        "http",
        "https",
    ):
        return False

    lowered = normalized.lower()

    if lowered.startswith(
        (
            "javascript:",
            "data:",
            "mailto:",
        )
    ):
        return False

    return True


def find_link_after_quality_heading(
    quality_heading,
    movie_url: str,
) -> str | None:
    """
    Find the download link located after
    the exact 1080p x264 heading.

    The parser only searches nearby sibling
    elements so that a link belonging to
    another quality is not accidentally selected.
    """

    sibling = (
        quality_heading.next_sibling
    )

    checked_nodes = 0

    while (
        sibling is not None
        and checked_nodes < 12
    ):

        checked_nodes += 1

        # BeautifulSoup can return text nodes.
        if not getattr(
            sibling,
            "name",
            None,
        ):
            sibling = sibling.next_sibling
            continue

        # Direct <a href="...">
        if sibling.name == "a":

            href = sibling.get(
                "href"
            )

            if href and is_valid_download_link(
                href,
                movie_url,
            ):

                return normalize_url(
                    href
                )

        # Link inside another element.
        anchor = sibling.find(
            "a",
            href=True,
        )

        if anchor:

            href = anchor.get(
                "href"
            )

            if href and is_valid_download_link(
                href,
                movie_url,
            ):

                return normalize_url(
                    href
                )

        sibling = sibling.next_sibling

    return None


def find_quality_link(
    soup: BeautifulSoup,
    movie_url: str,
) -> str | None:
    """
    Find the download link associated with
    the exact '1080p x264' heading.
    """

    quality_headings = []

    for element in soup.find_all(
        ["h2", "h3", "h4"],
    ):

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if (
            text.lower()
            == EXACT_QUALITY.lower()
        ):

            quality_headings.append(
                element
            )

    print(
        f"Found {len(quality_headings)} "
        f"exact '{EXACT_QUALITY}' heading(s)."
    )

    if not quality_headings:
        return None

    for heading in quality_headings:

        heading_text = clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

        print(
            "Exact quality heading found:",
            heading_text,
        )

        download_url = (
            find_link_after_quality_heading(
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
    """
    Read one movie page and return Movie
    information only if exact 1080p x264
    is available.
    """

    print(
        f"Reading movie page: {movie_url}"
    )

    response = session.get(
        movie_url,
        timeout=(20, 60),
        allow_redirects=True,
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


def find_movie_candidates(
    session: requests.Session,
) -> list[Movie]:
    """
    Scan all movie pages and return every movie
    that has an exact 1080p x264 download link.

    Duplicate checking is intentionally NOT done here.
    main.py handles the database check.
    """

    movie_links = find_movie_links(
        session
    )

    print(
        f"Found {len(movie_links)} "
        f"movie page(s)."
    )

    movies: list[Movie] = []

    for movie_url in movie_links:

        print()
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
                f"Could not read movie page: "
                f"{exc}"
            )

            continue

        except Exception as exc:

            print(
                f"Unexpected scraper error: "
                f"{exc}"
            )

            continue

        if movie is None:
            continue

        print(
            f"Exact quality found: "
            f"{EXACT_QUALITY}"
        )

        print(
            f"Movie title: "
            f"{movie.title}"
        )

        print(
            f"Download URL: "
            f"{movie.download_url}"
        )

        movies.append(
            movie
        )

    print()
    print(
        f"Total eligible movies: "
        f"{len(movies)}"
    )

    return movies
