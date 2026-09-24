"""Our lead fields live in one amoCRM tab (field group) named just "uzbridge".

Fields made before that were called "uzbridge: …" and sat in the main tab; they are
renamed and moved into the tab the next time we touch them, so no data is lost.
"""

import logging

log = logging.getLogger(__name__)

GROUP_NAME = "uzbridge"
GROUPS = "/api/v4/leads/custom_fields/groups"


def lead_fields(client) -> list[dict]:
    data = client.request("GET", "/api/v4/leads/custom_fields", params={"limit": 250}) or {}
    return data.get("_embedded", {}).get("custom_fields", [])


def group_id(conn, client) -> str | None:
    """The "uzbridge" tab's id (made on first use). None if amoCRM won't make it: fields go to the main tab."""
    try:
        groups = (client.request("GET", GROUPS) or {}).get("_embedded", {}).get("custom_field_groups", [])
        ours = next((g for g in groups if g["id"] == conn.field_group), None) or next(
            (g for g in groups if g.get("name") == GROUP_NAME or str(g.get("name", "")).startswith("uzbridge:")), None
        )
        if ours and ours.get("name") != GROUP_NAME:
            client.request("PATCH", f"{GROUPS}/{ours['id']}", json={"name": GROUP_NAME})
        if ours is None:
            made = client.request("POST", GROUPS, json=[{"name": GROUP_NAME, "sort": 5}]) or {}
            ours = (made.get("_embedded", {}).get("custom_field_groups") or [{}])[0]
        gid = str(ours.get("id") or "")
    except Exception:  # noqa: BLE001 - no tab: the fields still work in the main tab
        log.warning("could not make the %s field group", GROUP_NAME, exc_info=True)
        return conn.field_group or None
    if gid and gid != conn.field_group:
        conn.field_group = gid
        conn.save(update_fields=["field_group"])
    return gid or None


def find(fields: list[dict], known_id, name: str, gid: str | None) -> dict | None:
    """Our field: by the id we kept, by its old "uzbridge: …" name, or by name inside our tab."""
    old = f"uzbridge: {name[:1].lower()}{name[1:]}"
    for f in fields:
        if known_id and f["id"] == known_id:
            return f
    for f in fields:
        if f["name"] in (old, f"uzbridge: {name}"):
            return f
    for f in fields:
        if f["name"] == name and (not gid or f.get("group_id") in (gid, None)):
            return f
    return None


def ensure(conn, client, specs: list[tuple[str, str, str, int | None]]) -> dict[str, int]:
    """specs: (key, name, type, id we kept). Finds, renames/moves or creates each; returns key → id."""
    gid = group_id(conn, client)
    fields = lead_fields(client)
    ids, patch, create = {}, [], []
    for i, (key, name, ftype, known) in enumerate(specs):
        f = find(fields, known, name, gid)
        if f is None:
            create.append((key, {"name": name, "type": ftype, "sort": 500 + i, **({"group_id": gid} if gid else {})}))
            continue
        ids[key] = f["id"]
        change = {}
        if f["name"] != name:
            change["name"] = name
        if gid and f.get("group_id") != gid:
            change["group_id"] = gid
        if change:
            patch.append({"id": f["id"], **change})
    if patch:
        client.request("PATCH", "/api/v4/leads/custom_fields", json=patch)
    if create:
        data = client.request("POST", "/api/v4/leads/custom_fields", json=[b for _k, b in create]) or {}
        by_name = {f["name"]: f["id"] for f in data.get("_embedded", {}).get("custom_fields", [])}
        for key, body in create:
            if body["name"] in by_name:
                ids[key] = by_name[body["name"]]
    return ids
