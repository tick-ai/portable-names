"""Tests for portable_names.py: the tool is run as a child process, as a user runs it."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "portable_names.py"


def run(args: list[str], stdin: bytes = b"", cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        input=stdin,
        capture_output=True,
        cwd=cwd,
        timeout=60,
    )


def lines(paths: list[str], sep: str = "\n") -> bytes:
    return "".join(p + sep for p in paths).encode("utf-8")


def plain(paths: list[str], *extra: str) -> list[str]:
    """Run --stdin on a list and return the stdout lines."""
    res = run(["--stdin", *extra], lines(paths))
    assert res.returncode in (0, 1), res.stderr
    return res.stdout.decode("utf-8").splitlines()


class ListCase(unittest.TestCase):
    def findings(self, paths: list[str], *extra: str) -> list[str]:
        return plain(paths, *extra)[:-1]


class ExampleTests(ListCase):
    EXAMPLE = ["aux.py", "src/Name.txt", "src/name.txt", "docs/a:b.md"]

    def test_job_example(self) -> None:
        res = run(["--stdin"], lines(self.EXAMPLE))
        self.assertEqual(
            res.stdout.decode(),
            "aux.py: error reserved-name\n"
            "docs/a:b.md: error forbidden-char\n"
            "src/name.txt: error case-collision (with src/Name.txt)\n"
            "paths: 6; errors: 3; warnings: 0\n",
        )
        self.assertEqual(res.returncode, 1)
        self.assertEqual(res.stderr, b"")

    def test_job_example_json(self) -> None:
        res = run(["--stdin", "--json"], lines(self.EXAMPLE))
        self.assertTrue(res.stdout.endswith(b"}\n"))
        self.assertEqual(
            json.loads(res.stdout),
            {
                "tool": "portable-names",
                "version": "0.1.0",
                "paths": 6,
                "errors": 3,
                "warnings": 0,
                "findings": [
                    {"path": "aux.py", "rule": "reserved-name", "severity": "error", "platforms": ["windows"], "with": None},
                    {"path": "docs/a:b.md", "rule": "forbidden-char", "severity": "error", "platforms": ["windows"], "with": None},
                    {"path": "src/name.txt", "rule": "case-collision", "severity": "error", "platforms": ["windows", "macos"], "with": "src/Name.txt"},
                ],
            },
        )


class ReservedTests(ListCase):
    def test_reserved(self) -> None:
        names = ["aux", "AUX.py", "Con.tar.gz", "lpt3.txt", "COM².log", "aux.py.bak", "NuL", "prn", "COM9", "lpt¹", "com³.x"]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.findings([name]), [f"{name}: error reserved-name"])

    def test_not_reserved(self) -> None:
        names = ["console.py", "COM10", "COM0", "x.aux", ".aux", "aux_1.py", "CONIN$", "CONOUT$", "CLOCK$", "LPT0", "au", "ａux"]
        for name in names:
            with self.subTest(name=name):
                out = self.findings([name])
                self.assertFalse(any("reserved-name" in line for line in out), out)

    def test_aux_space_is_trailing_not_reserved(self) -> None:
        self.assertEqual(self.findings(["aux "]), ["aux : error trailing-dot-space"])

    def test_folder_is_one_finding(self) -> None:
        self.assertEqual(self.findings(["aux/a.txt", "aux/b.txt"]), ["aux: error reserved-name"])

    def test_only_the_name_is_judged(self) -> None:
        self.assertEqual(self.findings(["aux/x/y.txt"]), ["aux: error reserved-name"])


class ForbiddenTests(ListCase):
    def test_each_forbidden_char(self) -> None:
        for ch in '<>:"\\|?*':
            with self.subTest(ch=ch):
                self.assertEqual(self.findings([f"a{ch}b"]), [f"a{ch}b: error forbidden-char"])

    def test_once_per_path(self) -> None:
        self.assertEqual(self.findings(["a<>:b"]), ["a<>:b: error forbidden-char"])

    def test_control_chars(self) -> None:
        self.assertEqual(self.findings(["a\tb"]), ["a\\x09b: error forbidden-char"])
        self.assertEqual(self.findings(["a\x01b", "c\x1fd"]), ["a\\x01b: error forbidden-char", "c\\x1fd: error forbidden-char"])

    def test_not_forbidden(self) -> None:
        for name in ["a\x7fb", "café", "a b", "~$#%", "«»"]:
            with self.subTest(name=name):
                self.assertEqual(self.findings([name]), [])

    def test_backslash_is_not_a_separator(self) -> None:
        self.assertEqual(plain(["a\\b"]), ["a\\b: error forbidden-char", "paths: 1; errors: 1; warnings: 0"])

    def test_nul_in_newline_mode(self) -> None:
        res = run(["--stdin"], b"a\x00b\n")
        self.assertEqual(res.stdout.decode(), "a\\x00b: error forbidden-char\npaths: 1; errors: 1; warnings: 0\n")

    def test_newline_in_nul_mode(self) -> None:
        res = run(["--stdin", "-z"], b"a\nb\0")
        self.assertEqual(res.stdout.decode(), "a\\x0ab: error forbidden-char\npaths: 1; errors: 1; warnings: 0\n")

    def test_carriage_return_kept(self) -> None:
        res = run(["--stdin"], b"a.txt\r\n")
        self.assertEqual(res.stdout.decode(), "a.txt\\x0d: error forbidden-char\npaths: 1; errors: 1; warnings: 0\n")


class TrailingTests(ListCase):
    def test_trailing(self) -> None:
        self.assertEqual(self.findings(["a."]), ["a.: error trailing-dot-space"])
        self.assertEqual(self.findings(["a "]), ["a : error trailing-dot-space"])
        self.assertEqual(self.findings(["x/a.b./c"]), ["x/a.b.: error trailing-dot-space"])

    def test_not_trailing(self) -> None:
        for name in [".a", " a", "a ", "a b", ".gitignore"]:
            with self.subTest(name=name):
                self.assertEqual(self.findings([name]), [])

    def test_two_rules_one_path(self) -> None:
        self.assertEqual(self.findings(["a:b."]), ["a:b.: error forbidden-char", "a:b.: error trailing-dot-space"])
        self.assertEqual(self.findings(["con."]), ["con.: error reserved-name", "con.: error trailing-dot-space"])


class LengthTests(ListCase):
    def test_limit_default(self) -> None:
        over = "a" * 261
        self.assertEqual(self.findings(["a" * 260]), [])
        self.assertEqual(self.findings([over]), [f"{over}: warn path-too-long"])

    def test_max_path_option(self) -> None:
        self.assertEqual(self.findings(["abcde"], "--max-path", "5"), [])
        self.assertEqual(self.findings(["abcdef"], "--max-path", "5"), ["abcdef: warn path-too-long"])
        self.assertEqual(self.findings(["abcdefg"], "--max-path", "007"), [])
        self.assertEqual(self.findings(["abcdefgh"], "--max-path", "007"), ["abcdefgh: warn path-too-long"])

    def test_separators_count(self) -> None:
        self.assertEqual(self.findings(["ab/cd"], "--max-path", "4"), ["ab/cd: warn path-too-long"])
        self.assertEqual(self.findings(["ab/cd"], "--max-path", "5"), [])

    def test_utf16_units(self) -> None:
        astral = "\U0001F600"
        self.assertEqual(self.findings([astral * 2], "--max-path", "4"), [])
        self.assertEqual(self.findings([astral * 2], "--max-path", "3"), [f"{astral * 2}: warn path-too-long"])
        self.assertEqual(self.findings(["é" * 3], "--max-path", "3"), [])

    def test_folder_and_files_each(self) -> None:
        self.assertEqual(
            self.findings(["abc/de"], "--max-path", "2"),
            ["abc: warn path-too-long", "abc/de: warn path-too-long"],
        )

    def test_warn_counts(self) -> None:
        self.assertEqual(plain(["abcdef"], "--max-path", "5")[-1], "paths: 1; errors: 0; warnings: 1")


class CollisionTests(ListCase):
    def test_case(self) -> None:
        self.assertEqual(self.findings(["README.md", "readme.md"]), ["readme.md: error case-collision (with README.md)"])

    def test_order_of_arrival_is_irrelevant(self) -> None:
        self.assertEqual(self.findings(["readme.md", "README.md"]), ["readme.md: error case-collision (with README.md)"])

    def test_group_of_three(self) -> None:
        self.assertEqual(
            self.findings(["a.txt", "A.txt", "A.TXT"]),
            ["A.txt: error case-collision (with A.TXT)", "a.txt: error case-collision (with A.TXT)"],
        )

    def test_normalization(self) -> None:
        nfc, nfd = "café", "café"
        # "e" (U+0065) sorts before "\u00e9" (U+00E9), so the decomposed name is the one kept.
        self.assertEqual(self.findings([nfc, nfd]), [f"{nfc}: error normalization-collision (with {nfd})"])

    def test_case_and_normalization_is_case(self) -> None:
        a, b = "CAFÉ", "café"
        self.assertEqual(self.findings([a, b]), [f"{b}: error case-collision (with {a})"])

    def test_sharp_s(self) -> None:
        self.assertEqual(self.findings(["straße", "strasse"]), ["straße: error case-collision (with strasse)"])

    def test_file_folder(self) -> None:
        self.assertEqual(self.findings(["Docs", "docs/a.md"]), ["docs: error file-folder-collision (with Docs)"])

    def test_file_folder_kept_is_first_even_if_file(self) -> None:
        self.assertEqual(self.findings(["a/x", "A"]), ["a: error file-folder-collision (with A)"])

    def test_file_folder_rule_covers_every_other_member(self) -> None:
        # Group {B (file), b (folder), b (same name is one path)}: only b is a finding.
        self.assertEqual(self.findings(["B", "b/x"]), ["b: error file-folder-collision (with B)"])

    def test_folders_and_a_file(self) -> None:
        out = self.findings(["a/x", "A/x", "b/x", "B"])
        self.assertEqual(out, ["a: error case-collision (with A)", "b: error file-folder-collision (with B)"])

    def test_two_folders_case(self) -> None:
        self.assertEqual(self.findings(["Docs/a.md", "docs/a.md"]), ["docs: error case-collision (with Docs)"])

    def test_not_siblings(self) -> None:
        self.assertEqual(self.findings(["x/a", "y/A"]), [])
        self.assertEqual(self.findings(["Docs/a.md", "docs/b.md"]), ["docs: error case-collision (with Docs)"])

    def test_duplicates_in_list(self) -> None:
        self.assertEqual(run(["--stdin"], b"a.txt\na.txt\n").stdout.decode(), "paths: 1; errors: 0; warnings: 0\n")

    def test_collision_json_platforms(self) -> None:
        nfc, nfd = "café", "café"
        doc = json.loads(run(["--stdin", "--json"], lines([nfc, nfd])).stdout)
        self.assertEqual(doc["findings"][0]["platforms"], ["macos"])
        self.assertEqual(doc["findings"][0]["path"], nfc)
        self.assertEqual(doc["findings"][0]["with"], nfd)
        doc = json.loads(run(["--stdin", "--json"], lines(["a", "A/b"])).stdout)
        self.assertEqual(doc["findings"][0]["rule"], "file-folder-collision")
        self.assertEqual(doc["findings"][0]["platforms"], ["windows", "macos"])


class ImpliedFolderTests(ListCase):
    def test_implied_folders_counted(self) -> None:
        self.assertEqual(plain(["a/b/c.txt"]), ["paths: 3; errors: 0; warnings: 0"])

    def test_bad_folder_is_one_finding(self) -> None:
        out = plain(["aux/a.txt", "aux/b/c.txt"])
        self.assertEqual(out, ["aux: error reserved-name", "paths: 4; errors: 1; warnings: 0"])

    def test_long_folder_is_judged_on_its_own(self) -> None:
        self.assertEqual(self.findings(["abcde/f"], "--max-path", "5"), ["abcde/f: warn path-too-long"])
        self.assertEqual(
            self.findings(["abcdef/g"], "--max-path", "5"),
            ["abcdef: warn path-too-long", "abcdef/g: warn path-too-long"],
        )


class OrderTests(ListCase):
    def test_order_by_path_then_rule(self) -> None:
        self.assertEqual(
            self.findings(["z:", "B", "a.", "b", "con.txt", "A"]),
            [
                "a.: error trailing-dot-space",
                "b: error case-collision (with B)",
                "con.txt: error reserved-name",
                "z:: error forbidden-char",
            ],
        )

    def test_code_point_order(self) -> None:
        out = self.findings(["b:", "Z:", "\u00e9:", "a:"])
        self.assertEqual([line.split(":")[0] for line in out], ["Z", "a", "b", "é"])

    def test_rule_order_on_one_path(self) -> None:
        res = run(["--stdin", "--json", "--max-path", "3"], lines(["aux.:."]))
        rules = [f["rule"] for f in json.loads(res.stdout)["findings"]]
        self.assertEqual(rules, ["reserved-name", "forbidden-char", "trailing-dot-space", "path-too-long"])

    def test_folder_before_its_content(self) -> None:
        out = self.findings(["a/b", "a-b", "a b"], "--max-path", "1")
        self.assertEqual([line.split(":")[0] for line in out], ["a b", "a-b", "a/b"])


class EmptyTests(unittest.TestCase):
    EMPTY = "paths: 0; errors: 0; warnings: 0\n"

    def test_empty_input(self) -> None:
        for args in (["--stdin"], ["--stdin", "-z"]):
            res = run(args, b"")
            self.assertEqual((res.stdout.decode(), res.returncode), (self.EMPTY, 0))

    def test_empty_json(self) -> None:
        res = run(["--stdin", "--json"], b"")
        self.assertEqual(
            json.loads(res.stdout),
            {"tool": "portable-names", "version": "0.1.0", "paths": 0, "errors": 0, "warnings": 0, "findings": []},
        )
        self.assertTrue(res.stdout.endswith(b"\n"))

    def test_empty_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            res = run([tmp])
            self.assertEqual((res.stdout.decode(), res.returncode), (self.EMPTY, 0))

    def test_clean_list_is_one_line(self) -> None:
        res = run(["--stdin"], b"a/b.txt\nc.txt\n")
        self.assertEqual((res.stdout.decode(), res.returncode), ("paths: 3; errors: 0; warnings: 0\n", 0))
        res = run(["--stdin", "--json"], b"a/b.txt\n")
        self.assertEqual(json.loads(res.stdout)["findings"], [])
        self.assertEqual(json.loads(res.stdout)["paths"], 2)


class StdinTests(unittest.TestCase):
    def test_no_trailing_separator(self) -> None:
        self.assertEqual(run(["--stdin"], b"a\nb").stdout.decode(), "paths: 2; errors: 0; warnings: 0\n")

    def test_only_one_trailing_separator_dropped(self) -> None:
        res = run(["--stdin"], b"a\n\n")
        self.assertEqual((res.returncode, res.stdout), (2, b""))

    def test_lone_newline_is_empty_path(self) -> None:
        res = run(["--stdin"], b"\n")
        self.assertEqual((res.returncode, res.stdout), (2, b""))
        self.assertIn(b"1", res.stderr)

    def test_nul_mode(self) -> None:
        self.assertEqual(run(["--stdin", "-z"], lines(["a b", "c/d"], "\0")).stdout.decode(), "paths: 3; errors: 0; warnings: 0\n")
        self.assertEqual(run(["--stdin", "-z"], b"a\0b").stdout.decode(), "paths: 2; errors: 0; warnings: 0\n")
        self.assertEqual(run(["--stdin", "-z"], b"\0").returncode, 2)

    def test_newline_is_not_a_separator_with_z(self) -> None:
        self.assertEqual(run(["--stdin", "-z"], b"a\nb\0").stdout.decode().splitlines()[-1], "paths: 1; errors: 1; warnings: 0")

    def test_invalid_paths(self) -> None:
        for path in ["", "/abs", "a//b", "a/", "./a", "a/./b", "..", "a/../b", ".", "a/..", "//", "/"]:
            with self.subTest(path=path):
                res = run(["--stdin"], f"ok\n{path}\n".encode())
                self.assertEqual((res.returncode, res.stdout), (2, b""))
                self.assertIn(b"2", res.stderr)

    def test_position_named(self) -> None:
        res = run(["--stdin"], b"a\nb\nc\n/d\ne\n")
        self.assertEqual((res.returncode, res.stdout), (2, b""))
        self.assertIn(b"4", res.stderr)

    def test_dots_inside_names_are_fine(self) -> None:
        res = run(["--stdin"], b"...\n..a\na..\n.a\n")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(
            res.stdout.decode().splitlines(),
            ["...: error trailing-dot-space", "a..: error trailing-dot-space", "paths: 4; errors: 2; warnings: 0"],
        )

    def test_non_utf8(self) -> None:
        for data in (b"a\xff\n", b"ok\n\xc3\n", b"\xed\xa0\x80\n"):
            with self.subTest(data=data):
                res = run(["--stdin"], data)
                self.assertEqual((res.returncode, res.stdout), (2, b""))
        res = run(["--stdin", "-z"], b"a\xff\0")
        self.assertEqual((res.returncode, res.stdout), (2, b""))

    def test_nothing_is_trimmed(self) -> None:
        res = run(["--stdin"], b" a\nb \n")
        self.assertEqual(res.stdout.decode(), "b : error trailing-dot-space\npaths: 2; errors: 1; warnings: 0\n")

    def test_git_quoting_not_undone(self) -> None:
        res = run(["--stdin", "--json"], '"a\\303\\251.txt"\n'.encode())
        self.assertEqual(json.loads(res.stdout)["findings"][0]["path"], '"a\\303\\251.txt"')

    def test_json_has_real_characters(self) -> None:
        res = run(["--stdin", "--json"], "a\tb\n".encode())
        self.assertEqual(json.loads(res.stdout)["findings"][0]["path"], "a\tb")

    def test_output_is_utf8_whatever_the_locale(self) -> None:
        env = dict(os.environ, LC_ALL="C", PYTHONUTF8="0", PYTHONIOENCODING="ascii")
        res = subprocess.run(
            [sys.executable, str(TOOL), "--stdin"], input="é\U0001F600:\n".encode(), capture_output=True, env=env
        )
        self.assertEqual(
            res.stdout.decode("utf-8"), "é\U0001F600:: error forbidden-char\npaths: 1; errors: 1; warnings: 0\n"
        )


class FolderTests(unittest.TestCase):
    def make(self, tmp: str, files: list[str], dirs: tuple[str, ...] = ()) -> None:
        for d in dirs:
            os.makedirs(os.path.join(tmp, d), exist_ok=True)
        for f in files:
            full = os.path.join(tmp, f)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            Path(full).write_text("x")

    def test_walk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["aux.py", "src/Name.txt", "src/name.txt", "docs/a.md"], ("empty/deeper",))
            res = run([tmp])
            self.assertEqual(res.returncode, 1)
            self.assertEqual(
                res.stdout.decode().splitlines(),
                [
                    "aux.py: error reserved-name",
                    "src/name.txt: error case-collision (with src/Name.txt)",
                    "paths: 8; errors: 2; warnings: 0",
                ],
            )

    def test_default_folder_is_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["con.txt"])
            res = run([], cwd=tmp)
            self.assertEqual(res.stdout.decode(), "con.txt: error reserved-name\npaths: 1; errors: 1; warnings: 0\n")

    def test_skipped_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for skipped in [".git", ".hg", ".svn", "node_modules", ".venv", "__pycache__"]:
                self.make(tmp, [f"{skipped}/aux.txt", f"sub/{skipped}/aux.txt"])
            res = run([tmp])
            self.assertEqual((res.stdout.decode(), res.returncode), ("paths: 1; errors: 0; warnings: 0\n", 0))

    def test_files_and_links_with_skipped_names_are_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, [".git", "x/node_modules"])
            os.symlink("x", os.path.join(tmp, "__pycache__"))
            self.assertEqual(json.loads(run([tmp, "--json"]).stdout)["paths"], 4)

    def test_root_named_like_a_skipped_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, ".git")
            self.make(root, ["a.txt"])
            self.assertEqual(run([root]).stdout.decode(), "paths: 1; errors: 0; warnings: 0\n")

    def test_symlinks_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["real/aux.txt"])
            os.symlink("real", os.path.join(tmp, "link"))
            os.symlink("nowhere", os.path.join(tmp, "dangling"))
            doc = json.loads(run([tmp, "--json"]).stdout)
            self.assertEqual(doc["paths"], 4)
            self.assertEqual([f["path"] for f in doc["findings"]], ["real/aux.txt"])

    def test_symlink_to_folder_is_a_file_for_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["real/x.txt"])
            os.symlink("real", os.path.join(tmp, "LINK"))
            os.makedirs(os.path.join(tmp, "link"))
            res = run([tmp])
            self.assertEqual(res.stdout.decode().splitlines()[0], "link: error file-folder-collision (with LINK)")

    def test_symlink_root_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["real/a.txt"])
            os.symlink("real", os.path.join(tmp, "link"))
            res = run([os.path.join(tmp, "link")])
            self.assertEqual(res.stdout.decode(), "paths: 1; errors: 0; warnings: 0\n")

    def test_bad_folder_on_disk_is_one_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["aux/a.txt", "aux/b.txt", "A\tB.txt"])
            self.assertEqual(
                run([tmp]).stdout.decode().splitlines(),
                ["A\\x09B.txt: error forbidden-char", "aux: error reserved-name", "paths: 4; errors: 2; warnings: 0"],
            )

    def test_long_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["abc/de.txt"])
            res = run([tmp, "--max-path", "6"])
            self.assertEqual(res.stdout.decode().splitlines()[0], "abc/de.txt: warn path-too-long")
            self.assertEqual(res.returncode, 0)

    def test_non_utf8_name_is_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                Path(os.fsdecode(os.path.join(os.fsencode(tmp), b"bad\xff"))).write_text("")
            except OSError:
                self.skipTest("the file system refuses non UTF-8 names")
            res = run([tmp])
            self.assertEqual((res.returncode, res.stdout), (2, b""))
            self.assertTrue(res.stderr)

    def test_non_utf8_name_in_skipped_folder_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".git"))
            try:
                Path(os.fsdecode(os.path.join(os.fsencode(tmp), b".git", b"bad\xff"))).write_text("")
            except OSError:
                self.skipTest("the file system refuses non UTF-8 names")
            self.assertEqual(run([tmp]).returncode, 0)

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs a non-root POSIX user")
    def test_unlistable_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["locked/a.txt"])
            locked = os.path.join(tmp, "locked")
            os.chmod(locked, 0)
            try:
                res = run([tmp])
            finally:
                os.chmod(locked, 0o700)
            self.assertEqual((res.returncode, res.stdout), (2, b""))

    def test_folder_and_list_agree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["a/CON.txt", "a/b/c.txt"])
            walked = json.loads(run([tmp, "--json"]).stdout)
            listed = json.loads(run(["--stdin", "--json"], b"a/CON.txt\na/b/c.txt\n").stdout)
            self.assertEqual(walked, listed)


class OptionTests(unittest.TestCase):
    def usage(self, args: list[str], stdin: bytes = b"a\n") -> None:
        res = run(args, stdin)
        self.assertEqual(res.returncode, 2, args)
        self.assertEqual(res.stdout, b"", args)
        self.assertTrue(res.stderr.strip(), args)

    def test_usage_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "f.txt")
            Path(file_path).write_text("x")
            cases = [
                ["--help"],
                ["-h"],
                ["-"],
                ["-x"],
                ["--max-path=5"],
                ["--stdin", "--max-path"],
                ["--stdin", "--fail-on"],
                [tmp, tmp],
                ["--stdin", tmp],
                ["-z"],
                ["-z", tmp],
                ["--stdin", "--max-path", "0"],
                ["--stdin", "--max-path", "000"],
                ["--stdin", "--max-path", "-1"],
                ["--stdin", "--max-path", "+5"],
                ["--stdin", "--max-path", "5.0"],
                ["--stdin", "--max-path", ""],
                ["--stdin", "--max-path", "abc"],
                ["--stdin", "--max-path", "٥"],
                ["--stdin", "--max-path", "5", "--max-path", "5"],
                ["--stdin", "--fail-on", "warning"],
                ["--stdin", "--fail-on", "ERROR"],
                ["--stdin", "--fail-on", ""],
                ["--stdin", "--fail-on", "warn", "--fail-on", "warn"],
                [os.path.join(tmp, "missing")],
                [file_path],
                [""],
                ["--stdin", "--max-path", "--stdin"],
            ]
            for args in cases:
                with self.subTest(args=args):
                    self.usage(args)

    def test_value_is_the_next_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            res = run(["--max-path", "5", "--fail-on", "none", tmp, "--json"])
            self.assertEqual(res.returncode, 0)
            res = run(["--stdin", "--fail-on", "--json"], b"a\n")
            self.assertEqual(res.returncode, 2)

    def test_any_order(self) -> None:
        res = run(["--json", "-z", "--fail-on", "none", "--max-path", "3", "--stdin"], b"abcd\0")
        self.assertEqual(json.loads(res.stdout)["warnings"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "abcd").write_text("")
            self.assertEqual(run(["--max-path", "3", tmp, "--fail-on", "warn"]).returncode, 1)

    def test_repeatable_flags(self) -> None:
        res = run(["--stdin", "--stdin", "-z", "-z", "--json", "--json"], b"a\0")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(json.loads(res.stdout)["paths"], 1)

    def test_huge_max_path(self) -> None:
        self.assertEqual(run(["--stdin", "--max-path", "9" * 5000], b"a\n").returncode, 0)

    def test_usage_error_comes_before_any_output(self) -> None:
        res = run(["--stdin", "--json"], b"aux\n/bad\n")
        self.assertEqual((res.returncode, res.stdout), (2, b""))

    def test_main_takes_argv(self) -> None:
        sys.path.insert(0, str(TOOL.parent))
        try:
            import portable_names
        finally:
            sys.path.pop(0)
        self.assertEqual(portable_names.main(["-x"]), 2)


class ExitCodeTests(unittest.TestCase):
    def code(self, paths: list[str], *extra: str) -> int:
        return run(["--stdin", *extra], lines(paths)).returncode

    def test_error_finding(self) -> None:
        self.assertEqual(self.code(["aux"]), 1)
        self.assertEqual(self.code(["aux"], "--fail-on", "error"), 1)
        self.assertEqual(self.code(["aux"], "--fail-on", "warn"), 1)
        self.assertEqual(self.code(["aux"], "--fail-on", "none"), 0)

    def test_warn_finding(self) -> None:
        self.assertEqual(self.code(["abcdef"], "--max-path", "3"), 0)
        self.assertEqual(self.code(["abcdef"], "--max-path", "3", "--fail-on", "error"), 0)
        self.assertEqual(self.code(["abcdef"], "--max-path", "3", "--fail-on", "warn"), 1)
        self.assertEqual(self.code(["abcdef"], "--max-path", "3", "--fail-on", "none"), 0)

    def test_clean(self) -> None:
        for level in ("error", "warn", "none"):
            self.assertEqual(self.code(["ok.txt"], "--fail-on", level), 0)

    def test_json_follows_fail_on(self) -> None:
        self.assertEqual(self.code(["aux"], "--json"), 1)
        self.assertEqual(self.code(["aux"], "--json", "--fail-on", "none"), 0)

    def test_nothing_on_stderr_on_success(self) -> None:
        self.assertEqual(run(["--stdin"], b"aux\n").stderr, b"")


class SourceShapeTests(unittest.TestCase):
    def test_first_line_and_main(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "#!/usr/bin/env python3")
        self.assertTrue(text.rstrip().endswith('if __name__ == "__main__":\n    raise SystemExit(main())'))

    def test_stdlib_imports_and_type_hints(self) -> None:
        tree = ast.parse(TOOL.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], sys.stdlib_module_names)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0], sys.stdlib_module_names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.assertIsNotNone(node.returns, node.name)
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    if arg.arg not in ("self", "cls"):
                        self.assertIsNotNone(arg.annotation, f"{node.name}({arg.arg})")


if __name__ == "__main__":
    unittest.main()
