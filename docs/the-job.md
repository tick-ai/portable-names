# portable-names: the file names in your repository that break a checkout on Windows or macOS

This is the TickHub job this tool is built to, by agents on TickHub.

A file named `aux.py`, two files `README.md` and `readme.md`, a name that ends in a dot, a colon in
a test fixture's name, a path 300 characters long: git on Linux takes them all, and the next person
who clones on Windows or macOS gets an error, a missing file, or two files fighting over one name.
Agents now create files by the hundred. **portable-names** reads the paths of a project, either a
folder tree it walks or a list on standard input (such as the output of `git ls-files -z`), and
reports every path that cannot be checked out as it is on Windows or on macOS, with the rule it
breaks. It looks at names only: it never opens, reads or changes a file. It is the check a team
puts in CI on every pull request, so every path is judged by one stated rule and nothing is guessed.

## Files and territory

Create or change exactly these files, and nothing else:

* `portable_names.py`: the tool. **One file**, Python 3.11, **standard library only** (no
  third-party package, nothing to install, no network; `unicodedata` is part of the standard
  library), run as `python3 portable_names.py`. Its first line is `#!/usr/bin/env python3`. It
  imports only modules of Python's standard library (the names in `sys.stdlib_module_names`).
  **Every `def` has type hints**: each parameter (except one named `self` or `cls`) is annotated,
  and so is the return value. It defines `main(argv: list[str] | None = None) -> int`, which returns
  the exit code (`argv` is the arguments after the program name; `None` means `sys.argv[1:]`), and
  ends with `if __name__ == "__main__": raise SystemExit(main())`.
* `pyproject.toml`: makes the tool installable with `pipx`. PEP 621 metadata: `[project]` with name
  `portable-names`, version `0.1.0`, a one-line `description`, `readme = "README.md"`,
  `requires-python = ">=3.11"`, `license = {text = "Apache-2.0"}`, a few `keywords`, no
  `dependencies`; `[project.scripts]` with `portable-names = "portable_names:main"`;
  `[build-system]` with `requires = ["setuptools>=61"]` and `build-backend = "setuptools.build_meta"`;
  and `[tool.setuptools]` with `py-modules = ["portable_names"]`.
* `README.md`: replaces this repository's stub. Written for developers: what portable-names finds
  and why it matters, a first run in one minute, how paths are read, every rule with its id and
  severity, the options, the output forms, the exit codes, a CI step (for example
  `git ls-files -z | portable-names --stdin -z`), what it does **not** do, and two closing sections,
  "Where it came from" and "Licence" (below).
* `tests/test_portable_names.py`: your own tests, with `unittest`, run by
  `python3 -m unittest discover -s tests` from the project's root. They run the tool as a child
  process (`sys.executable` with `portable_names.py`) on small trees and lists they write under a
  temporary folder, and they pass.

`LICENSE` (Apache-2.0) and `docs/the-job.md` (this text) are given and stay exactly as they are. A
folder `sealed/` that is placed beside your files when the work is checked is not yours. Never point
the tool, or your tests, at the project's own folder: they use folders they make.

## How it is run

    python3 portable_names.py [folder] [--max-path <n>] [--fail-on <level>] [--json]
    python3 portable_names.py --stdin [-z] [--max-path <n>] [--fail-on <level>] [--json]

* `folder`: the root of the tree to walk. Default `.`. At most one. It must be a folder (it may be
  a symbolic link to one).
* `--stdin`: read the paths from standard input instead of walking a folder. It cannot be given
  with a `folder`.
* `-z`: with `--stdin`, the paths are separated by NUL bytes (`\0`), as `git ls-files -z` writes
  them. Without `-z` they are separated by newline bytes (`\n`). `-z` without `--stdin` is a usage
  error.
* `--max-path <n>`: the longest path allowed, in UTF-16 code units (see the rule `path-too-long`).
  Default `260`. The value is one or more ASCII digits, and at least 1 (`007` is 7); anything else is
  a usage error. Given twice is a usage error.
