#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional


# ---------- 工具函数 ----------

def safe_name(text: str, limit: int = 60) -> str:
    if not isinstance(text, str):
        text = str(text or "")
    text = re.sub(r"[\\/:*?\"<>|#%^$@!~`+=\[\]{};,\n\r\t]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def prompt_for_metadata(pdf_path: Path) -> dict:
    print(f"\n📄 Processing file: {pdf_path.name}")
    authors = input("请输入 <=3 个作者的 last name (逗号分隔): ").strip()
    year = input("请输入年份: ").strip()
    journal = input("请输入期刊简称: ").strip()

    authors_list = [a.strip() for a in authors.split(",") if a.strip()]
    if len(authors_list) > 3:
        authors_list = authors_list[:3]

    return {
        "authors": authors_list or ["Unknown"],
        "year": year or "noyear",
        "journal": journal or "nojournal"
    }


def make_folder_name(meta: dict) -> str:
    names = meta.get("authors") or ["Unknown"]
    author_part = "_".join(names)
    year = meta.get("year", "noyear")
    journal = meta.get("journal", "nojournal")
    return f"{safe_name(author_part)}-{year}-{safe_name(journal)}"


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def find_references(paragraphs: List[str], label: str) -> List[str]:
    if not paragraphs:
        return []
    pat = re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE)
    out, seen = [], set()
    for p in paragraphs:
        if isinstance(p, str) and pat.search(p):
            ps = p.strip()
            if ps and ps not in seen:
                out.append(ps)
                seen.add(ps)
    return out


# ---------- minerU 调用与解析 ----------

def run_mineru_cli(pdf_path: Path, out_dir: Path):
    ensure_dir(out_dir)
    cmd = ["mineru", "extract", "-p", str(pdf_path), "-o", str(out_dir)]
    subprocess.run(cmd, check=True)


def load_content_list_json(out_dir: Path) -> Optional[List[Dict[str, Any]]]:
    cands = sorted(out_dir.rglob("*_content_list.json"), key=lambda p: p.stat().st_size, reverse=True)
    for jf in cands:
        try:
            data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return None


def normalize_from_content_list(clist: List[Dict[str, Any]], base_dir: Path) -> Dict[str, Any]:
    text_blocks: List[str] = []
    paragraphs: List[str] = []
    for b in clist:
        if b.get("type") in ("title", "text"):
            s = (b.get("text") or "").strip()
            if s:
                text_blocks.append(s)
                paragraphs.append(s)
    full_text = "\n\n".join(text_blocks)

    # figures from JSON (only metadata, real copy later)
    figures = []
    fig_idx = 0
    for b in clist:
        if b.get("type") == "image":
            fig_idx += 1
            cap_list = b.get("img_caption") or []
            cap = " ".join([c.strip() for c in cap_list if c and isinstance(c, str)])
            figures.append({"id": fig_idx, "caption": cap, "image_path": None})

    # tables
    tables = []
    tab_idx = 0
    for b in clist:
        if b.get("type") == "table":
            tab_idx += 1
            cap_list = b.get("table_caption") or []
            cap = " ".join([c.strip() for c in cap_list if c and isinstance(c, str)])
            table_body = b.get("table_body")
            csv_path = None
            if table_body and isinstance(table_body, str) and "<table" in table_body.lower():
                try:
                    import pandas as pd
                    dfs = pd.read_html(table_body)
                    if dfs:
                        tables_dir = base_dir / "tables"
                        tables_dir.mkdir(exist_ok=True)
                        csv_path = tables_dir / f"Table{tab_idx}.csv"
                        dfs[0].to_csv(csv_path, index=False)
                except Exception:
                    tables_dir = base_dir / "tables"
                    tables_dir.mkdir(exist_ok=True)
                    html_path = tables_dir / f"Table{tab_idx}.html"
                    html_path.write_text(table_body, encoding="utf-8")
                    csv_path = html_path
            tables.append({"id": tab_idx, "caption": cap, "csv_path": csv_path})

    return {
        "text": full_text,
        "paragraphs": paragraphs,
        "figures": figures,
        "tables": tables,
    }


# ---------- 处理全文 md (找图片、改 main.md) ----------

