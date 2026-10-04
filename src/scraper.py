import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://YOUR-AUTHORIZED-SOURCE.example/"
TARGET_RESOLUTION = "1080p"


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
            "*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    return session


def normalize_url(url: str) -> str:
    return urljoin(BASE_URL, url)


def get_source_id(url: str) -> str:
    parsed = urlparse(url)
    filename = parsed.path.rstrip("/").split("/")[-1]

    match = re.match(r"(\d+)", filename)

    if match:
        return match.group(1)

    return filename or url


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_movie_url(url: str) -> bool:
    parsed = urlparse(url)
    base_domain = urlparse(BASE_URL).netloc

    if parsed.netloc != base_domain:
        return False

    return bool(
        re.search(
            r"\.(html?|php)$",
            parsed.path,
            re.IGNORECASE,
        )
    )


def find_movie_links(
    session: requests.Session,
) -> list[str]:

    print(f"Opening source website: {BASE_URL}")

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

    heading = soup.find("h1")

    if heading:
        title = heading.get_text(
            " ",
            strip=True,
        )

        if title:
            return title

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True,
        )

        if title:
            return title

    return source_id


def is_valid_link(
    url: str,
    movie_url: str,
) -> bool:

    if not url:
        return False

    absolute = normalize_url(url)

    if absolute == normalize_url(movie_url):
        return False

    parsed = urlparse(absolute)

    if parsed.scheme not in (
        "http",
        "https",
    ):
        return False

    lowered = absolute.lower()

    if lowered.startswith(
        (
            "javascript:",
            "data:",
            "mailto:",
        )
    ):
        return False

    return True


def quality_score(text: str) -> int:
    """
    Higher score = preferred 1080p release.
    Non-1080p releases are rejected.
    """

    value = clean_text(text).lower()

    if not re.search(
        r"\b1080p\b",
        value,
    ):
        return -100000

    score = 1000

    # Source quality
    if "bluray" in value:
        score += 180
    elif "web-dl" in value:
        score += 160
    elif "webrip" in value:
        score += 140
    elif "brrip" in value:
        score += 120
    elif "hdrip" in value:
        score += 80
    elif "hdtv" in value:
        score += 50
    elif "hdtc" in value:
        score += 20

    # Codec
    if "10bit-hevc" in value:
        score += 55
    elif "hevc" in value:
        score += 45
    elif "x265" in value:
        score += 45
    elif "x264" in value:
        score += 35
    elif "h264" in value:
        score += 35

    # Audio
    if "dd5.1" in value:
        score += 35
    elif "5.1" in value:
        score += 25
    elif "aac" in value:
        score += 10

    # Dual audio
    if "dual audio" in value:
        score += 20

    # Subtitles
    if "esubs" in value:
        score += 5

    # Reject low-quality sources
    bad_terms = (
        "camrip",
        "cam",
        "telesync",
        "telecine",
        "screener",
        "scr",
        "ts",
    )

    for term in bad_terms:
        if re.search(
            rf"\b{re.escape(term)}\b",
            value,
        ):
            score -= 1000

    return score


def find_nearby_link(
    element,
    movie_url: str,
) -> str | None:

    # Direct <a>
    if element.name == "a":
        href = element.get("href")

        if href and is_valid_link(
            href,
            movie_url,
        ):
            return normalize_url(href)

    # Child <a>
    anchor = element.find(
        "a",
        href=True,
    )

    if anchor:
        href = anchor.get("href")

        if href and is_valid_link(
            href,
            movie_url,
        ):
            return normalize_url(href)

    # Parent <a>
    parent = element.parent

    if parent:
        anchor = parent.find(
            "a",
            href=True,
        )

        if anchor:
            href = anchor.get("href")

            if href and is_valid_link(
                href,
                movie_url,
            ):
                return normalize_url(href)

    # Nearby siblings
    sibling = element.next_sibling

    for _ in range(10):

        if sibling is None:
            break

        if getattr(
            sibling,
            "name",
            None,
        ):

            if sibling.name == "a":

                href = sibling.get("href")

                if href and is_valid_link(
                    href,
                    movie_url,
                ):
                    return normalize_url(href)

            anchor = sibling.find(
                "a",
                href=True,
            )

            if anchor:

                href = anchor.get("href")

                if href and is_valid_link(
                    href,
                    movie_url,
                ):
                    return normalize_url(href)

        sibling = sibling.next_sibling

    return None


def find_best_1080p_link(
    soup: BeautifulSoup,
    movie_url: str,
) -> tuple[str, str] | None:

    candidates: list[
        tuple[int, str, str]
    ] = []

    elements = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "a",
            "div",
            "p",
            "li",
        ]
    )

    for element in elements:

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if "1080p" not in text.lower():
            continue

        score = quality_score(text)

        if score < 0:
            continue

        link = find_nearby_link(
            element,
            movie_url,
        )

        if not link:
            continue

        candidate = (
            score,
            text,
            link,
        )

        if candidate not in candidates:
            candidates.append(candidate)

    if not candidates:
        return None

    # Highest score first
    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    print()
    print("1080p candidates:")

    for score, quality, url in candidates:

        print(
            f"  Score: {score}"
        )

        print(
            f"  Quality: {quality}"
        )

        print(
            f"  URL: {url}"
        )

        print()

    best_score = candidates[0][0]
    best_quality = candidates[0][1]
    best_url = candidates[0][2]

    print(
        "Selected 1080p release:"
    )

    print(
        f"  Score: {best_score}"
    )

    print(
        f"  Quality: {best_quality}"
    )

    print(
        f"  URL: {best_url}"
    )

    return (
        best_url,
        best_quality,
    )


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

    result = find_best_1080p_link(
        soup,
        movie_url,
    )

    if not result:

        print(
            "No usable 1080p option found."
        )

        return None

    download_url, quality = result

    return Movie(
        source_id=source_id,
        title=title,
        source_url=movie_url,
        download_url=download_url,
        quality=quality,
    )


def find_movie_candidates(
    session: requests.Session,
) -> list[Movie]:

    movie_links = find_movie_links(
        session
    )

    print(
        f"Found {len(movie_links)} "
        "movie page(s)."
    )

    movies: list[Movie] = []

    for index, movie_url in enumerate(
        movie_links,
        start=1,
    ):

        print()
        print(
            "=" * 60
        )

        print(
            f"Checking movie "
            f"{index}/{len(movie_links)}"
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
            f"Title: {movie.title}"
        )

        print(
            f"Selected quality: "
            f"{movie.quality}"
        )

        movies.append(movie)

    print()
    print(
        f"Total eligible 1080p movies: "
        f"{len(movies)}"
    )

    return movies
