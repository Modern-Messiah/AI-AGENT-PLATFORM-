from __future__ import annotations

from packages.storage.object_store import ObjectStore


class _FakeMinio:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    def remove_object(self, bucket: str, key: str) -> None:
        self.removed.append((bucket, key))


def test_delete_removes_object_from_configured_bucket() -> None:
    store = ObjectStore()
    client = _FakeMinio()
    store.__dict__["_client"] = client

    store.delete("tenant-a/document/file.pdf")

    assert client.removed == [("app-files", "tenant-a/document/file.pdf")]
