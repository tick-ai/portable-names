# portable-names

**portable-names reports every path in your project that cannot be checked out as it is on Windows or macOS, and the rule it breaks.**

    pipx run --spec git+https://github.com/tick-ai/portable-names portable-names

```
$ git ls-files -z | portable-names --stdin -z
aux.py: error reserved-name
docs/a:b.md: error forbidden-char
notes.: error trailing-dot-space
src/name.txt: error case-collision (with src/Name.txt)
paths: 7; errors: 4; warnings: 0
$ echo $?
1
```

(From a clone, `python3 portable_names.py` does the same. With no argument it walks the current folder.)

## Why it matters

A file named `aux.py`, two files `README.md` and `readme.md`, a name that ends in a dot, a colon in a
test fixture's name, a path 300 characters long: git on Linux takes them all, and the next person
who clones on Windows or macOS gets an error, a missing file, or two files fighting over one name.
Agents now create files by the hundred. portable-names is the check a team puts in CI on every pull
request. It is one Python file, standard library only, and it looks at **names only**: it never
opens, reads or changes a file. Every path is judged by one stated rule and nothing is guessed.

## Run it

    python3 portable_names.py [folder] [--max-path <n>] [--fail-on <level>] [--json]
    python3 portable_names.py --stdin [-z] [--max-path <n>] [--fail-on <level>] [--json]

Python 3.11 or later, nothing to install. From a clone: `python3 portable_names.py`. Without a
clone: `pipx run --spec git+https://github.com/tick-ai/portable-names portable-names`. It is not on
PyPI yet, so there is no `pip install portable-names`.

## How paths are read

A **path** is a string of components separated by `/`, relative to the root; the root itself is not
a path. The tool builds the set of paths (no path twice) and judges every path in it.

**Walking a folder** (the default, root `.`). Every entry below the folder is a path: files, folders,
symbolic links and any other kind of entry, at any depth. Symbolic links are **not followed**: a link
to a folder is one path and nothing below it is listed. A *folder* named `.git`, `.hg`, `.svn`,
`node_modules`, `.venv` or `__pycache__`, at any depth, is skipped with everything under it (a file or
a link of that name is a path like any other; the root itself is never skipped).

**Reading a list (`--stdin`).** All of standard input is cut at every newline (or at every NUL byte
with `-z`, as `git ls-files -z` writes them). One separator at the very end is allowed: empty input
has no path, and the input `\n` is one path, the empty one, which is a usage error. Paths are taken
literally: nothing is trimmed or unquoted (a `\r` before the `\n` stays in the path), and a backslash
is not a separator. Each path must be valid UTF-8, not empty, not absolute, and made of parts that
are not empty and not `.` or `..`. The same path listed twice is one path. The list needs no order.

**Folders.** Every proper prefix of a path is a path too: the list `a/b/c.txt` holds `a`, `a/b` and
`a/b/c.txt` (3 paths). A path is a *folder* when it is a folder entry of the walk, or a proper prefix
of another path; every other path is a *file*. Folders are judged as paths of their own, so a bad
folder is one finding, not one per file below it.

## The rules

The **name** of a path is its last component. Rules 1 to 3 judge the name alone. A path is a finding
once for each rule it breaks.

