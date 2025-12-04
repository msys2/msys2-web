from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .utils import vercmp
from pydantic import BaseModel, Field
from .appstate import get_repositories, find_packages, Source

custom_settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)
mcpapp = FastMCP(name="MSYS2Server", stateless_http=True, json_response=False,
                 transport_security=custom_settings)


@mcpapp.tool()
def msys2_vercmp(versionA: str, versionB: str) -> int:
    """Compare two MSYS2 package versions.

    Returns:
        -1 if versionA < versionB
         0 if versionA == versionB
         1 if versionA > versionB
    """

    return vercmp(versionA, versionB)


class MCPRepository(BaseModel):
    """A MSYS2 repository"""

    name: str = Field(..., description="Name of the repository")
    pacman_url: str = Field(..., description="A full URL to a location where the database, packages, and signatures for this repository can be found.")
    src_url: str = Field(..., description="Git source URL of the repository, where the PKGBUILD and other source files can be found.")


@mcpapp.tool()
def msys2_list_repositories() -> list[MCPRepository]:
    """Returns a list of MSYS2 repositories"""

    res = []
    for repo in get_repositories():
        res.append(MCPRepository(name=repo.name, pacman_url=repo.url, src_url=repo.src_url))
    return res


class MCPPackage(BaseModel):
    """A MSYS2 package"""

    name: str = Field(..., description="Name of the package")
    version: str = Field(..., description="Version of the package")
    description: str = Field(..., description="Description of the package")
    repository: str = Field(..., description="Repository where the package is located")


class MCPBasePackage(BaseModel):
    """A base package in MSYS2"""

    name: str = Field(..., description="Name of the base package")
    description: str = Field(..., description="Description of the base package")
    packages: list[MCPPackage] = Field(default_factory=list, description="List of packages that belong to this base package")


@mcpapp.tool()
def msys2_search_base_packages(query: str, limit: int = 25) -> list[MCPBasePackage]:
    """Find MSYS2 base packages

    Args:
        query: The search query to find base packages.
        limit: The maximum number of results to return (default is 25).

    Returns:
        A list of package names that match the query, sorted by relevance.
    """

    res = []
    for src in find_packages(query, "pkg")[:limit]:
        assert isinstance(src, Source)
        pkgres = []
        for pkg in src.packages.values():
            pkgres.append(MCPPackage(name=pkg.name, version=pkg.version, description=pkg.desc, repository=pkg.repo))
        res.append(MCPBasePackage(name=src.name, description=src.desc, packages=pkgres))
    return res
