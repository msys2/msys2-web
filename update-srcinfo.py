#!/usr/bin/env python3
# Copyright 2017 Christoph Reiter
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE

import sys
import os
import json
from collections import OrderedDict
import hashlib
import time
import subprocess
from multiprocessing.pool import ThreadPool
from multiprocessing import cpu_count


def get_cache_key(pkgbuild_path):
    pkgbuild_path = os.path.abspath(pkgbuild_path)
    git_cwd = os.path.dirname(pkgbuild_path)
    git_path = os.path.relpath(pkgbuild_path, git_cwd)
    h = hashlib.new("SHA1")

    with open(pkgbuild_path, "rb") as f:
        h.update(f.read())

    fileinfo = subprocess.check_output(
        ["git", "ls-files", "-s", "--full-name", git_path],
        cwd=git_cwd).decode("utf-8").strip()
    h.update(fileinfo.encode("utf-8"))

    repo = subprocess.check_output(
        ["git", "ls-remote", "--get-url", "origin"],
        cwd=git_cwd).decode("utf-8").strip()
    h.update(repo.encode("utf-8"))

    return h.hexdigest()


def fixup_makepkg_output(text):
    # makepkg-mingw runs makepkg twice for mingw32/64. In case of msys
    # packages this results in the output geting duplicated.
    # Dedup the output so we can use makepkg-mingw for all packages and still
    # get the right output.
    if text[len(text)//2:] == text[:len(text)//2]:
        return text[len(text)//2:]
    return text


def get_srcinfo_for_pkgbuild(pkgbuild_path):
    pkgbuild_path = os.path.abspath(pkgbuild_path)
    git_cwd = os.path.dirname(pkgbuild_path)
    git_path = os.path.relpath(pkgbuild_path, git_cwd)
    key = get_cache_key(pkgbuild_path)

    print("Parsing %r" % pkgbuild_path)
    try:
        with open(os.devnull, 'wb') as devnull:
            text = subprocess.check_output(
                ["bash", "/usr/bin/makepkg-mingw", "--printsrcinfo", "-p",
                 git_path],
                cwd=git_cwd,
                stderr=devnull).decode("utf-8")

        text = fixup_makepkg_output(text)

        repo = subprocess.check_output(
            ["git", "ls-remote", "--get-url", "origin"],
            cwd=git_cwd).decode("utf-8").strip()

        relpath = subprocess.check_output(
            ["git", "ls-files", "--full-name", git_path],
            cwd=git_cwd).decode("utf-8").strip()
        relpath = os.path.dirname(relpath)

        date = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci", git_path],
            cwd=git_cwd).decode("utf-8")
        date = date.rsplit(" ", 1)[0]

        meta = {"repo": repo, "path": relpath, "date": date, "srcinfo": text}
    except subprocess.CalledProcessError as e:
        print("ERROR: %s %s" % (pkgbuild_path, e.output.splitlines()))
        return

    return (key, meta)


def iter_pkgbuild_paths(repo_path):
    repo_path = os.path.abspath(repo_path)
    print("Searching for PKGBUILD files in %s" % repo_path)
    for base, dirs, files in os.walk(repo_path):
        for f in files:
            if f == "PKGBUILD":
                # in case we find a PKGBUILD, don't go deeper
                del dirs[:]
                path = os.path.join(base, f)
                yield path


def get_srcinfo_from_cache(args):
    pkgbuild_path, cache = args
    key = get_cache_key(pkgbuild_path)
    if key in cache:
        return (pkgbuild_path, (key, cache[key]))
    else:
        return (pkgbuild_path, None)


def iter_srcinfo(repo_paths, cache):
    to_check = []
    for repo_path in repo_paths:
        for pkgbuild_path in iter_pkgbuild_paths(repo_path):
            to_check.append(pkgbuild_path)

    pool = ThreadPool(cpu_count() * 3)
    to_parse = []
    pool_iter = pool.imap_unordered(
        get_srcinfo_from_cache, ((p, cache) for p in to_check))
    for pkgbuild_path, srcinfo in pool_iter:
        if srcinfo is not None:
            yield srcinfo
        else:
            to_parse.append(pkgbuild_path)

    pool_iter = pool.imap_unordered(get_srcinfo_for_pkgbuild, to_parse)
    print("Parsing PKGBUILD files...")
    for srcinfo in pool_iter:
        yield srcinfo
    pool.close()


def main(argv):
    srcinfo_path = os.path.abspath(argv[1])
    try:
        with open(srcinfo_path, "rb") as h:
            cache = json.loads(h.read())
    except FileNotFoundError:
        cache = {}

    t = time.monotonic()
    srcinfos = []
    repo_paths = [os.path.abspath(p) for p in argv[2:]]
    for entry in iter_srcinfo(repo_paths, cache):
        if entry is None:
            continue
        srcinfos.append(entry)
        # XXX: give up so we end before appveyor times out
        if time.monotonic() - t > 60 * 30:
            break

    srcinfos = OrderedDict(sorted(srcinfos))
    with open(srcinfo_path, "wb") as h:
        h.write(json.dumps(srcinfos, indent=2).encode("utf-8"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
