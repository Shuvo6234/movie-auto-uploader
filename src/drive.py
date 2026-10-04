import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    refresh_token = os.environ["GOOGLE_REFRESH_TOKEN"]

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )

    return build("drive", "v3", credentials=credentials)


def upload_file(file_path: str, file_name: str | None = None) -> str:
    service = get_drive_service()

    folder_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    upload_name = file_name or path.name

    metadata = {
        "name": upload_name,
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        str(path),
        resumable=True,
    )

    result = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,name,size,mimeType,parents",
        )
        .execute()
    )

    file_id = result.get("id")

    if not file_id:
        raise RuntimeError("Google Drive did not return a file ID.")

    return file_id


def verify_upload(file_id: str, expected_size: int | None = None) -> bool:
    service = get_drive_service()

    result = (
        service.files()
        .get(
            fileId=file_id,
            fields="id,name,size,mimeType,parents",
        )
        .execute()
    )

    if result.get("id") != file_id:
        return False

    if expected_size is not None:
        uploaded_size = int(result.get("size", 0))

        if uploaded_size != expected_size:
            return False

    return True
