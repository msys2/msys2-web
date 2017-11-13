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
import subprocess
from multiprocessing.pool import ThreadPool
from multiprocessing import cpu_count



def get_srcinfo_for_pkgbuild(args):
    pkgbuild_path, cache = args

    with open(pkgbuild_path, "rb") as f:
        h = hashlib.new("SHA1")
        h.update(f.read())
        digest = h.hexdigest()

    text = cache.get(digest)

    if text is None:
        print("Parsing %r" % pkgbuild_path)
        try:
            with open(os.devnull, 'wb') as devnull:
                text = subprocess.check_output(
                    ["bash", "/usr/bin/makepkg-mingw", "--printsrcinfo", "-p",
                     os.path.basename(pkgbuild_path)],
                    cwd=os.path.dirname(pkgbuild_path),
                    stderr=devnull).decode("utf-8")
        except subprocess.CalledProcessError as e:
            print("ERROR: %s %s" % (pkgbuild_path, e.output.splitlines()))
            return

    return (digest, text)


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


def iter_srcinfo(repo_path, cache):
    pool_items = ((p, cache) for p in iter_pkgbuild_paths(repo_path))
    pool = ThreadPool(cpu_count() * 2)
    pool_iter = pool.imap_unordered(get_srcinfo_for_pkgbuild, pool_items)
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

    srcinfos = []
    for repo in argv[2:]:
        repo_path = os.path.abspath(repo)
        for entry in iter_srcinfo(repo_path, cache):
            if entry is None:
                continue
            srcinfos.append(entry)

    srcinfos = OrderedDict(sorted(srcinfos))
    with open(srcinfo_path, "wb") as h:
        h.write(json.dumps(srcinfos, indent=2).encode("utf-8"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
