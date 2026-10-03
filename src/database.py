import json
from pathlib import Path
from typing import Any


DB_FILE = Path(__file__).resolve().parent.parent / "data" / "downloaded.json"


def _ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not DB_FILE.exists():
        DB_FILE.write_text(
            json.dumps({"movies": []}, indent=2),
            encoding="utf-8",
        )


def load_database() -> dict[str, Any]:
    _ensure_db()

    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {"movies": []}

    if not isinstance(data, dict):
        data = {"movies": []}

    if not isinstance(data.get("movies"), list):
        data["movies"] = []

    return data


def save_database(data: dict[str, Any]) -> None:
    _ensure_db()

    temp_file = DB_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temp_file.replace(DB_FILE)


def is_downloaded(source_id: str | None = None, source_url: str | None = None) -> bool:
    data = load_database()

    for movie in data["movies"]:
        if source_id and movie.get("source_id") == source_id:
            return True

        if source_url and movie.get("source_url") == source_url:
            return True

    return False


def add_completed_movie(
    source_id: str,
    title: str,
    source_url: str,
    quality: str,
    drive_file_id: str,
) -> None:
    data = load_database()

    data["movies"].append(
        {
            "source_id": source_id,
            "title": title,
            "source_url": source_url,
            "quality": quality,
            "drive_file_id": drive_file_id,
            "uploaded_at": __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat(),
        }
    )

    save_database(data)


def count_movies() -> int:
    return len(load_database()["movies"])