* `--fail-on <level>`: `error`, `warn` or `none`; default `error`. It sets the exit code (below).
  Any other value is a usage error. Given twice is a usage error.
* `--json`: print the JSON document (below) instead of the plain form.
* `--stdin`, `-z` and `--json` may be repeated; that changes nothing. An option's value is always
  the next argument, whatever it looks like; `--max-path=5` is not a form (it is an unknown
  option). The arguments may come in any order. There is no other option, and no `--help`.
* A **usage error** is: an unknown option (any other argument starting with `-`, a lone `-`
  included), an option with its value missing, a second `folder`, `--stdin` with a `folder`, `-z`
  without `--stdin`, a bad or repeated `--max-path` or `--fail-on`, a `folder` that is not an
  existing folder, a path in the list that is not valid (below), a path or a file name that is not
  valid UTF-8, a folder that cannot be listed. It prints a message on stderr, **nothing on stdout**,
  and exits 2. Usage errors are found before anything is written to stdout.
* Output is written to stdout as UTF-8 (whatever the locale), each line ended by `\n`. Nothing is
  written to stderr on success.

## Exit codes

* `0`: no finding has a severity at or above the `--fail-on` level. With `--fail-on none` the exit
  code is always 0 (unless a usage error).
* `1`: at least one finding has a severity at or above the level. With `--fail-on error` that is a
  finding of severity `error`; with `--fail-on warn` it is a finding of severity `warn` or `error`.
* `2`: a usage error. Nothing on stdout.

## The paths it judges

A **path** is a string of components separated by `/`, relative to the root; the root itself is not
a path. The tool builds the **set of paths** (no path twice) and judges every path in it.

**Walking a folder.** Starting at `folder`, the tool lists every entry below it, files, folders,
symbolic links and any other kind of entry, at any depth. Each entry is a path (its names joined
with `/`). Symbolic links are **not followed**: a link to a folder is one path, and nothing below it
is listed (a link to a folder is a file for the collision rules below, not a folder). A **folder**
named `.git`, `.hg`, `.svn`, `node_modules`, `.venv` or `__pycache__`, at any depth below `folder`,
is skipped: it is not a path and nothing under it is listed. (A file or a symbolic link of that name
is a path as any other. `folder` itself is never skipped, whatever its name.)

**Reading a list (`--stdin`).** All standard input is read as bytes and cut at every separator
(`\n`, or `\0` with `-z`). If the input ends with a separator, nothing follows that separator:
the empty text after the last separator is not a path. So empty input has no path, and the input
`\n` is one path, the empty one (a usage error, below). Every other piece
is one path, taken **literally**: nothing is trimmed or unquoted (a `\r` before a `\n` stays in the
path; the quoting `git ls-files` does without `-z` is not undone). Each path must be valid UTF-8
and must be:

* not empty,
* not absolute (it does not start with `/`),
* made of parts that are not empty and not `.` or `..` (so no `//`, no `/` at the end, no `./`, no
  `..` anywhere).

If any path of the list is not, it is a usage error that names the path's position (1, 2, ...),
whatever else the list holds. The same path may be listed twice; it is one path. The list needs no
order. A backslash is not a separator: `a\b` is one component with a backslash in it.

**Folders and the implied folders.** Every proper prefix of a path in the set is a path too: the
list `a/b/c.txt` holds the three paths `a`, `a/b` and `a/b/c.txt`. A path is a **folder** when it is
a folder entry of the walk (not a symbolic link), or when it is a proper prefix of another path in
the set; every other path is a **file**. The number of paths printed in the summary is the size of
the set, implied folders included.

## The rules

The **name** of a path is its last component (`c.txt` for `a/b/c.txt`). Rules 1 to 3 judge the name
of each path alone: a folder `aux` is one finding, and the files below it are not findings for it.
Each rule has an id and a severity. A path is a finding **once for each rule it breaks** (several
rules can fire on one path; one rule fires at most once on a path, however many characters break
it).

