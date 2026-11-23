from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import check_format as fmt
import check_references as refs


class FloatReferences(unittest.TestCase):
    floats = (r"\begin{figure}\caption{Antenna}\label{fig:model}\end{figure}"
              r"\begin{table}\caption{Numbers}\label{table:counts}\end{table}")

    def diagnostics(self, text):
        return [d.rule for d in fmt.inspect_source(text + "\n" + self.floats)
                if d.rule.startswith("REF")]

    def test_linked_figure_and_table_references(self):
        self.assertEqual(self.diagnostics(r"形状をFig.~\ref{fig:model}，諸元をTable~\ref{table:counts}に示す．"), [])

    def test_wrong_reference_prefix_or_spacing(self):
        for text in (r"表\ref{table:counts}", r"表 \ref{table:counts}", r"図\ref{fig:model}",
                     r"図 \ref{fig:model}", r"写真\ref{fig:model}", r"画像\ref{fig:model}",
                     r"Figure~\ref{fig:model}", r"Fig~\ref{fig:model}", r"Table \ref{table:counts}",
                     r"Fig.~\ref{table:counts}", r"\autoref{fig:model}", r"\ref{fig:model}"):
            with self.subTest(text=text):
                self.assertEqual(self.diagnostics(text), ["REF002"])

    def test_unresolved_or_non_float_label(self):
        for text in (r"Fig.~\ref{fig:absent}", r"Table~\ref{missing}",
                     r"Fig.~\ref{sec:intro}\section{Introduction}\label{sec:intro}"):
            with self.subTest(text=text):
                self.assertEqual(self.diagnostics(text), ["REF003"])

    def test_directly_written_float_numbers(self):
        for text in ("図 2", "表3", "画像1", "写真1", "Fig 2", "Figure 2", "Fig. 2", "Table 3"):
            with self.subTest(text=text):
                self.assertEqual(self.diagnostics(text), ["REF001"])

    def test_generic_words_and_unrelated_references(self):
        self.assertEqual(self.diagnostics(r"図表を比較し，図と表を示す．画像を取得し写真を撮る．"
                                          r"発表2回．第\ref{sec:intro}章と式\eqref{eq:value}．"), [])

    def test_non_prose_is_excluded(self):
        source = ("% 図2 Fig~\\ref{fig:comment}\n"
                  r"\begin{equation}\text{図2}\ref{fig:math}\end{equation}"
                  r"\begin{thebibliography}{1}\bibitem{x}Fig 2\end{thebibliography}"
                  r"\begin{figure}\caption{Comparison with \ref{fig:caption}}"
                  r"\label{fig:main}\end{figure}")
        self.assertEqual(self.diagnostics(source), [])


class NumbersAndPunctuation(unittest.TestCase):
    def test_visible_digits(self):
        for s in ['本文１２３．', r'\section{第２章}', r'\caption[Short ２]{Title ３}',
                  r'$x=２$', r'\begin{equation}x=３\end{equation}',
                  r'\num{３}', r'\SI{４}{m}',
                  r'\title{資料５}\begin{document}本文．\end{document}',
                  r'\section[第７章]{第8章}', r'\cite[p. ２]{key}', r'\si{m２}']:
            with self.subTest(s=s):
                self.assertTrue(any(d.rule == 'NUM001' and d.severity == 'ERROR' for d in fmt.inspect_source(s)))

    def test_hidden_digits_and_normal_numbers(self):
        for s in ['本文123，説明．', '% １２３\n本文．',
                  r'\cite{論文２}\label{図３}\ref{図３}\url{https://a/４}\path{５.pdf}',
                  r'\includegraphics[width=２mm]{図３.png}',
                  r'\newcommand{\foo}{\title{未使用２}}\begin{document}本文．\end{document}',
                  r'\begin{verbatim}１２\end{verbatim}']:
            with self.subTest(s=s):
                self.assertFalse(any(d.rule == 'NUM001' for d in fmt.inspect_source(s)))

    def test_punctuation_reuses_existing_id(self):
        bad = [d for d in fmt.inspect_source('本文、説明。') if d.rule == 'PUNCT001']
        self.assertEqual(len(bad), 2)
        self.assertTrue(all(d.severity == 'ERROR' for d in bad))
        self.assertFalse(any(d.rule == 'PUNCT001' for d in fmt.inspect_source(
            r'本文，説明． English, sentence. $x=1.2$ \url{https://a/。} \cite{、} file.pdf')))

    def test_offsets(self):
        source = '本文．\n第１２章'
        d = next(d for d in fmt.inspect_source(source) if d.rule == 'NUM001')
        self.assertIn('main.tex:2: NUM001 ERROR', d.format(Path('main.tex'), source))


