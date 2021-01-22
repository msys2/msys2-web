# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

REPO_URL = "https://repo.msys2.org"

REPOSITORIES = [
    ("mingw32", "", REPO_URL + "/mingw/i686", "https://github.com/msys2/MINGW-packages"),
    ("mingw64", "", REPO_URL + "/mingw/x86_64", "https://github.com/msys2/MINGW-packages"),
    ("msys", "x86_64", REPO_URL + "/msys/x86_64", "https://github.com/msys2/MSYS2-packages"),
]

CONFIG = [
    (REPO_URL + "/mingw/i686/mingw32.files", "mingw32", ""),
    (REPO_URL + "/mingw/x86_64/mingw64.files", "mingw64", ""),
    (REPO_URL + "/msys/x86_64/msys.files", "msys", "x86_64"),
]

VERSION_CONFIG = []
for repo in ["core", "extra", "community", "testing", "community-testing",
             "multilib"]:
    VERSION_CONFIG.append(
        ("https://mirror.f4st.host/archlinux/"
         "{0}/os/x86_64/{0}.db".format(repo), repo, ""))

SRCINFO_CONFIG = [
    ("https://github.com/msys2/MINGW-packages/releases/download/srcinfo-cache/srcinfo.json",
     "", ""),
    ("https://github.com/msys2/MSYS2-packages/releases/download/srcinfo-cache/srcinfo.json",
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

UPDATE_INTERVAL = 60 * 5
REQUEST_TIMEOUT = 60
CACHE_LOCAL = False