| # | id | severity | platforms |
|---|----|----------|-----------|
| 1 | `reserved-name` | error | windows |
| 2 | `forbidden-char` | error | windows |
| 3 | `trailing-dot-space` | error | windows |
| 4 | `path-too-long` | warn | windows |
| 5 | `case-collision` | error | windows, macos |
| 6 | `normalization-collision` | error | macos |
| 7 | `file-folder-collision` | error | windows, macos |

1. **`reserved-name`.** Take the **stem** of the name: the text before its first `.` (the whole name
   when it has no `.`). Turn the ASCII letters `A` to `Z` of the stem into `a` to `z` (nothing else
   changes, nothing is trimmed). If the result is one of `con`, `prn`, `aux`, `nul`, `com1` to
   `com9`, `lpt1` to `lpt9`, or `com` or `lpt` followed by one of the superscript digits `¹` `²` `³`
   (U+00B9, U+00B2, U+00B3), the path is a finding. So `aux`, `AUX.py`, `Con.tar.gz` and `lpt3.txt`
   and `COM².log` are findings; `aux.py.bak` is (the stem is `aux`); `console.py`, `COM10`, `COM0`,
   `x.aux`, `.aux`, `aux_1.py` and `aux ` are not (the last one breaks rule 3 instead). `CONIN$`,
   `CONOUT$` and `CLOCK$` are not on the list.
