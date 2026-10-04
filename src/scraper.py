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
            "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
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


def find_movie_links(session: requests.Session) -> list[str]:
    print(f"Opening source website: {BASE_URL}")

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

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")

        if not href:
            continue

        url = normalize_url(href)

        if not is_movie_url(url):
            continue

        if url not in links:
            links.append(url)

    return links


def extract_title(soup: BeautifulSoup, source_id: str) -> str:
    """
    Extract a useful movie title from the movie page.
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

    # Then try page title.
    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True,
        )

        if title:
            # Remove common website suffix.
            title = re.sub(
                r"\s*[-|]\s*Vegamovies.*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()

            return title

    return source_id


def find_quality_link(
    soup: BeautifulSoup,
    movie_url: str,
) -> str | None:
    """
    Find the download link associated with the exact
    '1080p x264' quality label.

    Important:
    The old scraper used parent.find('a'), which could
    accidentally return the site's homepage link.

    This function instead looks AFTER the exact quality
    heading and validates the candidate URL.
    """

    base_url_normalized = normalize_url(BASE_URL).rstrip("/")

    movie_url_normalized = normalize_url(
        movie_url
    ).rstrip("/")

    # Find elements containing the exact quality text.
    candidates = []

    for element in soup.find_all(
        ["h1", "h2", "h3", "h4", "div", "span", "p", "strong", "b"]
    ):
        text = element.get_text(
            " ",
            strip=True,
        )

        if EXACT_QUALITY.lower() in text.lower():
            candidates.append(element)

    print(
        f"Found {len(candidates)} element(s) containing "
        f"'{EXACT_QUALITY}'."
    )

    for quality_element in candidates:

        print(
            "Checking quality element:",
            quality_element.get_text(
                " ",
                strip=True,
            ),
        )

        # --------------------------------------------------
        # 1. If the quality element itself contains a link
        # --------------------------------------------------

        direct_link = quality_element.find(
            "a",
            href=True,
        )

        if direct_link:
            href = direct_link.get("href")

            if href:
                candidate_url = normalize_url(href)

                if _is_valid_download_candidate(
                    candidate_url,
                    base_url_normalized,
                    movie_url_normalized,
                ):
                    print(
                        "Download link found directly:",
                        candidate_url,
                    )

                    return candidate_url

        # --------------------------------------------------
        # 2. Check the immediate parent/container
        # --------------------------------------------------

        parent = quality_element.parent

        if parent:
            parent_link = parent.find(
                "a",
                href=True,
            )

            if parent_link:
                href = parent_link.get("href")

                if href:
                    candidate_url = normalize_url(href)

                    if _is_valid_download_candidate(
                        candidate_url,
                        base_url_normalized,
                        movie_url_normalized,
                    ):
                        print(
                            "Download link found in parent:",
                            candidate_url,
                        )

                        return candidate_url

        # --------------------------------------------------
        # 3. Most important:
        #    find the NEXT link after the quality heading
        # --------------------------------------------------

        next_link = quality_element.find_next(
            "a",
            href=True,
        )

        while next_link:

            href = next_link.get("href")

            if href:
                candidate_url = normalize_url(href)

                if _is_valid_download_candidate(
                    candidate_url,
                    base_url_normalized,
                    movie_url_normalized,
                ):
                    print(
                        "Download link found after quality label:",
                        candidate_url,
                    )

                    return candidate_url

            next_link = next_link.find_next(
                "a",
                href=True,
            )

    return None


def _is_valid_download_candidate(
    candidate_url: str,
    base_url: str,
    movie_url: str,
) -> bool:
    """
    Reject obvious non-download links.
    """

    candidate = candidate_url.rstrip("/")

    # Never use the homepage as the download URL.
    if candidate == base_url:
        print(
            "Rejected candidate: source homepage."
        )
        return False

    # Never use the movie page itself.
    if candidate == movie_url:
        print(
            "Rejected candidate: movie page itself."
        )
        return False

    parsed = urlparse(candidate)

    if parsed.scheme not in (
        "http",
        "https",
    ):
        print(
            "Rejected candidate: invalid URL scheme:",
            candidate_url,
        )
        return False

    # Reject javascript/data links.
    if candidate.lower().startswith(
        (
            "javascript:",
            "data:",
            "mailto:",
        )
    ):
        print(
            "Rejected candidate:",
            candidate_url,
        )
        return False

    return True


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

    source_id = get_source_id(movie_url)

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
            f"No valid '{EXACT_QUALITY}' download "
            f"link found on this page."
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
    """
    Scan the source website and return the first movie
    that contains the exact 1080p x264 option.
    """

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
            f"Exact quality found: {EXACT_QUALITY}"
        )

        print(
            f"Movie title: {movie.title}"
        )

        print(
            f"Download URL: {movie.download_url}"
        )

        return movie

    return None
