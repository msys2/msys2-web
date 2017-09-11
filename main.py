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

import traceback
from urllib.parse import quote
import contextlib
import datetime
import io
import re
import os
import tarfile
import threading
import time
from itertools import zip_longest

import requests
from flask import Flask, render_template, request, url_for


CONFIG = [
    ("http://repo.msys2.org/mingw/i686/mingw32.files", "mingw32", ""),
    ("http://repo.msys2.org/mingw/x86_64/mingw64.files", "mingw64", ""),
    ("http://repo.msys2.org/msys/i686/msys.files", "msys", "i686"),
    ("http://repo.msys2.org/msys/x86_64/msys.files", "msys", "x86_64"),
]

VERSION_CONFIG = []
for repo in ["core", "extra", "community", "testing", "community-testing"]:
    VERSION_CONFIG.append(
        ("http://ftp.halifax.rwth-aachen.de/archlinux/"
         "{0}/os/x86_64/{0}.db".format(repo), repo, ""))

UPDATE_INTERVAL = 60 * 15
CACHE_LOCAL = False  # enable this during development

sources = []
versions = {}
last_update = 0

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
                 version, base, desc, groups):
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
        self.groups = groups

    def __repr__(self):
        return "Package(%s)" % self.fileurl

    @property
    def realname(self):
        if self.repo.startswith("mingw"):
            return self.name.split("-", 3)[-1]
        return self.name

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
                   d.get("%DESC%", [""])[0], d.get("%GROUPS%", []))


class Source:

    def __init__(self, name, desc, url, version, licenses, packager, repo,
                 repo_variant):
        self.name = name
        self.desc = desc
        self.url = url
        self.version = version
        self.licenses = licenses
        self.packager = packager
        self.repo = repo
        self.repo_variant = repo_variant

        self.packages = {}

    @property
    def arch_url(self):
        arch_info = get_arch_info_for_base(self)
        if arch_info is not None:
            return arch_info[1]
        return ""

    @property
    def upstream_version(self):
        arch_info = get_arch_info_for_base(self)
        if arch_info is not None:
            return extract_upstream_version(arch_info[0])
        return ""

    @property
    def is_outdated(self):
        arch_version = self.upstream_version
        if not arch_version:
            return False

        msys_version = extract_upstream_version(self.version)

        return version_is_newer_than(arch_version, msys_version)

    @property
    def realname(self):
        if self.repo.startswith("mingw"):
            return self.name.split("-", 2)[-1]
        return self.name

    @property
    def date(self):
        """One of the package build dates"""

        for n, p in sorted(self.packages.items()):
            return p.builddate
        return 0

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
                   d["%PACKAGER%"][0], repo, repo_variant)

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

    if CACHE_LOCAL:
        fn = url.replace("/", "_")
        if not os.path.exists(fn):
            r = requests.get(url)
            with open(fn, "wb") as h:
                h.write(r.content)
        with open(fn, "rb") as h:
            data = h.read()
    else:
        r = requests.get(url)
        data = r.content

    with io.BytesIO(data) as f:
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
            res = url_for("package", name=name or package.name)
            res += "?repo=" + package.repo
            if package.repo_variant:
                res += "&variant=" + package.repo_variant
        else:
            res = url_for("package", name=re.split("[<>=]+", name)[0])
            if package.repo_variant:
                res += "?repo=" + package.repo
                res += "&variant" + package.repo_variant
        return res

    def package_name(package, name=None):
        name = name or package.name
        name = re.split("[<>=]+", name)[0]
        return (name or package.name) + (
            "/" + package.repo_variant if package.repo_variant else "")

    def package_restriction(package, name=None):
        name = name or package.name
        return name[len(re.split("[<>=]+", name)[0]):].strip()

    def update_timestamp():
        return last_update

    return dict(package_url=package_url, package_name=package_name,
                package_restriction=package_restriction,
                update_timestamp=update_timestamp)


@app.route('/')
@app.route('/base')
@app.route('/base/<name>')
def base(name=None):
    global sources

    if name is not None:
        res = [s for s in sources if s.name == name]
        return render_template('base.html', sources=res)
    else:
        return render_template('index.html', sources=sources)


@app.route('/group/')
@app.route('/group/<name>')
def group(name=None):
    global sources

    if name is not None:
        res = []
        for s in sources:
            for k, p in sorted(s.packages.items()):
                if name in p.groups:
                    res.append(p)

        return render_template('group.html', name=name, packages=res)
    else:
        groups = {}
        for s in sources:
            for k, p in sorted(s.packages.items()):
                for name in p.groups:
                    groups[name] = groups.get(name, 0) + 1
        return render_template('groups.html', groups=groups)


