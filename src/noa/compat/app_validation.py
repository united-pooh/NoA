from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import ClassVar, cast


class AppHTMLValidationError(ValueError):
    def __init__(self, message: str, *, violations: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.violations = violations


@dataclass(frozen=True)
class AppHTMLValidationResult:
    heading_visible: bool
    resource_uri_visible: bool


class AppCSPValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AppCSPValidationResult:
    domains: dict[str, list[str]]
    metadata_consistent: bool


_CSP_FIELDS = {
    "connectDomains": "connect_domains",
    "resourceDomains": "resource_domains",
    "frameDomains": "frame_domains",
    "baseUriDomains": "base_uri_domains",
}
_EXPECTED_CSS_RULES: dict[str, dict[str, str]] = {
    ":root": {
        "color-scheme": "light dark",
        "font-family": "system-ui, sans-serif",
    },
    "body": {
        "margin": "0",
        "padding": "24px",
        "background": "Canvas",
        "color": "CanvasText",
    },
    "main": {
        "max-width": "720px",
        "margin": "0 auto",
    },
    ".status": {
        "padding": "20px",
        "border": "1px solid color-mix(in srgb, CanvasText 25%, transparent)",
        "border-radius": "12px",
    },
    "code": {
        "color": "inherit",
        "font-family": "ui-monospace, monospace",
        "overflow-wrap": "anywhere",
        "word-break": "break-word",
    },
}
_CSS_RULE_PATTERN = re.compile(r"([^{}]+)\{([^{}]*)\}")
_HIDDEN_TEXT_TAGS = frozenset({"head", "title", "style"})
_VOID_TAGS = frozenset({"meta"})


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _parse_css_stylesheet(stylesheet: str) -> dict[str, dict[str, str]]:
    if "\\" in stylesheet:
        raise ValueError("CSS escapes are not allowed")
    if "//" in stylesheet:
        raise ValueError("protocol-relative CSS content is not allowed")
    if "/*" in stylesheet or "*/" in stylesheet:
        raise ValueError("CSS comments are not allowed")
    if "@" in stylesheet:
        raise ValueError("CSS at-rules are not allowed")

    rules: dict[str, dict[str, str]] = {}
    position = 0
    for match in _CSS_RULE_PATTERN.finditer(stylesheet):
        if stylesheet[position : match.start()].strip():
            raise ValueError("invalid CSS rule syntax")
        selector = _normalize_whitespace(match.group(1))
        if selector in rules:
            raise ValueError(f"duplicate CSS selector: {selector}")

        declarations: dict[str, str] = {}
        for raw_declaration in match.group(2).split(";"):
            declaration = raw_declaration.strip()
            if not declaration:
                continue
            if ":" not in declaration:
                raise ValueError(f"invalid CSS declaration for selector {selector}")
            property_name, raw_value = declaration.split(":", maxsplit=1)
            property_name = property_name.strip()
            value = _normalize_whitespace(raw_value)
            if not property_name or not value:
                raise ValueError(f"invalid CSS declaration for selector {selector}")
            if property_name in declarations:
                raise ValueError(f"duplicate CSS property on {selector}: {property_name}")
            declarations[property_name] = value
        rules[selector] = declarations
        position = match.end()

    if stylesheet[position:].strip():
        raise ValueError("invalid trailing CSS content")
    return rules


class _CompatibilityAppHTMLPolicyParser(HTMLParser):
    _ALLOWED_TAGS = frozenset(
        {"html", "head", "meta", "title", "style", "body", "main", "section", "h1", "p", "code"}
    )
    _ALLOWED_ATTRIBUTES: ClassVar[dict[str, frozenset[str]]] = {
        "html": frozenset({"lang"}),
        "section": frozenset({"class"}),
    }
    _NO_ATTRIBUTES: frozenset[str] = frozenset()

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[str] = []
        self.h1_texts: list[str] = []
        self.code_texts: list[str] = []
        self._open_tags: list[str] = []
        self._text_frames: list[tuple[str, int, list[str]]] = []
        self._style_chunks: list[str] = []
        self._style_count = 0
        self._doctype_count = 0

    def handle_decl(self, decl: str) -> None:
        if decl.lower() != "doctype html" or self._doctype_count:
            self.violations.append(f"invalid declaration: {decl}")
            return
        self._doctype_count += 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._inspect_element(tag, attrs)
        normalized_tag = tag.lower()
        if normalized_tag not in _VOID_TAGS:
            self._open_tags.append(normalized_tag)
            if normalized_tag in {"h1", "code"} and not self._has_hidden_ancestor():
                self._text_frames.append((normalized_tag, len(self._open_tags), []))
        if normalized_tag == "style":
            self._style_count += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._inspect_element(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.violations.append(f"self-closing tag is not allowed: {tag.lower()}")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in self._ALLOWED_TAGS:
            self.violations.append(f"unknown tag: {normalized_tag}")
            return
        if normalized_tag in _VOID_TAGS:
            self.violations.append(f"void tag must not have an end tag: {normalized_tag}")
            return
        if not self._open_tags or self._open_tags[-1] != normalized_tag:
            self.violations.append(f"unbalanced end tag: {normalized_tag}")
            return
        if (
            self._text_frames
            and self._text_frames[-1][0] == normalized_tag
            and self._text_frames[-1][1] == len(self._open_tags)
        ):
            frame_tag, _, chunks = self._text_frames.pop()
            visible_text = _normalize_whitespace("".join(chunks))
            target = self.h1_texts if frame_tag == "h1" else self.code_texts
            target.append(visible_text)
        self._open_tags.pop()

    def handle_data(self, data: str) -> None:
        if "style" in self._open_tags:
            self._style_chunks.append(data)
        if any(tag in _HIDDEN_TEXT_TAGS for tag in self._open_tags):
            return
        for _, _, chunks in self._text_frames:
            chunks.append(data)

    def handle_comment(self, data: str) -> None:
        self.violations.append("HTML comments are not allowed")

    def finish(self) -> None:
        if self._doctype_count != 1:
            self.violations.append("exactly one HTML5 doctype is required")
        if self._open_tags:
            self.violations.append(f"unclosed tags: {', '.join(self._open_tags)}")
        if self._style_count != 1:
            self.violations.append("exactly one style element is required")
            return
        try:
            rules = _parse_css_stylesheet("".join(self._style_chunks))
        except ValueError as exc:
            self.violations.append(str(exc))
            return
        if rules != _EXPECTED_CSS_RULES:
            self.violations.append("CSS rules must exactly match the compatibility App allowlist")

    def _has_hidden_ancestor(self) -> bool:
        return any(tag in _HIDDEN_TEXT_TAGS for tag in self._open_tags[:-1])

    def _inspect_element(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in self._ALLOWED_TAGS:
            self.violations.append(f"unknown tag: {normalized_tag}")

        if normalized_tag == "meta":
            self._inspect_meta_attributes(attrs)
            return

        allowed_attributes = self._ALLOWED_ATTRIBUTES.get(normalized_tag, self._NO_ATTRIBUTES)
        normalized_attrs = [(name.lower(), value) for name, value in attrs]
        names = [name for name, _ in normalized_attrs]
        if len(names) != len(set(names)):
            self.violations.append(f"duplicate attribute on {normalized_tag}")
        for name, _ in normalized_attrs:
            if name.startswith("on") or name not in allowed_attributes:
                self.violations.append(f"unknown attribute on {normalized_tag}: {name}")
        values = dict(normalized_attrs)
        if normalized_tag == "html" and values != {"lang": "en"}:
            self.violations.append("html attributes must exactly match the allowlist")
        if normalized_tag == "section" and values != {"class": "status"}:
            self.violations.append("section attributes must exactly match the allowlist")

    def _inspect_meta_attributes(self, attrs: list[tuple[str, str | None]]) -> None:
        normalized_attrs = [(name.lower(), value) for name, value in attrs]
        names = [name for name, _ in normalized_attrs]
        values = dict(normalized_attrs)
        valid = len(names) == len(values) and values in (
            {"charset": "utf-8"},
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        )
        if not valid:
            self.violations.append("meta attributes must exactly match the allowlist")


def _extract_csp(metadata: object, *, label: str) -> dict[str, object]:
    if not isinstance(metadata, dict):
        raise AppCSPValidationError(f"{label} metadata must be an object")
    metadata_object = cast(dict[str, object], metadata)
    ui = metadata_object.get("ui")
    if not isinstance(ui, dict) or set(ui) != {"csp"}:
        raise AppCSPValidationError(f"{label} metadata.ui must contain exactly csp")
    ui_object = cast(dict[str, object], ui)
    csp = ui_object["csp"]
    if not isinstance(csp, dict):
        raise AppCSPValidationError(f"{label} metadata.ui.csp must be an object")
    csp_object = cast(dict[str, object], csp)
    unknown_fields = set(csp_object) - set(_CSP_FIELDS)
    if unknown_fields:
        raise AppCSPValidationError(
            f"{label} metadata.ui.csp has unknown fields: {sorted(unknown_fields)}"
        )
    return csp_object


def validate_compatibility_app_csp(
    content_metadata: object,
    resource_metadata: object,
) -> AppCSPValidationResult:
    content_csp = _extract_csp(content_metadata, label="content")
    resource_csp = _extract_csp(resource_metadata, label="resource")
    if content_csp != resource_csp:
        raise AppCSPValidationError("content and resource CSP metadata must be structurally equal")

    domains: dict[str, list[str]] = {}
    for external_name, result_name in _CSP_FIELDS.items():
        value = content_csp.get(external_name)
        if value is None or value == []:
            domains[result_name] = []
            continue
        raise AppCSPValidationError(f"{external_name} must be absent, null, or an empty list")
    return AppCSPValidationResult(domains=domains, metadata_consistent=True)


def validate_compatibility_app_html(
    html: str,
    *,
    expected_heading: str,
    expected_resource_uri: str,
) -> AppHTMLValidationResult:
    parser = _CompatibilityAppHTMLPolicyParser()
    parser.feed(html)
    parser.close()
    parser.finish()
    if parser.h1_texts != [expected_heading]:
        parser.violations.append("visible h1 text must exactly match the expected heading")
    if parser.code_texts != [expected_resource_uri]:
        parser.violations.append("visible code text must exactly match the expected resource URI")
    if parser.violations:
        violations = tuple(parser.violations)
        raise AppHTMLValidationError(
            f"MCP App HTML policy violations: {'; '.join(violations)}",
            violations=violations,
        )
    return AppHTMLValidationResult(
        heading_visible=True,
        resource_uri_visible=True,
    )
