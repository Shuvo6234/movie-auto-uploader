import sys
from pathlib import Path

from src.database import (
    add_completed_movie,
    is_downloaded,
    uploaded_today,
)
from src.downloader import download_file
from src.drive import upload_file, verify_upload
from src.scraper import create_session, find_movie_candidates


DOWNLOAD_DIR = (
    Path(__file__).resolve().parent.parent
    / "downloads"
)


def safe_filename(title: str, source_id: str) -> str:

    name = "".join(
        c if c.isalnum() or c in " ._-()"
        else "_"
        for c in title
    ).strip()

    return name or source_id


def main() -> int:

    print("=" * 60)
    print("Movie Auto Uploader started")
    print("=" * 60)

    # --------------------------------------------------
    # Daily successful-upload limit
    # --------------------------------------------------

    if uploaded_today():

        print(
            "Today's successful upload limit "
            "has already been reached."
        )

        print("Stopping.")

        return 0

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = create_session()

    print(
        "Searching for eligible movies..."
    )

    try:

        movies = find_movie_candidates(
            session
        )

    except Exception as exc:

        print(
            f"SCRAPER FAILED: {exc}"
        )

        return 1

    print(
        f"Eligible movie candidates found: "
        f"{len(movies)}"
    )

    if not movies:

        print(
            "No movie with exact "
            "'1080p x264' was found."
        )

        return 0

    # --------------------------------------------------
    # Try movies one by one
    # --------------------------------------------------

    for index, movie in enumerate(
        movies,
        start=1,
    ):

        print()
        print("=" * 60)

        print(
            f"Candidate {index}/{len(movies)}"
        )

        print(
            f"Title: {movie.title}"
        )

        print(
            f"Source: {movie.source_url}"
        )

        print(
            f"Download URL: "
            f"{movie.download_url}"
        )

        # ----------------------------------------------
        # Duplicate check
        # ----------------------------------------------

        if is_downloaded(
            source_id=movie.source_id,
            source_url=movie.source_url,
        ):

            print(
                "SKIP: Movie already uploaded."
            )

            continue

        safe_title = safe_filename(
            movie.title,
            movie.source_id,
        )

        output_path = (
            DOWNLOAD_DIR
            / f"{safe_title} "
              f"[1080p x264].mkv"
        )

        # ----------------------------------------------
        # Download
        # ----------------------------------------------

        print(
            "Starting download..."
        )

        try:

            downloaded_file = download_file(
                movie.download_url,
                str(output_path),
            )

        except Exception as exc:

            print(
                f"DOWNLOAD SKIPPED: {exc}"
            )

            # Important:
            # failed download does NOT count
            # toward daily quota.

            continue

        if not downloaded_file.exists():

            print(
                "DOWNLOAD SKIPPED: "
                "output file does not exist."
            )

            continue

        file_size = (
            downloaded_file.stat().st_size
        )

        if file_size <= 0:

            print(
                "DOWNLOAD SKIPPED: "
                "downloaded file is empty."
            )

            try:
                downloaded_file.unlink()
            except OSError:
                pass

            continue

        print(
            f"Download completed: "
            f"{file_size} bytes"
        )

        # ----------------------------------------------
        # Google Drive upload
        # ----------------------------------------------

        print(
            "Uploading to Google Drive..."
        )

        try:

            drive_file_id = upload_file(
                str(downloaded_file),
                downloaded_file.name,
            )

        except Exception as exc:

            print(
                f"UPLOAD SKIPPED: {exc}"
            )

            # Failed upload does NOT count.

            try:
                downloaded_file.unlink()
            except OSError:
                pass

            continue

        print(
            f"Drive file ID: "
            f"{drive_file_id}"
        )

        # ----------------------------------------------
        # Verify upload
        # ----------------------------------------------

        print(
            "Verifying Google Drive upload..."
        )

        try:

            verified = verify_upload(
                drive_file_id,
                expected_size=file_size,
            )

        except Exception as exc:

            print(
                f"VERIFICATION FAILED: {exc}"
            )

            # The Drive file may exist, but since
            # verification failed we do NOT mark the
            # movie as completed.

            return 1

        if not verified:

            print(
                "VERIFICATION FAILED."
            )

            return 1

        print(
            "Drive upload verified successfully."
        )

        # ----------------------------------------------
        # ONLY NOW mark as completed
        # ----------------------------------------------

        add_completed_movie(
            source_id=movie.source_id,
            title=movie.title,
            source_url=movie.source_url,
            quality=movie.quality,
            drive_file_id=drive_file_id,
        )

        print(
            "Movie recorded in database."
        )

        # ----------------------------------------------
        # Remove temporary local file
        # ----------------------------------------------

        try:

            downloaded_file.unlink()

            print(
                "Local temporary file removed."
            )

        except OSError as exc:

            print(
                f"Warning: could not remove "
                f"local file: {exc}"
            )

        # ----------------------------------------------
        # SUCCESS
        # ----------------------------------------------

        print("=" * 60)

        print(
            "SUCCESS: 1 movie uploaded."
        )

        print(
            "Daily successful-upload limit "
            "reached."
        )

        print("=" * 60)

        return 0

    # --------------------------------------------------
    # Nothing succeeded
    # --------------------------------------------------

    print()
    print("=" * 60)

    print(
        "No movie could be downloaded and "
        "successfully uploaded today."
    )

    print(
        "No daily quota was consumed."
    )

    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
