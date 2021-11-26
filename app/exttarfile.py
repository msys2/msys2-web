import io
import tarfile
import zstandard


class ExtTarFile(tarfile.TarFile):
    """Extends TarFile to support zstandard"""

    @classmethod
    def zstdopen(cls, name, mode="r", fileobj=None, cctx=None, dctx=None, **kwargs):  # type: ignore
        """Open zstd compressed tar archive name for reading or writing.
           Appending is not allowed.
        """
        if mode not in ("r"):
            raise ValueError("mode must be 'r'")

        try:
            zobj = zstandard.open(fileobj or name, mode + "b", cctx=cctx, dctx=dctx)
            with zobj:
                data = zobj.read()
        except (zstandard.ZstdError, EOFError) as e:
            raise tarfile.ReadError("not a zstd file") from e

        fileobj = io.BytesIO(data)
        t = cls.taropen(name, mode, fileobj, **kwargs)
        t._extfileobj = False
        return t

    OPEN_METH = {"zstd": "zstdopen", **tarfile.TarFile.OPEN_METH}
