from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CHUNK_SIZE = 1024 * 1024  # 1 MB

HTML_MARKERS = (
    b"<!doctype html",
    b"<html",
    b"<head",
    b"<body",
    b"verify that you are human",
    b"captcha",
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


def looks_like_html(data: bytes) -> bool:
    sample = data[:8192].lower()

    return any(
        marker in sample
        for marker in HTML_MARKERS
    )


def download_file(
    url: str,
    output_path: str,
    timeout: int = 60,
) -> Path:

    output = Path(output_path)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = output.with_suffix(
        output.suffix + ".part"
    )

    session = create_session()

    try:
        with session.get(
            url,
            stream=True,
            timeout=(20, timeout),
            allow_redirects=True,
        ) as response:

            response.raise_for_status()

            content_type = response.headers.get(
                "Content-Type",
                "",
            ).split(";")[0].strip().lower()

            print(
                f"Final URL: {response.url}"
            )

            print(
                f"Content-Type: {content_type}"
            )

            # HTML page হলে video হিসেবে download করবে না
            if content_type == "text/html":
                raise RuntimeError(
                    "Download URL returned an HTML page "
                    "instead of a video file."
                )

            expected_size = None

            content_length = response.headers.get(
                "Content-Length"
            )

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

                        if looks_like_html(chunk):
                            raise RuntimeError(
                                "Download response looks like "
                                "HTML/CAPTCHA, not a video file."
                            )

                    file.write(chunk)
                    downloaded += len(chunk)

            if downloaded == 0:
                raise RuntimeError(
                    "Downloaded file is empty."
                )

            if (
                expected_size is not None
                and downloaded != expected_size
            ):
                raise RuntimeError(
                    f"Incomplete download: "
                    f"{downloaded} / "
                    f"{expected_size} bytes"
                )

        temp_file.replace(output)

        return output

    except Exception:

        if temp_file.exists():
            temp_file.unlink()

        raise
