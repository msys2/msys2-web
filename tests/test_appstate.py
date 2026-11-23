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
