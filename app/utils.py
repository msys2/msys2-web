# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import re
from itertools import zip_longest
from typing import List, Tuple, Optional, Dict, Set


def vercmp(v1: str, v2: str) -> int:

    def cmp(a: int, b: int) -> int:
        return (a > b) - (a < b)

    def split(v: str) -> Tuple[str, str, Optional[str]]:
        if "~" in v:
            e, v = v.split("~", 1)
        else:
            e, v = ("0", v)

        r: Optional[str] = None
        if "-" in v:
            v, r = v.rsplit("-", 1)
        else:
            v, r = (v, None)

        return (e, v, r)

    digit, alpha, other = range(3)

    def get_type(c: str) -> int:
        assert c
        if c.isdigit():
            return digit
        elif c.isalpha():
            return alpha
        else:
            return other

    def parse(v: str) -> List[Tuple[int, Optional[str]]]:
        parts: List[Tuple[int, Optional[str]]] = []
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

    def rpmvercmp(v1: str, v2: str) -> int:
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


def extract_upstream_version(version: str) -> str:
    return version.rsplit(
        "-")[0].split("+", 1)[0].split("~", 1)[-1].split(":", 1)[-1]


def strip_vcs(package_name: str) -> str:
    if package_name.endswith(
            ("-cvs", "-svn", "-hg", "-darcs", "-bzr", "-git")):
        return package_name.rsplit("-", 1)[0]
    return package_name


def arch_version_to_msys(v: str) -> str:
    return v.replace(":", "~")


def version_is_newer_than(v1: str, v2: str) -> bool:
    return vercmp(v1, v2) == 1


def split_depends(deps: List[str]) -> Dict[str, Set[str]]:
    r: Dict[str, Set[str]] = {}
    for d in deps:
        parts = re.split("([<>=]+)", d, 1)
        first = parts[0].strip()
        second = "".join(parts[1:]).strip()
        r.setdefault(first, set()).add(second)
    return r


def split_optdepends(deps: List[str]) -> Dict[str, Set[str]]:
    r: Dict[str, Set[str]] = {}
    for d in deps:
        if ":" in d:
            a, b = d.split(":", 1)
            a, b = a.strip(), b.strip()
        else:
            a, b = d.strip(), ""
        e = r.setdefault(a, set())
        if b:
            e.add(b)
    return r
