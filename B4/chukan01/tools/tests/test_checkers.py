from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import check_format as fmt
import check_terminology as terms


class FormatSamples(unittest.TestCase):
    def test_samples(self):
        samples = json.loads((Path(__file__).parent / "format_cases.json").read_text())
        for case in samples:
            with self.subTest(case=case["name"]):
                result = fmt.inspect_source(case["source"])
                for severity, key in [("ERROR", "errors"), ("WARNING", "warnings")]:
                    self.assertEqual(sorted(d.rule for d in result if d.severity == severity), sorted(case[key]))

    def test_offsets_and_output(self):
        source = "一行目．\n二行目、説明。"
        d = fmt.inspect_source(source)[0]
        self.assertIn("sample.tex:2: PUNCT001 ERROR: 、", d.format(Path("sample.tex"), source))
        self.assertTrue(d.suggestion)

    def test_malformed_source(self):
        for s in ["$unfinished", r"\caption{unfinished", r"\begin{equation}unfinished"]:
            with self.subTest(s=s), self.assertRaises(fmt.TexError):
                fmt.inspect_source(s)

    def test_cli_codes_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for source, expected in [("正しい本文．", 0), ("本文、説明。", 1), ("Fig. 3", 0), ("$unfinished", 2)]:
                f = p / "main.tex"
                f.write_text(source)
                r = subprocess.run([sys.executable, str(TOOLS / "check_format.py"), str(f)], capture_output=True)
                self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
            (p / "main.tex").write_text("正しい本文．")
            (p / "build").mkdir()
            (p / "build" / "bad.tex").write_text("本文、。")
            files = terms.collect_tex_files([p, p / "main.tex"])
            self.assertEqual(len(files), 1)
            for target in [p / "absent.tex", p / "empty"]:
                if target.name == "empty":
                    target.mkdir()
                r = subprocess.run([sys.executable, str(TOOLS / "check_format.py"), str(target)], capture_output=True)
                self.assertEqual(r.returncode, 2)
            invalid = p / "invalid.tex"
            invalid.write_bytes(b"\xff\xfe")
            r = subprocess.run([sys.executable, str(TOOLS / "check_format.py"), str(invalid)], capture_output=True)
            self.assertEqual(r.returncode, 2)


class ExistingTerminology(unittest.TestCase):
    def test_dictionary_and_masking_contract(self):
        rules = terms.load_dictionary(terms.DEFAULT_RULES)
        source = "% Engine\n$Engine$ \\cite{Engine} \\label{Engine} \\url{Engine}\nEngine"
        visible = terms.searchable_text(source, rules)
        self.assertEqual(visible.count("Engine"), 1)
        self.assertEqual(visible.count("\n"), source.count("\n"))

    def test_existing_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.tex"
            for text, expected in [("通常の本文", 0), ("Engine", 1), ("テンセグリティ", 0)]:
                p.write_text(text)
                r = subprocess.run([sys.executable, str(TOOLS / "check_terminology.py"), str(p)], capture_output=True)
                self.assertEqual(r.returncode, expected)
            r = subprocess.run([sys.executable, str(TOOLS / "check_terminology.py"), str(p.parent / "missing")], capture_output=True)
            self.assertEqual(r.returncode, 2)

    def test_combined_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "main.tex"
            for text, expected in [("通常の本文．", 0), ("本文、。", 1), ("Engine", 1), ("$unfinished", 2)]:
                p.write_text(text)
                r = subprocess.run([sys.executable, str(TOOLS / "check_all.py"), str(p)], capture_output=True)
                self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
                self.assertIn(b"check_terminology.py", r.stdout)
                self.assertIn(b"check_format.py", r.stdout)


if __name__ == "__main__":
    unittest.main()
