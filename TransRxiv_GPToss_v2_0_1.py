# biorxiv_gui_full_fixed.py
# -*- coding: utf-8 -*-
"""
bioRxiv/medRxiv details API → タイトル/抄録を LM Studio で日本語訳 → HTML出力（GUI）

今回の更新:
- 🔧 HTML ビューアのズームバー（スライダー／＋－／Reset）を削除
- 外部リンク (https://...) は既定ブラウザで開く → tkinterweb の 404風ページを回避
- <base> だけ注入。 target="_blank" の強制書き換えは廃止（Chrome 等の自然挙動を維持）
- ビューアに Home ボタン実装（最初に開いたページへ戻る）
- pack(side="LEFT") を "left" に修正（過去エラー対策）
- 421 対策: requests に Connection: close + UA を付与
"""

import os
import re
import sys
import json
import time
import random
import calendar
import threading
import urllib.parse
import webbrowser
from datetime import date as ddate, timedelta
from html import escape
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# ========== 依存ライブラリ ==========
try:
    import requests
except Exception:
    raise SystemExit("このスクリプトには 'requests' が必要です。 pip install requests")

try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    pygame = None
    PYGAME_AVAILABLE = False

try:
    from tkcalendar import DateEntry
    HAS_TKCALENDAR = True
except Exception:
    HAS_TKCALENDAR = False

# tkinterweb（HTML埋め込み）
TKWEB_IMPORT_ERR = ""
HAS_TKINTERWEB = False
HtmlFrame = None
try:
    from tkinterweb import HtmlFrame as _HtmlFrame
    HtmlFrame = _HtmlFrame
    HAS_TKINTERWEB = True
except Exception as _e1:
    TKWEB_IMPORT_ERR = f"{type(_e1).__name__}: {_e1}"
    try:
        from tkinterweb.htmlwidgets import HtmlFrame as _HtmlFrame
        HtmlFrame = _HtmlFrame
        HAS_TKINTERWEB = True
        TKWEB_IMPORT_ERR = ""
    except Exception as _e2:
        TKWEB_IMPORT_ERR += f" | alt: {type(_e2).__name__}: {_e2}"

# フォント列挙
try:
    import tkinter.font as tkfont
    HAS_TKFONT = True
except Exception:
    tkfont = None
    HAS_TKFONT = False

# ========== 定数 ==========
DEFAULT_API_BASE = "https://api.biorxiv.org/details"
DEFAULT_SERVER = "biorxiv"
LMSTUDIO_API_URL_DEFAULT = "http://127.0.0.1:1234/v1/chat/completions"
LMSTUDIO_MODEL_DEFAULT = "openai/gpt-oss-20b"

LM_TEMPERATURE = 0.2
LM_MAX_RETRY = 2
TIMEOUT_SEC = 60

PERIOD_MAP = {"Day": 1, "Week": 7, "Month": 30, "Year": 365}

LICENSE_PRESETS = [
    "Any",
    "cc_by",
    "cc_by_nc",
    "cc_by_nd",
    "cc_by_sa",
    "cc_by_nc_nd",
    "cc_by_nc_sa",
]

CATALOG_FILENAME = "catalog.json"

REQ_HEADERS = {
    "User-Agent": "biorxiv-gui/1.0 (+https://example.local)",
    "Connection": "close",
}

# ========== ユーティリティ ==========
def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def write_text(path: Path, text: str) -> None:
    ensure_parent_dir(path)
    path.write_text(text, encoding="utf-8")

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""

def html_escape_or_none(s: Optional[str]) -> str:
    return "" if s is None else escape(str(s))

def slugify_category(cat: Optional[str]) -> str:
    s = (cat or "uncategorized").strip()
    s = s.replace(" ", "_")
    s = re.sub(r"[\/\\]+", "_", s)
    s = re.sub(r"[^\w\.-]", "_", s, flags=re.UNICODE)
    return s or "uncategorized"

def extract_doi_parts(doi: str) -> Tuple[str, str]:
    doi = doi.strip()
    if "/" not in doi:
        raise ValueError(f"Unexpected DOI format: {doi}")
    right = doi.split("/", 1)[1]
    parts = right.split(".")
    if len(parts) < 4:
        raise ValueError(f"Unexpected DOI right part: {right}")
    doidate = ".".join(parts[0:3])
    doino = parts[3]
    return doidate, doino

def doi_parts_to_1101_url(doidate: str, doino: str) -> str:
    return f"https://doi.org/10.1101/{doidate}.{doino}"

def make_row_id(date: str, category: str, doidate: str, doino: str) -> str:
    return f"{date}__{category}__{doidate}__{doino}"

def _fallback_open(path_or_url: str):
    try:
        if str(path_or_url).startswith(("http://", "https://")):
            webbrowser.open(path_or_url)
        else:
            webbrowser.open(Path(path_or_url).resolve().as_uri())
    except Exception:
        pass

