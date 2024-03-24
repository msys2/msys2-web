# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

REPO_URL = "https://repo.msys2.org"
DOWNLOAD_URL = "https://mirror.msys2.org"
REPOSITORIES = [
    ("mingw32", "", "mingw-w64-i686-", "mingw-w64-", REPO_URL + "/mingw/mingw32", DOWNLOAD_URL + "/mingw/mingw32", "https://github.com/msys2/MINGW-packages"),
    ("mingw64", "", "mingw-w64-x86_64-", "mingw-w64-", REPO_URL + "/mingw/mingw64", DOWNLOAD_URL + "/mingw/mingw64", "https://github.com/msys2/MINGW-packages"),
    ("ucrt64", "", "mingw-w64-ucrt-x86_64-", "mingw-w64-", REPO_URL + "/mingw/ucrt64", DOWNLOAD_URL + "/mingw/ucrt64", "https://github.com/msys2/MINGW-packages"),
    ("clang64", "", "mingw-w64-clang-x86_64-", "mingw-w64-", REPO_URL + "/mingw/clang64", DOWNLOAD_URL + "/mingw/clang64", "https://github.com/msys2/MINGW-packages"),
    ("clang32", "", "mingw-w64-clang-i686-", "mingw-w64-", REPO_URL + "/mingw/clang32", DOWNLOAD_URL + "/mingw/clang32", "https://github.com/msys2/MINGW-packages"),
    ("clangarm64", "", "mingw-w64-clang-aarch64-", "mingw-w64-", REPO_URL + "/mingw/clangarm64", DOWNLOAD_URL + "/mingw/clangarm64", "https://github.com/msys2/MINGW-packages"),
    ("msys", "x86_64", "", "", REPO_URL + "/msys/x86_64", DOWNLOAD_URL + "/msys/x86_64", "https://github.com/msys2/MSYS2-packages"),
]
DEFAULT_REPO = "ucrt64"

ARCH_REPO_URL = "https://ftp.halifax.rwth-aachen.de/archlinux"
ARCH_REPO_CONFIG = []
for repo in ["core", "core-testing", "extra", "extra-testing"]:
    ARCH_REPO_CONFIG.append(
        (ARCH_REPO_URL + f"/{repo}/os/x86_64/{repo}.db", repo)
    )
AUR_METADATA_URL = "https://aur.archlinux.org/packages-meta-ext-v1.json.gz"

SRCINFO_URLS = [
    "https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/srcinfo.json.gz",
    "https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/srcinfo.json.gz",
]

CYGWIN_METADATA_URL = "https://ftp.acc.umu.se/mirror/cygwin/x86_64/setup.zst"

BUILD_STATUS_URLS = [
    "https://github.com/msys2/msys2-autobuild/releases/download/status/status.json",
    "https://github.com/msys2-arm/msys2-autobuild/releases/download/status/status.json",
]

PYPI_URLS = [
    "https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/pypi.json.gz",
    "https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/pypi.json.gz",
]

CDX_URLS = [
    "https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/sbom.vuln.cdx.json",
    "https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/sbom.vuln.cdx.json"
]

GENTOO_SNAPSHOT_URL = "https://mirror.leaseweb.com/gentoo/snapshots/gentoo-latest.tar.xz"

# Check for updates every 5 minutes by default, at max 1 time every minute even if triggered
UPDATE_INTERVAL = 60 * 5
UPDATE_MIN_INTERVAL = 60
UPDATE_MIN_RATE = 1

REQUEST_TIMEOUT = 60
CACHE_DIR: str | None = None
