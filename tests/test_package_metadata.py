import sys
from importlib.metadata import version

from noa import __version__


def test_runtime_and_direct_dependency_versions_are_exact() -> None:
    package_version = version("noa-mcp")

    assert sys.version_info[:2] == (3, 11)
    assert package_version == "0.1.0a0"
    assert __version__ == package_version
    assert version("fastmcp") == "4.0.0b3"
    assert version("fastmcp-slim") == "4.0.0b3"
    assert version("mcp") == "2.0.0"
    assert version("ladybug") == "0.19.1"
    assert version("packaging") == "26.3"
    assert version("pydantic") == "2.13.4"
    assert version("anyio") == "4.14.2"
