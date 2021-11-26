import io

from app.exttarfile import ExtTarFile


def test_zst() -> None:
    DATA = (
        b'(\xb5/\xfd\x00X\xd5\x02\x00\xd4\x03test.txt\x00000664 '
        b'\x00001750 14150172601 013031\x00 0\x00ustar\x0000lazka'
        b'\x00 \n\x00\x8b\xc0\x0fLX\xb0*\xe74C\x0c\x85\x03\xc0V'
        b'\x01H\r4`\x85S8\x81#')

    with io.BytesIO(DATA) as fobj:
        with ExtTarFile.open(fileobj=fobj, mode="r") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            info = members[0]
            assert info.name == 'test.txt'
            infofile = tar.extractfile(info)
            assert infofile is not None
            assert infofile.read() == b''
