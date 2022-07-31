# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

from typing import Optional


REPO_URL = "https://repo.msys2.org"
DOWNLOAD_URL = "https://mirror.msys2.org"

REPOSITORIES = [
    ("mingw32", "", REPO_URL + "/mingw/mingw32", DOWNLOAD_URL + "/mingw/mingw32", "https://github.com/msys2/MINGW-packages"),
    ("mingw64", "", REPO_URL + "/mingw/mingw64", DOWNLOAD_URL + "/mingw/mingw64", "https://github.com/msys2/MINGW-packages"),
    ("ucrt64", "", REPO_URL + "/mingw/ucrt64", DOWNLOAD_URL + "/mingw/ucrt64", "https://github.com/msys2/MINGW-packages"),
    ("clang64", "", REPO_URL + "/mingw/clang64", DOWNLOAD_URL + "/mingw/clang64", "https://github.com/msys2/MINGW-packages"),
    ("clang32", "", REPO_URL + "/mingw/clang32", DOWNLOAD_URL + "/mingw/clang32", "https://github.com/msys2/MINGW-packages"),
    ("clangarm64", "", REPO_URL + "/mingw/clangarm64", DOWNLOAD_URL + "/mingw/clangarm64", "https://github.com/msys2/MINGW-packages"),
    ("msys", "x86_64", REPO_URL + "/msys/x86_64", DOWNLOAD_URL + "/msys/x86_64", "https://github.com/msys2/MSYS2-packages"),
]

CONFIG = [
    (REPO_URL + "/mingw/mingw32/mingw32.files", "mingw32", ""),
    (REPO_URL + "/mingw/mingw64/mingw64.files", "mingw64", ""),
    (REPO_URL + "/mingw/ucrt64/ucrt64.files", "ucrt64", ""),
    (REPO_URL + "/mingw/clang64/clang64.files", "clang64", ""),
    (REPO_URL + "/mingw/clang32/clang32.files", "clang32", ""),
    (REPO_URL + "/msys/x86_64/msys.files", "msys", "x86_64"),
]

DEFAULT_REPO = "mingw64"

ARCH_VERSION_CONFIG = []
for repo in ["core", "extra", "community", "testing", "community-testing",
             "multilib"]:
    ARCH_VERSION_CONFIG.append(
        ("https://mirror.f4st.host/archlinux/"
         "{0}/os/x86_64/{0}.db".format(repo), repo, ""))

AUR_VERSION_CONFIG = [
    ("https://aur.archlinux.org/packages-meta-v1.json.gz",
     "", "")
]

SRCINFO_CONFIG = [
    ("https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/srcinfo.json.gz",
     "", ""),
    ("https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/srcinfo.json.gz",
     "", "")
]

ARCH_MAPPING_CONFIG = [
    ("https://raw.githubusercontent.com/msys2/msys2-web/master/arch-mapping.json",
     "", "")
]

CYGWIN_VERSION_CONFIG = [
    ("https://mirrors.kernel.org/sourceware/cygwin/x86_64/setup.ini",
     "", "")
]

BUILD_STATUS_CONFIG = [
    ("https://github.com/msys2/msys2-autobuild/releases/download/status/status.json",
     "", "")
]

# Update every 30 minutes at least, at max every 5 minutes
UPDATE_INTERVAL_MAX = 60 * 30
UPDATE_INTERVAL_MIN = 60 * 5

REQUEST_TIMEOUT = 60
CACHE_DIR: Optional[str] = None