@app.route('/package/<name>')
def package(name):
    global sources

    repo = request.args.get('repo')
    variant = request.args.get('variant')

    packages = []
    for s in sources:
        for k, p in sorted(s.packages.items()):
            if p.name == name or name in p.provides:
                if not repo or p.repo == repo:
                    if not variant or p.repo_variant == variant:
                        packages.append(p)
    return render_template('package.html', packages=packages)


@app.route('/updates')
def updates():
    global sources

    packages = []
    for s in sources:
        packages.extend(s.packages.values())
    packages.sort(key=lambda p: p.builddate, reverse=True)
    return render_template('updates.html', packages=packages[:150])


def package_name_is_vcs(package_name):
    return package_name.endswith(
        ("-cvs", "-svn", "-hg", "-darcs", "-bzr", "-git"))


def get_arch_name(name):
    mapping = {
        "freetype": "freetype2",
        "lzo2": "lzo",
        "liblzo2": "lzo",
        "python-bsddb3": "python-bsddb",
        "graphite2": "graphite",
        "mpc": "libmpc",
        "eigen3": "eigen",
        "python-icu": "python-pyicu",
        "python-bsddb3": "python-bsddb",
        "python3": "python",
        "sqlite3": "sqlite",
        "gexiv2": "libgexiv2",
        "webkitgtk3": "webkitgtk",
        "python2-nuitka": "nuitka",
        "python2-ipython": "ipython",
        "openssl": "openssl-1.0",
        "gtksourceviewmm3": "gtksourceviewmm",
        "librest": "rest",
        "gcc-libgfortran": "gcc-fortran",
        "meld3": "meld",
        "antlr3": "libantlr3c",
        "geoclue": "geoclue2",
        "python-zope.event": "python-zope-event",
        "python-zope.interface": "python-zope-interface",
        "tesseract-ocr": "tesseract",
    }

    name = name.lower()

    if name.startswith("python3-"):
        name = name.replace("python3-", "python-")

    if name in mapping:
        return mapping[name]

    return name


def vercmp(v1, v2):

    def cmp(a, b):
        return (a > b) - (a < b)

    def split(v):
        e, v = v.split("~", 1) if "~" in v else ("0", v)
        v, r = v.rsplit("-", 1) if "-" in v else (v, None)
        return (e, v, r)

    digit, alpha, other = range(3)

    def get_type(c):
        assert c
        if c.isdigit():
            return digit
        elif c.isalpha():
            return alpha
        else:
            return other

    def parse(v):
        parts = []
        seps = 0
        current = ""
        for c in v:
            if get_type(c) == other:
                if current:
                    parts.append((seps, current))
                    current = ""
                seps += 1
            else:
                if not current:
                    current += c
                else:
                    if get_type(c) == get_type(current):
                        current += c
                    else:
                        parts.append((seps, current))
                        current = c

        parts.append((seps, current or None))

        return parts

    def rpmvercmp(v1, v2):
        for (s1, p1), (s2, p2) in zip_longest(parse(v1), parse(v2),
                                              fillvalue=(None, None)):

            if s1 is not None and s2 is not None:
                ret = cmp(s1, s2)
                if ret != 0:
                    return ret

            if p1 is None and p2 is None:
                return 0

            if p1 is None:
                if get_type(p2) == alpha:
                    return 1
                return -1
            elif p2 is None:
                if get_type(p1) == alpha:
                    return -1
                return 1

            t1 = get_type(p1)
            t2 = get_type(p2)
            if t1 != t2:
                if t1 == digit:
                    return 1
                elif t2 == digit:
                    return -1
            elif t1 == digit:
                ret = cmp(int(p1), int(p2))
                if ret != 0:
                    return ret
            elif t1 == alpha:
                ret = cmp(p1, p2)
                if ret != 0:
                    return ret

        return 0

    e1, v1, r1 = split(v1)
    e2, v2, r2 = split(v2)

    ret = rpmvercmp(e1, e2)
    if ret == 0:
        ret = rpmvercmp(v1, v2)
        if ret == 0 and r1 is not None and r2 is not None:
            ret = rpmvercmp(r1, r2)

    return ret


def arch_version_to_msys(v):
    return v.replace(":", "~")


def version_is_newer_than(v1, v2):
    return vercmp(v1, v2) == 1


