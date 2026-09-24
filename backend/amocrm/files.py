"""Put a file into a lead's "Файлы" tab through amoCRM's file service (drive).

Flow (developers/content/files/files-api): account ?with=drive_url →
POST {drive}/v1.0/sessions → POST the parts to upload_url / next_url → the last
part answers with the file's uuid → PUT /api/v4/leads/{id}/files.
Needs the integration's "files" scope; without it amoCRM answers 403.
"""

from .client import AmoClient, AmoError


class NoFileAccess(AmoError):
    pass


def drive_url(client: AmoClient) -> str:
    data = client.request("GET", "/api/v4/account", params={"with": "drive_url"}) or {}
    url = data.get("drive_url") or ""
    if not url.startswith("https://"):
        raise AmoError(502, "amoCRM didn't give its file service address.")
    return url.rstrip("/")


def upload(client: AmoClient, name: str, data: bytes, content_type: str, *, file_uuid: str = "") -> str:
    """Upload bytes; returns the file's uuid. With `file_uuid`, uploads a new version of that file."""
    body = {"file_name": name, "file_size": len(data), "content_type": content_type}
    if file_uuid:
        body["file_uuid"] = file_uuid
    try:
        session = client.request("POST", f"{drive_url(client)}/v1.0/sessions", json=body, mark_errors=False) or {}
    except AmoError as e:
        if e.status in (401, 403):
            raise NoFileAccess(e.status, "The amoCRM integration has no access to files.") from e
        raise
    url = session.get("upload_url")
    part = int(session.get("max_part_size") or 524288)
    if not url:
        raise AmoError(502, "amoCRM didn't open an upload session.")
    offset, answer = 0, {}
    while offset < len(data) or not answer:
        chunk = data[offset : offset + part]
        answer = (
            client.request(
                "POST", url, content=chunk, headers={"Content-Type": "application/octet-stream"}, mark_errors=False
            )
            or {}
        )
        offset += len(chunk)
        if answer.get("uuid"):
            return answer["uuid"]
        url = answer.get("next_url")
        if not url:
            break
    raise AmoError(502, "amoCRM didn't confirm the upload.")


def attach_to_lead(client: AmoClient, lead_id: int, file_uuid: str) -> None:
    client.request("PUT", f"/api/v4/leads/{int(lead_id)}/files", json=[{"file_uuid": file_uuid}], mark_errors=False)
