import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from database import (
    add_completed_movie,
    is_downloaded,
)
from downloader import download_file
from drive import upload_file, verify_upload
from scraper import create_session, find_latest_movie


DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"


def already_uploaded_today() -> bool:
    # The daily limit is enforced by the GitHub Actions run itself.
    # This function is intentionally kept simple; the workflow runs once daily.
    return False


def main() -> int:
    print("=" * 60)
    print("Movie Auto Uploader started")
    print("=" * 60)

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    session = create_session()

    print("Searching for an eligible movie...")

    movie = find_latest_movie(session)

    if movie is None:
        print("No movie with exact 1080p x264 was found.")
        return 0

    print(f"Found: {movie.title}")
    print(f"Source: {movie.source_url}")
    print(f"Download page: {movie.download_url}")

    # Duplicate protection uses source ID and canonical source URL.
    if is_downloaded(
        source_id=movie.source_id,
        source_url=movie.source_url,
    ):
        print("Movie already uploaded. Skipping.")
        return 0

    safe_title = "".join(
        c if c.isalnum() or c in " ._-()" else "_"
        for c in movie.title
    ).strip()

    if not safe_title:
        safe_title = movie.source_id

    output_path = DOWNLOAD_DIR / f"{safe_title} [1080p x264].mp4"

    # Download
    print("Starting download...")

    try:
        downloaded_file = download_file(
            movie.download_url,
            str(output_path),
        )
    except Exception as exc:
        print(f"DOWNLOAD FAILED: {exc}")
        return 1

    if not downloaded_file.exists():
        print("DOWNLOAD FAILED: output file does not exist.")
        return 1

    file_size = downloaded_file.stat().st_size

    if file_size <= 0:
        print("DOWNLOAD FAILED: downloaded file is empty.")
        return 1

    print(f"Download completed: {file_size} bytes")

    # Upload
    print("Uploading to Google Drive...")

    try:
        drive_file_id = upload_file(
            str(downloaded_file),
            downloaded_file.name,
        )
    except Exception as exc:
        print(f"UPLOAD FAILED: {exc}")
        return 1

    print(f"Drive file ID: {drive_file_id}")

    # Verify upload
    print("Verifying Google Drive upload...")

    try:
        verified = verify_upload(
            drive_file_id,
            expected_size=file_size,
        )
    except Exception as exc:
        print(f"VERIFICATION FAILED: {exc}")
        return 1

    if not verified:
        print("VERIFICATION FAILED.")
        return 1

    print("Drive upload verified successfully.")

    # Only now mark the movie as completed.
    add_completed_movie(
        source_id=movie.source_id,
        title=movie.title,
        source_url=movie.source_url,
        quality=movie.quality,
        drive_file_id=drive_file_id,
    )

    print("Movie recorded in database.")

    # Remove local file after successful verification.
    try:
        downloaded_file.unlink()
        print("Local temporary file removed.")
    except OSError as exc:
        print(f"Warning: could not remove temporary file: {exc}")

    print("=" * 60)
    print("SUCCESS: 1 movie uploaded.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
