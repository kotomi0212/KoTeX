#!/usr/bin/env python3
"""Check LaTeX sources against the project's terminology dictionary."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_RULES = Path(__file__).resolve().parents[1] / "writing_rules" / "forbidden_terms.json"
IGNORED_DIRECTORIES = {".git", ".agents", ".codex", "build", "dist", "node_modules", ".venv", "venv"}


def blank_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] != "\n":
            chars[index] = " "


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def balanced_group_end(text: str, start: int, opening: str, closing: str) -> int | None:
    if start >= len(text) or text[start] != opening:
        return None
    depth = 1
    index = start + 1
    while index < len(text):
        if not is_escaped(text, index):
            if text[index] == opening:
                depth += 1
            elif text[index] == closing:
                depth -= 1
                if depth == 0:
                    return index + 1
        index += 1
    return None


def mask_environments(text: str, environments: list[str]) -> str:
    chars = list(text)
    for environment in environments:
        escaped = re.escape(environment)
        pattern = re.compile(
            rf"\\begin\s*\{{{escaped}\}}(?:\s*\[[^\]]*\])?[\s\S]*?\\end\s*\{{{escaped}\}}"
        )
        for match in pattern.finditer(text):
            blank_span(chars, match.start(), match.end())
    return "".join(chars)


def mask_comments(text: str) -> str:
    chars = list(text)
    index = 0
    while index < len(text):
        if text[index] == "%" and not is_escaped(text, index):
            end = text.find("\n", index)
            if end == -1:
                end = len(text)
            blank_span(chars, index, end)
            index = end
        else:
            index += 1
    return "".join(chars)


def mask_math(text: str) -> str:
    chars = list(text)
    index = 0
    while index < len(text):
        closing: str | None = None
        opening_length = 0
        if text.startswith(r"\[", index) or text.startswith(r"\(", index):
            closing = r"\]" if text.startswith(r"\[", index) else r"\)"
            opening_length = 2
        elif text[index] == "$" and not is_escaped(text, index):
            closing = "$$" if text.startswith("$$", index) else "$"
            opening_length = len(closing)
        if closing is None:
            index += 1
            continue

        search_from = index + opening_length
        end = text.find(closing, search_from)
        while end != -1 and is_escaped(text, end):
            end = text.find(closing, end + len(closing))
        if end == -1:
            index += opening_length
            continue
        end += len(closing)
        blank_span(chars, index, end)
        index = end
    return "".join(chars)


def mask_commands(text: str, excluded: dict[str, int], verbatim_commands: list[str]) -> str:
    chars = list(text)
    command_pattern = re.compile(r"\\([A-Za-z@]+)(\*)?")
    verbatim = set(verbatim_commands)
    index = 0
    while index < len(text):
        match = command_pattern.search(text, index)
        if match is None:
            break
        name = match.group(1)
        if name in verbatim:
            delimiter_index = match.end()
            if delimiter_index < len(text):
                delimiter = text[delimiter_index]
                end = text.find(delimiter, delimiter_index + 1)
                if end != -1:
                    blank_span(chars, match.start(), end + 1)
                    index = end + 1
                    continue
        if name not in excluded:
            index = match.end()
            continue

        cursor = match.end()
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        while cursor < len(text) and text[cursor] == "[":
            end = balanced_group_end(text, cursor, "[", "]")
            if end is None:
                break
            cursor = end
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
        for _ in range(excluded[name]):
            end = balanced_group_end(text, cursor, "{", "}")
            if end is None:
                break
            cursor = end
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
        blank_span(chars, match.start(), cursor)
        index = max(cursor, match.end())
    return "".join(chars)


def searchable_text(text: str, dictionary: dict[str, Any]) -> str:
    text = mask_environments(text, dictionary.get("masked_environments", []))
    text = mask_comments(text)
    text = mask_math(text)
    return mask_commands(
        text,
        dictionary.get("excluded_commands", {}),
        dictionary.get("verbatim_commands", []),
    )


def collect_tex_files(paths: list[Path]) -> list[Path]:
    found: dict[Path, Path] = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file():
            if path.suffix.lower() == ".tex":
                found[path.resolve()] = path
            continue
        for candidate in path.rglob("*.tex"):
            relative_parts = candidate.relative_to(path).parts
            if any(part in IGNORED_DIRECTORIES for part in relative_parts[:-1]):
                continue
            found[candidate.resolve()] = candidate
    return sorted(found.values(), key=lambda item: item.as_posix().casefold())


def load_dictionary(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        dictionary = json.load(stream)
    if not isinstance(dictionary, dict) or not isinstance(dictionary.get("rules"), list):
        raise ValueError("辞書には rules 配列が必要です")
    for index, rule in enumerate(dictionary["rules"], start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"rules[{index - 1}] はオブジェクトである必要があります")
        if not all(key in rule for key in ("term", "pattern", "severity", "recommendation")):
            raise ValueError(f"rules[{index - 1}] に必須キーがあります: term, pattern, severity, recommendation")
        if rule["severity"] not in {"error", "warning"}:
            raise ValueError(f"rules[{index - 1}].severity は error または warning で指定してください")
        flags = re.IGNORECASE if rule.get("ignore_case", False) else 0
        try:
            rule["_compiled"] = re.compile(rule["pattern"], flags)
        except re.error as error:
            raise ValueError(f"rules[{index - 1}].pattern が不正です: {error}") from error
    return dictionary


def inspect_file(path: Path, dictionary: dict[str, Any]) -> tuple[list[str], bool]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"{path}: error: ファイルを読み込めません: {error}"], True

    visible = searchable_text(source, dictionary)
    diagnostics: list[str] = []
    has_error = False
    for rule in dictionary["rules"]:
        for match in rule["_compiled"].finditer(visible):
            line = visible.count("\n", 0, match.start()) + 1
            severity = rule["severity"]
            label = "ERROR" if severity == "error" else "WARNING"
            diagnostics.append(
                f"{path}:{line}: {label}: {match.group(0)}（{rule['term']}）— 推奨: {rule['recommendation']}"
            )
            has_error = has_error or severity == "error"
    return diagnostics, has_error


def main() -> int:
    parser = argparse.ArgumentParser(description="LaTeX用語を辞書ベースで検査します")
    parser.add_argument("paths", nargs="*", type=Path, help=".texファイルまたは検索するディレクトリ（省略時は現在のディレクトリ）")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="検査規則JSON（既定: プロジェクトの forbidden_terms.json）")
    arguments = parser.parse_args()
    paths = arguments.paths or [Path(".")]

    try:
        dictionary = load_dictionary(arguments.rules)
        files = collect_tex_files(paths)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        return 2

    any_error = False
    total = 0
    for path in files:
        diagnostics, file_error = inspect_file(path, dictionary)
        total += len(diagnostics)
        any_error = any_error or file_error
        for diagnostic in diagnostics:
            print(diagnostic)

    if total == 0:
        print(f"用語規則違反・注意語はありません（検査ファイル数: {len(files)}）")
    else:
        print(f"検査完了: {len(files)} ファイル，検出 {total} 件")
    return 1 if any_error else 0


if __name__ == "__main__":
    raise SystemExit(main())