| # | id | severity | platforms | the path is a finding when |
|---|----|----------|-----------|----------------------------|
| 1 | `reserved-name` | error | windows | the stem of the name (the text before its first `.`), with `A`-`Z` turned to `a`-`z`, is `con`, `prn`, `aux`, `nul`, `com1`-`com9`, `lpt1`-`lpt9`, or `com`/`lpt` followed by `¹` `²` `³` |
| 2 | `forbidden-char` | error | windows | the name holds one of `<` `>` `:` `"` `\` `|` `?` `*`, or a character from U+0000 to U+001F |
| 3 | `trailing-dot-space` | error | windows | the name ends in `.` or in a space (U+0020) |
| 4 | `path-too-long` | warn | windows | the whole path is **more than** the limit, in UTF-16 code units |
| 5 | `case-collision` | error | windows, macos | a sibling's name differs from it only in case |
| 6 | `normalization-collision` | error | macos | a sibling's name differs from it only in Unicode normalization |
| 7 | `file-folder-collision` | error | windows, macos | a sibling of the same key is a folder and one is a file |

Rule 1: `aux`, `AUX.py`, `Con.tar.gz`, `lpt3.txt`, `COM².log` and `aux.py.bak` are findings;
`console.py`, `COM10`, `COM0`, `x.aux`, `.aux`, `aux_1.py`, `CONIN$`, `CONOUT$` and `CLOCK$` are not.

Rule 4: a character above U+FFFF counts 2, any other character 1, each `/` counts 1. A path of exactly
the limit is not a finding. Every path is measured on its own, so a folder and the files below it can
all be findings. The limit is `--max-path`, 260 by default.

**Collisions (rules 5 to 7).** Only *siblings* (paths with the same parent) are compared; `Docs/a.md`
and `docs/a.md` are not compared with each other, though the folders `Docs` and `docs` are. The *key*
of a name is `unicodedata.normalize("NFC", name).casefold()`; siblings with the same key are a *group*.
A group has one rule: `file-folder-collision` if it holds a folder and a file; otherwise
`case-collision` if the names are not all the same after NFC; otherwise `normalization-collision`.
The group's paths are put in order, compared code point by code point; the **first is kept** and
every other path of the group is one finding whose `with` is the kept path. So `README.md` and
`readme.md` are one finding, on `readme.md`, with `README.md`. `casefold()` is a deliberate over-reach:
`ß` and `ss` are the same key.

## Options

| option | meaning |
|---|---|
| `folder` | the root of the tree to walk; default `.`; at most one; a symbolic link to a folder is fine |
| `--stdin` | read the paths from standard input; cannot be given with a `folder` |
| `-z` | with `--stdin`, paths are separated by NUL bytes instead of newlines; without `--stdin` it is a usage error |
| `--max-path <n>` | the longest path allowed, in UTF-16 code units; digits only, at least 1 (`007` is 7); default 260; once |
| `--fail-on <level>` | `error` (default), `warn` or `none`; sets the exit code; once |
| `--json` | print the JSON document instead of the plain form |

`--stdin`, `-z` and `--json` may be repeated. An option's value is always the next argument,
whatever it looks like; `--max-path=5` is not a form. Arguments may come in any order. There is no
other option and no `--help`.

## Output

**Plain.** One line per finding, then one summary line. Findings are ordered by path (code point by
code point), then by rule number.

    <path>: <severity> <rule>
    <path>: <severity> <rule> (with <other>)
    paths: <p>; errors: <e>; warnings: <w>

Control characters U+0000 to U+001F in a path are shown as `\xNN` (two lowercase hex digits; a tab is
`\x09`), so a finding is always one line. With no path at all, or no finding, the output is only the
summary line, for example `paths: 0; errors: 0; warnings: 0`.

**`--json`.** One JSON document, then a newline:

```json
{"tool": "portable-names", "version": "0.1.0", "paths": 6, "errors": 3, "warnings": 0,
 "findings": [
  {"path": "aux.py", "rule": "reserved-name", "severity": "error", "platforms": ["windows"], "with": null},
  {"path": "src/name.txt", "rule": "case-collision", "severity": "error", "platforms": ["windows", "macos"], "with": "src/Name.txt"}
 ]}
```

(The real document is on one line.) `path` and `with` hold the real characters; `with` is `null` for
rules 1 to 4. With no path the findings list is `[]`.

Output is UTF-8 whatever the locale. Nothing is written to stderr on success.

## Exit codes

| code | meaning |
|---|---|
| `0` | no finding at or above the `--fail-on` level (always with `--fail-on none`) |
| `1` | at least one finding at or above the level: `error` means an error; `warn` means a warning or an error |
| `2` | a usage error: a message on stderr, nothing on stdout |

Usage errors: an unknown option (any other argument starting with `-`, a lone `-` included), a
missing option value, a second folder, `--stdin` with a folder, `-z` without `--stdin`, a bad or
repeated `--max-path` or `--fail-on`, a folder that is not an existing folder, an invalid path in the
list (the message names its position), a path or file name that is not valid UTF-8, a folder that
cannot be listed. They are found before anything is written to stdout.

## In CI

```yaml
- uses: actions/checkout@v4
- run: git ls-files -z | pipx run --spec git+https://github.com/tick-ai/portable-names portable-names --stdin -z
```

Use `--fail-on warn` to fail on long paths too, or `--max-path 200` to leave room for a long clone
path. Walking a checkout (`portable-names .`) also works, but `git ls-files` judges exactly what is
tracked.

## What it does not do

- It does not open, read or change any file, and does not judge file contents or types.
- It does not flag names that are only unusual: spaces inside, non-ASCII letters, a leading dot, `~`,
  `$`, `#`, `%`.
- It does not flag names Windows treats specially that are not in rule 1 (`CONIN$`, `COM0`, `aux_1`).
- It does not measure a name alone, only the whole path, and does not flag a path that is long on
  disk but not over the limit.
- It does not compare names that are not siblings, and it ignores duplicates in a list.
- It does not look inside skipped folders or below symbolic links.
- It does not know the machine where the checkout will be: how long its clone path is, or whether long
  paths or a case-sensitive volume are enabled there. It judges the paths by the rules above and
  nothing else.

## Where it came from

Built by agents on TickHub, as TickHub job `a73eee84-5c6f-46d8-a9a2-fd0a0e9fd530`:
https://tick.company/hub/#/job/a73eee84-5c6f-46d8-a9a2-fd0a0e9fd530. The job, the hand-ins and the
receipt are on TickHub's public log. `docs/the-job.md` is the job as it was given.

AI does the work. Tick makes it trustworthy. https://tick.company

## Licence

Apache-2.0. Copyright 2026 Parsa Esmaeili. See `LICENSE`.
