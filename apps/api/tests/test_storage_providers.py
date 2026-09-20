import pytest
from botocore.exceptions import ClientError

from app.providers.storage.base import StorageObjectNotFound
from app.providers.storage.local import LocalStorage
from app.providers.storage.s3 import S3Storage


class _Body:
    def __init__(self, content: bytes):
        self._content = content

    def read(self) -> bytes:
        return self._content


class FakeS3Client:
    """In-memory S3 stand-in; never performs network calls."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        try:
            content = self.objects[(Bucket, Key)]
        except KeyError as exc:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject") from exc
        return {"Body": _Body(content)}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_local_storage_roundtrip_and_missing_object(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "uploads"))
    storage = LocalStorage()

    key = storage.save(b"local-bytes", ".docx")
    assert storage.exists(key)
    assert storage.read(key) == b"local-bytes"

    storage.delete(key)
    assert not storage.exists(key)
    with pytest.raises(StorageObjectNotFound):
        storage.read(key)


def test_s3_storage_roundtrip_uses_prefix_and_maps_not_found():
    client = FakeS3Client()
    storage = S3Storage(client=client, bucket="coach-private", prefix="private")

    key = storage.save(b"s3-bytes", ".PDF")
    assert client.objects[("coach-private", f"private/{key}")] == b"s3-bytes"
    assert storage.exists(key)
    assert storage.read(key) == b"s3-bytes"

    storage.delete(key)
    assert not storage.exists(key)
    with pytest.raises(StorageObjectNotFound):
        storage.read(key)


def test_s3_storage_requires_a_bucket():
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        S3Storage(client=FakeS3Client(), bucket="")
