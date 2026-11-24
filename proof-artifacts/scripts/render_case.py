from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
}
REDACTED = re.compile(r"(?:Bearer |Basic )?(?:\[redacted\]|<redacted>)", re.IGNORECASE)
HTTP_VERSION = r"HTTP/[0-9]+(?:\.[0-9]+)?"
REQUEST_LINE = re.compile(rf"([^\s]+) ([^\s]+) {HTTP_VERSION}")
STATUS_LINE = re.compile(rf"{HTTP_VERSION} ([1-5][0-9]{{2}})(?: .*)?")
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
JSON_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[][{}:,]|[^\s\[\]{}:,]+')


@dataclass(frozen=True)
class Message:
    start_line: str
    header_lines: list[str]
    headers: list[tuple[str, str]]
    body: bytes

    def values(self, name: str) -> list[str]:
        return [value for key, value in self.headers if key == name]


def read_message(path: Path) -> Message:
    raw = path.read_bytes()
    boundary = re.search(rb"\r?\n\r?\n", raw)
    if boundary is None:
        raise ValueError(f"{path.name} is missing the blank line between headers and body")
    lines = re.split(r"\r?\n", raw[: boundary.start()].decode("latin-1"))
    headers = []
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if not separator or HEADER_NAME.fullmatch(name) is None:
            raise ValueError(f"{path.name} contains a malformed header")
        key = name.lower()
        trimmed = value.strip()
        if key in SENSITIVE_HEADERS and REDACTED.fullmatch(trimmed) is None:
            raise ValueError(f"{path.name} contains an unredacted {key} header")
        headers.append((key, trimmed))
    return Message(lines[0], lines[1:], headers, raw[boundary.end() :])


def check_length(message: Message, label: str, *, bodyless: bool = False) -> None:
    if bodyless or message.values("transfer-encoding"):
        return
    lengths = message.values("content-length")
    if not lengths:
        return
    if any(re.fullmatch(r"[0-9]+", length) is None for length in lengths):
        raise ValueError(f"{label} contains an invalid Content-Length")
    if any(int(length) > 0 for length in lengths) and not message.body:
        raise ValueError(f"{label} is missing its body")
    if any(value.lower() != "identity" for value in message.values("content-encoding")):
        return
    if any(int(length) != len(message.body) for length in lengths):
        raise ValueError(f"{label} Content-Length differs from the captured body length")


def reject_non_json_constant(_: str) -> None:
    raise ValueError("Non-JSON constant")


def indent_json(body: str) -> str:
    json.loads(
        body,
        parse_int=str,
        parse_float=str,
        parse_constant=reject_non_json_constant,
    )
    tokens = JSON_TOKEN.findall(body)
    parts = []
    depth = 0
    for index, token in enumerate(tokens):
        if token in ("}", "]"):
            depth -= 1
            if tokens[index - 1] not in ("{", "["):
                parts.append("\n" + "  " * depth)
        parts.append(token)
        if token in ("{", "["):
            depth += 1
            if tokens[index + 1] not in ("}", "]"):
                parts.append("\n" + "  " * depth)
        elif token == ",":
            parts.append("\n" + "  " * depth)
        elif token == ":":
            parts.append(" ")
    return "".join(parts)


def fenced(content: str, language: str) -> str:
    longest_backticks = max(map(len, re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest_backticks + 1)
    return f"{fence}{language}\n{content}\n{fence}"


def visible(text: str) -> str:
    return "".join(
        char if char in "\r\n\t" or char.isprintable() else json.dumps(char)[1:-1] for char in text
    )


def render_message(message: Message) -> list[str]:
    head = "\n".join((message.start_line, *message.header_lines))
    if not message.body:
        return [fenced(visible(head), "http"), "正文为空。"]
    body = message.body.decode("utf-8", errors="backslashreplace")
    sections = [fenced(visible(head), "http"), "### 正文"]
    types = [value.partition(";")[0].strip().lower() for value in message.values("content-type")]
    if any(value == "application/json" or value.endswith("+json") for value in types):
        try:
            return [*sections, fenced(visible(indent_json(body)), "json")]
        except (ValueError, RecursionError):
            pass
    return [*sections, fenced(visible(body), "text")]


def render_case(directory: Path) -> None:
    request = read_message(directory / "request.http")
    response = read_message(directory / "response.http")
    request_match = REQUEST_LINE.fullmatch(request.start_line)
    status_match = STATUS_LINE.fullmatch(response.start_line)
    if request_match is None or status_match is None:
        raise ValueError("The captured HTTP request line or response status line is malformed")
    status = int(status_match[1])
    check_length(request, "request.http")
    check_length(
        response,
        "response.http",
        bodyless=request_match[1] == "HEAD" or status < 200 or status in (204, 304),
    )
    links = ["[原始请求](request.http)", "[原始响应](response.http)"]
    if (directory / "request.hurl").is_file():
        links.append("[Hurl 用例](request.hurl)")
    sections = [
        "# HTTP 用例",
        " · ".join(links),
        "## 请求参数",
        *render_message(request),
        "## 响应",
        *render_message(response),
    ]
    with (directory / "README.md").open("x", encoding="utf-8", newline="\n") as output:
        output.write("\n\n".join(sections) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a human-readable README.md from sanitized request.http and response.http. "
            "Existing README.md and source captures are preserved."
        )
    )
    parser.add_argument("case_dir", type=Path, help="directory containing the paired HTTP captures")
    path = parser.parse_args().case_dir
    try:
        render_case(path)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