def get_article_md(mineru_out_dir: Path) -> tuple[Optional[Path], str]:
    md_candidates = sorted(mineru_out_dir.rglob("*.md"),
                           key=lambda p: p.stat().st_size if p.is_file() else 0,
                           reverse=True)
    if md_candidates:
        p = md_candidates[0]
        return p, p.read_text(encoding="utf-8", errors="ignore")
    return None, ""


def extract_image_paths_from_md(md_text: str, md_file_dir: Path) -> list[Path]:
    paths = []
    for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', md_text):
        raw = m.group(1).strip()
        clean = re.split(r'\s+"', raw, 1)[0]
        clean = re.split(r'[#?]', clean, 1)[0]
        p = Path(clean)
        if not p.is_absolute():
            p = (md_file_dir / clean).resolve()
        paths.append(p)
    for m in re.finditer(r'<img[^>]*src=["\']([^"\']+)["\']', md_text, flags=re.IGNORECASE):
        raw = m.group(1).strip()
        clean = re.split(r'[#?]', raw, 1)[0]
        p = Path(clean)
        if not p.is_absolute():
            p = (md_file_dir / clean).resolve()
        paths.append(p)
    seen, out = set(), []
    for p in paths:
        try:
            rp = p.resolve()
        except Exception:
            continue
        if rp.exists() and rp not in seen:
            out.append(rp)
            seen.add(rp)
    return out


def copy_figures_from_md(md_img_paths: list[Path], fig_dir: Path, figures: list[dict]):
    ensure_dir(fig_dir)
    n_md = len(md_img_paths)
    n_fig = len(figures)
    if n_md > n_fig:
        for i in range(n_fig + 1, n_md + 1):
            figures.append({"id": i, "caption": "", "image_path": None})
    for idx, src in enumerate(md_img_paths, start=1):
        ext = src.suffix.lower() if src.suffix else ".png"
        target = fig_dir / f"Fig{idx}{ext}"
        try:
            shutil.copy2(src, target)
            figures[idx - 1]["obsidian_path"] = target.name
        except Exception:
            figures[idx - 1]["obsidian_path"] = f"Fig{idx}{ext}"


def generate_main_md_from_article(article_md_text: str, figures: list[dict], tables: list[dict], out_path: Path):
    text = article_md_text or ""

    # 去掉 markdown 图片
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 去掉 HTML <img>
    text = re.sub(r'<img[^>]*>', '', text, flags=re.IGNORECASE)
    # 去掉 markdown 表格
    text = re.sub(r'(?:^\|.*\|\s*\n?)+', '', text, flags=re.MULTILINE)
    # 去掉 HTML 表格
    text = re.sub(r'<table.*?>.*?</table>', '', text, flags=re.IGNORECASE | re.DOTALL)

    # 替换 Figure/Table 引用
    for fg in figures:
        fid = fg.get("id")
        text = re.sub(rf'\b(Figure\s+{fid}|Fig\.\s*{fid})\b',
                      f'[[figures/Fig{fid}]]', text, flags=re.IGNORECASE)

    for tb in tables:
        tid = tb.get("id")
        text = re.sub(rf'\b(Table\s+{tid})\b',
                      f'[[tables/Table{tid}]]', text, flags=re.IGNORECASE)

    out_path.write_text(text, encoding="utf-8")


# ---------- 输出 Obsidian ----------

