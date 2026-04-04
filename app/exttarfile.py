import sys

if sys.version_info >= (3, 14):
    import tarfile
else:
    from backports.zstd import tarfile  # type: ignore

__all__ = ["tarfile"]
