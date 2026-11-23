"""Conservative BibTeX/IEEE checks; no network, rewriting, or guessed metadata."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from check_format import Diagnostic, TexView
from check_terminology import is_escaped, mask_comments


@dataclass
class Entry:
    kind: str
    key: str
    offset: int
    fields: dict[str, tuple[str, int]]


def parse_bib(source: str) -> list[Entry]:
    """Balanced braces/quotes, multiline values, macros and concatenation.

    Keep unresolved expressions literal; validation never invents their values.
    """
    text = mask_comments(source)
    entries = []
    pos = 0
    while m := re.search(r"@([A-Za-z]+)\s*([{(])", text[pos:]):
        start = pos + m.start()
        kind = m[1].lower()
        cursor = pos + m.end()
        closing = "}" if m[2] == "{" else ")"
        depth, quoted, end = 0, False, cursor
        while end < len(text):
            c = text[end]
            if not is_escaped(text, end):
                if c == '"' and depth == 0:
                    quoted = not quoted
                elif not quoted:
                    if c == "{":
                        depth += 1
                    elif c == "}" and depth:
                        depth -= 1
                    elif c == closing and depth == 0:
                        break
            end += 1
        if end == len(text):
            raise ValueError(f"line {source.count(chr(10), 0, start)+1}: unclosed BibTeX entry")
        pos = end + 1
        if kind in {"comment", "preamble", "string"}:
            continue
        key = re.match(r"\s*([^,\s]+)\s*,", text[cursor:end])
        if not key:
            raise ValueError(f"invalid BibTeX key at offset {cursor}")
        fields = {}
        cursor += key.end()
        while cursor < end:
            field = re.match(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*", text[cursor:end])
            if not field:
                if not text[cursor:end].strip(' \t\r\n,'):
                    break
                raise ValueError(f"invalid BibTeX field at offset {cursor}")
            name = field[1].lower()
            cursor += field.end()
            value_start = cursor
            depth, quoted = 0, False
            while cursor < end:
                c = text[cursor]
                if not is_escaped(text, cursor):
                    if c == '"' and depth == 0:
                        quoted = not quoted
                    elif not quoted:
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                        elif c == "," and depth == 0:
                            break
                cursor += 1
            if name in fields:
                raise ValueError(f"duplicate BibTeX field {name} at offset {value_start}")
            fields[name] = (text[value_start:cursor].strip(), value_start)
            cursor += 1
        entries.append(Entry(kind, key[1], start, fields))
    return entries


def literal(value: str) -> str | None:
    if value.startswith('{') and value.endswith('}'):
        return value[1:-1].strip()
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', value, re.S):
        return value[1:-1].strip()
    if re.fullmatch(r"\d+", value):
        return value
    return None  # macro, concatenation or other unresolved expression


def inspect_references(sources: list[tuple[Path, str]]) -> list[tuple[Path, str, list[Diagnostic]]]:
    results = []
    for path, source in sources:
        view = TexView(source)
        view.walk(0, len(source))  # include preamble, skip comments/math/definitions
        directives = [(n, a, source[a:b]) for n, a, b in view.directives]
        databases = [(a, v) for n, a, v in directives if n == "bibliography"]
        styles = [(a, v.strip()) for n, a, v in directives if n == "bibliographystyle"]
        clean = mask_comments(source)
        manual = re.search(r"\\begin\s*\{thebibliography\}", clean)
        if not databases and not styles and not manual:
            continue  # fragments/samples need not declare a bibliography
        found = []

        def emit(offset, rule, severity, problem, suggestion):
            found.append(Diagnostic(offset, rule, severity, problem, suggestion))

        if len(styles) != 1 or styles[0][1] not in {"IEEEtran", "IEEEtranS"}:
            emit(styles[0][0] if styles else 0, "BIB001", "ERROR", "IEEE参考文献スタイル設定",
                 "bibliographystyleをIEEEtran（出現順）またはIEEEtranS（ソート順）で1回指定する。")
        if manual:
            emit(manual.start(), "BIB006", "WARNING", "手書き参考文献", "IEEE体裁・書誌情報をPDFで個別確認する。")
        if not databases:
            emit(0, "BIB002", "WARNING", "BibTeXデータベース未指定", "bibliography指定または手書き参考文献を確認する。")
        entries = {}
        for offset, names in databases:
            for name in names.split(','):
                name = name.strip()
                if not name or '\\' in name or '#' in name:
                    emit(offset, "BIB006", "WARNING", name, "動的な文献パスは手動確認する。")
                    continue
                database = path.parent / (name if name.endswith('.bib') else name + '.bib')
                if not database.is_file():
                    emit(offset, "BIB002", "ERROR", str(database), "参照する.bibファイルを配置・指定する。")
                    continue
                bib = database.read_text(encoding='utf-8')
                bib_found = []
                try:
                    parsed = parse_bib(bib)
                except ValueError as exc:
                    bib_found.append(Diagnostic(0, "BIB002", "ERROR", str(exc), "BibTeX構文を修正する。"))
                    parsed = []
                for entry in parsed:
                    if entry.key in entries:
                        bib_found.append(Diagnostic(entry.offset, "BIB003", "ERROR", entry.key, "重複する引用キーを解消する。"))
                    entries[entry.key] = entry
                    required = {
                        'article': ['author', 'title', 'journal', 'year'],
                        'inproceedings': ['author', 'title', 'booktitle', 'year'],
                        'conference': ['author', 'title', 'booktitle', 'year'],
                        'phdthesis': ['author', 'title', 'school', 'year'],
                        'mastersthesis': ['author', 'title', 'school', 'year'],
                        'book': ['title', 'publisher', 'year'],
                        'techreport': ['author', 'title', 'institution', 'year'],
                        'misc': [], 'unpublished': ['author', 'title', 'note'],
                        'incollection': ['author', 'title', 'booktitle', 'publisher', 'year'],
                    }.get(entry.kind)
                    def issue(rule, severity, problem, suggestion, at=None):
                        bib_found.append(Diagnostic(entry.offset if at is None else at, rule, severity,
                                                    entry.key + ': ' + problem, suggestion))
                    if required is None:
                        issue('BIB006', 'WARNING', entry.kind, '未対応のエントリ種別をIEEEtran仕様・PDFで確認する。')
                    else:
                        for field in required:
                            if field not in entry.fields or literal(entry.fields[field][0]) == '':
                                issue('BIB004', 'WARNING' if 'crossref' in entry.fields else 'ERROR', field + '不足', '原著・出版社情報とcrossref継承を確認して補完する。推測しない。')
                    if entry.kind == 'book' and not any(f in entry.fields for f in ('author', 'editor')):
                        issue('BIB004', 'ERROR', 'author/editor不足', '原著に基づき著者または編者を記載する。')
                    for field, (value, at) in entry.fields.items():
                        val = literal(value)
                        if val is None:
                            issue('BIB006', 'WARNING', field + 'のマクロ・連結値', '展開後の値をBibTeXログとPDFで確認する。', at)
                            continue
                        if re.search('[０-９]', val) and field not in {'url', 'doi', 'crossref'}:
                            issue('NUM001', 'ERROR', val, '表示書誌情報の全角数字を半角にする。', at)
                        if field == 'year' and not re.fullmatch(r'[0-9]{4}', val):
                            issue('BIB005', 'ERROR', 'year=' + val, '出版年を原著に基づく半角4桁で記載する。', at)
                        if field == 'pages' and re.search(r'(?<!-)\d-\d(?!-)', val):
                            issue('BIB005', 'ERROR', 'pages=' + val, 'ページ範囲はBibTeXの--で区切る。', at)
                        if field == 'pages' and val.isdigit():
                            issue('BIB006', 'WARNING', '単一のpages=' + val, '単一ページか論文番号かを原著とPDFで確認する。自動変換しない。', at)
                        if field == 'doi' and not re.match(r'^10\.\d{4,9}/\S+$', val):
                            issue('BIB005', 'WARNING', 'doi=' + val, 'DOIの形式を出版社で確認する。', at)
                    if entry.kind in {'article', 'inproceedings', 'conference'} and not any(f in entry.fields for f in ('pages', 'eid', 'number')):
                        issue('BIB004', 'WARNING', 'ページ・論文番号情報なし', '電子論文番号等を原著で確認する。推測で補完しない。')
                    if entry.kind == 'article' and 'volume' not in entry.fields:
                        issue('BIB004', 'WARNING', 'volume未指定', '早期公開等の可能性も含め原著で確認する。')
                    if 'crossref' in entry.fields:
                        issue('BIB006', 'WARNING', 'crossref継承', '親エントリから継承される必須項目を手動確認する。')
                results.append((database, bib, bib_found))
        for name, offset, keys in directives:
            if name in {'cite', 'citep', 'citet', 'citeauthor', 'citeyear', 'autocite', 'parencite', 'textcite', 'nocite'}:
                for key in keys.split(','):
                    key = key.strip()
                    if key != '*' and key not in entries:
                        emit(offset, 'BIB003', 'ERROR', key, '引用キーに対応するBibTeXエントリを確認する。')
            if name in {'input', 'include', 'subfile'}:
                emit(offset, 'BIB006', 'WARNING', keys, '分割原稿の引用はルートと各断片を指定して別途確認する。マクロ展開・依存関係追跡はしない。')
        emit(databases[0][0] if databases else 0, 'BIB007', 'INFO', 'IEEE参考文献のPDF確認',
             '番号・引用順・著者・題名・掲載先・年・巻号・ページ/論文番号を原著と照合する。静的検査は真偽を保証しない。')
        results.append((path, source, found))
    return results