def write_obsidian_bundle(data: Dict[str, Any], meta: Dict[str, Any], out_root: Path, mineru_out: Path) -> str:
    folder_name = make_folder_name(meta)
    base = out_root / folder_name
    ensure_dir(base)

    (base / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    article_md_path, article_md_text = get_article_md(mineru_out)
    md_img_paths = extract_image_paths_from_md(article_md_text, article_md_path.parent if article_md_path else mineru_out)

    fig_dir = base / "figures"
    tab_dir = base / "tables"
    ensure_dir(fig_dir)
    ensure_dir(tab_dir)

    figures: list[dict] = data.get("figures", [])
    copy_figures_from_md(md_img_paths, fig_dir, figures)

    for tb in data.get("tables", []):
        tab_id = tb.get("id")
        src = tb.get("csv_path")
        if src and Path(src).exists():
            target = tab_dir / (f"Table{tab_id}{Path(src).suffix.lower()}" if Path(src).suffix else f"Table{tab_id}.csv")
            shutil.copy2(src, target)
            tb["obsidian_path"] = target.name

    generate_main_md_from_article(article_md_text, figures, data.get("tables", []), base / "main.md")

    paragraphs = data.get("paragraphs") or []

    for fg in figures:
        fig_id = fg.get("id")
        cap = fg.get("caption") or ""
        refs = find_references(paragraphs, f"Figure {fig_id}")
        img_name = fg.get("obsidian_path", f"Fig{fig_id}.png")
        md = [f"![[{img_name}]]\n", f"**Caption:** {cap}\n"]
        if refs:
            md.append("**Referenced in text:**")
            md.extend([f"- {r}" for r in refs])
        md.append("\n**My Notes:**\n- [ ] ")
        (fig_dir / f"Fig{fig_id}.md").write_text("\n".join(md), encoding="utf-8")

    for tb in data.get("tables", []):
        tab_id = tb.get("id")
        cap = tb.get("caption") or ""
        refs = find_references(paragraphs, f"Table {tab_id}")
        link = tb.get("obsidian_path", f"Table{tab_id}.csv")
        body = "Table" if link.endswith(".csv") else ("Table (HTML)" if link.endswith(".html") else "Table (other)")
        md = [f"**{body}:** [[{link}]]\n", f"**Caption:** {cap}\n"]
        if refs:
            md.append("**Referenced in text:**")
            md.extend([f"- {r}" for r in refs])
        md.append("\n**My Notes:**\n- [ ] ")
        (tab_dir / f"Table{tab_id}.md").write_text("\n".join(md), encoding="utf-8")

    (base / "notes.md").write_text("# Overall Notes\n\n- [ ] ", encoding="utf-8")
    return folder_name


# ---------- 顶层流程 ----------

def process_single_pdf(pdf_path: Path, out_root: Path) -> Optional[str]:
    meta = prompt_for_metadata(pdf_path)

    with tempfile.TemporaryDirectory(prefix="mineru_out_") as tmpd:
        tmp_dir = Path(tmpd)
        run_mineru_cli(pdf_path, tmp_dir)
        clist = load_content_list_json(tmp_dir)
        if clist:
            data = normalize_from_content_list(clist, tmp_dir)
        else:
            data = {"text": "", "paragraphs": [], "figures": [], "tables": []}
        folder_name = write_obsidian_bundle(data, meta, out_root, tmp_dir)
    print(f"✅ Done: {folder_name}")
    return folder_name


def batch_process(pdf_input: Path, out_root: Path) -> List[str]:
    created: List[str] = []
    if pdf_input.is_file() and pdf_input.suffix.lower() == ".pdf":
        name = process_single_pdf(pdf_input, out_root)
        if name:
            created.append(name)
    elif pdf_input.is_dir():
        for pdf in sorted(pdf_input.glob("*.pdf")):
            name = process_single_pdf(pdf, out_root)
            if name:
                created.append(name)
    else:
        print(f"❌ Error: {pdf_input} is neither a PDF file nor a folder.")
    return created


def update_index(out_root: Path, new_entries: List[str]):
    if not new_entries:
        return
    index_path = out_root / "index.md"
    mode = "a" if index_path.exists() else "w"
    with open(index_path, mode, encoding="utf-8") as f:
        if mode == "w":
            f.write("# Literature Index\n\n")
        for name in new_entries:
            f.write(f"- [[{name}/main|{name}]]\n")
    print(f"📑 Index file updated at {index_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract PDFs into Obsidian-ready folders with minerU")
    parser.add_argument("-i", "--input", required=True, help="Input PDF file or folder")
    parser.add_argument("-o", "--output", required=True, help="Output folder (Obsidian vault subfolder)")
    args = parser.parse_args()

    pdf_input = Path(args.input).expanduser().resolve()
    out_root = Path(args.output).expanduser().resolve()
    ensure_dir(out_root)

    created = batch_process(pdf_input, out_root)
    update_index(out_root, created)


if __name__ == "__main__":
    main()
