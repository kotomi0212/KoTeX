#!/usr/bin/env python3
"""Read-only, conservative checks of visible LaTeX prose (Python stdlib only)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from check_terminology import collect_tex_files, is_escaped, mask_comments

JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]")
HIDDEN = "\0"  # Mask syntax without inventing visible spaces inside parentheses.
SKIP_ENVS = {
    "math", "displaymath", "equation", "align", "alignat", "gather",
    "multline", "flalign", "split", "cases", "eqnarray", "verbatim",
    "Verbatim", "lstlisting", "minted", "alltt", "thebibliography",
    "filecontents", "filecontents*", "tikzpicture",
}
SKIP_ARGS = {
    **{k: 1 for k in (
        "label ref eqref autoref pageref nameref vref cref Cref cpageref "
        "cite citep citet citeauthor citeyear autocite parencite textcite nocite "
        "url path nolinkurl includegraphics includesvg input include subfile "
        "bibliography bibliographystyle addbibresource index gls Gls "
        "si unit num numlist numrange vspace hspace color"
    ).split()},
    "SI": 2, "qty": 2, "SIrange": 3, "qtyrange": 3,
    "setlength": 2, "addtolength": 2, "setcounter": 2,
    "newcommand": 2, "renewcommand": 2, "providecommand": 2,
}
DISPLAY = set((
    "textbf textit textsl textsc textsf textrm textnormal emph underline "
    "mbox hbox fbox texttt section subsection subsubsection paragraph "
    "subparagraph chapter title author footnote footnotetext captionof"
).split())
REFERENCE = re.compile(
    r"(?:(?<![A-Za-z])(?:Fig\.|Figure|Table|Eq\.|Equation|式)|(?<![\u3400-\u9fff])[図表])"
    r"[ \t~\u3000]*[（(]?[ \t]*[0-9]+(?:[.\-][0-9]+)*"
)
FLOAT_NAMES = r"(?:(?<![A-Za-z])(?:Figure|Fig\.?|Table)|(?<![\u3400-\u9fff])(?:図|表|画像|写真))"
FLOAT_LITERAL = re.compile(
    rf"{FLOAT_NAMES}[\s~]*[（(]?[ \t]*[0-9０-９]+"
)
FLOAT_PREFIX = re.compile(rf"{FLOAT_NAMES}(?:[\s~]|\\[ ,])*\Z")
FLOAT_REFERENCE_COMMANDS = {"ref", "autoref", "pageref", "nameref", "vref", "cref", "Cref", "cpageref", "eqref"}


class TexError(ValueError):
    pass


@dataclass(frozen=True)
class Diagnostic:
    offset: int
    rule: str
    severity: str
    problem: str
    suggestion: str

    def format(self, path: Path, source: str) -> str:
        line = source.count("\n", 0, self.offset) + 1
        snippet = self.problem.replace("\n", r"\n")
        return f"{path}:{line}: {self.rule} {self.severity}: {snippet} — {self.suggestion}"


@dataclass(frozen=True)
class Caption:
    start: int
    end: int
    environment: str | None
    short: bool


class TexView:
    """Subset parser: keep source offsets; inspect known visible arguments.

    Unknown macro arguments are retained but marked uncertain. No macro
    expansion, conditional evaluation, catcode interpretation, or file execution.
    """
    def __init__(self, source: str, *, numeric: bool = False):
        self.source = source
        self.numeric = numeric
        self.directives: list[tuple[str, int, int]] = []
        self.float_label_types: dict[str, str] = {}
        self.reference_commands: list[tuple[int, int, str]] = []
        self.commentless = mask_comments(source)
        self.chars = ["\n" if c == "\n" else HIDDEN for c in source]
        self.captions: list[Caption] = []
        self.uncertain: list[tuple[int, int]] = []
        self.environments: list[str] = []

    def group(self, pos: int, end: int, opening: str = "{") -> tuple[int, int] | None:
        while pos < end:
            if self.source[pos].isspace():
                pos += 1
            elif self.source[pos] == "%" and not is_escaped(self.source, pos):
                newline = self.source.find("\n", pos, end)
                pos = end if newline < 0 else newline + 1
            else:
                break
        if pos >= end or self.source[pos] != opening:
            return None
        closing = "}" if opening == "{" else "]"
        depth, braces, cursor = 1, 0, pos + 1
        while cursor < end:
            c = self.source[cursor]
            if c == "%" and not is_escaped(self.source, cursor):
                newline = self.source.find("\n", cursor, end)
                cursor = end if newline < 0 else newline + 1
                continue
            if not is_escaped(self.source, cursor):
                if opening == "[" and c == "{":
                    braces += 1
                elif opening == "[" and c == "}":
                    braces -= 1
                elif not braces and c == opening:
                    depth += 1
                elif not braces and c == closing:
                    depth -= 1
                    if depth == 0:
                        return pos + 1, cursor
            cursor += 1
        raise TexError(f"line {self.source.count(chr(10), 0, pos)+1}: unclosed {opening}")

    def after(self, group: tuple[int, int]) -> int:
        return group[1] + 1

    def walk(self, start: int, end: int) -> None:
        s = self.source
        i = start
        while i < end:
            if s[i] == "%":
                newline = s.find("\n", i, end)
                i = end if newline < 0 else newline
                continue
            if not self.numeric and (s[i] == "$" or s.startswith((r"\(", r"\["), i)):
                opening = "$$" if s.startswith("$$", i) else s[i:i+2] if s[i] == "\\" else "$"
                closing = {r"\(": r"\)", r"\[": r"\]"}.get(opening, opening)
                j = i + len(opening)
                while True:
                    j = self.commentless.find(closing, j, end)
                    if j < 0:
                        raise TexError(f"unclosed math delimiter at line {s.count(chr(10), 0, i)+1}")
                    if not is_escaped(s, j):
                        break
                    j += len(closing)
                i = j + len(closing)
                continue
            if s[i] == "\\":
                m = re.match(r"\\([A-Za-z@]+)(\*)?", s[i:end])
                if not m:
                    if i + 1 < end and s[i+1] not in "\\":
                        self.chars[i+1] = s[i+1]  # escaped %, braces, etc.
                    i += 2
                    continue
                name = m[1]
                pos = i + len(m[0])
                if name in {"verb", "lstinline"}:
                    opt = self.group(pos, end, "[")
                    if opt:
                        pos = self.after(opt)
                    if pos >= end:
                        raise TexError("missing verbatim delimiter")
                    stop = s.find(s[pos], pos+1, end)
                    if stop < 0:
                        raise TexError("unclosed inline verbatim")
                    i = stop + 1
                    continue
                if name in {"begin", "end"}:
                    g = self.group(pos, end)
                    if not g:
                        raise TexError(f"missing environment name after {name}")
                    env = s[g[0]:g[1]]
                    pos = self.after(g)
                    skipped = SKIP_ENVS - {"math", "displaymath", "equation", "align", "alignat", "gather", "multline", "flalign", "split", "cases", "eqnarray"} if self.numeric else SKIP_ENVS
                    if name == "begin" and env.rstrip("*") in skipped:
                        searchable = s if env.rstrip("*") in {"verbatim", "Verbatim", "lstlisting", "minted", "alltt", "filecontents"} else self.commentless
                        close = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", searchable[pos:end])
                        if not close:
                            raise TexError(f"unclosed environment {env}")
                        i = pos + close.end()
                        continue
                    if name == "begin":
                        self.environments.append(env)
                    elif self.environments and self.environments[-1] == env:
                        self.environments.pop()
                    if name == "begin":
                        while (opt := self.group(pos, end, "[")) is not None:
                            pos = self.after(opt)
                        if env.rstrip("*") in {"tabular", "tabularx", "minipage"}:
                            g = self.group(pos, end)
                            if g:
                                pos = self.after(g)
                    i = pos
                    continue
                optional: list[tuple[int, int]] = []
                while (g := self.group(pos, end, "[")) is not None:
                    optional.append(g)
                    pos = self.after(g)
                numeric_options = DISPLAY | {"cite", "citep", "citet", "autocite", "parencite", "textcite"}
                if name in {"twocolumn", "item"} or (self.numeric and name in numeric_options):
                    for opt in optional:
                        self.walk(*opt)
                if name in {"caption", "captionof"}:
                    env = next((e.rstrip("*") for e in reversed(self.environments)
                                if e.rstrip("*") in {"figure", "table"}), None)
                    if name == "captionof":
                        g = self.group(pos, end)
                        if not g:
                            raise TexError("missing captionof type")
                        env = s[g[0]:g[1]]
                        pos = self.after(g)
                        while (opt := self.group(pos, end, "[")) is not None:
                            optional.append(opt)
                            pos = self.after(opt)
                    g = self.group(pos, end)
                    if not g:
                        raise TexError("missing caption title")
                    for title, short in [(g, False)] + [(o, True) for o in optional]:
                        self.captions.append(Caption(*title, env, short))
                        self.walk(*title)
                    i = self.after(g)
                    continue
                if name in {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"}:
                    g = self.group(pos, end)
                    if g:
                        pos = self.after(g)
                    else:
                        command = re.match(r"\s*\\[A-Za-z@]+", s[pos:end])
                        if not command:
                            raise TexError("macro definition requires a command name")
                        pos += command.end()
                    while (opt := self.group(pos, end, "[")) is not None:
                        pos = self.after(opt)
                    g = self.group(pos, end)
                    if not g:
                        raise TexError("missing macro definition body")
                    i = self.after(g)
                    continue
                count = SKIP_ARGS.get(name)
                if self.numeric and name in {"num", "numlist", "numrange", "SI", "si", "unit", "qty", "SIrange", "qtyrange"}:
                    count = None  # These arguments contain displayed numbers.
                if name == "href" or name in {"textcolor", "colorbox", "foreignlanguage", "parbox"}:
                    g = self.group(pos, end)
                    if g:
                        pos = self.after(g)
                    name = "textnormal"  # next argument is displayed
                if name == "texorpdfstring":
                    g = self.group(pos, end)
                    if g:
                        self.walk(*g)
                        pos = self.after(g)
                    g = self.group(pos, end)
                    i = self.after(g) if g else pos
                    continue
                if count is not None:
                    for _ in range(count):
                        g = self.group(pos, end)
                        if not g:
                            break
                        self.directives.append((name, *g))
                        if not self.numeric and name == "label":
                            kind = next((e.rstrip("*") for e in reversed(self.environments)
                                         if e.rstrip("*") in {"figure", "table"}), None)
                            if kind:
                                self.float_label_types[s[g[0]:g[1]].strip()] = kind
                        if not self.numeric and name in FLOAT_REFERENCE_COMMANDS:
                            self.reference_commands.append((i, self.after(g), s[g[0]:g[1]].strip()))
                        pos = self.after(g)
                    i = pos
                    continue
                g = self.group(pos, end)
                if g:
                    if name in {"title", "author", "date"}:
                        self.directives.append((name, *g))
                    if name not in DISPLAY:
                        self.uncertain.append(g)
                    self.walk(*g)
                    pos = self.after(g)
                    if name not in DISPLAY:
                        while (extra := self.group(pos, end)) is not None:
                            self.uncertain.append(extra)
                            self.walk(*extra)
                            pos = self.after(extra)
                    i = pos
                else:
                    i = pos
                continue
            if s[i] not in "{}":
                self.chars[i] = " " if s[i] == "~" else s[i]
            i += 1

    def parse(self) -> str:
        # Only a genuine, uncommented document boundary limits a full source.
        clean = self.commentless
        begin = re.search(r"\\begin\s*\{document\}", clean)
        finish = re.search(r"\\end\s*\{document\}", clean)
        self.walk(begin.end() if begin else 0, finish.start() if finish else len(clean))
        if self.numeric and begin:
            # Only displayed metadata, not documentclass/package options.
            metadata = TexView(self.source)
            metadata.walk(0, begin.start())
            for name, a, b in metadata.directives:
                if name in {"title", "author", "date"}:
                    self.walk(a, b)
        text = "".join(self.chars)
        # Bare URLs and path-looking tokens are opaque, as are explicit \url/\path.
        pattern = r"https?://[^\s{}]+|(?<![\w])(?:[~.]*/|[A-Za-z]:[\\/])[\w./\\、。()（）-]+|[\w.-]+\.(?:tex|bib|pdf|png|jpe?g|csv|md|py)\b"
        for match in re.finditer(pattern, text):
            for i in range(*match.span()):
                if self.chars[i] != "\n":
                    self.chars[i] = HIDDEN
        return "".join(self.chars)


def inspect_float_references(view: TexView, text: str) -> list[Diagnostic]:
    found = []
    for start, end, label in view.reference_commands:
        if any(cap.start <= start < cap.end for cap in view.captions):
            continue
        prefix = FLOAT_PREFIX.search(view.commentless, 0, start)
        if prefix and text[prefix.start()] == HIDDEN:
            prefix = None
        kind = view.float_label_types.get(label)
        looks_like_float = label.startswith(("fig:", "tab:", "table:"))
        if not (prefix or kind or looks_like_float):
            continue
        offset = prefix.start() if prefix else start
        display = view.source[offset:end]
        if kind is None:
            found.append(Diagnostic(offset, "REF003", "ERROR", display,
                                    "本文の図表参照には対応する図または表のラベルを指定する。"))
            continue
        expected = "Fig." if kind == "figure" else "Table"
        if display != rf"{expected}~\ref{{{label}}}":
            found.append(Diagnostic(offset, "REF002", "ERROR", display,
                                    rf"本文の参照には {expected}~\ref{{{label}}} を使う。"))
    return found


def inspect_source(source: str) -> list[Diagnostic]:
    view = TexView(source)
    text = view.parse()
    found: list[Diagnostic] = []

    def add(pos: int, rule: str, severity: str, problem: str, suggestion: str) -> None:
        found.append(Diagnostic(pos, rule, severity, problem, suggestion))

    def uncertain(pos: int) -> bool:
        return any(a <= pos < b for a, b in view.uncertain)

    numeric_text = TexView(source, numeric=True).parse()
    for m in re.finditer("[０-９]+", numeric_text):
        add(m.start(), "NUM001", "ERROR", m[0], "全角数字を半角数字にする：" + m[0].translate(str.maketrans("０１２３４５６７８９", "0123456789")))

    for m in re.finditer("[、。]", text):
        line = text[text.rfind("\n", 0, m.start())+1:text.find("\n", m.start()) if "\n" in text[m.start():] else len(text)]
        severity = "WARNING" if uncertain(m.start()) or not JP.search(line) else "ERROR"
        add(m.start(), "PUNCT001", severity, m[0], "日本語本文では「，」「．」を使用する。書誌情報等は文脈を確認。")

    references = list(REFERENCE.finditer(text))
    for m in references:
        add(m.start(), "REF001", "WARNING", m[0], "番号直書きの疑い。対応ラベルを確認し、\\ref・\\eqref等を使う。")
    legacy_offsets = {m.start() for m in references}
    for m in FLOAT_LITERAL.finditer(text):
        if m.start() not in legacy_offsets and not any(cap.start <= m.start() < cap.end for cap in view.captions):
            add(m.start(), "REF001", "WARNING", m[0], "図表番号は直書きせず、Fig. または Table と対応する\\refを使う。")
    found.extend(inspect_float_references(view, text))

    stack: list[tuple[int, str, bool]] = []
    pairs: list[tuple[int, int, bool]] = []
    for i, char in enumerate(text):
        if char in "(（":
            if stack:
                a, c, _ = stack[-1]
                stack[-1] = (a, c, True)
            stack.append((i, char, False))
        elif char in ")）":
            if not stack:
                add(i, "PAREN004", "WARNING", char, "対応する開き括弧を確認する。")
                continue
            a, opening, nested = stack.pop()
            if not stack:
                pairs.append((a, i, nested))
            if (opening, char) not in {( "(", ")"), ("（", "）")}:
                add(a, "PAREN004", "WARNING", source[a:i+1], "括弧の対応・種類を確認する。")
    for a, _, _ in stack:
        add(a, "PAREN004", "WARNING", source[a:a+30], "閉じ括弧またはTeX構文を確認する。")
    for a, b, nested in pairs:
        if any(m.start() <= a <= m.end() for m in references):
            continue
        inside = text[a+1:b].replace(HIDDEN, "")
        if not inside.strip():
            continue
        raw = source[a+1:b]
        unit = re.fullmatch(r"(?:mm|cm|m|s|ms|kg|g|N|Pa|kPa|MPa|K|Hz|rad|deg|W|V|A|mol|cd|J|[A-Za-zµΩ°]+[/·*][A-Za-z0-9^+*/-]+)", raw.strip())
        if nested or unit or "$" in raw or re.search(r"\\(?:SI|si|qty|unit|num)\b", raw) or any(uncertain(p) for p in range(a, b+1)):
            add(a, "PAREN003", "WARNING", source[a:b+1], "入れ子・未展開マクロ・単位・数式を含む括弧は表示を確認する。")
            continue
        first = inside.lstrip()[0]
        if re.match(r"[A-Za-z0-9]", first):
            if text[a] != "(" or text[b] != ")" or not (inside.startswith(" ") and inside.endswith(" ")):
                add(a, "PAREN001", "ERROR", source[a:b+1], "先頭が半角英数字の場合は半角括弧と内側両端の半角空白を使う。例：( MPC )")
        elif JP.match(first):
            if text[a] != "（" or text[b] != "）" or inside != inside.strip():
                add(a, "PAREN002", "ERROR", source[a:b+1], "先頭が日本語の場合は内側に空白のない全角括弧を使う。例：（村優大）")
        else:
            add(a, "PAREN003", "WARNING", source[a:b+1], "先頭文字の種類や単位・記号の用法を人間が確認する。")

    for cap in view.captions:
        title = text[cap.start:cap.end]
        matches = list(JP.finditer(title))
        known = [m for m in matches if not uncertain(cap.start + m.start())]
        if known:
            add(cap.start + known[0].start(), "CAP001", "ERROR", source[cap.start:cap.end],
                f"{cap.environment or '不明環境'}の{'短縮名' if cap.short else 'タイトル'}を英語にする。非表示のラベル・引用キーは対象外。")
        elif matches:
            add(cap.start, "CAP003", "WARNING", source[cap.start:cap.end], "未知のマクロ引数に日本語あり。実際に表示される文字か確認する。")
        plain = title.replace(HIDDEN, "").strip()
        if not matches and (not re.search("[A-Za-z]", plain) or re.search(r"[^\x00-\x7f]", plain)):
            add(cap.start, "CAP004", "WARNING", source[cap.start:cap.end], "文字種だけでは英語タイトルと判定できないため、言語を確認する。")
        if REFERENCE.search(title) or re.match(r"\s*[0-9]+(?:[.\-][0-9]+)*[\s.:]", title.replace(HIDDEN, "")):
            add(cap.start, "CAP002", "WARNING", source[cap.start:cap.end], "図表番号をタイトルに直書きせずLaTeXの自動番号を使用する。")
        if cap.environment not in {"figure", "table"}:
            add(cap.start, "CAP005", "WARNING", source[cap.start:cap.end], "図・表の環境を確定できない。マクロやcaptionofの用法を確認する。")
    if view.captions:
        add(view.captions[0].start, "PDF001", "INFO", "キャプションのPDF確認", "英語の妥当性、Fig. <番号>、番号後の半角2スペース相当、フォント・配置をPDFで確認する。静的チェックでは保証しない。")
    return sorted(found, key=lambda d: (d.offset, d.rule))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help=".texファイルまたはディレクトリ（既定：現在地）")
    args = parser.parse_args(argv)
    try:
        files = collect_tex_files(args.paths or [Path(".")])
        if not files:
            raise ValueError("検査対象の.texファイルがありません")
        results = [(p, p.read_text(encoding="utf-8")) for p in files]
        diagnostics = [(p, s, inspect_source(s)) for p, s in results]
        from check_references import inspect_references
        diagnostics.extend(inspect_references(results))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(f"実行エラー: {exc}", file=sys.stderr)
        return 2
    counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
    for path, source, items in diagnostics:
        for item in items:
            counts[item.severity] += 1
            print(item.format(path, source))
    print(f"書式検査: {len(files)}ファイル / " + " / ".join(f"{k} {v}" for k, v in counts.items()))
    return int(counts["ERROR"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