class Bibliography(unittest.TestCase):
    GOOD = '@article{key, author={A. Author and B. Writer}, title={A {Protected} title}, journal={Journal}, volume={2}, pages={1--9}, year={2024}}'
    TEX = r'\begin{document}\cite{key}\bibliographystyle{IEEEtran}\bibliography{bib}\end{document}'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'main.tex'

    def inspect(self, bib=None, tex=None):
        (self.root / 'bib.bib').write_text(self.GOOD if bib is None else bib)
        source = self.TEX if tex is None else tex
        return [(p, s, d) for p, s, ds in refs.inspect_references([(self.path, source)]) for d in ds]

    def errors(self, **kwargs):
        return [d.rule for _, _, d in self.inspect(**kwargs) if d.severity == 'ERROR']

    def test_valid_ieee(self):
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.errors(tex=self.TEX.replace('IEEEtran', 'IEEEtranS')), [])

    def test_wrong_missing_duplicate_style(self):
        for tex in [self.TEX.replace('IEEEtran', 'plain'), self.TEX.replace(r'\bibliographystyle{IEEEtran}', ''),
                    self.TEX + r'\bibliographystyle{IEEEtran}']:
            self.assertIn('BIB001', self.errors(tex=tex))

    def test_missing_entry_and_duplicate_keys(self):
        self.assertIn('BIB003', self.errors(tex=self.TEX.replace('cite{key}', 'cite{absent}')))
        self.assertIn('BIB003', self.errors(bib=self.GOOD + '\n' + self.GOOD))

    def test_missing_required_fields(self):
        self.assertIn('BIB004', self.errors(bib=self.GOOD.replace('journal={Journal},', '')))
        self.assertIn('BIB004', self.errors(bib=self.GOOD.replace('title={A {Protected} title}', 'title={}')))

    def test_year_and_page_range(self):
        for before, after in [('2024', '24'), ('1--9', '1-9')]:
            self.assertIn('BIB005', self.errors(bib=self.GOOD.replace(before, after)))

    def test_bib_digits_and_key_exclusion(self):
        self.assertIn('NUM001', self.errors(bib=self.GOOD.replace('Protected', '論文２')))
        self.assertEqual(self.errors(bib=self.GOOD.replace('key', 'key２'), tex=self.TEX.replace('key', 'key２')), [])

    def test_macro_concat_crossref_are_uncertain(self):
        bib = '@string{j="Journal"}\n' + self.GOOD.replace('journal={Journal}', 'journal=j # " Supplement"')
        result = self.inspect(bib=bib)
        self.assertFalse(any(d.severity == 'ERROR' for _, _, d in result))
        self.assertTrue(any(d.rule == 'BIB006' and d.severity == 'WARNING' for _, _, d in result))
        bib = self.GOOD.replace('journal={Journal}', 'crossref={parent}')
        self.assertNotIn('BIB004', self.errors(bib=bib))

    def test_article_number_requires_review(self):
        ds = self.inspect(bib=self.GOOD.replace('1--9', '110825'))
        self.assertTrue(any(d.rule == 'BIB006' and d.severity == 'WARNING' for _, _, d in ds))
        self.assertFalse(any(d.severity == 'ERROR' for _, _, d in ds))

    def test_comments_verbatim_definitions_cites_ignored(self):
        tex = self.TEX.replace(r'\cite{key}', r'\cite[p. 1]{key}')
        tex = '% \\bibliographystyle{plain}\n' + tex + '\n' + r'\newcommand{\unused}{\cite{absent}}\begin{verbatim}\cite{absent}\end{verbatim}'
        self.assertEqual(self.errors(tex=tex), [])

    def test_syntax_and_offsets(self):
        self.assertIn('BIB002', self.errors(bib=self.GOOD[:-1]))
        ds = self.inspect(bib='\n' + self.GOOD.replace('2024', 'bad'))
        p, s, d = next(item for item in ds if item[2].rule == 'BIB005')
        self.assertIn('bib.bib:2:', d.format(p, s))

    def test_missing_database_and_manual_bibliography(self):
        ds = self.inspect(tex=self.TEX.replace('{bib}', '{absent}'))
        self.assertTrue(any(d.rule == 'BIB002' and d.severity == 'ERROR' for _, _, d in ds))
        self.assertIn('BIB001', self.errors(tex=r'\begin{thebibliography}{1}\bibitem{key}A\end{thebibliography}'))

    def test_cli_and_combined_runner(self):
        self.path.write_text(self.TEX)
        for checker in ['check_format.py', 'check_all.py']:
            for bib, code in [(self.GOOD, 0), (self.GOOD.replace('2024', 'bad'), 1)]:
                (self.root / 'bib.bib').write_text(bib)
                r = subprocess.run([sys.executable, str(TOOLS / checker), str(self.path)], capture_output=True)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
