"""Turn a case folder (or .zip) of bank documents into plain text the builder agent can read.

    python builder/materials.py CASE_FOLDER_OR_ZIP OUT_DIR

Markdown, text, JSON, CSV and YAML are copied as they are. Word (.docx) and Excel (.xlsx) are read
with the standard library (they are zip files of XML). PDF is read with pypdf when it is installed;
otherwise, and for images, the file is listed in INDEX.md for the agent to open with its Read tool.
Holds no bank rule.
"""
import pathlib, re, shutil, sys, zipfile
import xml.etree.ElementTree as ET

TEXT = {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".tsv", ".html", ".htm", ".xml", ".js", ".ts", ".py", ".sql"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def docx_text(path):
    out = []
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    for el in body:
        if el.tag == W + "p":
            out.append(_para(el))
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells = [" ".join(_para(p) for p in tc.iter(W + "p")).strip() for tc in tr.findall(W + "tc")]
                out.append(" | ".join(cells))
            out.append("")
    return "\n".join(out)


def _para(p):
    style = p.find(f"{W}pPr/{W}pStyle")
    text = "".join((t.text or "") if t.tag == W + "t" else ("\t" if t.tag == W + "tab" else "\n") for t in p.iter() if t.tag in (W + "t", W + "tab", W + "br"))
    level = style.get(W + "val", "") if style is not None else ""
    m = re.match(r"(?i)heading\s*(\d)|ba.l.k\s*(\d)", level)
    if m and text.strip():
        return "#" * int(m.group(1) or m.group(2)) + " " + text
    if (p.find(f"{W}pPr/{W}numPr") is not None or "list" in level.lower()) and text.strip():
        return "- " + text
    return text


def xlsx_text(path):
    out = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
                rels[rel.get("Id")] = rel.get("Target")
        for sheet in wb.iter(S + "sheet"):
            target = rels.get(sheet.get(R + "id"), "")
            target = target.lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            if target not in names:
                continue
            out.append(f"## Sheet: {sheet.get('name')}")
            root = ET.fromstring(z.read(target))
            for row in root.iter(S + "row"):
                cells = []
                for c in row.findall(S + "c"):
                    ref = c.get("r", "")
                    col = re.sub(r"\d", "", ref)
                    while len(cells) < _col(col):
                        cells.append("")
                    v = c.find(S + "v")
                    t = c.get("t")
                    if t == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(S + "t"))
                    else:
                        val = (v.text or "") if v is not None else ""
                        f = c.find(S + "f")
                        if f is not None and f.text:
                            val = f"{val} (formula ={f.text})".strip()
                    cells.append(val or "")
                if any(cells):
                    out.append("\t".join(cells))
            out.append("")
    out.append("Note: dates in Excel may appear as serial numbers (days since 1899-12-30).")
    return "\n".join(out)


def _col(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return max(n - 1, 0)


def pdf_text(path):
    try:
        import pypdf
    except Exception:
        return None
    reader = pypdf.PdfReader(str(path))
    return "\n\n".join(f"--- page {i + 1} ---\n" + (page.extract_text() or "") for i, page in enumerate(reader.pages))


def convert(src, out_dir):
    src = pathlib.Path(src)
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    if src.is_file() and src.suffix.lower() == ".zip":
        unpacked = out_dir / "_case"
        with zipfile.ZipFile(src) as z:
            z.extractall(unpacked)
        src = unpacked
    rows = []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        if any(part.startswith(("__MACOSX", ".")) for part in rel.parts):
            continue
        ext = f.suffix.lower()
        target = out_dir / (str(rel).replace("/", "__").replace("\\", "__") + ".txt")
        note = ""
        try:
            if ext in TEXT:
                text = f.read_text(encoding="utf-8", errors="replace")
            elif ext == ".docx":
                text = docx_text(f)
            elif ext in (".xlsx", ".xlsm"):
                text = xlsx_text(f)
            elif ext == ".pdf":
                text = pdf_text(f)
                if text is None or len(text.strip()) < 40:
                    text, note = None, "PDF without extractable text here: open it with the Read tool"
            elif ext in IMAGES:
                text, note = None, "image (a drawing): open it with the Read tool"
            else:
                text, note = None, "unknown type: open it with the Read tool if it matters"
        except Exception as e:
            text, note = None, f"could not convert ({e!r}): open it with the Read tool"
        if text is not None:
            target.write_text(text, encoding="utf-8")
            rows.append((str(rel), str(target), f"{len(text)} chars", note))
        else:
            rows.append((str(rel), str(f.resolve()), "", note))
    index = ["# Case materials", "", f"Source: {src}", "",
             "| Original file | Read this | Size | Note |", "|---|---|---|---|"]
    index += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    (out_dir / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return out_dir / "INDEX.md", rows


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    idx, rows = convert(sys.argv[1], sys.argv[2])
    print(idx.read_text(encoding="utf-8"))