def update_versions():
    global VERSION_CONFIG, versions, sources

    print("update versions")
    arch_versions = {}
    for (url, repo, variant) in VERSION_CONFIG:
        for source in parse_repo(repo, variant, url).values():
            msys_ver = arch_version_to_msys(source.version)
            for p in source.packages.values():
                url = "https://www.archlinux.org/packages/%s/%s/%s/" % (
                    p.repo, p.arch, p.name)

                if p.name in arch_versions:
                    old_ver = arch_versions[p.name][0]
                    if version_is_newer_than(msys_ver, old_ver):
                        arch_versions[p.name] = (msys_ver, url)
                else:
                    arch_versions[p.name] = (msys_ver, url)
    print("done")

    print("update versions from AUR")
    # a bit hacky, try to get the remaining versions from AUR
    possible_names = set()
    for s in sources:
        if package_name_is_vcs(s.name):
            continue
        for p in s.packages.values():
            possible_names.add(get_arch_name(p.realname))
        possible_names.add(get_arch_name(s.realname))

    r = requests.get("https://aur.archlinux.org/packages.gz")
    aur_packages = set()
    for name in r.text.splitlines():
        if name.startswith("#"):
            continue
        if name in arch_versions:
            continue
        if name not in possible_names:
            continue
        aur_packages.add(name)

    aur_url = (
        "https://aur.archlinux.org/rpc/?v=5&type=info&" +
        "&".join(["arg[]=%s" % n for n in aur_packages]))
    r = requests.get(aur_url)
    for result in r.json()["results"]:
        name = result["Name"]
        if name not in aur_packages or name in arch_versions:
            continue
        url = "https://aur.archlinux.org/packages/%s" % name
        arch_versions[name] = (result["Version"], url)
    print("done")

    versions = arch_versions


def extract_upstream_version(version):
    return version.rsplit(
        "-")[0].split("+", 1)[0].split("~", 1)[-1].split(":", 1)[-1]


def get_arch_info_for_base(s):
    """tuple or None"""

    global versions

    variants = sorted([s.realname] + [p.realname for p in s.packages.values()])

    for realname in variants:
        arch_name = get_arch_name(realname)
        if arch_name in versions:
            return tuple(versions[arch_name])


@app.route('/outofdate')
def outofdate():
    global sources, versions

    missing = []
    to_update = []
    all_sources = []
    for s in sources:
        if package_name_is_vcs(s.name):
            continue

        all_sources.append(s)

        arch_info = get_arch_info_for_base(s)
        if arch_info is None:
            missing.append((s, get_arch_name(s.realname)))
            continue

        arch_version, url = arch_info
        arch_version = extract_upstream_version(arch_version)
        msys_version = extract_upstream_version(s.version)

        if version_is_newer_than(arch_version, msys_version):
            to_update.append((s, msys_version, arch_version, url))

    # show packages which have recently been build first.
    # assumes high frequency update packages are more important
    to_update.sort(key=lambda i: i[0].date, reverse=True)

    missing.sort(key=lambda i: i[0].name)

    return render_template(
        'outofdate.html',
        all_sources=all_sources, to_update=to_update, missing=missing)


@app.route('/search')
def search():
    global sources

    query = request.args.get('q', '')
    qtype = request.args.get('t', '')

    if qtype not in ["pkg"]:
        qtype = "pkg"

    parts = query.split()
    res_pkg = []

    if not query:
        pass
    elif qtype == "pkg":
        for s in sources:
            if [p for p in parts if p.lower() in s.name.lower()] == parts:
                res_pkg.append(s)

    res_pkg.sort(key=lambda s: s.name)

    return render_template(
        'search.html', sources=res_pkg, query=query, qtype=qtype)


@contextlib.contextmanager
def check_needs_update(_last_time=[""]):
    """Raises RequestException"""

    if CACHE_LOCAL:
        yield True
        return

    t = ""
    for config in sorted(CONFIG + VERSION_CONFIG):
        url = config[0]
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
    for (url, repo, variant) in CONFIG:
        for name, source in parse_repo(repo, variant, url).items():
            if name in final:
                final[name].packages.update(source.packages)
            else:
                final[name] = source

    sources = [x[1] for x in sorted(final.items())]


def update_thread():
    global sources, UPDATE_INTERVAL, last_update

    while True:
        try:
            print("check for update")
            with check_needs_update() as needs:
                if needs:
                    print("update source/versions")
                    update_source()
                    update_versions()
                else:
                    print("not update needed")
        except Exception as e:
            traceback.print_exc()
        else:
            last_update = time.time()
        print("Sleeping for %d" % UPDATE_INTERVAL)
        time.sleep(UPDATE_INTERVAL)


thread = threading.Thread(target=update_thread)
thread.daemon = True
thread.start()


if __name__ == "__main__":
    from twisted.internet import reactor
    from twisted.web.server import Site
    from twisted.web.wsgi import WSGIResource

    port = 8160
    wsgiResource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(wsgiResource)
    print("http://localhost:%d" % port)
    reactor.listenTCP(port, site)
    reactor.run()