# ========== HTML テンプレ ==========
HTML_DOC_TPL = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans JP', Roboto, 'Hiragino Sans', 'Yu Gothic', 'Meiryo', sans-serif; line-height: 1.65; padding: 1.2rem; }}
h1 {{ font-size: 1.6rem; margin: 0 0 .6rem; }}
h2 {{ font-size: 1.2rem; margin: 1.2rem 0 .4rem; }}
p  {{ margin: .5rem 0; }}
.small {{ color: #666; font-size: .9rem; }}
a {{ color: #0366d6; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.meta {{ margin:.5rem 0 1rem; color:#333; }}
.table-wrap {{ margin-top: 1.2rem; overflow-x:auto; }}
.footer {{ margin-top:2rem; font-size:.9rem; color:#666; }}
</style>
</head>
<body>
<article>
  <h1>{title_ja}</h1>
  <div class="meta small">
    <div><strong>原題:</strong> {title_en}</div>
    <div><strong>日付:</strong> {date}　/　<strong>カテゴリ:</strong> {category}　/　<strong>サーバ:</strong> {server}</div>
    <div><strong>DOI:</strong> <a href="{doi_1101_url}" target="_blank" rel="noopener">{doi_1101_url}</a></div>
    <div><strong>DOI (raw):</strong> <a href="{doi_url}" target="_blank" rel="noopener">{doi_raw}</a></div>
    {jats_line}
  </div>

  <h2>抄録（日本語）</h2>
  <p>{abstract_ja}</p>

  <h2>Abstract (Original)</h2>
  <p>{abstract_en}</p>

  <h2>Authors</h2>
  <p>{authors}</p>

  <h2>License</h2>
  <p>{license}</p>

  <h2>Corresponding</h2>
  <p><strong>author_corresponding:</strong> {author_corresponding}</p>
  <p><strong>author_corresponding_institution:</strong> {author_corresponding_institution}</p>

  <h2>Version / Type</h2>
  <p><strong>Version:</strong> {version}</p>
  <p><strong>Type:</strong> {type_str}</p>
</article>

<div class="footer">Generated by biorxiv_gui_full_fixed.py</div>
</body>
</html>
"""

HTML_INDEX_TPL = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans JP', Roboto, 'Hiragino Sans', 'Yu Gothic', 'Meiryo', sans-serif; line-height: 1.6; padding:1.2rem; }}
h1 {{ font-size: 1.5rem; margin: .2rem 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: .4rem .5rem; text-align: left; }}
th {{ background: #f3f4f6; }}
.small {{ color:#666; font-size:.92rem; }}
a {{ color: #0366d6; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="small">{subtitle}</div>
<div class="table-wrap">
<table>
<thead>
<tr>
  {header_cols}
</tr>
</thead>
<tbody>
<!--ROWS-->
</tbody>
</table>
</div>
</body>
</html>
"""

# ========== HTML index helpers ==========
def build_index_row(date: str, category_display: str, doidate: str, doino: str,
                    local_href: str, doi_href: str) -> str:
    row_id = make_row_id(date, category_display, doidate, doino)
    cells = [
        escape(doino),
        escape(doidate),
        f'<a href="{escape(local_href)}" target="_self" rel="noopener">open</a>',
        f'<a href="{escape(doi_href)}" target="_blank" rel="noopener">{escape(doi_href)}</a>',
        escape(category_display),
    ]
    return f'<tr data-rowid="{escape(row_id)}"><td>' + "</td><td>".join(cells) + "</td></tr>\n"

def ensure_index_file(path: Path, title: str, subtitle: str, header_cols: List[str]) -> None:
    if not path.exists():
        html = HTML_INDEX_TPL.format(
            title=escape(title),
            subtitle=escape(subtitle),
            header_cols="".join(f"<th>{escape(h)}</th>" for h in header_cols),
        )
        write_text(path, html)

def append_row_if_absent(index_path: Path, row_html: str, rowid: str) -> None:
    html = read_text(index_path)
    if f'data-rowid="{rowid}"' in html:
        return
    if "<!--ROWS-->" in html:
        html = html.replace("<!--ROWS-->", row_html + "<!--ROWS-->")
    else:
        html = html.replace("</tbody>", row_html + "</tbody>")
    write_text(index_path, html)

def prepend_row_if_absent(index_path: Path, row_html: str, rowid: str) -> None:
    html = read_text(index_path)
    if f'data-rowid="{rowid}"' in html:
        return
    html = re.sub(r"(<tbody>\s*)", r"\1" + row_html, html, count=1, flags=re.DOTALL)
    write_text(index_path, html)

# ========== フォント ==========
def list_system_fonts() -> list:
    if not HAS_TKFONT:
        return []
    try:
        fams = tkfont.families()
        uniq = sorted(set([str(f) for f in fams]))
        preferred = ["Meiryo", "Yu Gothic UI", "Yu Gothic", "Segoe UI", "Noto Sans JP", "Hiragino Sans", "MS Gothic"]
        ordered = [f for f in preferred if f in uniq] + [f for f in uniq if f not in preferred]
        return ordered
    except Exception:
        return []

def css_quote_font(font_name: str) -> str:
    if not font_name:
        return ""
    return '"' + font_name.replace('"', '\\"') + '"'

def inject_font_css(html: str, font_name: str) -> str:
    if not font_name:
        return html
    try:
        q = css_quote_font(font_name)
        css = f"<style>body, html, p, a, li, td, th, h1, h2, h3, h4, h5, h6 {{ font-family: {q}, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans JP', Roboto, 'Hiragino Sans', 'Yu Gothic', 'Meiryo', sans-serif !important; }}</style>"
        if "<head" in html:
            return re.sub(r"(<head[^>]*>)", r"\1" + css, html, count=1, flags=re.IGNORECASE|re.DOTALL)
        return css + html
    except Exception:
        return html

# ========== all_date / logs ==========
def update_all_date_index(base_dir: Path, date: str, collected: int):
    all_index = base_dir / "date" / "all_date.html"
    ensure_index_file(
        all_index,
        title="All Dates Index",
        subtitle="全日付の索引（date, index, collected）",
        header_cols=["date", "index", "collected"],
    )
    rowid = date
    local_href = f"./{date}/date.html"
    row_html = (
        f'<tr data-rowid="{escape(rowid)}">'
        f'<td>{escape(date)}</td>'
        f'<td><a href="{escape(local_href)}" target="_self" rel="noopener">{escape(local_href)}</a></td>'
        f'<td>{int(collected)}</td>'
        f'</tr>\n'
    )
    append_row_if_absent(all_index, row_html, rowid)

def update_month_log(base_dir: Path, date: str, collected: int):
    y, m, _ = date.split("-")
    month_index = base_dir / "log" / y / m / "all_month.html"
    ensure_index_file(
        month_index,
        title=f"All Dates in {y}-{m}",
        subtitle="当月の索引（date, index, collected）",
        header_cols=["date", "index", "collected"],
    )
    local_href = f"../../../date/{date}/date.html"
    rowid = date
    row_html = (
        f'<tr data-rowid="{escape(rowid)}">'
        f'<td>{escape(date)}</td>'
        f'<td><a href="{escape(local_href)}" target="_self" rel="noopener">{escape(local_href)}</a></td>'
        f'<td>{int(collected)}</td>'
        f'</tr>\n'
    )
    append_row_if_absent(month_index, row_html, rowid)

def update_year_log(base_dir: Path, date: str):
    y, m, _ = date.split("-")
    year_index = base_dir / "log" / "year" / "all_year.html"
    ensure_index_file(
        year_index,
        title="All Months Index",
        subtitle="年次索引（YYYY-MM, monthly index link）",
        header_cols=["YYYY-MM", "index"],
    )
    ym = f"{y}-{m}"
    local_href = f"../{y}/{m}/all_month.html"
    rowid = ym
    row_html = (
        f'<tr data-rowid="{escape(rowid)}">'
        f'<td>{escape(ym)}</td>'
        f'<td><a href="{escape(local_href)}" target="_self" rel="noopener">{escape(local_href)}</a></td>'
        f'</tr>\n'
    )
    append_row_if_absent(year_index, row_html, rowid)

# ========== daily_report / category_report ==========
def update_daily_report(base_dir: Path, date: str, cat_slug: str, category_display: str,
                        doidate: str, doino: str, title_ja: str, license_str: str):
    path = base_dir / "date" / date / "daily_report.html"
    ensure_index_file(
        path,
        title=f"Daily Report for {date}",
        subtitle=f"{date} の処理結果",
        header_cols=["title_ja", "local", "doi", "category", "license"],
    )
    local_href = f"./{cat_slug}/{doidate}/{doino}.html"
    doi_href = doi_parts_to_1101_url(doidate, doino)
    rowid = make_row_id(date, category_display, doidate, doino)
    row = (
        f'<tr data-rowid="{escape(rowid)}">'
        f'<td>{escape(title_ja)}</td>'
        f'<td><a href="{escape(local_href)}" target="_self" rel="noopener">open</a></td>'
        f'<td><a href="{escape(doi_href)}" target="_blank" rel="noopener">doi</a></td>'
        f'<td>{escape(category_display)}</td>'
        f'<td>{escape(license_str or "")}</td>'
        f'</tr>\n'
    )
    append_row_if_absent(path, row, rowid)

def update_category_report(base_dir: Path, date: str, cat_slug: str, category_display: str,
                           doidate: str, doino: str, title_ja: str, license_str: str):
    path = base_dir / "category" / cat_slug / "category_report.html"
    ensure_index_file(
        path,
        title=f"Category Report: {category_display}",
        subtitle="新規登録順（上が最新）",
        header_cols=["date", "title_ja", "local", "doi", "license"],
    )
    local_href = f"../../date/{date}/{cat_slug}/{doidate}/{doino}.html"
    doi_href = doi_parts_to_1101_url(doidate, doino)
    rowid = make_row_id(date, category_display, doidate, doino)
    row = (
        f'<tr data-rowid="{escape(rowid)}">'
        f'<td>{escape(date)}</td>'
        f'<td>{escape(title_ja)}</td>'
        f'<td><a href="{escape(local_href)}" target="_self" rel="noopener">open</a></td>'
        f'<td><a href="{escape(doi_href)}" target="_blank" rel="noopener">doi</a></td>'
        f'<td>{escape(license_str or "")}</td>'
        f'</tr>\n'
    )
    prepend_row_if_absent(path, row, rowid)

# ========== catalog.json ==========
def catalog_path(base_dir: Path) -> Path:
    return base_dir / CATALOG_FILENAME

def load_catalog(base_dir: Path) -> Dict[str, Any]:
    p = catalog_path(base_dir)
    if not p.exists():
        return {"version": 1, "items": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"version": 1, "items": []}

def save_catalog(base_dir: Path, catalog: Dict[str, Any]) -> None:
    p = catalog_path(base_dir)
    ensure_parent_dir(p)
    with p.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

def upsert_catalog_item(base_dir: Path, item: Dict[str, Any]) -> None:
    cat = load_catalog(base_dir)
    key = item.get("key") or ""
    for i, it in enumerate(cat["items"]):
        if it.get("key") == key:
            cat["items"][i] = item
            save_catalog(base_dir, cat)
            return
    cat["items"].append(item)
    save_catalog(base_dir, cat)

def build_catalog_item(date: str, category_display: str, cat_slug: str, doidate: str, doino: str,
                       title_ja: str, title_en: str, license_str: str, server: str, doi_raw: str) -> Dict[str, Any]:
    key = make_row_id(date, category_display, doidate, doino)
    local_html_rel = str(Path("date") / date / cat_slug / doidate / f"{doino}.html")
    return {
        "key": key,
        "date": date,
        "category": category_display,
        "cat_slug": cat_slug,
        "doidate": doidate,
        "doino": doino,
        "title_ja": title_ja,
        "title_en": title_en,
        "license": license_str or "",
        "server": server,
        "doi_raw": doi_raw,
        "doi_url": doi_parts_to_1101_url(doidate, doino),
        "html_rel": local_html_rel,
        "ts": time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()),
    }

# ========== API / 翻訳 ==========
def load_json_from_url(url: str, timeout: int = TIMEOUT_SEC) -> dict:
    r = requests.get(url, timeout=timeout, headers=REQ_HEADERS)
    r.raise_for_status()
    return r.json()

def parse_cursor_from_url(url: str) -> Tuple[int, str, str]:
    m = re.search(r"/(\d+)$", url.strip())
    if m:
        return int(m.group(1)), url[: m.start(1)], url[m.end(1):]
    if url.endswith("/"):
        url0 = url + "0"
    else:
        url0 = url + "/0"
    m = re.search(r"/(\d+)$", url0)
    return int(m.group(1)), url0[: m.start(1)], url0[m.end(1):]

def fetch_page(url: str) -> Tuple[List[dict], Optional[int]]:
    data = load_json_from_url(url)
    msgs = data.get("messages", []) or []
    col = data.get("collection", []) or []
    total = None
    if msgs:
        t = msgs[0].get("total")
        try:
            total = int(t) if t is not None else None
        except Exception:
            total = None
    return col, total

def fetch_all_pages_step(base_url: str, log_fn=print, stop_event: Optional[threading.Event] = None) -> Tuple[List[dict], int]:
    try:
        cursor0, head, tail = parse_cursor_from_url(base_url)
        url0 = f"{head}{cursor0}{tail}"
        log_fn(f"[INFO] Fetching cursor={cursor0}: {url0}")
        col0, total = fetch_page(url0)

        if total is None:
            total = len(col0)
            log_fn(f"[INFO] total (fallback) = {total}")
        else:
            log_fn(f"[INFO] total = {total}")

        records: List[dict] = []
        records.extend(col0)

        next_cursors = list(range(((cursor0 // 100) + 1) * 100, total, 100))
        for cur in next_cursors:
            if stop_event and stop_event.is_set():
                log_fn("[INFO] Stop requested. Abort paging.")
                break
            url = f"{head}{cur}{tail}"
            log_fn(f"[INFO] Fetching cursor={cur}: {url}")
            col, _ = fetch_page(url)
            records.extend(col)
            if len(col) < 100:
                break

        log_fn(f"[INFO] collected (raw) = {len(records)}")
        return records, total or len(records)
    except requests.HTTPError as e:
        log_fn(f"[ERROR] fetch_all_pages_step 失敗: {e}")
        return [], 0
    except Exception as e:
        log_fn(f"[ERROR] fetch_all_pages_step 例外: {e}")
        return [], 0

def clean_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text, flags=re.DOTALL)
        text = re.sub(r"\s*```$", "", text, flags=re.DOTALL)
    return text.strip()

def parse_json_safe(text: str) -> Optional[dict]:
    text = clean_code_fence(text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None

def translate_title_abstract_ja(title_en: str, abstract_en: str,
                                lm_url: str, lm_model: str,
                                log_fn=print) -> Tuple[str, str, bool]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional scientific translator. "
                "Translate the given English title and abstract into natural, precise Japanese for researchers. "
                "Return ONLY valid JSON with keys: title_ja, abstract_ja. No extra text."
            ),
        },
        {
            "role": "user",
            "content": (
                "Translate to Japanese (ja). Output strictly JSON.\n"
                "{\n"
                f'  "title": {json.dumps(title_en, ensure_ascii=False)},\n'
                f'  "abstract": {json.dumps(abstract_en, ensure_ascii=False)}\n'
                "}"
            ),
        },
    ]

    payload = {
        "model": lm_model,
        "messages": messages,
        "temperature": LM_TEMPERATURE,
    }

    for attempt in range(1, LM_MAX_RETRY + 1):
        try:
            resp = requests.post(lm_url, json=payload, timeout=TIMEOUT_SEC)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = parse_json_safe(content)
            if parsed and "title_ja" in parsed and "abstract_ja" in parsed:
                return str(parsed["title_ja"]).strip(), str(parsed["abstract_ja"]).strip(), True
        except Exception as e:
            log_fn(f"[LM] attempt {attempt}/{LM_MAX_RETRY} failed: {e}")
            time.sleep(1.0)

    log_fn("[LM] fallback to original text")
    return title_en, abstract_en, False

# ========== HTML生成 ==========
def build_paper_html(record: dict, title_ja: str, abstract_ja: str,
                     doidate: str, doino: str) -> str:
    title_en = html_escape_or_none(record.get("title"))
    abstract_en = html_escape_or_none(record.get("abstract"))
    date = html_escape_or_none(record.get("date"))
    category_display = html_escape_or_none(record.get("category"))
    server = html_escape_or_none(record.get("server"))
    doi_raw = html_escape_or_none(record.get("doi"))
    doi_url_full = f"https://doi.org/{record.get('doi','')}"
    doi_1101 = doi_parts_to_1101_url(doidate, doino)
    jats = record.get("jatsxml")
    jats_line = (
        f'<div><strong>JATS XML:</strong> <a href="{escape(jats)}" target="_blank" rel="noopener">{escape(jats)}</a></div>'
        if jats else ""
    )
    authors = html_escape_or_none(record.get("authors"))
    license_str = html_escape_or_none(record.get("license"))
    author_corresponding = html_escape_or_none(record.get("author_corresponding"))
    author_corresponding_institution = html_escape_or_none(record.get("author_corresponding_institution"))
    version = html_escape_or_none(record.get("version"))
    type_str = html_escape_or_none(record.get("type"))

    return HTML_DOC_TPL.format(
        title=escape(f"{category_display} | {date} | {doino}"),
        title_ja=escape(title_ja),
        title_en=title_en,
        date=date,
        category=category_display,
        server=server,
        doi_1101_url=escape(doi_1101),
        doi_url=escape(doi_url_full),
        doi_raw=doi_raw,
        jats_line=jats_line,
        abstract_ja=escape(abstract_ja),
        abstract_en=abstract_en,
        authors=authors,
        license=license_str,
        author_corresponding=author_corresponding,
        author_corresponding_institution=author_corresponding_institution,
        version=version,
        type_str=type_str,
    )

def process_record(base_dir: Path, rec: dict, total: int, index: int,
                   lm_url: str, lm_model: str, log_fn=print) -> Tuple[str, str, str, str, str, bool]:
    doi = rec.get("doi") or ""
    date = rec.get("date") or ""
    category_display = rec.get("category") or "uncategorized"
    cat_slug = slugify_category(category_display)

    try:
        doidate, doino = extract_doi_parts(doi)
        prog_note = doino
    except Exception:
        doidate, doino = "unknown", "unknown"
        prog_note = doi

    log_fn(f"[PROC] {index}/{total}  doi/doidate/doino: {prog_note}")

    title_en = rec.get("title") or ""
    abstract_en = rec.get("abstract") or ""
    title_ja, abstract_ja, used_lm = translate_title_abstract_ja(title_en, abstract_en, lm_url, lm_model, log_fn)

    paper_rel = Path("date") / date / cat_slug / doidate / f"{doino}.html"
    paper_path = base_dir / paper_rel
    html = build_paper_html(rec, title_ja, abstract_ja, doidate, doino)
    write_text(paper_path, html)

    # per-date index
    date_dir = base_dir / "date" / date
    date_index = date_dir / "date.html"
    ensure_index_file(
        date_index,
        title=f"Index for {date}",
        subtitle=f"日付 {date} の一覧",
        header_cols=["doino", "doidate", "local", "doi", "category"],
    )
    local_link_for_date = f"./{cat_slug}/{doidate}/{doino}.html"
    rowid = make_row_id(date, category_display, doidate, doino)
    append_row_if_absent(
        date_index,
        build_index_row(date, category_display, doidate, doino, local_link_for_date, doi_parts_to_1101_url(doidate, doino)),
        rowid=rowid,
    )

    # per-date, per-category index
    date_cat_dir = date_dir / cat_slug
    date_cat_index = date_cat_dir / "category.html"
    ensure_index_file(
        date_cat_index,
        title=f"Category '{category_display}' on {date}",
        subtitle=f"{date} のカテゴリ {category_display} 集約",
        header_cols=["doino", "doidate", "local", "doi", "category"],
    )
    local_link_for_date_cat = f"./{doidate}/{doino}.html"
    append_row_if_absent(
        date_cat_index,
        build_index_row(date, category_display, doidate, doino, local_link_for_date_cat, doi_parts_to_1101_url(doidate, doino)),
        rowid=rowid,
    )

    # global category index
    global_cat_dir = base_dir / "category" / cat_slug
    global_cat_index = global_cat_dir / "category.html"
    ensure_index_file(
        global_cat_index,
        title=f"Category '{category_display}' (All Dates)",
        subtitle=f"カテゴリ {category_display} の全日付集約",
        header_cols=["doino", "doidate", "local", "doi", "category"],
    )
    local_link_for_global_cat = f"../../date/{date}/{cat_slug}/{doidate}/{doino}.html"
    append_row_if_absent(
        global_cat_index,
        build_index_row(date, category_display, doidate, doino, local_link_for_global_cat, doi_parts_to_1101_url(doidate, doino)),
        rowid=rowid,
    )

    # reports
    update_daily_report(base_dir, date, cat_slug, category_display, doidate, doino, title_ja, rec.get("license") or "")
    update_category_report(base_dir, date, cat_slug, category_display, doidate, doino, title_ja, rec.get("license") or "")

    # catalog
    item = build_catalog_item(
        date=date,
        category_display=category_display,
        cat_slug=cat_slug,
        doidate=doidate,
        doino=doino,
        title_ja=title_ja,
        title_en=title_en,
        license_str=rec.get("license") or "",
        server=rec.get("server") or "",
        doi_raw=rec.get("doi") or "",
    )
    upsert_catalog_item(base_dir, item)

    corr = rec.get("author_corresponding") or ""
    inst = rec.get("author_corresponding_institution") or ""
    authors = rec.get("authors") or ""
    license_str = rec.get("license") or ""
    return title_ja, corr, inst, authors, license_str, used_lm

# ========== Flash Display ==========
class FlashDisplay:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.top: Optional[tk.Toplevel] = None
        self.title_lbl: Optional[tk.Label] = None
        self.info_lbl: Optional[tk.Label] = None
        self.meta_lbl: Optional[tk.Label] = None

    def open(self):
        if self.top and self.top.winfo_exists():
            try:
                self.top.deiconify()
                self.top.lift()
            except Exception:
                pass
            return
        self.top = tk.Toplevel(self.master)
        self.top.title("Flash Display")
        self.top.configure(bg="#000000")
        self.top.geometry("960x420")
        try:
            self.top.attributes("-topmost", True)
        except Exception:
            pass

        self.title_lbl = tk.Label(
            self.top, text="", fg="#FFFFFF", bg="#000000",
            font=("Helvetica", 24, "bold"), wraplength=920, justify="left"
        )
        self.title_lbl.pack(fill="x", padx=20, pady=(20, 10))

        self.info_lbl = tk.Label(
            self.top, text="", fg="#EEEEEE", bg="#000000",
            font=("Helvetica", 18), wraplength=920, justify="left"
        )
        self.info_lbl.pack(fill="x", padx=20, pady=(0, 6))

        self.meta_lbl = tk.Label(
            self.top, text="", fg="#A9A9A9", bg="#000000",
            font=("Helvetica", 15), wraplength=920, justify="left"
        )
        self.meta_lbl.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.top.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        if self.top and self.top.winfo_exists():
            self.top.destroy()
        self.top = None
        self.title_lbl = None
        self.info_lbl = None
        self.meta_lbl = None

    def show(self, title_ja: str, corr: str, inst: str, authors: str, license_str: str):
        if not (self.top and self.top.winfo_exists()):
            self.open()
        if self.title_lbl:
            self.title_lbl.config(text=title_ja or "")
        lines_info = []
        if corr:
            lines_info.append(corr)
        if inst:
            lines_info.append(inst)
        if self.info_lbl:
            self.info_lbl.config(text="\n".join(lines_info))

        lines_meta = []
        if authors:
            lines_meta.append(f"author: {authors}")
        if license_str:
            lines_meta.append(f"license: {license_str}")
        if self.meta_lbl:
            self.meta_lbl.config(text="\n".join(lines_meta))

# ========== ViewerWindow ==========
def _inject_base_and_targets(html: str, file_dir: Path) -> str:
    """ローカル HTML 用: <base> だけ注入。target の書き換えはしない。"""
    try:
        base_tag = f'<base href="{file_dir.as_uri().rstrip("/") + "/"}">'
        if "<head" in html and "<base" not in html:
            html = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html, count=1,
                          flags=re.IGNORECASE | re.DOTALL)
    except Exception:
        pass
    return html

def _safe_float(v, default):
    try:
        return float(v)
    except Exception:
        return default

class ViewerWindow(tk.Toplevel):
    def __init__(self, master, base_dir_getter, initial_zoom=1.0, zoom_changed_cb=None, initial_font=""):
        super().__init__(master)
        self.title("HTML Viewer")
        self.geometry("1080x860")
        self.base_dir_getter = base_dir_getter
        self.zoom_changed_cb = zoom_changed_cb
        self.font_family: str = initial_font or ""

        self.current: Optional[Tuple[str, str]] = None
        self.last_local_dir: Optional[Path] = None
        self.zoom_level: float = initial_zoom if initial_zoom > 0 else 1.0
        self._zoom_syncing = False
        self._zoom_slider_cmd = None  # UI削除後の安全策
        self.home_target: Optional[Tuple[str, str]] = None  # ("file"|"url", value)

        # Top bar
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.addr_var = tk.StringVar()
        ttk.Label(top, text="Link/Path:").pack(side="left")
        addr = ttk.Entry(top, textvariable=self.addr_var, width=72)
        addr.pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(top, text="Go", command=self.on_go).pack(side="left", padx=(6,0))
        ttk.Button(top, text="Home", command=self.on_home).pack(side="left", padx=6)
        ttk.Button(top, text="Open in Browser", command=self.on_open_external).pack(side="left", padx=8)

        # Font
        fbar = ttk.Frame(self, padding=(8,0,8,6))
        fbar.pack(fill="x")
        ttk.Label(fbar, text="Font:").pack(side="left")
        self.font_var = tk.StringVar(value=self.font_family)
        font_list = list_system_fonts()
        self.font_cb = ttk.Combobox(fbar, textvariable=self.font_var, state="readonly", width=32, values=font_list)
        self.font_cb.pack(side="left", padx=(6,6))
        ttk.Button(fbar, text="Apply", command=self.apply_font).pack(side="left")

        # HtmlFrame
        if HAS_TKINTERWEB:
            self.web_init_error = ""
            try:
                self.web = HtmlFrame(self, messages_enabled=False, horizontal_scrollbar="auto")
            except Exception as _e_init:
                self.web = None
                self.web_init_error = f"{type(_e_init).__name__}: {_e_init}"
            if self.web:
                self.web.pack(fill="both", expand=True)
                # リンクフック
                try:
                    if hasattr(self.web, "on_link_click"):
                        self.web.on_link_click(self._on_link_clicked)
                    elif hasattr(self.web, "set_link_callback"):
                        self.web.set_link_callback(self._on_link_clicked)
                except Exception:
                    pass
        else:
            self.web = None
            self.web_init_error = TKWEB_IMPORT_ERR or "not installed"

        self._sync_zoom_ui()  # UI消しても安全に動くように防御

    # ------- Home -------
    def set_home(self, kind: str, val: str):
        self.home_target = (kind, val)

    def on_home(self):
        if not self.home_target:
            messagebox.showinfo("Home", "Home が未設定です。App から表示ボタンでページを開いてください。")
            return
        kind, val = self.home_target
        if kind == "file":
            self.open_local(Path(val), push_history=False)
        else:
            self.open_url(val, push_history=False)

    # ------- Zoom（UIなし・内部値のみ）-------
    def _sync_zoom_ui(self):
        """UIが無くても落ちないよう安全に。必要なら Web 側へだけ反映。"""
        if self._zoom_syncing:
            return
        self._zoom_syncing = True
        try:
            # ラベル/スライダーは存在しない想定なので何もしない
            self._apply_zoom_to_widget()
        finally:
            self._zoom_syncing = False

    def set_zoom(self, level: float):
        level = max(0.5, min(2.0, float(level)))
        self.zoom_level = level
        self._sync_zoom_ui()
        if callable(self.zoom_changed_cb):
            try:
                self.zoom_changed_cb(level)
            except Exception:
                pass
        if self.current and self.current[0] == "file":
            self.on_reload_current()

    def _apply_zoom_to_widget(self):
        if not (HAS_TKINTERWEB and self.web):
            return
        try:
            if hasattr(self.web, "set_zoom"):
                self.web.set_zoom(self.zoom_level)
                return
        except Exception:
            pass
        # set_zoom がない場合、open_local/open_url の読み込み時に CSS で zoom 反映

    def apply_font(self):
        self.font_family = self.font_var.get().strip()
        if self.current and self.current[0] == "file":
            self.on_reload_current()

    # ------- Link Hook -------
    def _on_link_clicked(self, url: str):
        try:
            url = (url or "").strip()
        except Exception:
            return "break"
        if not url:
            return "break"

        # 外部URLは外部ブラウザで開く（tkinterwebの404風を回避）
        if re.match(r"^https?://", url, re.I):
            self.addr_var.set(url)
            try:
                webbrowser.open(url)
            except Exception as e:
                try:
                    messagebox.showerror("Open external", f"外部ブラウザで開けませんでした。\n{e}")
                except Exception:
                    pass
            return "break"

        # file:// or 相対
        if url.lower().startswith("file://"):
            p = Path(urllib.parse.unquote(url[7:]))
            if not p.is_absolute() and self.last_local_dir:
                p = (self.last_local_dir / p).resolve()
            self.open_local(p)
            return "break"

        if self.last_local_dir:
            p = (self.last_local_dir / urllib.parse.unquote(url)).resolve()
            self.open_local(p)
        else:
            try:
                p = Path(urllib.parse.unquote(url)).resolve()
            except Exception:
                p = Path(url)
            self.open_local(p)
        return "break"

    # ------- Loaders -------
    def on_reload_current(self):
        if not self.current:
            return
        kind, val = self.current
        if kind == "file":
            self.open_local(Path(val), push_history=False)
        else:
            self.open_url(val, push_history=False)

    def open_local(self, path: Path, push_history=True):
        # tkinterweb チェック
        if not HAS_TKINTERWEB or not getattr(self, "web", None):
            try:
                messagebox.showwarning("Viewer", "tkinterweb が見つかりません。'pip install tkinterweb' を実行してください。")
            except Exception:
                pass
            _fallback_open(str(path))
            return

        self.last_local_dir = path.parent
        if not path.exists():
            self.web.load_html(f"<html><body><h3>ファイルが見つかりません</h3><p>{escape(str(path))}</p></body></html>")
            return

        html = read_text(path)
        # base 追加
        html = _inject_base_and_targets(html, path.parent)
        # フォント CSS 注入
        if self.font_family:
            html = inject_font_css(html, self.font_family)
        # set_zoom 非対応なら CSS で補助（内部 zoom_level は維持）
        if not hasattr(self.web, "set_zoom"):
            zpct = int(round(self.zoom_level * 100))
            zoom_css = f"<style>html{{zoom:{zpct}%}}</style>"
            if "<head" in html:
                html = re.sub(r"(<head[^>]*>)", r"\1" + zoom_css, html, count=1, flags=re.IGNORECASE|re.DOTALL)
            else:
                html = zoom_css + html

        self.web.load_html(html)
        self.addr_var.set(str(path))
        self.current = ("file", str(path))

    def open_url(self, url: str, push_history=True):
        # 原則: http(s) は外部ブラウザで開く方針
        try:
            webbrowser.open(url)
        except Exception:
            pass
        self.addr_var.set(url)
        self.current = ("url", url)

    # ------- Controls -------
    def on_go(self):
        link = (self.addr_var.get() or "").strip()
        if not link:
            return
        if re.match(r"^https?://", link, re.I):
            self.open_url(link)
            return
        if link.lower().startswith("file://"):
            p = Path(urllib.parse.unquote(link[7:]))
        else:
            p = Path(link)
        self.open_local(p)

    def on_open_external(self):
        link = (self.addr_var.get() or "").strip()
        if not link and self.current:
            kind, val = self.current
            link = val if kind == "url" else Path(val).as_uri()
        if not link:
            return
        try:
            webbrowser.open(link)
        except Exception as e:
            messagebox.showerror("Open in Browser", f"外部ブラウザで開けませんでした。\n{e}")

# ========== アプリ ==========
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("bioRxiv / medRxiv Daily → JA & HTML Generator")
        self.geometry("1320x980")

        self.stop_now_event = threading.Event()
        self.stop_after_day_event = threading.Event()
        self.stop_after_article_event = threading.Event()
        self.pause_request_event = threading.Event()

        self.worker_thread = None
        self.log_buffer: List[str] = []
        self.start_ts_str: Optional[str] = None
        self.pause_ts_str: Optional[str] = None

        self.flash = FlashDisplay(self)
        self.viewer_win: Optional[ViewerWindow] = None

        self.viewer_zoom: float = 1.0
        self.viewer_font: str = ""

        # Top form
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="x")

        self.style = ttk.Style(self)
        self.style.configure("NavWide.TButton", padding=(18, 2))

        ttk.Label(frm, text="Server:").grid(row=0, column=0, sticky="w")
        self.server_var = tk.StringVar(value=DEFAULT_SERVER)
        self.server_cb = ttk.Combobox(frm, textvariable=self.server_var, values=["biorxiv", "medrxiv"], width=12, state="readonly")
        self.server_cb.grid(row=0, column=1, sticky="w", padx=(5,10))

        ttk.Label(frm, text="Date (YYYY-MM-DD):").grid(row=0, column=2, sticky="w")
        self.date_var = tk.StringVar()
        if HAS_TKCALENDAR:
            self.date_entry = DateEntry(frm, textvariable=self.date_var, date_pattern="yyyy-mm-dd", width=14)
        else:
            self.date_entry = ttk.Entry(frm, textvariable=self.date_var, width=16)
            self.date_var.set("2025-10-17")
        self.date_entry.grid(row=0, column=3, sticky="w", padx=(5,10))

        ttk.Label(frm, text="Period:").grid(row=0, column=4, sticky="e")
        self.period_var = tk.StringVar(value="Day")
        self.period_cb = ttk.Combobox(frm, textvariable=self.period_var, values=list(PERIOD_MAP.keys()), width=8, state="readonly")
        self.period_cb.grid(row=0, column=5, sticky="w", padx=(5,10))

        navf = ttk.Frame(frm)
        navf.grid(row=1, column=2, columnspan=6, sticky="w")
        wch = 6
        self.nav_year_prev = ttk.Button(navf, text="◀年", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(years=-1))
        self.nav_month_prev = ttk.Button(navf, text="◀月", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(months=-1))
        self.nav_day_prev = ttk.Button(navf, text="◀日", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(days=-1))
        self.nav_day_next = ttk.Button(navf, text="▶日", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(days=+1))
        self.nav_month_next = ttk.Button(navf, text="▶月", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(months=+1))
        self.nav_year_next = ttk.Button(navf, text="▶年", style="NavWide.TButton", width=wch, command=lambda: self.shift_date(years=+1))
        for i, btn in enumerate([self.nav_year_prev, self.nav_month_prev, self.nav_day_prev, self.nav_day_next, self.nav_month_next, self.nav_year_next]):
            btn.grid(row=0, column=i, padx=5, pady=4, sticky="w")

        ttk.Label(frm, text="Base Dir:").grid(row=2, column=0, sticky="w")
        self.base_dir_var = tk.StringVar(value=str(Path(".").resolve()))
        self.base_dir_entry = ttk.Entry(frm, textvariable=self.base_dir_var, width=60)
        self.base_dir_entry.grid(row=2, column=1, columnspan=5, sticky="we", padx=(5,5))
        ttk.Button(frm, text="Browse...", command=self.browse_dir).grid(row=2, column=6, sticky="w", padx=(5,0))

        ttk.Label(frm, text="LM URL:").grid(row=3, column=0, sticky="w")
        self.lm_url_var = tk.StringVar(value=LMSTUDIO_API_URL_DEFAULT)
        ttk.Entry(frm, textvariable=self.lm_url_var, width=40).grid(row=3, column=1, sticky="w", padx=(5,10))

        ttk.Label(frm, text="LM Model:").grid(row=3, column=2, sticky="w")
        self.lm_model_var = tk.StringVar(value=LMSTUDIO_MODEL_DEFAULT)
        ttk.Entry(frm, textvariable=self.lm_model_var, width=30).grid(row=3, column=3, sticky="w", padx=(5,10))

        # License
        licf = ttk.LabelFrame(self, text="License Filter", padding=8)
        licf.pack(fill="x", padx=10, pady=(4, 8))
        ttk.Label(licf, text="License Preset:").grid(row=0, column=0, sticky="w")
        self.license_preset_var = tk.StringVar(value="Any")
        self.license_preset_cb = ttk.Combobox(licf, textvariable=self.license_preset_var, values=LICENSE_PRESETS, width=16, state="readonly")
        self.license_preset_cb.grid(row=0, column=1, sticky="w", padx=(6,12))
        self.require_cc_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(licf, text="Require 'cc' in license", variable=self.require_cc_var).grid(row=0, column=2, sticky="w", padx=(6,12))
        ttk.Label(licf, text="Exclude components:").grid(row=1, column=0, sticky="w", pady=(4,0))
        self.ex_by_var = tk.BooleanVar(value=False)
        self.ex_nc_var = tk.BooleanVar(value=False)
        self.ex_nd_var = tk.BooleanVar(value=False)
        self.ex_sa_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(licf, text="by", variable=self.ex_by_var).grid(row=1, column=1, sticky="w", padx=(6,6), pady=(4,0))
        ttk.Checkbutton(licf, text="nc", variable=self.ex_nc_var).grid(row=1, column=2, sticky="w", padx=(6,6), pady=(4,0))
        ttk.Checkbutton(licf, text="nd", variable=self.ex_nd_var).grid(row=1, column=3, sticky="w", padx=(6,6), pady=(4,0))
        ttk.Checkbutton(licf, text="sa", variable=self.ex_sa_var).grid(row=1, column=4, sticky="w", padx=(6,6), pady=(4,0))

        # Keyword
        kwf = ttk.LabelFrame(self, text="Keyword Filter", padding=8)
        kwf.pack(fill="x", padx=10, pady=(0,8))
        ttk.Label(kwf, text="Keywords (comma-separated):").grid(row=0, column=0, sticky="w")
        self.kw_var = tk.StringVar()
        ttk.Entry(kwf, textvariable=self.kw_var, width=60).grid(row=0, column=1, sticky="we", padx=(6,10))
        ttk.Label(kwf, text="Mode:").grid(row=0, column=2, sticky="e")
        self.kw_mode_var = tk.StringVar(value="OR")
        ttk.Combobox(kwf, textvariable=self.kw_mode_var, values=["OR", "AND"], width=6, state="readonly").grid(row=0, column=3, sticky="w")
        kwf.columnconfigure(1, weight=1)

        # Actions
        act = ttk.Frame(self, padding=(10,0,10,5))
        act.pack(fill="x")
        self.run_btn = ttk.Button(act, text="Fetch & Generate", command=self.on_run)
        self.run_btn.pack(side="left", padx=(0,8))
        self.stop_now_btn = ttk.Button(act, text="Stop Now", command=self.on_stop_now, state="disabled")
        self.stop_now_btn.pack(side="left", padx=(0,8))
        self.stop_after_day_btn = ttk.Button(act, text="Stop After This Day", command=self.on_stop_after_day, state="disabled")
        self.stop_after_day_btn.pack(side="left", padx=(0,8))
        self.stop_after_article_btn = ttk.Button(act, text="Stop After This Article", command=self.on_stop_after_article, state="disabled")
        self.stop_after_article_btn.pack(side="left", padx=(0,8))
        self.pause_btn = ttk.Button(act, text="Pause", command=self.on_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(0,8))
        self.resume_btn = ttk.Button(act, text="Resume", command=self.on_resume, state="disabled")
        self.resume_btn.pack(side="left", padx=(0,8))

        # TTS & Flash
        ttsf = ttk.Frame(self, padding=(10, 0, 10, 5))
        ttsf.pack(fill="x")
        self.tts_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ttsf, text="読み上げ (gTTS → pygame 再生)", variable=self.tts_var).pack(side="left", padx=(0,10))
        ttk.Button(ttsf, text="Open Display", command=self.flash.open).pack(side="left")

        # Progress
        prf = ttk.Frame(self, padding=(10,0,10,5))
        prf.pack(fill="x")
        self.progress = ttk.Progressbar(prf, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(5,2))
        self.prog_lbl = ttk.Label(prf, text="Progress: -/-")
        self.prog_lbl.pack(anchor="w")

        # Logs
        lgf = ttk.LabelFrame(self, text="Logs", padding=8)
        lgf.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text = ScrolledText(lgf, height=14, font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True)

        # Viewer controls
        vf = ttk.LabelFrame(self, text="Viewer Controls (別ウィンドウで表示)", padding=8)
        vf.pack(fill="x", padx=10, pady=6)

        ttk.Label(vf, text="doino:").grid(row=0, column=0, sticky="w")
        self.doino_var = tk.StringVar()
        ttk.Entry(vf, textvariable=self.doino_var, width=18).grid(row=0, column=1, sticky="w", padx=(5,8))
        ttk.Button(vf, text="表示", command=self.open_by_doino).grid(row=0, column=2, sticky="w", padx=(0,10))

        ttk.Button(vf, text="ランダム表示", command=self.open_random).grid(row=0, column=3, sticky="w", padx=(0,10))

        ttk.Button(vf, text="この日付の daily_report.html", command=self.open_daily_report).grid(row=0, column=4, sticky="w", padx=(0,10))

        ttk.Label(vf, text="カテゴリ:").grid(row=0, column=5, sticky="e")
        self.cat_var = tk.StringVar()
        self.cat_cb_view = ttk.Combobox(vf, textvariable=self.cat_var, width=26, state="readonly")
        self.cat_cb_view.grid(row=0, column=6, sticky="w", padx=(5,8))
        ttk.Button(vf, text="category_report.html", command=self.open_category_report).grid(row=0, column=7, sticky="w", padx=(0,10))

        # Openers
        btm = ttk.LabelFrame(self, text="Open Index (外部ブラウザ/システム)", padding=8)
        btm.pack(fill="x", padx=10, pady=5)
        ttk.Label(btm, text="Category (slug):").grid(row=0, column=0, sticky="w")
        self.cat_list_var = tk.StringVar()
        self.cat_cb = ttk.Combobox(btm, textvariable=self.cat_list_var, width=30, state="readonly")
        self.cat_cb.grid(row=0, column=1, sticky="w", padx=(5,10))
        ttk.Button(btm, text="Refresh", command=self.refresh_category_list).grid(row=0, column=2, sticky="w", padx=(0,10))
        ttk.Button(btm, text="Open Selected Category Index", command=self.open_selected_category_index).grid(row=0, column=3, sticky="w")

        ttk.Label(btm, text="Date:").grid(row=1, column=0, sticky="w")
        ttk.Button(btm, text="Open Selected Date Index", command=self.open_selected_date_index).grid(row=1, column=1, sticky="w")
        ttk.Button(btm, text="Open All Dates Index", command=self.open_all_dates_index).grid(row=1, column=2, sticky="w")

        # Footer
        opf = ttk.Frame(self, padding=10)
        opf.pack(fill="x")
        self.open_btn = ttk.Button(opf, text="Open Output Folder", command=self.open_output_folder, state="normal")
        self.open_btn.pack(side="left")
        ttk.Button(opf, text="Open Viewer Window", command=self.ensure_viewer_window).pack(side="left", padx=10)

        frm.columnconfigure(3, weight=1)

        if not HAS_TKCALENDAR:
            self.log("[INFO] tkcalendar が見つかりません。日付は YYYY-MM-DD 形式で入力してください。")
        if not HAS_TKINTERWEB:
            self.log("[INFO] tkinterweb が見つかりません（外部ブラウザで代替します）。")

        # 設定の読み込み（viewer_zoom, viewer_font）
        self._load_settings_on_start()

        self.refresh_category_list()
        self.refresh_category_list_for_viewer()

    # ---- 設定読込 ----
    def _load_settings_on_start(self):
        try:
            base_dir = Path(self.base_dir_var.get()).resolve()
            set_path = base_dir / "setting" / "setting.txt"
            if set_path.exists():
                txt = read_text(set_path)
                dic = {}
                for line in txt.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        dic[k.strip()] = v.strip()
                self.server_var.set(dic.get("server", self.server_var.get()))
                self.date_var.set(dic.get("date", self.date_var.get()))
                if dic.get("period"): self.period_var.set(dic["period"])
                if dic.get("base_dir"): self.base_dir_var.set(dic["base_dir"])
                if dic.get("lm_url"): self.lm_url_var.set(dic["lm_url"])
                if dic.get("lm_model"): self.lm_model_var.set(dic["lm_model"])
                if dic.get("keywords"): self.kw_var.set(dic["keywords"])
                if dic.get("mode"): self.kw_mode_var.set(dic["mode"])
                if dic.get("license_preset"): self.license_preset_var.set(dic["license_preset"])
                self.require_cc_var.set(dic.get("require_cc","False")=="True")
                self.ex_by_var.set(dic.get("exclude_by","False")=="True")
                self.ex_nc_var.set(dic.get("exclude_nc","False")=="True")
                self.ex_nd_var.set(dic.get("exclude_nd","False")=="True")
                self.ex_sa_var.set(dic.get("exclude_sa","False")=="True")
                self.tts_var.set(dic.get("tts","False")=="True")
                # viewer
                try:
                    vz = float(dic.get("viewer_zoom", "1.0"))
                except Exception:
                    vz = 1.0
                self.viewer_zoom = max(0.5, min(2.0, vz))
                self.viewer_font = dic.get("viewer_font", self.viewer_font)
        except Exception as e:
            self.log(f"[WARN] 設定読み込みに失敗: {e}")

    # ---- Viewer helper ----
    def ensure_viewer_window(self) -> ViewerWindow:
        if self.viewer_win and self.viewer_win.winfo_exists():
            try:
                self.viewer_win.deiconify()
                self.viewer_win.lift()
            except Exception:
                pass
            return self.viewer_win
        self.viewer_win = ViewerWindow(
            self,
            base_dir_getter=lambda: Path(self.base_dir_var.get()).resolve(),
            initial_zoom=self.viewer_zoom,
            zoom_changed_cb=self._on_viewer_zoom_changed,
            initial_font=self.viewer_font
        )
        return self.viewer_win

    def _on_viewer_font_changed(self, font_name: str):
        self.viewer_font = font_name or ""
        try:
            base_dir = Path(self.base_dir_var.get()).resolve()
            set_path = base_dir / "setting" / "setting.txt"
            txt = read_text(set_path) if set_path.exists() else ""
            lines = []
            found = False
            if txt:
                for line in txt.splitlines():
                    if line.startswith("viewer_font="):
                        lines.append(f"viewer_font={self.viewer_font}")
                        found = True
                    else:
                        lines.append(line)
            if not found:
                lines.append(f"viewer_font={self.viewer_font}")
            write_text(set_path, "\n".join(lines))
        except Exception as e:
            self.log(f"[WARN] viewer_font の保存に失敗: {e}")

    def _on_viewer_zoom_changed(self, level: float):
        self.viewer_zoom = level
        try:
            base_dir = Path(self.base_dir_var.get()).resolve()
            set_path = base_dir / "setting" / "setting.txt"
            txt = read_text(set_path) if set_path.exists() else ""
            lines = []
            found = False
            if txt:
                for line in txt.splitlines():
                    if line.startswith("viewer_zoom="):
                        lines.append(f"viewer_zoom={level}")
                        found = True
                    else:
                        lines.append(line)
            if not found:
                lines.append(f"viewer_zoom={level}")
            write_text(set_path, "\n".join(lines))
        except Exception as e:
            self.log(f"[WARN] viewer_zoom の保存に失敗: {e}")

    def refresh_category_list_for_viewer(self):
        items = list(self.collect_categories_from_fs())
        self.cat_cb_view["values"] = items
        if items:
            self.cat_var.set(items[0])

    # ---- FS ----
    def collect_categories_from_fs(self):
        base_dir = Path(self.base_dir_var.get()).resolve()
        cats_dir = base_dir / "category"
        items = []
        if cats_dir.exists():
            for p in sorted(cats_dir.iterdir()):
                if p.is_dir():
                    items.append(p.name)
        return items

    # ---- TTS ----
    def speak_title_async(self, base_dir: Path, text: str):
        def play_with_pygame(path: Path) -> bool:
            if not PYGAME_AVAILABLE:
                return False
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                return True
            except Exception as e:
                self.log(f"[TTS] pygame 再生失敗: {e}")
                return False

        def runner():
            try:
                from gtts import gTTS
            except Exception as e:
                self.log(f"[TTS] gTTS が利用できません: {e}")
                return

            mp3_dir = base_dir / "log" / "tts"
            mp3_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            mp3_path = mp3_dir / f"{ts}.mp3"
            try:
                tts = gTTS(text=text or "", lang="ja")
                tts.save(str(mp3_path))
            except Exception as e:
                self.log(f"[TTS] 生成失敗: {e}")
                return

            if play_with_pygame(mp3_path):
                return

            try:
                from playsound import playsound
                playsound(str(mp3_path))
                return
            except Exception as e:
                self.log(f"[TTS] playsound 再生失敗: {e}")

            try:
                if sys.platform.startswith("win"):
                    os.system(f'start /min "" "{mp3_path}"')
                elif sys.platform == "darwin":
                    os.system(f'afplay "{mp3_path}"')
                else:
                    os.system(f'xdg-open "{mp3_path}"')
            except Exception as e:
                self.log(f"[TTS] OS 再生失敗: {e}")

        threading.Thread(target=runner, daemon=True).start()

    # ---- 日付移動 ----
    def shift_date(self, years=0, months=0, days=0):
        try:
            y, m, d = [int(x) for x in self.date_var.get().split("-")]
            cur = ddate(y, m, d)
        except Exception:
            cur = ddate.today()
        new_date = cur + timedelta(days=days)
        if months or years:
            total_months = cur.month - 1 + months + years * 12
            new_year = cur.year + total_months // 12
            new_month = total_months % 12 + 1
            last_day = calendar.monthrange(new_year, new_month)[1]
            day = min(cur.day, last_day)
            new_date = ddate(new_year, new_month, day)
        self.date_var.set(new_date.strftime("%Y-%m-%d"))

    @staticmethod
    def ts_now_str():
        return time.strftime("%Y-%m-%d_%H-%M", time.localtime())

    def save_settings_files(self, base_dir: Path, ts_str: str):
        settings = {
            "server": self.server_var.get().strip(),
            "date": self.date_var.get().strip(),
            "period": self.period_var.get().strip(),
            "base_dir": str(base_dir),
            "lm_url": self.lm_url_var.get().strip(),
            "lm_model": self.lm_model_var.get().strip(),
            "keywords": self.kw_var.get().strip(),
            "mode": self.kw_mode_var.get().strip(),
            "license_preset": self.license_preset_var.get().strip(),
            "require_cc": str(self.require_cc_var.get()),
            "exclude_by": str(self.ex_by_var.get()),
            "exclude_nc": str(self.ex_nc_var.get()),
            "exclude_nd": str(self.ex_nd_var.get()),
            "exclude_sa": str(self.ex_sa_var.get()),
            "timestamp": ts_str,
            "tts": str(self.tts_var.get()),
            "viewer_zoom": str(self.viewer_zoom),
            "viewer_font": self.viewer_font,
        }
        set_path = base_dir / "setting" / "setting.txt"
        text_lines = [f"{k}={v}" for k, v in settings.items()]
        write_text(set_path, "\n".join(text_lines))
        set_log_path = base_dir / "log" / "setting" / f"{ts_str}.log"
        write_text(set_log_path, "\n".join(text_lines))

    def save_log_file(self, base_dir: Path, kind: str, ts_str: str):
        log_dir = base_dir / "log" / kind
        path = log_dir / f"{ts_str}.log"
        write_text(path, "\n".join(self.log_buffer))

    def log(self, msg: str):
        self.log_buffer.append(msg)
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.update_idletasks()

    def browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.base_dir_var.get())
        if d:
            self.base_dir_var.set(d)
            self.refresh_category_list()
            self.refresh_category_list_for_viewer()

    def open_output_folder(self):
        p = Path(self.base_dir_var.get()).resolve()
        if p.exists():
            if sys.platform.startswith("win"):
                os.startfile(str(p))
            elif sys.platform == "darwin":
                os.system(f'open "{p}"')
            else:
                os.system(f'xdg-open "{p}"')
        else:
            messagebox.showerror("Error", f"Folder not found: {p}")

    def set_running(self, running: bool):
        self.run_btn.config(state="disabled" if running else "normal")
        self.stop_now_btn.config(state="normal" if running else "disabled")
        self.stop_after_day_btn.config(state="normal" if running else "disabled")
        self.stop_after_article_btn.config(state="normal" if running else "disabled")
        self.pause_btn.config(state="normal" if running else "disabled")
        self.resume_btn.config(state="disabled")
        state = "disabled" if running else "normal"
        for w in (self.cat_cb, self.period_cb):
            w.config(state="readonly" if state == "normal" else "disabled")

    # ---- Stop/Pause ----
    def on_stop_now(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_now_event.set()
            if not self.pause_ts_str:
                self.pause_ts_str = self.ts_now_str()
            self.log("[INFO] Stop Now 要求を送信しました。")

    def on_stop_after_day(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_after_day_event.set()
            if not self.pause_ts_str:
                self.pause_ts_str = self.ts_now_str()
            self.log("[INFO] Stop After This Day 要求を送信しました。")

    def on_stop_after_article(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_after_article_event.set()
            if not self.pause_ts_str:
                self.pause_ts_str = self.ts_now_str()
            self.log("[INFO] Stop After This Article 要求を送信しました（現在の論文完了後に停止）。")

    def on_pause(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.pause_request_event.set()
            if not self.pause_ts_str:
                self.pause_ts_str = self.ts_now_str()
            self.log("[INFO] Pause 要求を送信しました（現在の論文完了後に一時停止）。")
            base_dir = Path(self.base_dir_var.get()).resolve()
            self.save_log_file(base_dir, kind="pause", ts_str=self.pause_ts_str)
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")

    def on_resume(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.pause_request_event.clear()
            self.log("[INFO] Resume を受け付けました。次の論文から処理を再開します。")
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")

    def on_paper_done_ui(self, base_dir: Path, title_ja: str, corr: str, inst: str, authors: str, license_str: str, used_lm: bool):
        try:
            self.flash.show(title_ja, corr, inst, authors, license_str)
        except Exception as e:
            self.log(f"[FLASH] 表示エラー: {e}")
        if used_lm and self.tts_var.get():
            self.speak_title_async(base_dir, title_ja)

    # ---- Viewer actions ----
    def open_daily_report(self):
        vw = self.ensure_viewer_window()
        base_dir = Path(self.base_dir_var.get()).resolve()
        date = (self.date_var.get() or "").strip()
        p = base_dir / "date" / date / "daily_report.html"
        vw.open_local(p)
        vw.set_home("file", str(p))

    def open_category_report(self):
        vw = self.ensure_viewer_window()
        base_dir = Path(self.base_dir_var.get()).resolve()
        slug = (self.cat_var.get() or "").strip()
        if not slug:
            messagebox.showwarning("カテゴリ未選択", "カテゴリを選択してください。")
            return
        p = base_dir / "category" / slug / "category_report.html"
        vw.open_local(p)
        vw.set_home("file", str(p))

    def open_by_doino(self):
        vw = self.ensure_viewer_window()
        doino = (self.doino_var.get() or "").strip()
        if not doino:
            messagebox.showwarning("doino 未入力", "doino を入力してください。")
            return
        base_dir = Path(self.base_dir_var.get()).resolve()
        cat = load_catalog(base_dir)
        hits = [it for it in cat.get("items", []) if str(it.get("doino")) == doino]
        if not hits:
            messagebox.showinfo("見つかりません", f"doino={doino} は catalog.json に見つかりません。")
            return
        target = hits[0] if len(hits) == 1 else self.choose_from_candidates(hits)
        if not target:
            return
        p = base_dir / target["html_rel"]
        vw.open_local(p)
        vw.set_home("file", str(p))

    def choose_from_candidates(self, items: List[Dict[str, Any]]):
        dlg = tk.Toplevel(self)
        dlg.title("候補を選択")
        dlg.geometry("760x420")
        cols = ("date", "category", "doidate", "doino", "title_ja")
        tree = ttk.Treeview(dlg, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=120 if c!="title_ja" else 360, anchor="w")
        for it in items:
            tree.insert("", "end", values=(it.get("date"), it.get("category"), it.get("doidate"), it.get("doino"), it.get("title_ja","")))
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        sel = {"item": None}
        def ok():
            cur = tree.focus()
            if cur:
                vals = tree.item(cur, "values")
                for it in items:
                    if (it.get("date"), it.get("category"), it.get("doidate"), str(it.get("doino")), it.get("title_ja","")) == tuple(vals):
                        sel["item"] = it
                        break
            dlg.destroy()
        ttk.Button(dlg, text="OK", command=ok).pack(pady=(0,8))
        dlg.transient(self)
        dlg.grab_set()
        dlg.wait_window()
        return sel["item"]

    def open_random(self):
        vw = self.ensure_viewer_window()
        base_dir = Path(self.base_dir_var.get()).resolve()
        cat = load_catalog(base_dir)
        items = cat.get("items", [])
        if not items:
            messagebox.showinfo("catalog.json 空", "catalog.json に記事がありません。Fetch 後にお試しください。")
            return
        it = random.choice(items)
        p = base_dir / it["html_rel"]
        vw.open_local(p)
        vw.set_home("file", str(p))

    # 外部ブラウザ開き（旧インデックス）
    def refresh_category_list(self):
        items = self.collect_categories_from_fs()
        self.cat_cb["values"] = items
        if items:
            self.cat_list_var.set(items[0])

    def open_selected_category_index(self):
        base_dir = Path(self.base_dir_var.get()).resolve()
        slug = (self.cat_list_var.get() or "").strip()
        if not slug:
            messagebox.showwarning("No category", "カテゴリが見つかりません。Refresh を試してください。")
            return
        path = base_dir / "category" / slug / "category.html"
        self._open_file(path)

    def open_selected_date_index(self):
        base_dir = Path(self.base_dir_var.get()).resolve()
        date = (self.date_var.get() or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            messagebox.showerror("Invalid date", "日付は YYYY-MM-DD の形式で入力してください。")
            return
        path = base_dir / "date" / date / "date.html"
        self._open_file(path)

    def open_all_dates_index(self):
        base_dir = Path(self.base_dir_var.get()).resolve()
        path = base_dir / "date" / "all_date.html"
        self._open_file(path)

    def _open_file(self, path: Path):
        if not path.exists():
            messagebox.showerror("Not found", f"ファイルが見つかりません:\n{path}")
        else:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')

    # ---- 実処理（Fetch） ----
    def on_run(self):
        server = self.server_var.get().strip()
        start_date_str = self.date_var.get().strip()
        base_dir = Path(self.base_dir_var.get()).resolve()
        lm_url = self.lm_url_var.get().strip()
        lm_model = self.lm_model_var.get().strip()
        period = self.period_var.get()

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date_str):
            messagebox.showerror("Invalid date", "日付は YYYY-MM-DD の形式で入力してください。")
            return
        days = PERIOD_MAP.get(period, 1)

        raw_kws = self.kw_var.get()
        kws = [k.strip() for k in raw_kws.split(",") if k.strip()]
        mode = (self.kw_mode_var.get() or "OR").upper()
        if mode not in ("OR", "AND"):
            mode = "OR"

        lic_preset = self.license_preset_var.get().strip().lower()
        require_cc = bool(self.require_cc_var.get())
        ex_by = bool(self.ex_by_var.get())
        ex_nc = bool(self.ex_nc_var.get())
        ex_nd = bool(self.ex_nd_var.get())
        ex_sa = bool(self.ex_sa_var.get())

        self.log_buffer = []
        self.start_ts_str = self.ts_now_str()
        self.pause_ts_str = None

        self.save_settings_files(base_dir, self.start_ts_str)

        self.set_running(True)
        self.stop_now_event.clear()
        self.stop_after_day_event.clear()
        self.stop_after_article_event.clear()
        self.pause_request_event.clear()

        self.progress.config(value=0, maximum=100)
        self.prog_lbl.config(text="Progress: -/-")
        self.log_text.delete("1.0", "end")

        self.log(f"[START] server={server}, start_date={start_date_str}, period={period}({days} days), base_dir={base_dir}")
        if kws:
            self.log(f"[FILTER] keywords={kws} mode={mode}")
        self.log(f"[LICENSE] preset={lic_preset} require_cc={require_cc} exclude={{'by':{ex_by}, 'nc':{ex_nc}, 'nd':{ex_nd}, 'sa':{ex_sa}}}")
        self.log(f"[SETTINGS] saved at ./setting/setting.txt and ./log/setting/{self.start_ts_str}.log")

        try:
            y, m, d = [int(x) for x in start_date_str.split("-")]
            start_date = ddate(y, m, d)
        except Exception:
            messagebox.showerror("Invalid date", "日付の解析に失敗しました。")
            self.set_running(False)
            return

        dates = [(start_date - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]

        def matches_keywords(record: dict) -> bool:
            if not kws:
                return True
            text = ((record.get("title") or "") + " " + (record.get("abstract") or "")).lower()
            flags = [(kw.lower() in text) for kw in kws]
            return all(flags) if mode == "AND" else any(flags)

        def is_cc_license_ok(lic: str) -> bool:
            return lic.startswith("cc_") and lic != "cc_no"

        def matches_license(record: dict) -> bool:
            lic = (record.get("license") or "").lower().strip()
            if lic_preset and lic_preset != "any" and lic != lic_preset:
                return False
            if require_cc and not is_cc_license_ok(lic):
                return False
            if ex_by and "by" in lic:
                return False
            if ex_nc and "nc" in lic:
                return False
            if ex_nd and "nd" in lic:
                return False
            if ex_sa and "sa" in lic:
                return False
            return True

        def worker():
            try:
                terminate_all = False
                for di, day_str in enumerate(dates, start=1):
                    if terminate_all or self.stop_now_event.is_set():
                        self.log("[INFO] Stop Now: 期間処理を中断します。")
                        break

                    self.log(f"[DAY] {di}/{len(dates)}  Target date = {day_str}")
                    url = f"{DEFAULT_API_BASE}/{server}/{day_str}/{day_str}/0"

                    records, total_api = fetch_all_pages_step(url, log_fn=self.log, stop_event=self.stop_now_event)
                    if self.stop_now_event.is_set():
                        self.log("[INFO] Stop Now: 当日処理を開始前に中断。")
                        break

                    if not records:
                        self.log("[INFO] 収集対象なし（collection 空）")
                        update_all_date_index(base_dir, day_str, collected=0)
                        update_month_log(base_dir, day_str, collected=0)
                        update_year_log(base_dir, day_str)
                        if self.stop_after_day_event.is_set():
                            self.log("[INFO] Stop After This Day: 当日が空のためそのまま終了します。")
                            break
                        continue

                    lic_filtered = [r for r in records if matches_license(r)]
                    kw_filtered = [r for r in lic_filtered if matches_keywords(r)]
                    self.log(f"[FILTER] license={len(lic_filtered)}/{len(records)}; keywords={len(kw_filtered)}/{len(lic_filtered)} for {day_str}")
                    filtered = kw_filtered
                    total = len(filtered)

                    if total == 0:
                        self.log("[INFO] フィルタ一致なし。ログのみ更新します。")
                        update_all_date_index(base_dir, day_str, collected=0)
                        update_month_log(base_dir, day_str, collected=0)
                        update_year_log(base_dir, day_str)
                        if self.stop_after_day_event.is_set():
                            self.log("[INFO] Stop After This Day: 当日の処理完了（ゼロ件）。終了します。")
                            break
                        continue

                    self.progress.config(value=0, maximum=max(1, total))
                    self.prog_lbl.config(text=f"Day {di}/{len(dates)} — Progress: 0/{total}")

                    processed = 0
                    for i, rec in enumerate(filtered, start=1):
                        if self.stop_now_event.is_set():
                            self.log("[INFO] Stop Now: 当日処理を中断します。")
                            terminate_all = True
                            break
                        try:
                            title_ja, corr, inst, authors, license_str, used_lm = process_record(
                                base_dir, rec, total=total, index=i,
                                lm_url=lm_url, lm_model=lm_model, log_fn=self.log
                            )
                            processed += 1
                            self.after(0, self.on_paper_done_ui, base_dir, title_ja, corr, inst, authors, license_str, used_lm)
                        except Exception as e:
                            self.log(f"[WARN] 1件処理失敗: {e}")
                        self.progress.config(value=i)
                        self.prog_lbl.config(text=f"Day {di}/{len(dates)} — Progress: {i}/{total}")
                        self.update_idletasks()

                        if self.stop_after_article_event.is_set():
                            self.log("[INFO] Stop After This Article: 現在の論文処理完了後に停止します。")
                            terminate_all = True
                            break

                        if self.pause_request_event.is_set():
                            self.log("[INFO] Pause: 現在の論文処理が完了。再開指示を待機します（Resumeを押してください）。")
                            while self.pause_request_event.is_set():
                                if self.stop_now_event.is_set() or self.stop_after_day_event.is_set() or self.stop_after_article_event.is_set():
                                    break
                                time.sleep(0.2)
                            if self.stop_now_event.is_set() or self.stop_after_day_event.is_set() or self.stop_after_article_event.is_set():
                                terminate_all = True
                                break

                    update_all_date_index(base_dir, day_str, collected=processed)
                    update_month_log(base_dir, day_str, collected=processed)
                    update_year_log(base_dir, day_str)

                    if terminate_all or self.stop_after_day_event.is_set():
                        if self.stop_after_day_event.is_set():
                            self.log("[INFO] Stop After This Day: 当日の処理完了を確認。全体を終了します。")
                        break

                self.log("[DONE] 期間処理が終了。")
            except Exception as e:
                self.log(f"[ERROR] {e}")
            finally:
                if self.stop_now_event.is_set() or self.stop_after_day_event.is_set() or self.stop_after_article_event.is_set():
                    ts = self.pause_ts_str or self.ts_now_str()
                    self.save_log_file(base_dir, kind="pause", ts_str=ts)
                else:
                    ts = self.start_ts_str or self.ts_now_str()
                    self.save_log_file(base_dir, kind="fetch", ts_str=ts)

                self.set_running(False)
                self.refresh_category_list()
                self.refresh_category_list_for_viewer()

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

if __name__ == "__main__":
    App().mainloop()
