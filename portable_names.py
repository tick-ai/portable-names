#!/usr/bin/env python3
"""portable-names: report the paths of a project that break a checkout on Windows or macOS.

It looks at names only: it never opens, reads or changes a file.
Python 3.11, standard library only.
"""

import json
import os
import re
import sys
import unicodedata

VERSION = "0.1.0"
TOOL = "portable-names"
DEFAULT_MAX_PATH = 260
SKIPPED_FOLDERS = frozenset({".git", ".hg", ".svn", "node_modules", ".venv", "__pycache__"})

# (number, id, severity, platforms), in the order of the rule table.
RULES: dict[int, tuple[str, str, list[str]]] = {
    1: ("reserved-name", "error", ["windows"]),
    2: ("forbidden-char", "error", ["windows"]),
    3: ("trailing-dot-space", "error", ["windows"]),
    4: ("path-too-long", "warn", ["windows"]),
    5: ("case-collision", "error", ["windows", "macos"]),
    6: ("normalization-collision", "error", ["macos"]),
    7: ("file-folder-collision", "error", ["windows", "macos"]),
}

RESERVED_STEMS = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
    + ["com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³"]
)
FORBIDDEN_CHARS = frozenset('<>:"\\|?*')
ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}
LEVELS = ("error", "warn", "none")
LEVEL_RANK = {"warn": 1, "error": 2}


class UsageError(Exception):
    """A usage error: message on stderr, nothing on stdout, exit code 2."""


class Options:
    """The parsed command line."""

    def __init__(self) -> None:
        self.folder: str | None = None
        self.stdin: bool = False
        self.nul: bool = False
        self.json: bool = False
        self.max_path: int = DEFAULT_MAX_PATH
        self.fail_on: str = "error"


def parse_args(argv: list[str]) -> Options:
    """Parse the arguments after the program name, or raise UsageError."""
    opts = Options()
    seen_max = False
    seen_fail = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg == "--stdin":
            opts.stdin = True
        elif arg == "-z":
            opts.nul = True
        elif arg == "--json":
            opts.json = True
        elif arg in ("--max-path", "--fail-on"):
            if i >= len(argv):
                raise UsageError(f"option {arg} needs a value")
            value = argv[i]
            i += 1
            if arg == "--max-path":
                if seen_max:
                    raise UsageError("--max-path given twice")
                seen_max = True
                if re.fullmatch(r"[0-9]+", value) is None:
                    raise UsageError(f"--max-path needs a number of digits, at least 1, not {value!r}")
                digits = value.lstrip("0")
                if not digits:
                    raise UsageError("--max-path must be at least 1")
                opts.max_path = int(digits) if len(digits) <= 18 else 10**18
            else:
                if seen_fail:
                    raise UsageError("--fail-on given twice")
                seen_fail = True
                if value not in LEVELS:
                    raise UsageError(f"--fail-on must be error, warn or none, not {value!r}")
                opts.fail_on = value
        elif arg.startswith("-"):
            raise UsageError(f"unknown option {arg!r}")
        else:
            if opts.folder is not None:
                raise UsageError("at most one folder may be given")
            opts.folder = arg
    if opts.stdin and opts.folder is not None:
        raise UsageError("--stdin cannot be given with a folder")
    if opts.nul and not opts.stdin:
        raise UsageError("-z needs --stdin")
    return opts


def read_list(data: bytes, sep: bytes) -> set[str]:
    """Cut the standard input at every separator and check each path."""
    if not data:
        return set()
    pieces = data.split(sep)
    if data.endswith(sep):
        pieces.pop()
    paths: set[str] = set()
    for position, raw in enumerate(pieces, start=1):
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise UsageError(f"path {position} of the list is not valid UTF-8") from None
        if not path:
            raise UsageError(f"path {position} of the list is empty")
        if path.startswith("/"):
            raise UsageError(f"path {position} of the list is absolute")
        for part in path.split("/"):
            if part == "":
                raise UsageError(f"path {position} of the list has an empty part")
            if part in (".", ".."):
                raise UsageError(f"path {position} of the list has a part {part!r}")
        paths.add(path)
    return paths


def walk_folder(root: str) -> tuple[set[str], set[str]]:
    """Walk root without following links; return (all paths, folder paths)."""
    if not os.path.isdir(root):
        raise UsageError(f"{root!r} is not an existing folder")
    paths: set[str] = set()
    folders: set[str] = set()
    stack: list[tuple[bytes, str]] = [(os.fsencode(root), "")]
    while stack:
        disk, prefix = stack.pop()
        try:
            with os.scandir(disk) as it:
                entries = list(it)
        except OSError as exc:
            shown = prefix or root
            raise UsageError(f"cannot list the folder {shown!r}: {exc.strerror or exc}") from None
        for entry in entries:
            raw = entry.name if isinstance(entry.name, bytes) else os.fsencode(entry.name)
            try:
                name = raw.decode("utf-8")
            except UnicodeDecodeError:
                where = prefix or "the root folder"
                raise UsageError(f"a file name in {where!r} is not valid UTF-8") from None
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                if name in SKIPPED_FOLDERS:
                    continue
                path = prefix + name
                folders.add(path)
                paths.add(path)
                stack.append((os.path.join(disk, raw), path + "/"))
            else:
                paths.add(prefix + name)
    return paths, folders


