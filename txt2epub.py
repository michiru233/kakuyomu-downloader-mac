#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
txt2epub.py — 青空文庫形式テキスト → 縦書き EPUB3 変換器

kakuyomu ダウンローダー（kakuyomu_core.py）が出力した青空文庫形式 .txt を、
日本語の縦書き小説としてそのまま読める EPUB3 に変換します。

特徴:
  * 縦書き（writing-mode: vertical-rl）+ 右綴じ（page-progression-direction="rtl"）
  * 各話（［＃中見出し］）ごとに 1 ファイル → 目次が話単位で正確
  * 章（［＃大見出し］）は目次の第 1 レベルとしてグループ化
  * ルビ（｜漢字《かんじ》）/ 傍点 / 罫囲み / 改ページ / 挿絵リンク に対応
  * 表紙画像を埋め込み可能
  * 依存: Python 標準ライブラリのみ

使い方:
  python3 txt2epub.py 作品.txt
  python3 txt2epub.py 作品.txt --cover 封面.jpg
  python3 txt2epub.py 作品.txt -o 出力.epub --title "書名" --author "作者"
  python3 txt2epub.py *.txt --cover cover.jpg      # 複数まとめて変換
"""

from __future__ import annotations

import argparse
import datetime
import html
import mimetypes
import os
import re
import sys
import urllib.request
import uuid
import zipfile

# ---------------------------------------------------------------------------
# 正規表現
# ---------------------------------------------------------------------------

RE_H1 = re.compile(r'^［＃大見出し］(.*)［＃大見出し終わり］\s*$')
RE_H1_OLD = re.compile(r'^［＃「(.*)」は大見出し］\s*$')
RE_H2 = re.compile(r'^［＃中見出し］(.*)［＃中見出し終わり］\s*$')
RE_H2_OLD = re.compile(r'^［＃「(.*)」は中見出し］\s*$')
RE_H3 = re.compile(r'^［＃小見出し］(.*)［＃小見出し終わり］\s*$')
RE_PAGEBREAK = re.compile(r'^［＃(改ページ|改丁)］\s*$')
RE_KEI_START = re.compile(r'^［＃ここから罫囲み］\s*$')
RE_KEI_END = re.compile(r'^［＃ここで罫囲み終わり］\s*$')
RE_INDENT_START = re.compile(r'^［＃ここから(\d+)字下げ］\s*$')
RE_INDENT_END = re.compile(r'^［＃ここで字下げ終わり］\s*$')

# 行内要素
RE_ESC_HIRA = re.compile(r'※［＃始め二重山括弧、[\d-]+］')
RE_ESC_KAGI = re.compile(r'※［＃終わり二重山括弧、[\d-]+］')
RE_ESC_TATE = re.compile(r'※［＃縦線、[\d-]+］')
RE_IMG_LINK = re.compile(r'［＃リンクの図（(.*?)）入る］')
RE_COVER_IMG = re.compile(r'［＃表紙の図（(.*?)）入る］')
RE_EMPH_ON = re.compile(r'［＃丸傍点］')
RE_EMPH_OFF = re.compile(r'［＃丸傍点終わり］')
RE_ANY_TAG = re.compile(r'［＃[^］]*］')
# ルビ: ｜base《rt》 → まず明示指定を処理
RE_RUBY_EXPLICIT = re.compile(r'｜([^《》｜\n]*?)《([^》\n]*?)》')
# ルビ: 漢字《rt》 （青空文庫の暗黙ルール）
RE_RUBY_IMPLICIT = re.compile(
    r'([\u3400-\u9FFF\uF900-\uFAFF\u3005\u3006\u30F6]+)《([^》\n]*?)》')

STATUS_PREFIX = re.compile(r'^【(連載中|完結|短編)】')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')


# ---------------------------------------------------------------------------
# テキスト整形の小道具
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_inline(s: str, images: 'ImageStore') -> str:
    """本文 1 行をインライン要素込みの XHTML 断片に変換する。"""
    s = esc(s)
    # 青空文庫の代替表記 → 実際の記号
    s = RE_ESC_HIRA.sub('《', s)
    s = RE_ESC_KAGI.sub('》', s)
    s = RE_ESC_TATE.sub('｜', s)
    # 挿絵
    s = RE_IMG_LINK.sub(lambda m: images.html_for(m.group(1)), s)
    # 傍点
    s = RE_EMPH_ON.sub('<em class="emph">', s)
    s = RE_EMPH_OFF.sub('</em>', s)
    # ルビ
    s = RE_RUBY_EXPLICIT.sub(
        lambda m: f'<ruby>{m.group(1)}<rt>{m.group(2)}</rt></ruby>', s)
    s = RE_RUBY_IMPLICIT.sub(
        lambda m: f'<ruby>{m.group(1)}<rt>{m.group(2)}</rt></ruby>', s)
    # 未対応の注記は落とす
    s = RE_ANY_TAG.sub('', s)
    return s


class ImageStore:
    """挿絵リンクを実際の画像として取り込む（失敗時はリンク文字列に退避）。"""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.items = []          # (href, bytes, media_type)
        self._map = {}

    def html_for(self, url: str) -> str:
        url = url.strip()
        if not url:
            return ''
        if not self.enabled:
            return f'<span class="imgref">［画像: {url}］</span>'
        if url in self._map:
            return f'<img class="illust" src="../{self._map[url]}" alt="挿絵"/>'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            ext = self._guess_ext(url, r.headers.get('Content-Type', ''))
            name = f'images/illust_{len(self.items) + 1:03d}{ext}'
            media = mimetypes.guess_type('x' + ext)[0] or 'image/jpeg'
            self.items.append((name, data, media))
            self._map[url] = name
            return f'<img class="illust" src="../{name}" alt="挿絵"/>'
        except Exception:                       # noqa: BLE001
            return f'<span class="imgref">［画像: {esc(url)}］</span>'

    @staticmethod
    def _guess_ext(url: str, ctype: str) -> str:
        ctype = (ctype or '').split(';')[0].strip().lower()
        if ctype in ('image/png',):
            return '.png'
        if ctype in ('image/gif',):
            return '.gif'
        if ctype in ('image/webp',):
            return '.webp'
        m = re.search(r'\.(jpe?g|png|gif|webp)(?:\?|$)', url, re.I)
        if m:
            return '.' + m.group(1).lower().replace('jpeg', 'jpg')
        return '.jpg'


# ---------------------------------------------------------------------------
# 青空文庫テキストの解析
# ---------------------------------------------------------------------------

class Section:
    def __init__(self, title, chapter=None):
        self.title = title
        self.chapter = chapter
        self.blocks = []       # ('p', str) / ('h3', str) / ('keikakumi', [blocks]) / ('blank',)

    @property
    def anchor(self):
        return None


class Book:
    def __init__(self):
        self.title = ''
        self.author = ''
        self.status = ''
        self.title_blocks = []     # 巻首（書名・作者以外の前書き/あらすじ）
        self.sections = []


def parse_aozora(text: str, strip_status=True) -> Book:
    text = text.lstrip('\ufeff')
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    book = Book()
    # 1 行目 = 書名, 2 行目 = 作者
    if lines:
        book.title = lines[0].strip()
    if len(lines) > 1:
        book.author = lines[1].strip()

    m = STATUS_PREFIX.match(book.title)
    if m:
        book.status = m.group(0)
        if strip_status:
            book.title = book.title[m.end():].strip()

    images = ImageStore(enabled=False)   # 解析段階では画像取得しない

    cur_sec: Section | None = None
    cur_chapter: str | None = None
    chapter_pending = False       # 次の Section の先頭に章題を出すか
    in_intro = True
    kei_stack = None              # 罫囲み中のブロックリスト
    blank_pending = False

    def target():
        return kei_stack if kei_stack is not None else (
            cur_sec.blocks if cur_sec is not None else book.title_blocks)

    for raw in lines[2:]:
        line = raw.rstrip('\n')
        if line.strip() == '':
            # 空行は 1 つに圧縮して保持
            if not in_intro or True:
                blank_pending = True
            continue

        # --- 見出し ---
        m = RE_H1.match(line) or RE_H1_OLD.match(line)
        if m:
            cur_chapter = m.group(1).strip()
            chapter_pending = True
            in_intro = False
            blank_pending = False
            continue
        m = RE_H2.match(line) or RE_H2_OLD.match(line)
        if m:
            title = m.group(1).strip()
            cur_sec = Section(title, cur_chapter)
            if chapter_pending:
                cur_sec.chapter_first = True   # type: ignore[attr-defined]
                chapter_pending = False
            book.sections.append(cur_sec)
            in_intro = False
            blank_pending = False
            continue
        m = RE_H3.match(line)
        if m:
            target().append(('h3', m.group(1).strip()))
            blank_pending = False
            continue

        # --- 改ページ ---
        if RE_PAGEBREAK.match(line):
            in_intro = False
            blank_pending = False
            continue

        # --- 罫囲み ---
        if RE_KEI_START.match(line):
            kei_stack = []
            blank_pending = False
            continue
        if RE_KEI_END.match(line):
            if kei_stack is not None:
                blk = ('keikakumi', kei_stack)
                kei_stack = None
                target().append(blk)
            blank_pending = False
            continue

        # --- 字下げ（近似的に無視） ---
        if RE_INDENT_START.match(line) or RE_INDENT_END.match(line):
            continue

        # --- 通常行 ---
        if blank_pending:
            tgt = target()
            if tgt:                      # セクション/巻首の先頭に来る空行は無視
                tgt.append(('blank',))
            blank_pending = False
        target().append(('p', line))

    if kei_stack is not None and book.sections:
        book.sections[-1].blocks.append(('keikakumi', kei_stack))

    return book


# ---------------------------------------------------------------------------
# XHTML 生成
# ---------------------------------------------------------------------------

def block_to_xhtml(blocks, images: ImageStore) -> str:
    out = []
    for blk in blocks:
        kind = blk[0]
        if kind == 'blank':
            out.append('<p class="blank"><br/></p>')
        elif kind == 'p':
            txt = blk[1]
            if txt.strip() == '':
                out.append('<p class="blank"><br/></p>')
            else:
                out.append(f'<p>{render_inline(txt.lstrip() if False else txt, images)}</p>')
        elif kind == 'h3':
            out.append(f'<h3>{render_inline(blk[1], images)}</h3>')
        elif kind == 'keikakumi':
            inner = block_to_xhtml(blk[1], images)
            out.append(f'<div class="keikakumi">{inner}</div>')
    return '\n'.join(out)


XHTML_HEAD = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ja" lang="ja">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="../css/style.css"/>
</head>
<body>
{body}
</body>
</html>
'''


def section_xhtml(sec: Section, images: ImageStore, book: Book) -> str:
    parts = []
    if getattr(sec, 'chapter_first', False) and sec.chapter:
        parts.append(f'<h1 class="chapter">{render_inline(sec.chapter, images)}</h1>')
    if sec.title:
        parts.append(f'<h2 class="episode">{render_inline(sec.title, images)}</h2>')
    parts.append(block_to_xhtml(sec.blocks, images))
    body = '<section epub:type="chapter">\n' + '\n'.join(parts) + '\n</section>'
    return XHTML_HEAD.format(title=esc(sec.title or book.title), body=body)


def title_xhtml(book: Book, images: ImageStore) -> str:
    body = ('<div class="titlepage">\n'
            f'<h1 class="booktitle">{render_inline(book.title, images)}</h1>\n'
            f'<p class="author">{render_inline(book.author, images)}</p>\n'
            '</div>')
    return XHTML_HEAD.format(title=esc(book.title), body=body)


def intro_xhtml(book: Book, images: ImageStore) -> str | None:
    if not book.title_blocks:
        return None
    inner = block_to_xhtml(book.title_blocks, images)
    if not inner.strip():
        return None
    body = ('<section epub:type="preface" class="preface">\n'
            '<h2 class="introtit">あらすじ</h2>\n'
            f'{inner}\n</section>')
    return XHTML_HEAD.format(title='あらすじ', body=body)


def cover_xhtml(cover_href: str) -> str:
    body = ('<div class="coverpage">\n'
            f'<img src="../{cover_href}" alt="表紙"/>\n'
            '</div>')
    return XHTML_HEAD.format(title='表紙', body=body)


def nav_xhtml(book: Book, pages) -> str:
    """pages: list of dict(kind, title, href, chapter)"""
    # 章ごとにグループ化
    groups = []
    for p in pages:
        if p['kind'] in ('title', 'intro', 'cover'):
            continue
        ch = p.get('chapter')
        if groups and ch is not None and groups[-1]['chapter'] == ch:
            groups[-1]['items'].append(p)
        else:
            groups.append({'chapter': ch, 'items': [p]})

    li = []
    for g in groups:
        if g['chapter'] and len(groups) > 1:
            sub = '\n'.join(
                f'      <li><a href="{p["href"]}">{esc(p["title"])}</a></li>'
                for p in g['items'])
            li.append(
                f'    <li><a href="{g["items"][0]["href"]}">{esc(g["chapter"])}</a>\n'
                f'      <ol>\n{sub}\n      </ol>\n    </li>')
        else:
            for p in g['items']:
                li.append(f'    <li><a href="{p["href"]}">{esc(p["title"])}</a></li>')

    body = ('<nav epub:type="toc" id="toc">\n'
            '<h1>目次</h1>\n<ol>\n' + '\n'.join(li) + '\n</ol>\n</nav>')
    return XHTML_HEAD.format(title='目次', body=body)


def ncx_xml(book: Book, pages, uid: str) -> str:
    pts = []
    order = 0
    for p in pages:
        if p['kind'] in ('title', 'intro', 'cover'):
            continue
        order += 1
        pts.append(
            f'    <navPoint id="np{order}" playOrder="{order}">\n'
            f'      <navLabel><text>{esc(p["title"])}</text></navLabel>\n'
            f'      <content src="{p["href"]}"/>\n'
            f'    </navPoint>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="ja">\n'
        '  <head>\n'
        f'    <meta name="dtb:uid" content="{uid}"/>\n'
        '    <meta name="dtb:depth" content="2"/>\n'
        '  </head>\n'
        f'  <docTitle><text>{esc(book.title)}</text></docTitle>\n'
        f'  <docAuthor><text>{esc(book.author)}</text></docAuthor>\n'
        '  <navMap>\n' + '\n'.join(pts) + '\n  </navMap>\n</ncx>\n')


STYLE_CSS = '''@charset "utf-8";

/* --- 縦書き（右綴じ）設定 --- */
html {
  -epub-writing-mode: vertical-rl;
  -webkit-writing-mode: vertical-rl;
  writing-mode: vertical-rl;
}
body {
  font-family: "Hiragino Mincho ProN", "Hiragino Mincho Pro", "Yu Mincho",
               "YuMincho", "Noto Serif JP", "Noto Serif CJK JP", serif;
  font-size: 1em;
  line-height: 1.75;
  margin: 0;
  padding: 0;
}

/* --- 本文 --- */
p {
  margin: 0;
  text-indent: 1em;          /* 縦書きでは下方向への字下げ */
  line-height: 1.75;
}
p.blank {
  text-indent: 0;
}

/* --- 見出し --- */
h1, h2, h3 {
  font-weight: 600;
  line-height: 1.4;
  margin: 0 0 1em 0;
  text-indent: 0;
}
h1.booktitle, h1.chapter {
  font-size: 1.5em;
  margin: 0 0 1.2em 0;
}
h2.episode, h2.introtit {
  font-size: 1.2em;
  margin: 0 0 1.2em 0;
}
h3 { font-size: 1.05em; }

/* --- 扉・あらすじ --- */
div.titlepage {
  margin-top: 15%;
  text-align: center;
  text-indent: 0;
}
div.titlepage p.author {
  font-size: 1em;
  text-indent: 0;
}
section.preface { text-indent: 0; }

/* --- 罫囲み（あらすじ等） --- */
div.keikakumi {
  border: 1px solid currentColor;
  padding: 0.6em 0.9em;
  margin: 1em 0;
}
div.keikakumi p { text-indent: 1em; }

/* --- 傍点 --- */
em.emph {
  font-style: normal;
  -epub-text-emphasis: filled dot;
  -webkit-text-emphasis: filled dot;
  text-emphasis: filled dot;
}

/* --- ルビ --- */
rt { font-size: 0.5em; }
ruby { ruby-align: center; }

/* --- 挿絵 --- */
img.illust {
  display: block;
  max-width: 100%;
  max-height: 100%;
  margin: 0.8em 0;
}
span.imgref { font-size: 0.85em; }

/* --- 表紙 --- */
div.coverpage {
  margin: 0;
  padding: 0;
  text-align: center;
  text-indent: 0;
}
div.coverpage img {
  max-width: 100%;
  max-height: 100%;
}
'''


CONTENT_OPF = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="ja">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{uid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>ja</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
{cover_meta}  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="css/style.css" media-type="text/css"/>
{cover_item}{img_items}{xhtml_items}  </manifest>
  <spine toc="ncx" page-progression-direction="rtl">
{spine_items}  </spine>
</package>
'''

CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''


# ---------------------------------------------------------------------------
# EPUB 書き出し
# ---------------------------------------------------------------------------

def build_epub(book: Book, out_path: str, cover_path: str | None = None,
               enable_images: bool = True) -> str:
    images = ImageStore(enabled=enable_images)

    # 各話 XHTML を生成
    pages = []       # dict(kind, title, href, chapter)
    files = {}       # href(within OEBPS) -> str

    uid = 'urn:uuid:' + str(uuid.uuid4())
    modified = datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')

    # 表紙
    cover_href = None
    if cover_path and os.path.isfile(cover_path):
        with open(cover_path, 'rb') as f:
            data = f.read()
        ext = os.path.splitext(cover_path)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            ext = '.jpg'
        cover_href = 'images/cover' + ('.jpg' if ext in ('.jpeg',) else ext)
        media = mimetypes.guess_type('x' + ext)[0] or 'image/jpeg'
        images.items.append((cover_href, data, media))
        files['text/cover.xhtml'] = cover_xhtml(cover_href)
        pages.append({'kind': 'cover', 'title': '表紙',
                      'href': 'text/cover.xhtml', 'chapter': None})

    # 扉
    files['text/title.xhtml'] = title_xhtml(book, images)
    pages.append({'kind': 'title', 'title': book.title,
                  'href': 'text/title.xhtml', 'chapter': None})

    # あらすじ
    intro = intro_xhtml(book, images)
    if intro:
        files['text/intro.xhtml'] = intro
        pages.append({'kind': 'intro', 'title': 'あらすじ',
                      'href': 'text/intro.xhtml', 'chapter': None})

    # 各話
    for i, sec in enumerate(book.sections, 1):
        href = f'text/sec_{i:04d}.xhtml'
        files[href] = section_xhtml(sec, images, book)
        pages.append({'kind': 'section', 'title': sec.title or f'第{i}話',
                      'href': href, 'chapter': sec.chapter})

    # 目次
    files['nav.xhtml'] = nav_xhtml(book, pages)
    files['toc.ncx'] = ncx_xml(book, pages, uid)
    files['css/style.css'] = STYLE_CSS

    # ---- content.opf ----
    cover_meta = ''
    if cover_href:
        cover_meta = '    <meta name="cover" content="cover-image"/>\n'

    manifest = []
    spine = []

    def add_spine(idref):
        spine.append(f'    <itemref idref="{idref}"/>')

    xhtml_items = []
    for idx, p in enumerate(pages):
        item_id = 'x%s' % idx if p['kind'] != 'cover' else 'cover'
        xhtml_items.append(
            f'    <item id="{item_id}" href="{p["href"]}" media-type="application/xhtml+xml"/>\n')
        add_spine(item_id)

    cover_item = ''
    if cover_href:
        cover_item = (f'    <item id="cover-image" href="{cover_href}" '
                      f'media-type="{mimetypes.guess_type("x" + os.path.splitext(cover_href)[1])[0] or "image/jpeg"}" '
                      f'properties="cover-image"/>\n')

    img_items = ''
    for i, (name, _data, media) in enumerate(images.items, 1):
        if cover_href and name == cover_href:
            continue
        img_items += f'    <item id="img{i}" href="{name}" media-type="{media}"/>\n'

    opf = CONTENT_OPF.format(
        uid=uid, title=esc(book.title), author=esc(book.author),
        modified=modified, cover_meta=cover_meta, cover_item=cover_item,
        img_items=img_items, xhtml_items=''.join(xhtml_items),
        spine_items=''.join(spine),
    )

    # ---- ZIP 書き出し ----
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        # mimetype は必ず最初・無圧縮
        zi = zipfile.ZipInfo('mimetype')
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, 'application/epub+zip')
        z.writestr('META-INF/container.xml', CONTAINER_XML)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', files['nav.xhtml'])
        z.writestr('OEBPS/toc.ncx', files['toc.ncx'])
        z.writestr('OEBPS/css/style.css', files['css/style.css'])
        for href, content in files.items():
            if href in ('nav.xhtml', 'toc.ncx', 'css/style.css'):
                continue
            z.writestr('OEBPS/' + href, content)
        for name, data, _media in images.items:
            z.writestr('OEBPS/' + name, data)

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def convert_one(txt_path, out_path=None, cover=None, title=None, author=None,
                horizontal=False, no_images=False, keep_status=False,
                log=print):
    with open(txt_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        text = f.read()
    book = parse_aozora(text, strip_status=not keep_status)
    if title:
        book.title = title
    if author:
        book.author = author
    if out_path is None:
        out_path = os.path.splitext(txt_path)[0] + '.epub'
    build_epub(book, out_path, cover_path=cover, enable_images=not no_images)
    log(f'{os.path.basename(txt_path)} → {out_path} '
        f'（{len(book.sections)} 話 / {len(book.title_blocks)} 巻首ブロック）')
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='青空文庫形式テキスト → 縦書き EPUB3 変換')
    ap.add_argument('inputs', nargs='+', help='入力 .txt（複数可）')
    ap.add_argument('-o', '--output', help='出力 .epub（入力 1 つのときのみ）')
    ap.add_argument('--cover', help='表紙画像（jpg/png）')
    ap.add_argument('--title', help='書名を上書き')
    ap.add_argument('--author', help='作者名を上書き')
    ap.add_argument('--keep-status', action='store_true',
                    help='書名の【連載中】等の接頭辞を残す')
    ap.add_argument('--no-images', action='store_true',
                    help='挿絵をダウンロードしない（リンク表示のみ）')
    args = ap.parse_args(argv)

    if args.output and len(args.inputs) > 1:
        ap.error('-o は入力が 1 つのときだけ指定できます')

    for p in args.inputs:
        if not os.path.isfile(p):
            print(f'見つかりません: {p}', file=sys.stderr)
            continue
        convert_one(p, out_path=args.output, cover=args.cover,
                    title=args.title, author=args.author,
                    no_images=args.no_images, keep_status=args.keep_status)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