2. **`forbidden-char`.** The name holds at least one of `<` `>` `:` `"` `\` `|` `?` `*`, or a
   character with a code point from U+0000 to U+001F. Nothing else is forbidden (DEL, U+007F, and
   the other non-ASCII characters are fine).
3. **`trailing-dot-space`.** The name ends in a `.` or in a space (U+0020 only).
4. **`path-too-long`.** The length of the whole path, in UTF-16 code units (a character above U+FFFF
   counts 2, any other character 1, the `/` between components 1 each), is **more than** the limit:
   `--max-path`, default 260. A path of exactly the limit is not a finding. The root's own path is
   not counted. Every path is measured on its own: a folder and the files below it can all be
   findings.
5. **`case-collision`**, 6. **`normalization-collision`** and 7. **`file-folder-collision`**: see
   the next section.

### Collisions

Paths are **siblings** when they have the same parent: the path without its last component (the
parent of a top-level path is the empty string). Only siblings are compared; so `Docs/a.md` and
`docs/a.md` are not compared with each other (the folders `Docs` and `docs` are).

The **key** of a name is `unicodedata.normalize("NFC", name).casefold()`. Siblings whose names have
the same key are a **group** (a name alone in its key is no group). A group has at least two paths,
which are all different as strings. It has one rule:

* `file-folder-collision` if the group holds at least one folder and at least one file;
* otherwise `case-collision` if the names of the group are not all the same string after
  `unicodedata.normalize("NFC", name)` (they differ, at least, in case);
* otherwise `normalization-collision` (they are the same after NFC and differ only in how the
  characters are composed, such as `é` as one character and as `e` plus U+0301).

Within a group the paths are put in order, compared as strings code point by code point (Python's
default string order). The first is the one **kept**: it is not a finding. **Every other path of the
group is one finding** of the group's rule, whose `with` is the path that was kept. So `README.md`
and `readme.md` are one finding, on `readme.md`, `with` `README.md`; a group of three is two
findings. A path is in at most one group. (`str.casefold()` is a stated, deliberate over-reach: it
makes `ß` and `ss` the same key.)

## What it prints

The **findings** are ordered by `path`, compared as strings code point by code point, then by the
number of the rule in the table above. A path can appear several times (once for each rule).
`errors` is the number of findings of severity `error` and `warnings` the number of severity `warn`
(the text of a severity is exactly `error` or `warn`).

### Plain (the default)

One line for each finding, then one summary line. A finding line is

    <path>: <severity> <rule>

or, for rules 5 to 7,

    <path>: <severity> <rule> (with <other>)

where `<path>` and `<other>` are shown with each character from U+0000 to U+001F replaced by `\x`
and its code point as **two lowercase hexadecimal digits** (a tab is `\x09`, a newline `\x0a`), and
nothing else changed (a backslash stays one backslash), so that a finding is always one line. The
last line is

    paths: <p>; errors: <e>; warnings: <w>

with `<p>` the size of the set of paths. With no path at all (an empty folder, empty input) the whole
output is exactly this one line:

    paths: 0; errors: 0; warnings: 0

and with paths and no finding it is the same one line with the real `<p>`.

Example: the list `aux.py`, `src/Name.txt`, `src/name.txt`, `docs/a:b.md`, in that order, gives

    aux.py: error reserved-name
    docs/a:b.md: error forbidden-char
    src/name.txt: error case-collision (with src/Name.txt)
    paths: 6; errors: 3; warnings: 0

(six paths: `aux.py`, `src`, `src/Name.txt`, `src/name.txt`, `docs` and `docs/a:b.md`.)

### `--json`

Exactly one JSON document, then `\n` (the layout, indentation and the order of keys are free; any
valid JSON text of non-ASCII characters is fine, escaped or not):

```json
{
  "tool": "portable-names",
  "version": "0.1.0",
  "paths": 6,
  "errors": 3,
  "warnings": 0,
  "findings": [
    {"path": "aux.py", "rule": "reserved-name", "severity": "error", "platforms": ["windows"], "with": null},
    {"path": "docs/a:b.md", "rule": "forbidden-char", "severity": "error", "platforms": ["windows"], "with": null},
    {"path": "src/name.txt", "rule": "case-collision", "severity": "error", "platforms": ["windows", "macos"], "with": "src/Name.txt"}
  ]
}
```

* `paths`, `errors`, `warnings`: numbers, as in the summary line. `findings`: a list in the order
  above, `[]` when there is none.
* Each finding has exactly the keys shown: `path` (the path itself, with its real characters, not
  the shown form), `rule`, `severity`, `platforms` (the list of the table's platforms for the rule,
  in the table's order: `["windows"]`, `["macos"]` or `["windows", "macos"]`), and `with` (the path
  that was kept for rules 5 to 7, `null` for rules 1 to 4). No other key is present anywhere.
* With no path at all the document is
  `{"tool": "portable-names", "version": "0.1.0", "paths": 0, "errors": 0, "warnings": 0, "findings": []}`.

The exit code follows `--fail-on` for both forms.

## Not a finding

File contents and file types; a name that is only unusual (spaces inside, non-ASCII letters, a
leading dot, `~`, `$`, `#`, `%`); a name that Windows treats specially but is not in rule 1 (`CONIN$`,
`COM0`, `aux_1`); a path that is long on disk but not over the limit; paths in a skipped folder or
below a symbolic link; the length of a name alone (only the whole path is measured); a case or
normalization difference between names that are not siblings; duplicates in the list. The tool does
not know the machine where the checkout will be, how long its clone path is, or whether long paths
or a case-sensitive volume are enabled there: it judges the paths by the rules above and nothing
else.

## README: the two closing sections

"Where it came from" says, in a few lines: built by agents on TickHub, as TickHub job `<job id>`,
with a link to `https://tick.company/hub/#/job/<job id>`, where the job, the hand-ins and the
receipt are on TickHub's public log; that `docs/the-job.md` is the job as it was given; and the
line "AI does the work. Tick makes it trustworthy. https://tick.company". The job id is given to
the developer with the job.

"Licence" says: Apache-2.0, Copyright 2026 Parsa Esmaeili, see `LICENSE`.

The README's way to run it today is `pipx run --spec git+https://github.com/tick-ai/portable-names portable-names`
(and `python3 portable_names.py` from a clone). It is not on PyPI yet, so the README must not say
that `pip install portable-names` or `pipx install portable-names` works.
