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


def test_minio_client_honors_secure_setting(monkeypatch) -> None:
    import sys

    from packages.core import settings

    # packages.storage re-exports the singleton `object_store`, so fetch the
    # module itself through sys.modules.
    object_store_module = sys.modules["packages.storage.object_store"]

    captured = {}

    class _FakeMinio:
        def __init__(self, endpoint, access_key=None, secret_key=None, secure=None):
            captured["endpoint"] = endpoint
            captured["secure"] = secure

        def bucket_exists(self, bucket):
            return True

    monkeypatch.setattr(object_store_module, "Minio", _FakeMinio)

    store = object_store_module.ObjectStore()  # fresh instance, own cached_property
    monkeypatch.setattr(settings, "minio_secure", False)
    store.ping()
    assert captured["secure"] is False

    store2 = object_store_module.ObjectStore()
    monkeypatch.setattr(settings, "minio_secure", True)
    store2.ping()
    assert captured["secure"] is True
