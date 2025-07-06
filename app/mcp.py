from mcp.server.fastmcp import FastMCP

from .utils import vercmp

mcpapp = FastMCP(name="MathServer", stateless_http=True, json_response=False)


@mcpapp.tool()
def msys2_vercmp(versionA: str, versionB: str) -> int:
    """Compare two MSYS2 package versions.

    Returns:
        -1 if versionA < versionB
         0 if versionA == versionB
         1 if versionA > versionB
    """

    return vercmp(versionA, versionB)
