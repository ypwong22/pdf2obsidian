# PDF → Obsidian (minerU 2.x)

This tool converts scientific PDFs into **Obsidian-ready** notes using the `mineru` **CLI** (v2.x).  
It supports:
- Input: a single PDF file **or** a folder of PDFs
- Output per paper:
  - Folder named **FirstThreeAuthors-Year-Journal**
  - `main.md` (full text with Obsidian links for figures & tables)
  - `figures/FigX.png` + `figures/FigX.md` (caption + referenced paragraphs + notes)
  - `tables/TableX.csv` + `tables/TableX.md` (caption + referenced paragraphs + notes)
  - `notes.md`
- `index.md` at the output root:
  - If missing → created
  - If exists → **appended** with new entries

> Works with **minerU 2.x**: output of `mineru extract` is a **directory**; this script reads the best JSON (or combines multiple files) and normalizes the result.

---

## Requirements

- The test environment is Python 3.10.10, minerU 2.5.4 (you should be able to run `mineru extract ...`).
- See environment.yml for the python setup

---

## Usage

```bash
# Single PDF
python pdf2obsidian.py -i ~/papers/awesome.pdf -o ~/Obsidian/Literature

# A folder of PDFs
python pdf2obsidian.py -i ~/papers -o ~/Obsidian/Literature
