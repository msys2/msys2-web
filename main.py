#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2016 Christoph Reiter
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
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from urllib.parse import quote
import contextlib
import datetime
import io
import re
import tarfile
import threading
import time

import requests
from flask import Flask, render_template, request


CONFIG = {
    "http://repo.msys2.org/mingw/i686/mingw32.files": ("mingw32", ""),
    "http://repo.msys2.org/mingw/x86_64/mingw64.files": ("mingw64", ""),
    "http://repo.msys2.org/msys/i686/msys.files": ("msys", "i686"),
    "http://repo.msys2.org/msys/x86_64/msys.files": ("msys", "x86_64"),
}

PORT = 8160
UPDATE_INTERVAL = 60 * 15

sources = []

app = Flask(__name__)


def parse_desc(t):
    d = {}
    cat = None
    values = []
    for l in t.splitlines():
        l = l.strip()
        if not l:
            d[cat] = values
            cat = None
            values = []
        elif cat is None:
            cat = l
        else:
            values.append(l)
    if cat is not None:
        d[cat] = values
    return d


class Package:

    def __init__(self, builddate, csize, depends, filename, files, isize,
                 makedepends, md5sum, name, pgpsig, sha256sum, arch,
                 base_url, repo, repo_variant, provides, conflicts, replaces,
                 version, base, desc):
        self.builddate = builddate
        self.csize = csize
        self.depends = depends
        self.filename = filename
        self.files = files
        self.isize = isize
        self.makedepends = makedepends
        self.md5sum = md5sum
        self.name = name
        self.pgpsig = pgpsig
        self.sha256sum = sha256sum
        self.arch = arch
        self.fileurl = base_url + "/" + quote(self.filename)
        self.repo = repo
        self.repo_variant = repo_variant
        self.provides = provides
        self.conflicts = conflicts
        self.replaces = replaces
        self.version = version
        self.base = base
        self.desc = desc

    def __repr__(self):
        return "Package(%s)" % self.fileurl

    @property
    def key(self):
        return (self.repo, self.repo_variant,
                self.name, self.arch, self.fileurl)

    @classmethod
    def from_desc(cls, d, base, base_url, repo, repo_variant):
        return cls(d["%BUILDDATE%"][0], d["%CSIZE%"][0],
                   d.get("%DEPENDS%", []), d["%FILENAME%"][0],
                   d.get("%FILES%", []), d["%ISIZE%"][0],
                   d.get("%MAKEDEPENDS%", []),
                   d["%MD5SUM%"][0], d["%NAME%"][0],
                   d.get("%PGPSIG%", [""])[0], d["%SHA256SUM%"][0],
                   d["%ARCH%"][0], base_url, repo, repo_variant,
                   d.get("%PROVIDES%", []), d.get("%CONFLICTS%", []),
                   d.get("%REPALCES%", []), d["%VERSION%"][0], base,
                   d.get("%DESC%", [""])[0])


class Source:

    def __init__(self, name, desc, url, version, licenses, packager, repo,
                 repo_variant, groups):
        self.name = name
        self.desc = desc
        self.url = url
        self.version = version
        self.licenses = licenses
        self.packager = packager
        self.repo = repo
        self.repo_variant = repo_variant
        self.groups = groups

        self.packages = {}

    @property
    def source_url(self):
        if self.repo.startswith("mingw"):
            return ("https://github.com/Alexpux/MINGW-packages/tree/master/%s"
                    % self.name)
        else:
            return ("https://github.com/Alexpux/MSYS2-packages/tree/master/%s"
                    % self.name)

    @property
    def history_url(self):
        if self.repo.startswith("mingw"):
            return ("https://github.com/Alexpux/MINGW-packages"
                    "/commits/master/%s" % self.name)
        else:
            return ("https://github.com/Alexpux/MSYS2-packages"
                    "/commits/master/%s" % self.name)

    @classmethod
    def from_desc(cls, d, repo, repo_variant):

        name = d["%NAME%"][0]
        if "%BASE%" not in d:
            if repo.startswith("mingw"):
                base = "mingw-w64-" + name.split("-", 3)[-1]
            else:
                base = name
        else:
            base = d["%BASE%"][0]

        return cls(base, d.get("%DESC%", [""])[0], d.get("%URL%", [""])[0],
                   d["%VERSION%"][0], d.get("%LICENSE%", []),
                   d["%PACKAGER%"][0], repo, repo_variant,
                   d.get("%GROUPS%", []))

    def add_desc(self, d, base_url):
        p = Package.from_desc(
            d, self.name, base_url, self.repo, self.repo_variant)
        assert p.key not in self.packages
        self.packages[p.key] = p


