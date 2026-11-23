"""Check figures and tables in the compiled, two-column midterm report."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


PT_PER_MM = 72 / 25.4
BODY_MARGIN_PT = 20 * PT_PER_MM
GUTTER_PT = 16.82
TOP_TOLERANCE_PT = 8
WIDTH_TOLERANCE_PT = 1
CAPTION_GAP_PT = 12
# Includes the class floatsep and the leading space inside the next float.
MAX_FLOAT_GAP_PT = 26
MIN_FLOAT_SEP_PT = 9
TEXT_FLOAT_SEP_PT = 18
MIN_TEXT_FLOAT_SEP_PT = 14  # The natural textfloatsep minus its allowed shrink, rounded down.
MIN_TEXT_FRACTION = 0.25


class AuditError(ValueError):
    """The available evidence is insufficient for a placement decision."""


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center(self):
        return (self.left + self.right) / 2


@dataclass(frozen=True, order=True)
class Position:
    page: int
    column: int
    top: float

    def __str__(self):
        return f"p{self.page} {'left' if self.column == 0 else 'right'} y={self.top:.1f}"


@dataclass(frozen=True)
class Float:
    label: str
    number: str
    page: int
    destination: str

    @property
    def kind(self):
        return self.destination.split(".", 1)[0]

    @property
    def name(self):
        return f"{'Fig.' if self.kind == 'figure' else 'Table'} {self.number}"


def union(boxes):
    return Box(min(b.left for b in boxes), min(b.top for b in boxes),
               max(b.right for b in boxes), max(b.bottom for b in boxes))


def xml_box(node):
    return Box(*(float(node.attrib[name]) for name in ("xMin", "yMin", "xMax", "yMax")))


def tex_floats(tex):
    """Return the labeled figure and table environments in the report source."""
    source = re.sub(r"(?<!\\)%[^\n]*", "", tex.read_text(encoding="utf-8-sig"))
    entries = {}
    for match in re.finditer(r"\\begin\{((?:figure|table)\*?)\}(.*?)\\end\{\1\}", source, re.S):
        labels = re.findall(r"\\label\{([^{}]+)\}", match[2])
        if len(labels) != 1 or labels[0] in entries:
            raise AuditError("every figure and table needs exactly one unique label")
        graphics_count = len(re.findall(r"\\includegraphics\b", match[2]))
        entries[labels[0]] = (match[1], graphics_count)
    if not entries:
        raise AuditError("no labeled figure or table environments found")
    return entries


def read_floats(aux, source):
    pattern = re.compile(
        r"\\newlabel\{([^{}]+)\}\{\{([^{}]+)\}\{(\d+)\}\{.*\}"
        r"\{((?:figure|table)\.[^{}]+)\}\{[^{}]*\}\}\s*$"
    )
    floats = []
    for line in aux.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.fullmatch(line)
        if match:
            label, number, page, destination = match.groups()
            floats.append(Float(label, number, int(page), destination))
    if {item.label for item in floats} != set(source) or len(floats) != len(source):
        raise AuditError("figure/table labels in the TeX source and .aux do not match; rebuild the PDF")
    if len({item.destination for item in floats}) != len(floats):
        raise AuditError("ambiguous figure/table destinations")
    if any(source[item.label][0].rstrip("*") != item.kind for item in floats):
        raise AuditError("figure/table types in the TeX source and .aux do not match")
    return floats


def column_bounds(width, column):
    margin = 15 * PT_PER_MM
    middle = width / 2
    return ((margin, middle - GUTTER_PT / 2) if column == 0
            else (middle + GUTTER_PT / 2, width - margin))


def top_group(entries, words, column, width, body_top=BODY_MARGIN_PT):
    """Find the uninterrupted prefix of figures and tables at the column top."""
    left, right = column_bounds(width, column)
    group = {}
    previous = None
    for position, extent in sorted(entries):
        if extent is None:
            break
        if previous is None:
            if abs(extent.top - body_top) > TOP_TOLERANCE_PT:
                break
        else:
            gap = extent.top - previous.bottom
            if not 0 <= gap <= MAX_FLOAT_GAP_PT:
                break
            if any(left <= word.center <= right
                   and previous.bottom < (word.top + word.bottom) / 2 < extent.top
                   for word in words):
                break
        group[position] = extent
        previous = extent
    return group


def placement_flags(position, caption, body, ref, width, height, in_group, ordered=True, kind="table",
                    body_top=BODY_MARGIN_PT):
    """Return the required checks and the reading-order column distance."""
    left, right = column_bounds(width, position.column)
    extent = union((caption, body))
    caption_gap = caption.top - body.bottom if kind == "figure" else body.top - caption.bottom
    flags = {
        "R1 top group": in_group,
        "R2 after reference": ref is not None and position > ref,
        "R3 within column": (extent.left >= left - WIDTH_TOLERANCE_PT
                             and extent.right <= right + WIDTH_TOLERANCE_PT),
        "R3 within body height": (extent.top >= body_top - WIDTH_TOLERANCE_PT
                                  and extent.bottom <= height - BODY_MARGIN_PT + WIDTH_TOLERANCE_PT),
        "R4 caption/body": 0 <= caption_gap <= CAPTION_GAP_PT,
        "R7 reference order": ordered,
    }
    columns = None if ref is None else 2 * (position.page - ref.page) + position.column - ref.column
    return flags, columns


def group_capacity(extent, page_height, max_top_fraction, body_top=BODY_MARGIN_PT):
    column_height = page_height - BODY_MARGIN_PT - body_top
    float_height = extent.bottom - body_top
    text_height = max(0, page_height - BODY_MARGIN_PT - extent.bottom - TEXT_FLOAT_SEP_PT)
    fits = (float_height <= column_height * max_top_fraction
            and text_height >= column_height * MIN_TEXT_FRACTION)
    return column_height, text_height, fits


def reference_order_errors(group, references):
    """Return the positions that invert first-reference order in a group."""
    last = None
    errors = set()
    for position in group:
        ref = references.get(position)
        if ref is None:
            continue
        if last is not None and ref < last:
            errors.add(position)
        else:
            last = ref
    return errors


def figure_priority_warnings(group, kinds):
    """Mark figures placed below a table in an otherwise continuous group."""
    seen_table = False
    warnings = set()
    for position in group:
        if kinds[position] == "table":
            seen_table = True
        elif seen_table:
            warnings.add(position)
    return warnings


def nearest_column(distance, ref, extent, groups, height, max_top_fraction, body_tops=None):
    """Check proximity, allowing a preceding measured group to fill a column."""
    if distance <= 1:
        return True
    if distance != 2:
        return False
    previous_column = (ref.page + ref.column, 1 - ref.column)
    occupied = groups.get(previous_column)
    if not occupied:
        return False
    # Use the observed minimum separation so marginal cases still get a WARN.
    body_top = body_tops[previous_column[0]] if body_tops else BODY_MARGIN_PT
    occupied_bottom = max(box.bottom for box in occupied.values())
    projected_bottom = occupied_bottom + MIN_FLOAT_SEP_PT + extent.bottom - extent.top
    projected = Box(extent.left, body_top, extent.right, projected_bottom)
    column_height, _, fits = group_capacity(projected, height, max_top_fraction, body_top)
    # LaTeX's top-room budget also charges textfloatsep for the first float.
    reserved_height = projected_bottom - body_top + MIN_TEXT_FLOAT_SEP_PT
    return not fits or reserved_height > column_height * max_top_fraction


def page_geometry(pdf_page, height):
    """Read horizontal strokes and direct image placements in PDF coordinates."""
    matrix = (1, 0, 0, 1, 0, 0)
    stack, segments, rules = [], [], []
    images = []
    resources = pdf_page["/Resources"].get_object()
    xobjects = resources.get("/XObject", {}).get_object() if "/XObject" in resources else {}
    point = None

    def transform(x, y):
        a, b, c, d, e, f = matrix
        return (a * x + c * y + e, height - (b * x + d * y + f))

    for args, op in pdf_page.get_contents().operations:
        if op == b"q":
            stack.append(matrix)
        elif op == b"Q":
            matrix = stack.pop()
        elif op == b"cm":
            a, b, c, d, e, f = matrix
            g, h, i, j, k, l = map(float, args)
            matrix = (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)
        elif op == b"Do" and xobjects[args[0]].get("/Subtype") == "/Image":
            points = [transform(x, y) for x, y in ((0, 0), (0, 1), (1, 0), (1, 1))]
            xs, ys = zip(*points)
            images.append(Box(min(xs), min(ys), max(xs), max(ys)))
        elif op == b"m":
            point = transform(*map(float, args))
        elif op == b"l" and point is not None:
            end = transform(*map(float, args))
            if abs(point[1] - end[1]) < 0.1 and abs(point[0] - end[0]) >= 50:
                lo, hi = sorted((point[0], end[0]))
                segments.append(Box(lo, end[1], hi, end[1]))
            point = end
        elif op in (b"S", b"s", b"B", b"B*", b"b", b"b*", b"f", b"f*", b"n"):
            if op in (b"S", b"s", b"B", b"B*", b"b", b"b*"):
                rules.extend(segments)
            segments, point = [], None
    return rules, images


def caption_at(page, number, anchor_x, anchor_y, kind="table"):
    prefix = r"Fig\." if kind == "figure" else r"Table\s*\.?"
    pattern = re.compile(r"^" + prefix + r"\s*" + re.escape(number) + r"(?:\s|$)")
    candidates = []
    for block in page.findall(".//{*}block"):
        lines = block.findall("{*}line")
        if not lines:
            continue
        first = " ".join(w.text or "" for w in lines[0].findall("{*}word"))
        rect = xml_box(lines[0])
        if (pattern.match(first) and -1 <= rect.top - anchor_y <= 12
                and rect.left - 1 <= anchor_x <= rect.right + 1):
            caption = " ".join(w.text or "" for w in block.findall(".//{*}word"))
            candidates.append((xml_box(block), caption))
    if len(candidates) != 1:
        raise AuditError(f"expected one caption at the PDF destination, found {len(candidates)}")
    return candidates[0]


def figure_body(caption, images, column, width):
    """Match one same-column image immediately above a figure caption."""
    candidates = [image for image in images
                  if int(image.center >= width / 2) == column
                  and image.left <= caption.center <= image.right
                  and 0 <= caption.top - image.bottom <= CAPTION_GAP_PT]
    if len(candidates) != 1:
        raise AuditError(f"expected one image directly above the caption (R4), found {len(candidates)}")
    return candidates[0]


def table_body(caption, rules, words, column, width, next_caption_top):
    matches = sorted((r for r in rules
                      if (int(r.center >= width / 2) == column
                          and r.left <= caption.center <= r.right
                          and caption.bottom <= r.top < next_caption_top)),
                     key=lambda r: r.top)
    if not matches or matches[0].top - caption.bottom > CAPTION_GAP_PT:
        raise AuditError("no matching top rule directly below the caption (R4)")
    first = matches[0]
    aligned = [r for r in matches if abs(r.left - first.left) < 1 and abs(r.right - first.right) < 1]
    if len(aligned) < 3:
        raise AuditError("cannot identify the header and bottom rules of the table body (R4)")
    last = aligned[-1]
    rows = [w for w in words
            if first.top <= (w.top + w.bottom) / 2 <= last.top
            and int(w.center >= width / 2) == column]
    if len({round(w.top) for w in rows}) < 2:
        raise AuditError("cannot identify the text rows between table rules (R4)")
    return union([first, last, *rows])


def reference_position(pdf_pages, destination, excluded, body_tops):
    positions = []
    for index, page in enumerate(pdf_pages, 1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        for entry in page.get("/Annots", []):
            link = entry.get_object()
            action = link.get("/A", {})
            if action.get("/S") != "/GoTo" or action.get("/D") != destination:
                continue
            left, bottom, right, top = map(float, link["/Rect"])
            x, y = (left + right) / 2, height - (top + bottom) / 2
            if any(b.left <= x <= b.right and b.top <= y <= b.bottom for b in excluded[index - 1]):
                continue
            if body_tops[index] - TOP_TOLERANCE_PT <= y <= height - BODY_MARGIN_PT:
                positions.append(Position(index, int(x >= width / 2), height - top))
    return min(positions, default=None)


def top_fraction(tex_path):
    source = re.sub(r"(?<!\\)%[^\n]*", "", tex_path.read_text(encoding="utf-8-sig"))
    matches = re.findall(r"\\renewcommand\s*\{\\topfraction\}\s*\{([\d.]+)\}", source)
    if len(matches) != 1 or not 0 < float(matches[0]) <= 1:
        raise AuditError("expected one explicit numeric \\topfraction in the report preamble")
    return float(matches[0])


def first_page_body_top(reader):
    """Use the verified first body anchor after the full-width title/abstract."""
    destinations = reader.named_destinations
    start = destinations.get("Doc-Start")
    first_section = destinations.get("section.1")
    if start is not None and first_section is not None:
        if reader.get_destination_page_number(start) == reader.get_destination_page_number(first_section) == 0:
            if start.top is not None and start.top == first_section.top:
                page_height = float(reader.pages[0].mediabox.height)
                top = page_height - float(start.top)
                if BODY_MARGIN_PT - TOP_TOLERANCE_PT <= top < page_height - BODY_MARGIN_PT:
                    return top
    return BODY_MARGIN_PT


def audit(pdf_path, aux_path, tex_path):
    from pypdf import PdfReader

    source = tex_floats(tex_path)
    max_top_fraction = top_fraction(tex_path)
    floats = read_floats(aux_path, source)
    reader = PdfReader(pdf_path)
    xml = subprocess.run(["pdftotext", "-enc", "UTF-8", "-bbox-layout", str(pdf_path), "-"],
                         check=True, stdout=subprocess.PIPE).stdout
    pages = ET.fromstring(xml).findall(".//{*}page")
    if len(pages) != len(reader.pages):
        raise AuditError("PDF page count disagrees between text and geometry readers")
    body_tops = dict.fromkeys(range(1, len(pages) + 1), BODY_MARGIN_PT)
    body_tops[1] = first_page_body_top(reader)
    destinations = reader.named_destinations
    if {d for d in destinations if d.startswith(("figure.", "table."))} != {t.destination for t in floats}:
        raise AuditError("PDF figure/table destinations disagree with .aux; rebuild or label every float")

    captions, bodies, errors = {}, {}, {}
    rules, images, words = {}, {}, {}
    for t in floats:
        try:
            environment, graphics_count = source[t.label]
            if environment.endswith("*"):
                raise AuditError("full-width float requires manual placement review")
            if t.kind == "figure" and graphics_count != 1:
                raise AuditError("figure needs one identifiable image for automatic placement review")
            dest = destinations[t.destination]
            page_index = reader.get_destination_page_number(dest)
            if page_index + 1 != t.page:
                raise AuditError("caption page disagrees with .aux")
            p = pages[page_index]
            w, h = float(p.attrib["width"]), float(p.attrib["height"])
            if abs(w - 210 * PT_PER_MM) > 1 or abs(h - 297 * PT_PER_MM) > 1:
                raise AuditError("page geometry differs from the calibrated A4 layout")
            cap, title = caption_at(p, t.number, float(dest.left), h - float(dest.top), t.kind)
            column = int(float(dest.left) >= w / 2)
            captions[t] = cap, title, Position(t.page, column, cap.top), w, h
            if t.page not in rules:
                rules[t.page], images[t.page] = page_geometry(reader.pages[page_index], h)
                words[t.page] = [xml_box(node) for node in p.findall(".//{*}word")]
        except AuditError as exc:
            errors[t] = str(exc)

    excluded = [[] for _ in pages]
    for t in sorted(captions, key=lambda item: item.kind):  # Figures supply bounds for the tables below/above them.
        cap, _, pos, width, _ = captions[t]
        excluded[t.page - 1].append(cap)
        try:
            if t.kind == "figure":
                bodies[t] = figure_body(cap, images[t.page], pos.column, width)
            else:
                next_top = min(((bodies[other].top if other.kind == "figure" and other in bodies else other_pos.top)
                                for other, (_, _, other_pos, _, _) in captions.items()
                                if other_pos.page == pos.page and other_pos.column == pos.column
                                and other_pos.top > pos.top), default=float("inf"))
                bodies[t] = table_body(cap, rules[t.page], words[t.page], pos.column, width, next_top)
            excluded[t.page - 1].append(bodies[t])
        except AuditError as exc:
            errors[t] = str(exc)

    refs = {t: reference_position(reader.pages, t.destination, excluded, body_tops) for t in floats}
    refs_by_pos = {}
    floats_by_pos, positions = {}, {}
    column_floats = defaultdict(list)
    for t, (cap, _, caption_pos, _, _) in captions.items():
        # A failed body identification also blocks a continuous group below it.
        extent = union((cap, bodies[t])) if t in bodies else None
        pos = (Position(t.page, caption_pos.column, extent.top) if extent else caption_pos)
        positions[t] = pos
        refs_by_pos[pos] = refs[t]
        floats_by_pos[pos] = t
        column_floats[pos.page, pos.column].append((pos, extent))

    groups, capacity = {}, {}
    order_errors, priority_warnings = set(), set()
    for key, entries in sorted(column_floats.items()):
        page, column = key
        page_node = pages[page - 1]
        width, height = float(page_node.attrib["width"]), float(page_node.attrib["height"])
        group = top_group(entries, words[page], column, width, body_tops[page])
        groups[key] = group
        if group:
            extent = union(group.values())
            col_height, text_height, fits = group_capacity(extent, height, max_top_fraction, body_tops[page])
            capacity[key] = fits
            kinds = {pos: floats_by_pos[pos].kind for pos in group}
            for kind in ("figure", "table"):
                order_errors.update(reference_order_errors((pos for pos in group if kinds[pos] == kind), refs_by_pos))
            priority_warnings.update(figure_priority_warnings(group, kinds))
            names = ", ".join(floats_by_pos[pos].name for pos in group)
            print(f"Top group p{page} {'left' if column == 0 else 'right'}: {names}, "
                  f"y={extent.top:.1f} to {extent.bottom:.1f} pt, height={extent.bottom - extent.top:.1f} pt; "
                  f"available text region={text_height:.1f} pt ({text_height / col_height:.1%})")

    failed = False
    for t in floats:
        ref = refs[t]
        if t in errors:
            print(f"FAIL {t.name} ({t.label}): {errors[t]}; first linked reference={ref or 'missing'}")
            failed = True
            continue
        cap, title, caption_pos, width, height = captions[t]
        pos = positions[t]
        body = bodies[t]
        key = (pos.page, pos.column)
        flags, distance = placement_flags(pos, cap, body, ref, width, height,
                                          pos in groups[key], pos not in order_errors, t.kind, body_tops[pos.page])
        if ref is None:
            print(f"FAIL {t.name}: no first linked reference in body text")
        near = ref is not None and nearest_column(distance, ref, union((cap, body)),
                                                    groups, height, max_top_fraction, body_tops)
        page_gap = pos.page - ref.page if ref is not None else None
        fits = capacity.get(key, False)
        if not all(flags.values()):
            status = "FAIL"
        else:
            status = "PASS" if near and page_gap < 2 and fits and pos not in priority_warnings else "WARN"
        failed |= status == "FAIL"
        print(f"{status} {title} ({t.label})")
        print(f"  caption={caption_pos}; body=({body.left:.1f}, {body.top:.1f}, "
              f"{body.right:.1f}, {body.bottom:.1f}) pt; first reference={ref or 'missing'}")
        print("  " + ", ".join(f"{rule}={'yes' if valid else 'no'}" for rule, valid in flags.items()))
        evidence = "image rectangle" if t.kind == "figure" else "table rules"
        print(f"  distance={distance} column(s), {page_gap} page(s); evidence=PDF anchor, link and {evidence}")
        if status != "FAIL":
            proximity = "next column" if distance == 1 else "intervening column full by estimate" if near else "review"
            print(f"  R5 proximity={proximity}; R6 within one page={'yes' if page_gap < 2 else 'no'}; "
                  f"R8 group capacity={'yes' if fits else 'review'}")
            if pos in priority_warnings:
                print("  R9 figure priority: a table is above this figure in the same top group")
    print(f"Identified {len(captions)}/{len(floats)} captions and {len(bodies)}/{len(floats)} float bodies.")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, default=Path("build/main.pdf"))
    parser.add_argument("--aux", type=Path, help="defaults to the .aux next to the PDF")
    parser.add_argument("--tex", type=Path, default=Path("main.tex"))
    args = parser.parse_args()
    try:
        return audit(args.pdf, args.aux or args.pdf.with_suffix(".aux"), args.tex)
    except (AuditError, OSError, ValueError, KeyError, TypeError, ImportError,
            subprocess.CalledProcessError, ET.ParseError) as exc:
        print(f"ERROR: figure/table placement audit could not finish: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
