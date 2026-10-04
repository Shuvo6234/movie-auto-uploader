import sys
from pathlib import Path

from src.database import (
    add_completed_movie,
    is_downloaded,
    uploaded_today,
)
from src.downloader import download_file
from src.drive import upload_file, verify_upload
from src.scraper import create_session, find_latest_movie


DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "downloads"


def main() -> int:
    print("=" * 60)
    print("Movie Auto Uploader started")
    print("=" * 60)

    # দিনে সফলভাবে সর্বোচ্চ ১টি upload
    if uploaded_today():
        print("Today's successful upload limit has already been reached.")
        print("Stopping.")
        return 0

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = create_session()

    print("Searching for an eligible movie...")

    try:
        movie = find_latest_movie(session)
    except Exception as exc:
        print(f"SCRAPER FAILED: {exc}")
        return 1

    if movie is None:
        print("No movie with exact 1080p x264 was found.")
        return 0

    print(f"Found: {movie.title}")
    print(f"Source: {movie.source_url}")
    print(f"Download URL: {movie.download_url}")

    # আগে upload করা হয়েছে কিনা check
    if is_downloaded(
        source_id=movie.source_id,
        source_url=movie.source_url,
    ):
        print("Movie already uploaded. Nothing to do.")
        return 0

    # Safe filename তৈরি
    safe_title = "".join(
        c if c.isalnum() or c in " ._-()" else "_"
        for c in movie.title
    ).strip()

    if not safe_title:
        safe_title = movie.source_id

    output_path = (
        DOWNLOAD_DIR
        / f"{safe_title} [1080p x264].mkv"
    )

    print(f"Output file: {output_path}")

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

    # Google Drive upload
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

    # Upload verification
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

    # Upload সফল হওয়ার পরেই database-এ save
    add_completed_movie(
        source_id=movie.source_id,
        title=movie.title,
        source_url=movie.source_url,
        quality=movie.quality,
        drive_file_id=drive_file_id,
    )

    print("Movie recorded in database.")

    # GitHub runner থেকে temporary file delete
    try:
        downloaded_file.unlink()
        print("Local temporary file removed.")
    except OSError as exc:
        print(f"Warning: could not remove local file: {exc}")

    print("=" * 60)
    print("SUCCESS: 1 movie uploaded.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
