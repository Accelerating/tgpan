from unittest.mock import AsyncMock

import pytest
from test_drive import upload_file, wait_for


def folder(client, name, parent=None):
    response = client.post("/api/files/folders", json={"name": name, "parent_id": parent})
    assert response.status_code == 201
    return response.json()


def test_move_changes_only_directory_mapping(setup, monkeypatch):
    client, app, storage = setup
    source = folder(client, "source")
    destination = folder(client, "destination")
    nested = upload_file(client, b"nested content", "nested.txt", source["id"])
    standalone = upload_file(client, b"standalone content", "standalone.txt")
    for task in (nested, standalone):
        wait_for(client, task["id"], "complete")
    share = client.post("/api/shares", json={"node_id": nested["node_id"]}).json()
    tables = ("uploads", "blocks", "configs", "shares", "cleanup")
    before = {table: app.state.db.all(f"SELECT * FROM {table} ORDER BY id") for table in tables}
    messages = dict(storage.messages)
    calls = []
    for name in ("upload", "download", "delete", "test"):
        mock = AsyncMock(side_effect=AssertionError("Moving must not access remote storage"))
        monkeypatch.setattr(storage, name, mock)
        calls.append(mock)
    for ids, parent in [
        ([source["id"], standalone["node_id"]], destination["id"]),
        ([source["id"]], None),
    ]:
        response = client.post("/api/files/batch", json={"ids": ids, "action": "move", "parent_id": parent})
        assert response.status_code == 200, response.text
        for identity in ids:
            assert (
                app.state.db.one("SELECT parent_id FROM nodes WHERE id=%s", (identity,))["parent_id"] == parent
            )
    assert (
        app.state.db.one("SELECT parent_id FROM nodes WHERE id=%s", (nested["node_id"],))["parent_id"]
        == source["id"]
    )
    assert client.get("/api/public/shares/" + share["path"].rsplit("/", 1)[-1]).status_code == 200
    assert before == {table: app.state.db.all(f"SELECT * FROM {table} ORDER BY id") for table in tables}
    assert storage.messages == messages
    for mock in calls:
        mock.assert_not_called()


def test_move_name_conflict_preserves_entire_selection(setup):
    client, app, _ = setup
    destination = folder(client, "destination")
    free = folder(client, "free")
    conflict = folder(client, "same")
    existing = folder(client, "same", destination["id"])
    response = client.post(
        "/api/files/batch",
        json={
            "ids": [free["id"], conflict["id"]],
            "action": "move",
            "parent_id": destination["id"],
        },
    )
    assert response.status_code == 409
    assert "same" in response.json()["detail"]
    rows = {node["id"]: node for node in app.state.db.all("SELECT * FROM nodes")}
    assert len(rows) == 4
    assert rows[free["id"]]["parent_id"] is None
    assert rows[conflict["id"]]["parent_id"] is None
    assert rows[existing["id"]]["parent_id"] == destination["id"]
    assert rows[conflict["id"]]["name"] == rows[existing["id"]]["name"] == "same"


@pytest.mark.parametrize("into_child", [False, True])
def test_batch_move_rejects_directory_cycles(setup, into_child):
    client, app, _ = setup
    source = folder(client, "parent")
    child = folder(client, "child", source["id"])
    response = client.post(
        "/api/files/batch",
        json={
            "ids": [source["id"]],
            "action": "move",
            "parent_id": child["id"] if into_child else source["id"],
        },
    )
    assert response.status_code == 400
    assert app.state.db.one("SELECT parent_id FROM nodes WHERE id=%s", (source["id"],))["parent_id"] is None
