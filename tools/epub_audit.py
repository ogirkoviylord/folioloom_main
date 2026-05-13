#!/usr/bin/env python3
import argparse
import collections
import html
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"p", "div", "br", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def text(self):
        out = html.unescape("".join(self.parts))
        out = re.sub(r"[ \t\r\f\v]+", " ", out)
        out = re.sub(r"\n\s+", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def read_epub(path):
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        opf_path = container.find(".//c:rootfile", ns).attrib["full-path"]
        opf_dir = posixpath.dirname(opf_path)
        opf = ET.fromstring(zf.read(opf_path))
        ns_opf = {
            "opf": "http://www.idpf.org/2007/opf",
            "dc": "http://purl.org/dc/elements/1.1/",
        }
        meta = {}
        for tag in ["title", "creator", "language", "publisher", "date"]:
            el = opf.find(f".//dc:{tag}", ns_opf)
            meta[tag] = (el.text or "").strip() if el is not None else ""
        manifest = {
            item.attrib["id"]: item.attrib
            for item in opf.findall(".//opf:manifest/opf:item", ns_opf)
        }
        spine_ids = [item.attrib["idref"] for item in opf.findall(".//opf:spine/opf:itemref", ns_opf)]
        docs = []
        for idref in spine_ids:
            item = manifest.get(idref)
            if not item:
                continue
            href = item.get("href", "")
            media = item.get("media-type", "")
            if "html" not in media and not href.lower().endswith((".xhtml", ".html")):
                continue
            full = posixpath.normpath(posixpath.join(opf_dir, href))
            raw = zf.read(full).decode("utf-8", "replace")
            parser = TextExtractor()
            parser.feed(raw)
            text = parser.text()
            heading = next((line.strip() for line in text.splitlines() if line.strip()), "")
            docs.append({"path": full, "text": text, "heading": heading, "bytes": len(raw.encode("utf-8"))})
        return {"path": str(path), "names": names, "meta": meta, "docs": docs}


def word_count(text, alphabet):
    if alphabet == "latin":
        return len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text))
    return len(re.findall(r"\b[А-Яа-яЁё][А-Яа-яЁё-]*\b", text))


def caps_sequences(text, alphabet):
    if alphabet == "latin":
        pattern = r"\b(?:[A-Z][a-z]+(?:\s+|$)){1,4}"
    else:
        pattern = r"\b(?:[А-ЯЁ][а-яё]+(?:\s+|$)){1,4}"
    counts = collections.Counter(m.group(0).strip() for m in re.finditer(pattern, text))
    return counts.most_common(80)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("original")
    parser.add_argument("translation")
    parser.add_argument("--out", default="epub_audit_output")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    books = [read_epub(Path(args.original)), read_epub(Path(args.translation))]
    labels = ["original", "translation"]
    for label, book in zip(labels, books):
        all_text = "\n\n".join(doc["text"] for doc in book["docs"])
        (out / f"{label}.txt").write_text(all_text, encoding="utf-8")
        print(f"== {label} ==")
        print("metadata:", book["meta"])
        print("spine docs:", len(book["docs"]), "archive files:", len(book["names"]))
        print("chars:", len(all_text), "latin words:", word_count(all_text, "latin"), "cyrillic words:", word_count(all_text, "cyrillic"))
        print("first headings:")
        for doc in book["docs"][:10]:
            print(f"  {doc['path']}: {doc['heading'][:120]}")
        print()

    print("== chapter size ratios translation/original ==")
    for odoc, tdoc in zip(books[0]["docs"], books[1]["docs"]):
        otext, ttext = odoc["text"], tdoc["text"]
        ratio = (len(ttext) / len(otext)) if otext else 0
        print(f"{odoc['path']} -> {tdoc['path']}: {len(otext)} -> {len(ttext)} ({ratio:.2f}x)")

    print("\n== likely names original ==")
    for name, count in caps_sequences((out / "original.txt").read_text(encoding="utf-8"), "latin")[:60]:
        print(f"{count:4d} {name}")

    print("\n== likely names translation ==")
    for name, count in caps_sequences((out / "translation.txt").read_text(encoding="utf-8"), "cyrillic")[:80]:
        print(f"{count:4d} {name}")

    translated = (out / "translation.txt").read_text(encoding="utf-8")
    print("\n== residual latin words in translation ==")
    latin = collections.Counter(re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", translated))
    for word, count in latin.most_common(80):
        print(f"{count:4d} {word}")


if __name__ == "__main__":
    main()
