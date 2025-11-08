import tarfile

HAS_ZSTD = True
try:
    from compression import zstd
except ImportError:
    HAS_ZSTD = False

ExtTarFile: type[tarfile.TarFile]

if not HAS_ZSTD:
    from pyzstd import ZstdFile, ZstdError

    class ZstTarFile(tarfile.TarFile):
        """Extends TarFile to support zstandard"""

        @classmethod
        def zstdopen(cls, name, mode="r", fileobj=None, **kwargs):  # type: ignore
            """Open zstd compressed tar archive"""

            if mode not in ("r", "w", "x", "a"):
                raise ValueError("mode must be 'r', 'w' or 'x' or 'a'")

            zstfileobj = None
            try:
                zstfileobj = ZstdFile(fileobj or name, mode)
                if "r" in mode:
                    zstfileobj.peek(1)  # raises ZstdError if not a zstd file
            except (ZstdError, EOFError) as e:
                if zstfileobj is not None:
                    zstfileobj.close()
                raise tarfile.ReadError("not a zstd file") from e

            try:
                t = cls.taropen(name, mode, zstfileobj, **kwargs)
            except Exception:
                zstfileobj.close()
                raise

            t._extfileobj = False
            return t

        OPEN_METH = {"zst": "zstdopen", **tarfile.TarFile.OPEN_METH}

    ExtTarFile = ZstTarFile
else:
    assert zstd
    ExtTarFile = tarfile.TarFile
