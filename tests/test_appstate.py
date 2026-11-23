from app.appstate import (
    AppState,
    Package,
    Source,
    SrcInfoPackage,
    get_removable_packages,
    get_repositories,
    state,
)


def test_lookup_package():
    repos = {repo.name: repo for repo in get_repositories()}
    source = Source("source")
    for name, repo in [("example", "ucrt64"), ("example-provider", "msys")]:
        source.add_desc(
            {
                "%NAME%": [name],
                "%VERSION%": ["1-1"],
                "%BUILDDATE%": ["0"],
                "%CSIZE%": ["0"],
                "%ISIZE%": ["0"],
                "%FILENAME%": [f"{name}-1-1.pkg.tar.zst"],
                "%SHA256SUM%": [""],
                "%ARCH%": ["x86_64"],
                "%PROVIDES%": ["example", "example-virtual"],
            },
            repos[repo],
        )
    exact, provider = source.packages.values()
    app_state = AppState()
    app_state.sources = {source.name: source}

    assert app_state.has_package("example")
    assert not app_state.has_package("example-virtual")
    assert app_state.lookup_package("example") == ([(source, exact)], [])
    assert app_state.lookup_package("example", repo="msys") == ([], [(source, provider)])
    assert app_state.lookup_package("example", variant="x86_64") == ([], [(source, provider)])
    assert app_state.lookup_package("example", repo="ucrt64", variant="x86_64") == ([], [])

    app_state.sources = {}
    assert not app_state.has_package("example")
    assert app_state.lookup_package("example") == ([], [])


def test_package_group_index():
    repo = next(repo for repo in get_repositories() if repo.name == "ucrt64")
    group = f"{repo.package_prefix}example"
    base_group = f"{repo.base_prefix}example"
    source = Source("example")
    for name in ("example-z", "example-a"):
        source.add_desc(
            {
                "%NAME%": [name],
                "%VERSION%": ["1-1"],
                "%BUILDDATE%": ["0"],
                "%CSIZE%": ["0"],
                "%ISIZE%": ["0"],
                "%FILENAME%": [f"{name}-1-1.pkg.tar.zst"],
                "%SHA256SUM%": [""],
                "%ARCH%": ["x86_64"],
                "%GROUPS%": [group, group],
            },
            repo,
        )
    app_state = AppState()
    app_state.sources = {source.name: source}

    assert app_state.package_group_counts() == {group: 2}
    assert [p.name for p in app_state.packages_in_group(group)] == ["example-a", "example-z"]
    assert not app_state.packages_in_group("missing")
    assert app_state.base_group_counts() == {base_group: 1}
    assert app_state.groups_in_base_group(base_group) == (group,)
    assert not app_state.groups_in_base_group(group)

    app_state.sources = {}
    assert app_state.package_group_counts() == {}
    assert not app_state.packages_in_group(group)
    assert app_state.base_group_counts() == {}
    assert not app_state.groups_in_base_group(base_group)


def test_get_removable_packages(monkeypatch):
    repo = next(r for r in get_repositories() if r.name == "msys")

    def package(name):
        return Package.from_desc(
            {
                "%NAME%": [name],
                "%VERSION%": ["1-1"],
                "%BUILDDATE%": ["0"],
                "%CSIZE%": ["0"],
                "%ISIZE%": ["0"],
                "%FILENAME%": [f"{name}-1-1.pkg.tar.zst"],
                "%SHA256SUM%": [""],
                "%ARCH%": ["x86_64"],
            },
            name,
            repo,
        )

    library = package("library")
    middle = package("middle")
    obsolete = package("obsolete")
    blocked_library = package("blocked-library")
    blocked_middle = package("blocked-middle")
    maintained = package("maintained")
    library.rdepends = {middle: set()}
    middle.rdepends = {obsolete: set()}
    blocked_library.rdepends = {blocked_middle: set()}
    blocked_middle.rdepends = {maintained: set()}
    packages = [library, middle, obsolete, blocked_library, blocked_middle, maintained]
    source = Source("source")
    source.packages = {p.key: p for p in packages}
    srcinfo = SrcInfoPackage(
        pkgbase=maintained.base,
        pkgname=maintained.name,
        pkgver="1",
        pkgrel="1",
        repo=repo.name,
        repo_url="",
        repo_path="",
        date="2026-01-01",
        pkgbasedesc=None,
    )
    monkeypatch.setattr(state, "sources", {"source": source})
    monkeypatch.setattr(state, "sourceinfos", {maintained.name: srcinfo})

    assert get_removable_packages() == [obsolete]
    assert get_removable_packages(recursive=True) == [library, middle, obsolete]

    obsolete.rdepends = {library: set()}
    assert get_removable_packages() == []
    assert get_removable_packages(recursive=True) == [library, middle, obsolete]
