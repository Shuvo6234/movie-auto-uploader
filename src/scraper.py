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
        )
    })

    return session


def normalize_url(url: str) -> str:
    return urljoin(BASE_URL, url)


def get_source_id(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    filename = path.split("/")[-1]

    match = re.match(r"(\d+)", filename)

    if match:
        return match.group(1)

    return filename or url


def is_movie_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.netloc != urlparse(BASE_URL).netloc:
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
        url = normalize_url(anchor["href"])

        if is_movie_url(url):
            if url not in links:
                links.append(url)

    return links


def extract_movie_info(
    session: requests.Session,
    movie_url: str,
) -> Movie | None:

    response = session.get(
        movie_url,
        timeout=(20, 60),
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    title = ""

    if soup.title:
        title = soup.title.get_text(
            " ",
            strip=True,
        )

    if not title:
        heading = soup.find("h1")

        if heading:
            title = heading.get_text(
                " ",
                strip=True,
            )

    quality_link = None

    for element in soup.find_all(
        ["a", "h1", "h2", "h3", "h4", "div", "span"]
    ):

        text = element.get_text(
            " ",
            strip=True,
        )

        if EXACT_QUALITY.lower() in text.lower():

            if element.name == "a" and element.get("href"):
                quality_link = element
                break

            parent = element.parent

            if parent:
                candidate = parent.find(
                    "a",
                    href=True,
                )

                if candidate:
                    quality_link = candidate
                    break

    if not quality_link:
        return None

    download_url = normalize_url(
        quality_link.get("href")
    )

    source_id = get_source_id(
        movie_url
    )

    return Movie(
        source_id=source_id,
        title=title or source_id,
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

        except Exception as exc:
            print(
                f"Could not read movie page: {exc}"
            )
            continue

        if movie is None:
            continue

        print(
            f"Exact quality found: {EXACT_QUALITY}"
        )

        return movie

    return None