def utf16_length(text: str) -> int:
    """The length of text in UTF-16 code units."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def name_findings(path: str, max_path: int) -> list[tuple[int, str | None]]:
    """Rules 1 to 4 for one path: (rule number, None) for each rule broken."""
    name = path.rsplit("/", 1)[-1]
    found: list[tuple[int, str | None]] = []
    if name.split(".", 1)[0].translate(ASCII_LOWER) in RESERVED_STEMS:
        found.append((1, None))
    if any(c in FORBIDDEN_CHARS or ord(c) < 0x20 for c in name):
        found.append((2, None))
    if name.endswith((".", " ")):
        found.append((3, None))
    if utf16_length(path) > max_path:
        found.append((4, None))
    return found


def collision_findings(paths: set[str], folders: set[str]) -> list[tuple[str, int, str]]:
    """Rules 5 to 7: (path, rule number, kept path) for each path that is not kept."""
    groups: dict[tuple[str, str], list[str]] = {}
    for path in paths:
        parent, _, name = path.rpartition("/")
        key = unicodedata.normalize("NFC", name).casefold()
        groups.setdefault((parent, key), []).append(path)
    found: list[tuple[str, int, str]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()
        kept = members[0]
        has_folder = any(m in folders for m in members)
        has_file = any(m not in folders for m in members)
        if has_folder and has_file:
            rule = 7
        else:
            nfc = {unicodedata.normalize("NFC", m.rpartition("/")[2]) for m in members}
            rule = 5 if len(nfc) > 1 else 6
        for other in members[1:]:
            found.append((other, rule, kept))
    return found


def judge(paths: set[str], folders: set[str], max_path: int) -> list[tuple[str, int, str | None]]:
    """All findings, ordered by path then rule number."""
    findings: list[tuple[str, int, str | None]] = []
    for path in paths:
        for rule, other in name_findings(path, max_path):
            findings.append((path, rule, other))
    for path, rule, kept in collision_findings(paths, folders):
        findings.append((path, rule, kept))
    findings.sort(key=lambda f: (f[0], f[1]))
    return findings


def show(text: str) -> str:
    """Show control characters U+0000 to U+001F as \\xNN."""
    return "".join(f"\\x{ord(c):02x}" if ord(c) < 0x20 else c for c in text)


def render_plain(count: int, findings: list[tuple[str, int, str | None]]) -> str:
    """The plain form: one line per finding, then the summary line."""
    lines: list[str] = []
    errors = warnings = 0
    for path, rule, other in findings:
        rule_id, severity, _ = RULES[rule]
        if severity == "error":
            errors += 1
        else:
            warnings += 1
        line = f"{show(path)}: {severity} {rule_id}"
        if other is not None:
            line += f" (with {show(other)})"
        lines.append(line)
    lines.append(f"paths: {count}; errors: {errors}; warnings: {warnings}")
    return "\n".join(lines) + "\n"


def render_json(count: int, findings: list[tuple[str, int, str | None]]) -> str:
    """The JSON document, then a newline."""
    items = []
    errors = warnings = 0
    for path, rule, other in findings:
        rule_id, severity, platforms = RULES[rule]
        if severity == "error":
            errors += 1
        else:
            warnings += 1
        items.append(
            {"path": path, "rule": rule_id, "severity": severity, "platforms": list(platforms), "with": other}
        )
    doc = {
        "tool": TOOL,
        "version": VERSION,
        "paths": count,
        "errors": errors,
        "warnings": warnings,
        "findings": items,
    }
    return json.dumps(doc) + "\n"


def write_stream(stream: object, text: str, errors: str) -> None:
    """Write text to a text stream as UTF-8 bytes, whatever the locale."""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8", errors))
        buffer.flush()
    else:
        stream.write(text)  # type: ignore[attr-defined]
        stream.flush()  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    """Run the tool; return the exit code."""
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        opts = parse_args(args)
        folders: set[str]
        if opts.stdin:
            data = sys.stdin.buffer.read()
            paths = read_list(data, b"\0" if opts.nul else b"\n")
            folders = set()
        else:
            paths, folders = walk_folder(opts.folder if opts.folder is not None else ".")
    except UsageError as exc:
        write_stream(sys.stderr, f"{TOOL}: {exc}\n", "backslashreplace")
        return 2
    # Every proper prefix of a path is a path, and a folder.
    for path in list(paths):
        prefix = path
        while "/" in prefix:
            prefix = prefix.rpartition("/")[0]
            if prefix in folders:
                break
            folders.add(prefix)
    paths |= folders
    findings = judge(paths, folders, opts.max_path)
    text = render_json(len(paths), findings) if opts.json else render_plain(len(paths), findings)
    write_stream(sys.stdout, text, "strict")
    if opts.fail_on == "none":
        return 0
    threshold = LEVEL_RANK[opts.fail_on]
    worst = max((LEVEL_RANK[RULES[rule][1]] for _, rule, _ in findings), default=0)
    return 1 if worst >= threshold else 0


if __name__ == "__main__":
    raise SystemExit(main())
