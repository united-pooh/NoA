from __future__ import annotations

from importlib.resources import files
from typing import cast

import pytest
from fastmcp import Client
from fastmcp.apps import ResourceCSP

import noa.compat.app_validation as app_validation
from noa.compat.app_validation import AppHTMLValidationError, validate_compatibility_app_html
from noa.server import COMPATIBILITY_APP_URI, mcp


def _bundled_app_html() -> str:
    return files("noa.compat.app").joinpath("index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fragment",
    (
        "<script>alert(1)</script>",
        "<iframe></iframe>",
        "<object></object>",
        "<embed>",
        "<base>",
        "<form></form>",
        '<img src="image.png">',
        '<img srcset="image.png 1x">',
        '<a href="page.html">link</a>',
        '<button action="submit">submit</button>',
        '<button formaction="submit">submit</button>',
        '<div data="payload"></div>',
        '<video poster="poster.png"></video>',
        '<div onclick="run()"></div>',
        '<meta http-equiv="refresh" content="0;url=/redirect">',
        '<body background="image.png"></body>',
        '<link imagesrcset="image.png 1x">',
        "<style>@import 'theme.css';</style>",
        "<style>body { background: url(image.png); }</style>",
        "<style>body { width: expression(alert(1)); }</style>",
        "<p>javascript:alert(1)</p>",
        "<p>http://example.invalid</p>",
        "<p>https://example.invalid</p>",
        "<p>ftp://example.invalid</p>",
        "<p>fetch('/data')</p>",
        "<p>XMLHttpRequest</p>",
        "<p>WebSocket</p>",
    ),
)
def test_compatibility_app_policy_rejects_active_and_remote_content(fragment: str) -> None:
    with pytest.raises(AppHTMLValidationError, match="MCP App HTML policy violation"):
        validate_compatibility_app_html(
            fragment,
            expected_heading="NoA Compatibility",
            expected_resource_uri=COMPATIBILITY_APP_URI,
        )


@pytest.mark.parametrize(
    "unsafe_css",
    [
        'body { background: image-set("//example.invalid/app.png" 1x); }',
        'body { background: -webkit-image-set("//example.invalid/app.png" 1x); }',
        "body { color: var(--untrusted); }",
        "b\\6f dy { color: inherit; }",
        ".unknown { color: inherit; }",
        "body { position: fixed; }",
        "body { padding: 25px; }",
    ],
)
def test_compatibility_app_css_is_fail_closed(unsafe_css: str) -> None:
    html = _bundled_app_html().replace("</style>", f"{unsafe_css}\n  </style>")

    with pytest.raises(AppHTMLValidationError, match="MCP App HTML policy violation"):
        validate_compatibility_app_html(
            html,
            expected_heading="NoA Compatibility",
            expected_resource_uri=COMPATIBILITY_APP_URI,
        )


@pytest.mark.parametrize(
    "spoofed_html",
    [
        _bundled_app_html().replace("<h1>NoA Compatibility</h1>", "<h1>Wrong heading</h1>"),
        _bundled_app_html().replace(
            "<code>ui://noa/compatibility.html</code>",
            "<code>ui://wrong/app.html</code><!-- ui://noa/compatibility.html -->",
        ),
        _bundled_app_html()
        .replace(
            "<h1>NoA Compatibility</h1>",
            "<h1>Wrong heading</h1><!-- NoA Compatibility -->",
        )
        .replace(
            "<code>ui://noa/compatibility.html</code>",
            "<code>ui://wrong/app.html</code><!-- ui://noa/compatibility.html -->",
        ),
    ],
)
def test_compatibility_app_requires_exact_visible_heading_and_uri(spoofed_html: str) -> None:
    with pytest.raises(AppHTMLValidationError):
        validate_compatibility_app_html(
            spoofed_html,
            expected_heading="NoA Compatibility",
            expected_resource_uri=COMPATIBILITY_APP_URI,
        )


async def test_compatibility_app_is_bundled_and_network_free() -> None:
    async with Client(mcp) as client:
        contents = await client.read_resource(COMPATIBILITY_APP_URI)

    assert len(contents) == 1
    content = contents[0]
    assert content.mime_type == "text/html;profile=mcp-app"

    html = content.text
    assert html is not None
    assert "NoA Compatibility" in html
    assert COMPATIBILITY_APP_URI in html

    validation = validate_compatibility_app_html(
        html,
        expected_heading="NoA Compatibility",
        expected_resource_uri=COMPATIBILITY_APP_URI,
    )
    assert validation.heading_visible is True
    assert validation.resource_uri_visible is True


def test_compatibility_app_csp_validator_accepts_matching_empty_domains() -> None:
    validation = app_validation.validate_compatibility_app_csp(
        {"ui": {"csp": {}}},
        {"ui": {"csp": {}}},
    )

    assert validation.domains == {
        "connect_domains": [],
        "resource_domains": [],
        "frame_domains": [],
        "base_uri_domains": [],
    }
    assert validation.metadata_consistent is True


@pytest.mark.parametrize(
    ("content_metadata", "resource_metadata"),
    [
        (
            {"ui": {"csp": {}}},
            {"ui": {"csp": {"connectDomains": ["https://evil.invalid"]}}},
        ),
        (
            {"ui": {"csp": {}}},
            {"ui": {"csp": {"connectDomains": []}}},
        ),
        (
            {"ui": {"csp": {"unknownDomains": []}}},
            {"ui": {"csp": {"unknownDomains": []}}},
        ),
        ({"ui": {}}, {"ui": {"csp": {}}}),
    ],
)
def test_compatibility_app_csp_validator_rejects_unsafe_or_inconsistent_metadata(
    content_metadata: dict[str, object],
    resource_metadata: dict[str, object],
) -> None:
    with pytest.raises(app_validation.AppCSPValidationError):
        app_validation.validate_compatibility_app_csp(content_metadata, resource_metadata)


async def test_compatibility_app_declares_deny_by_default_csp() -> None:
    async with Client(mcp) as client:
        contents = await client.read_resource(COMPATIBILITY_APP_URI)
        resources = {str(resource.uri): resource for resource in await client.list_resources()}

    content_metadata = cast(dict[str, object], contents[0].meta)
    content_ui_metadata = cast(dict[str, object], content_metadata["ui"])
    csp = ResourceCSP.model_validate(content_ui_metadata["csp"])
    assert csp.connect_domains in (None, [])
    assert csp.resource_domains in (None, [])
    assert csp.frame_domains in (None, [])
    assert csp.base_uri_domains in (None, [])

    resource_metadata = cast(dict[str, object], resources[COMPATIBILITY_APP_URI].meta)
    resource_ui_metadata = cast(dict[str, object], resource_metadata["ui"])
    assert "csp" in resource_ui_metadata


async def test_show_compatibility_app_returns_resource_uri() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("show_compatibility_app")

    assert result.data == {
        "status": "pass",
        "resource_uri": COMPATIBILITY_APP_URI,
    }
    assert result.is_error is False


async def test_show_compatibility_app_exposes_app_resource_metadata() -> None:
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    tool = tools["show_compatibility_app"]
    assert tool.description

    metadata = cast(dict[str, object], tool.meta)
    ui_metadata = cast(dict[str, object], metadata["ui"])
    assert ui_metadata["resourceUri"] == COMPATIBILITY_APP_URI