def parse_repo(repo, repo_variant, url):
    base_url = url.rsplit("/", 1)[0]
    sources = {}
    print("Loading %r" % url)

    def add_desc(d, base_url):
        source = Source.from_desc(d, repo, repo_variant)
        if source.name not in sources:
            sources[source.name] = source
        else:
            source = sources[source.name]

        source.add_desc(d, base_url)

    r = requests.get(url)
    with io.BytesIO(r.content) as f:
        with tarfile.open(fileobj=f, mode="r:gz") as tar:
            packages = {}
            for info in tar.getmembers():
                package_name = info.name.split("/", 1)[0]
                infofile = tar.extractfile(info)
                if infofile is None:
                    continue
                with infofile:
                    packages.setdefault(package_name, []).append(
                        (info.name, infofile.read()))

    for package_name, infos in sorted(packages.items()):
        t = ""
        for name, data in sorted(infos):
            if name.endswith("/desc"):
                t += data.decode("utf-8")
            if name.endswith("/files"):
                t += data.decode("utf-8")
        desc = parse_desc(t)
        add_desc(desc, base_url)

    return sources


@app.template_filter('timestamp')
def _jinja2_filter_timestamp(d):
    return datetime.datetime.fromtimestamp(
        int(d)).strftime('%Y-%m-%d %H:%M:%S')


@app.template_filter('filesize')
def _jinja2_filter_filesize(d):
    return "%.2f MB" % (int(d) / (1024.0 ** 2))


@app.context_processor
def funcs():

    def package_url(package, name=None):
        if name is None:
            res = name or package.name + "/" + package.repo
            if package.repo_variant:
                res += "/" + package.repo_variant
        else:
            res = re.split("[<>=]+", name)[0]
            if package.repo_variant:
                res += "/" + package.repo + "/" + package.repo_variant
        return res

    def package_name(package, name=None):
        name = name or package.name
        name = re.split("[<>=]+", name)[0]
        return (name or package.name) + (
            "/" + package.repo_variant if package.repo_variant else "")

    def package_restriction(package, name=None):
        name = name or package.name
        return name[len(re.split("[<>=]+", name)[0]):].strip()

    return dict(package_url=package_url, package_name=package_name,
                package_restriction=package_restriction)


@app.route('/base/<name>')
def base(name):
    global sources

    res = [s for s in sources if s.name == name]
    return render_template('base.html', sources=res)


@app.route('/')
def index():
    global sources

    return render_template('index.html', sources=sources)


@app.route('/group/<name>')
def group(name=None):
    global sources

    res = []
    for s in sources:
        if name in s.groups:
            res.append(s)

    return render_template('group.html', name=name, sources=res)


@app.route('/package/<name>')
@app.route('/package/<name>/<repo>')
@app.route('/package/<name>/<repo>/<variant>')
def package(name, repo=None, variant=None):
    global sources

    packages = []
    for s in sources:
        for k, p in sorted(s.packages.items()):
            if p.name == name or name in p.provides:
                if not repo or p.repo == repo:
                    if not variant or p.repo_variant == variant:
                        packages.append(p)
    return render_template('package.html', packages=packages)


@app.route('/search')
def search():
    global sources

    query = request.args.get('q')
    res = []
    if query is not None:
        parts = query.split()
        for s in sources:
            if [p for p in parts if p.lower() in s.name.lower()] == parts:
                res.append(s)

    return render_template('search.html', sources=res, query=query or "")


@contextlib.contextmanager
def check_needs_update(_last_time=[""]):
    """Raises RequestException"""

    t = ""
    for url in sorted(CONFIG):
        r = requests.head(url)
        t += r.headers["last-modified"]

    if t != _last_time[0]:
        yield True
        _last_time[0] = t
    else:
        yield False


def update_source():
    """Raises RequestException"""

    global sources, CONFIG

    final = {}
    for url, (repo, variant) in CONFIG.items():
        for name, source in parse_repo(repo, variant, url).items():
            if name in final:
                final[name].packages.update(source.packages)
            else:
                final[name] = source

    sources = [x[1] for x in sorted(final.items())]


def update_thread():
    global sources, CONFIG, UPDATE_INTERVAL

    while True:
        try:
            print("check for update")
            with check_needs_update() as needs:
                if needs:
                    print("update source")
                    update_source()
                else:
                    print("not update needed")
        except Exception as e:
            print(e)
        print("Sleeping for %d" % UPDATE_INTERVAL)
        time.sleep(UPDATE_INTERVAL)


def main():
    thread = threading.Thread(target=update_thread)
    thread.daemon = True
    thread.start()

    from twisted.internet import reactor
    from twisted.web.server import Site
    from twisted.web.wsgi import WSGIResource

    wsgiResource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(wsgiResource)
    print("http://localhost:%d" % PORT)
    reactor.listenTCP(PORT, site)
    reactor.run()


main()
