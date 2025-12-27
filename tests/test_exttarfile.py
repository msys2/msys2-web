import io
import pytest

from app.exttarfile import tarfile


def test_zst() -> None:
    DATA = (
        b'(\xb5/\xfd\x00X\xd5\x02\x00\xd4\x03test.txt\x00000664 '
        b'\x00001750 14150172601 013031\x00 0\x00ustar\x0000lazka'
        b'\x00 \n\x00\x8b\xc0\x0fLX\xb0*\xe74C\x0c\x85\x03\xc0V'
        b'\x01H\r4`\x85S8\x81#')

    with io.BytesIO(DATA) as fobj:
        with tarfile.TarFile.open(fileobj=fobj, mode="r") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            info = members[0]
            assert info.name == 'test.txt'
            infofile = tar.extractfile(info)
            assert infofile is not None
            assert infofile.read() == b''


def test_zstd_write() -> None:
    fileobj = io.BytesIO()
    with tarfile.TarFile.open(fileobj=fileobj, mode='w:zst') as tar:
        data = b"Hello world!"
        info = tarfile.TarInfo("test.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    fileobj.seek(0)

    with tarfile.TarFile.open(fileobj=fileobj, mode='r') as tar:
        assert len(tar.getnames()) == 1
        assert tar.getnames()[0] == "test.txt"
        file = tar.extractfile("test.txt")
        assert file is not None
        assert file.read() == b"Hello world!"


def test_zstd_invalid() -> None:
    with pytest.raises(tarfile.ReadError):
        fileobj = io.BytesIO()
        tarfile.TarFile.open(fileobj=fileobj, mode='r')

    with pytest.raises(tarfile.ReadError):
        fileobj = io.BytesIO(b"\x00\x00\x00")
        tarfile.TarFile.open(fileobj=fileobj, mode='r')
