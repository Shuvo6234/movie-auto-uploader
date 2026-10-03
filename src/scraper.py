import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://vegamoviess.io/"
DOMAIN = "vegamoviess.io"


@dataclass
class Movie:
    source_id: str
    title: str
    source_url: str
    download_url: str
    quality: str = "1080p x264"


def create_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            )
        }
    )

    return session


def get_soup(
    session: requests.Session,
    url: str,
    timeout: int = 30,
) -> BeautifulSoup:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def is_movie_url(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.netloc.lower() != DOMAIN:
        return False

    path = parsed.path.lower()

    return (
        path.endswith(".html")
        and bool(re.search(r"-\d{3,}-", path))
    )


def extract_source_id(url: str) -> str:
    path = urlparse(url).path

    match = re.search(r"/(\d+)-", path)

    if match:
        return match.group(1)

    # Fallback when the site's URL format changes.
    return url.rstrip("/").split("/")[-1]


def find_movie_links(
    session: requests.Session,
    page_url: str = BASE_URL,
) -> list[str]:
    soup = get_soup(session, page_url)

    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"])

        if not is_movie_url(href):
            continue

        if href in seen:
            continue

        seen.add(href)
        links.append(href)

    return links


def find_1080p_x264(
    session: requests.Session,
    movie_url: str,
) -> Movie | None:
    soup = get_soup(session, movie_url)

    title = soup.find("h1")

    if title:
        movie_title = title.get_text(" ", strip=True)
    else:
        movie_title = soup.title.get_text(" ", strip=True) if soup.title else movie_url

    # Find the exact heading "1080p x264".
    target_heading = None

    for heading in soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
        text = " ".join(heading.get_text(" ", strip=True).split())

        if text.casefold() == "1080p x264":
            target_heading = heading
            break

    if target_heading is None:
        return None

    # The site's current structure puts the download <a>
    # immediately after the quality heading.
    current = target_heading.find_next()

    while current is not None:
        if current.name == "a" and current.get("href"):
            href = urljoin(movie_url, current["href"])

            if urlparse(href).scheme in {"http", "https"}:
                return Movie(
                    source_id=extract_source_id(movie_url),
                    title=movie_title,
                    source_url=movie_url,
                    download_url=href,
                )

        # Stop before accidentally crossing into another quality section.
        if current.name in {"h2", "h3", "h4", "h5", "h6"}:
            text = " ".join(current.get_text(" ", strip=True).split())

            if text.casefold() != "1080p x264":
                break

        current = current.find_next()

    return None


def find_latest_movie(
    session: requests.Session,
) -> Movie | None:
    movie_links = find_movie_links(session)

    for movie_url in movie_links:
        movie = find_1080p_x264(session, movie_url)

        if movie is not None:
            return movie

    return None
