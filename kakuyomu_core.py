# -*- coding: utf-8 -*-
"""
kakuyomu_core.py — カクヨム小説ダウンローダー (kakuyomudl) の macOS/Python 移植版・コア処理

原作: minouejapan / kakuyomu-downloader (Object Pascal, MIT License)
      https://github.com/minouejapan/kakuyomu-downloader

移植方針:
  * 出力仕様（青空文庫形式テキスト / .log）は原作 4.97 に完全準拠。
  * 原作の Windows 専用コード（コンソールカーソル操作・Naro2mobi への
    WM_COPYDATA 送信・バージョンリソース）は移植対象外。
  * ネットワークは urllib（標準ライブラリ）のみ。追加依存ゼロ。

※ カクヨムネクスト等の有料作品はダウンロードできません（原作と同様）。
"""

from __future__ import annotations

import os
import re
import sys
import time
import urllib.error
import urllib.request

# ----------------------------------------------------------------------------
# 定数（原作 kakuyomudl.dpr より）
# ----------------------------------------------------------------------------

# データ抽出用の識別タグ
STITLEB = '<h1 .*?><.*?><a title="'                                  # 小説表題
STITLEE = '" href='
SAUTHERB = '<div class="partialGiftWidgetActivityName"><a href="'    # 作者
SAUTHERM = '" .*?>'
SAUTHERE = '</a>'
SSTRURLB = '{"__typename":"Episode","id":"'                          # 各話 ID
SSTRURLE = '","title":"'

SCHAPTB = '<p class="chapterTitle level1 js-vertical-composition-item"><span>'
SCHAPTB2 = '<p class="chapterTitle level2 js-vertical-composition-item"><span>'
SCHAPTE = '</span>'
SEPISB = '<p class="widget-episodeTitle js-vertical-composition-item">'
SEPISE = '</p>'

SERRSTR = '<div class="dots-indicator" id="LoadingEpisode">'
SHREFB = '<a href="'
SHREFE = '">'

# 青空文庫形式
AO_RBI = '｜'            # ルビのかかり始め
AO_RBL = '《'            # ルビ始め
AO_RBR = '》'            # ルビ終わり
AO_CPB = '［＃大見出し］'
AO_CPE = '［＃大見出し終わり］'
AO_SEB = '［＃中見出し］'
AO_SEE = '［＃中見出し終わり］'
AO_SEC = '」は中見出し］'
AO_CPI = '［＃「'
AO_PB2 = '［＃改ページ］'
AO_EMB = '［＃丸傍点］'
AO_EME = '［＃丸傍点終わり］'
AO_KKL = '［＃ここから罫囲み］'
AO_KKR = '［＃ここで罫囲み終わり］'
AO_PIB = '［＃リンクの図（'
AO_PIE = '）入る］'

CRLF = '\r\n'

# ログファイル表題
NVURL = '小説URL   :'
NVTITLE = 'タイトル  :'
NVAUTH = '作者      :'
NVAURL = '作者URL   :'
NVSYNP = 'あらすじ  :'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')

_TRIMSET = ' \u3000\t\r\n'   # 半角空白 / 全角空白 / タブ / CR / LF


# ----------------------------------------------------------------------------
# ネットワーク
# ----------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = 30) -> str:
    """指定 URL の HTML を UTF-8 文字列として取得する。失敗時は空文字列。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en;q=0.9',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return ''
    text = raw.decode('utf-8', errors='replace')
    # 行末を CRLF に正規化する。
    # 原作では Delphi/Lazarus の TStringList.Text が全行を CRLF で連結するため、
    # 後段の ElimCRLF が「行末だけ」を除去できる。ここで同じ状態を作る。
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')


# ----------------------------------------------------------------------------
# 文字列ユーティリティ（原作 1:1）
# ----------------------------------------------------------------------------

def ElimCRLF(base: str) -> str:
    """HTML テキスト内の CR/LF を除去する。"""
    return base.replace('\r\n', '')


def ElimTag(base: str) -> str:
    """前書き内のタグを削除する。"""
    return re.sub(r'<.*?>', '', base, flags=re.S)


def ElimBodyTag(base: str) -> str:
    """本文内の余計なタグを削除する（カクヨム限定）。"""
    base = re.sub(r'<.*?>', '', base, flags=re.S)
    base = base.replace(' ' * 10, '')        # 各話の最後に入る半角空白10個を削除
    lines = base.replace('\r\n', '\n').split('\n')
    out = []
    for line in lines:
        if 'class="blank">' in line:
            out.append('')
            continue
        p = line.find('">')
        if p >= 0:
            line = line[p + 2:]
        out.append(line)
    return CRLF.join(out)


def TrimSpace(base: str) -> str:
    """前後の空白（半角/全角/tab/CR/LF）を除去する。"""
    return base.strip(_TRIMSET)


def ChangeBRK(base: str) -> str:
    """本文の改行タグを改行コードに変換する。"""
    base = ElimCRLF(base)
    base = base.replace('<br /></p>', '\r\n')
    base = base.replace('<br />', '\r\n')
    return base.replace('</p>', '\r\n')


def ChangeAozoraTag(base: str) -> str:
    """青空文庫ルビ指定に用いられる文字を代替表記に変換する。"""
    tmp = base.replace('<rp>《</rp>', '<rp>(</rp>')
    tmp = tmp.replace('<rp>》</rp>', '<rp>)</rp>')
    tmp = tmp.replace('《', '※［＃始め二重山括弧、1-1-52］')
    tmp = tmp.replace('》', '※［＃終わり二重山括弧、1-1-53］')
    tmp = tmp.replace('｜', '※［＃縦線、1-1-35］')
    return tmp


def ChangeRuby(base: str) -> str:
    """本文のルビタグを青空文庫形式に変換する。"""
    tmp = base.replace('<rp>(</rp>', '')
    tmp = tmp.replace('<rp>)</rp>', '')
    tmp = tmp.replace('<rp>（</rp>', '')
    tmp = tmp.replace('<rp>）</rp>', '')
    tmp = tmp.replace('<rb>', '')
    tmp = tmp.replace('</rb>', '')
    tmp = tmp.replace('<ruby>', AO_RBI)
    tmp = tmp.replace('<rt>', AO_RBL)
    tmp = tmp.replace('</rt></ruby>', AO_RBR)
    tmp = tmp.replace('<em class="emphasisDots"><span>', AO_EMB)
    tmp = tmp.replace('<span>', AO_EMB)
    tmp = tmp.replace('</span></em>', AO_EME)
    tmp = tmp.replace('</span>', AO_EME)
    return tmp


_ENT_RE = re.compile(r'&#(\w{2,6});')
_UNI_RE = re.compile(r'\\u([0-9A-Fa-f]{4})')


def _ent_repl(m: re.Match) -> str:
    cd = m.group(1)
    try:
        cp = int(cd[1:], 16) if cd[:1] in 'xX' else int(cd)
        return chr(cp)
    except (ValueError, OverflowError):
        return '?'


def _uni_repl(m: re.Match) -> str:
    try:
        return chr(int(m.group(1), 16))
    except (ValueError, OverflowError):
        return '？'


def Restore2RealChar(base: str) -> str:
    """HTML 特殊文字（エスケープ / &#xxxx; / \\uxxxx）を実際の文字に戻す。"""
    tmp = base.replace('&lt;', '<')
    tmp = tmp.replace('&gt;', '>')
    tmp = tmp.replace('&quot;', '"')
    tmp = tmp.replace('&nbsp;', ' ')
    tmp = tmp.replace('&yen;', '\\')
    tmp = tmp.replace('&brvbar;', '|')
    tmp = tmp.replace('&copy;', '©')
    tmp = tmp.replace('&amp;', '&')
    tmp = _ENT_RE.sub(_ent_repl, tmp)
    return _UNI_RE.sub(_uni_repl, tmp)


def ChangeImage(base: str) -> str:
    """埋め込まれた画像リンクを青空文庫形式に変換する（画像自体はDLしない）。"""
    base = re.sub(r'<figure id=.*?src="', AO_PIB, base, flags=re.S)
    base = re.sub(r'" /></figure>', AO_PIE, base, flags=re.S)
    base = re.sub(r'<img id=.*?src="', AO_PIB, base, flags=re.S)
    base = re.sub(r'" alt=".*?" />', AO_PIE, base, flags=re.S)
    return base


def Delete_href(base: str) -> str:
    """本文のリンクタグ <a href="..."> を除去する（リンク文字列は残す）。"""
    while True:
        i = base.find(SHREFB)
        if i < 0:
            break
        j = base.find(SHREFE, i)
        if j < 0:
            break
        base = base[:i] + base[j + len(SHREFE):]
    return base


_FILENAME_NG_RE = re.compile(r'[\\/:;*?+,."<>|.\t ]')


def PathFilter(pass_name: str) -> str:
    """タイトル名をファイル名として使えるよう整形する。

    原作は Shift_JIS で表現できない文字を除去する処理を挟んでいるが、
    macOS は UTF-8 ファイル名をそのまま扱えるため、ここでは不正文字の
    置換のみを行う。
    """
    return _FILENAME_NG_RE.sub('-', pass_name)


# ----------------------------------------------------------------------------
# ダウンローダ本体
# ----------------------------------------------------------------------------

class NovelNotAvailableError(Exception):
    """作品情報・本文を取得できなかった場合。"""


class Downloader:
    """1 作品をダウンロードして青空文庫形式テキストと .log を出力する。"""

    def __init__(self, url, out_dir=None, filename=None, start_page=None,
                 log=print, progress=None, on_ready=None):
        self.url = (url or '').strip()
        self.out_dir = out_dir or os.getcwd()
        self.filename = (filename or '').strip()       # 空なら作品名から生成
        if self.filename and not self.filename.lower().endswith('.txt'):
            self.filename += '.txt'
        self.start_page = (start_page or '').strip()   # -s オプション相当
        try:
            self.start_n = int(self.start_page) if self.start_page else 0
        except ValueError:
            raise ValueError('Error: Invalid Start Page Number.')
        self._log = log
        self._progress = progress
        self._on_ready = on_ready

        self.nvstat = ''          # 連載状況（【連載中】/【完結】/【短編】）
        self.chapter = ''         # 章（大見出し）
        self.st_ep_title = ' '    # 短編の話タイトル
        self.text_page = []       # 出力本文
        self.log_page = []        # ログ

    # -- ログ出力 ----------------------------------------------------------
    def _p(self, msg):
        self._log(msg)

    # -- 小説の連載状況をチェック -----------------------------------------
    @staticmethod
    def get_novel_status(main_page: str) -> str:
        if main_page.find('">連載中<!-- --> 全<!-- -->') >= 0:
            return '【連載中】'
        if main_page.find('">完結済<!-- --> 全<!-- -->') >= 0:
            if main_page.find('">完結済<!-- --> 全<!-- -->1<!-- -->話') >= 0:
                return '【短編】'
            return '【完結】'
        return ''

    # -- 小説本文をHTMLから抜き出す ---------------------------------------
    def parse_page(self, page: str) -> bool:
        result = False
        page = ChangeAozoraTag(page)
        page = re.sub(r'<!--.*?-->', '', page, flags=re.S)

        chapt = ''

        # 章 Level-1
        sp = page.find(SCHAPTB)
        if sp > 0:
            page = page[sp + len(SCHAPTB):]
            ep = page.find(SCHAPTE)
            if ep > 0:
                chapt = TrimSpace(page[:ep])
                if self.chapter == chapt:
                    chapt = ''
                else:
                    self.chapter = chapt
                page = page[ep + len(SCHAPTE):]

        # 章 Level-2
        sp = page.find(SCHAPTB2)
        if sp > 0:
            page = page[sp + len(SCHAPTB2):]
            ep = page.find(SCHAPTE)
            if ep > 0:
                chapt = TrimSpace(page[:ep])
                chapt = Restore2RealChar(chapt)
                if self.chapter != '':
                    chapt = self.chapter + '【' + chapt + '】'
                page = page[ep + len(SCHAPTE):]

        # 話（Episode）
        sp = page.find(SEPISB)
        if sp > 0:
            page = page[sp + len(SEPISB):]
            ep = page.find(SEPISE)
            if ep > 0:
                subt = TrimSpace(page[:ep])
                subt = Restore2RealChar(subt)
                if subt == '':
                    if self.nvstat == '【短編】':
                        subt = self.st_ep_title
                    else:
                        subt = '\u3000'   # Naro2mobi 誤作動防止の全角空白
                page = page[ep + len(SEPISE):]

                m = re.search(r'<p id="p1".*?</div>', page, re.S)
                if m:
                    body = m.group(0)
                else:
                    m = re.search(r'<figure id="p1".*?</div>', page, re.S)
                    body = m.group(0) if m else ''

                if body != '':
                    body = ChangeBRK(body)
                    body = ChangeImage(body)
                    body = Delete_href(body)
                    body = ChangeRuby(body)
                    body = ElimBodyTag(body)
                    body = Restore2RealChar(body)

                    if chapt:
                        self.text_page.append(AO_CPB + chapt + AO_CPE)

                    err = body.find(SERRSTR)
                    if 0 <= err < 10:
                        self.text_page.append(AO_CPI + subt + AO_SEC)
                        self.text_page.append('★HTMLページ読み込みエラー')
                        result = True
                    else:
                        self.text_page.append(AO_SEB + subt + AO_SEE)
                        self.text_page.append(body)
                        self.text_page.append('')
                        self.text_page.append(AO_PB2)
                else:
                    self._p(subt + ' から本文を抽出出来ませんでした.')
        return result

    # -- トップページからタイトル/作者/前書き/各話URLを取り出す -----------
    def parse_chapter(self, main_page: str) -> None:
        self._p('小説情報を取得中 ' + self.url + ' ... ')
        main_page = re.sub(r'<!--.*?-->', '', main_page)

        m = re.search(r'<h1.*?<a title=.*?</body></html>', main_page, re.S)
        body = m.group(0) if m else main_page

        # ---- タイトル名 ----
        m = re.search(STITLEB, body, re.S)
        if not m:
            return
        body = body[m.start() + len(m.group(0)):]

        sp = body.find(STITLEE)
        if sp < 0:
            return
        ss = body[:sp]
        while ss and ss[0] <= ' ':
            ss = ss[1:]

        title = Restore2RealChar(ss)
        fname = title
        self.st_ep_title = title if self.nvstat == '【短編】' else ' '

        # タイトルに「完結」が無ければ連載状況を先頭に付加
        if '完結' not in title:
            title = self.nvstat + title
            fname = self.nvstat + fname
        fname = PathFilter(Restore2RealChar(fname))

        if not self.filename:
            fn = fname
            if len(fn) > 26:
                fn = fn[:26]
            if self.start_page:
                fn = fn + '(' + self.start_page + ')'
            self.filename = os.path.join(self.out_dir, fn + '.txt')

        self.text_page.append(title)
        self.log_page.append(NVURL + self.url)
        self.log_page.append(NVTITLE + title)

        body = body[sp + len(STITLEE):]

        # ---- 作者 ----
        authurl = ''
        sp = body.find(SAUTHERB)
        if sp < 0:
            return
        body = body[sp + len(SAUTHERB):]

        m = re.search(SAUTHERM, body)
        if not m:
            return
        ts = body[:m.start()]
        authurl = 'https://kakuyomu.jp' + ts
        body = body[m.start() + len(m.group(0)):]

        ep = body.find(SAUTHERE)
        if ep < 0:
            return
        author = TrimSpace(body[:ep])
        body = body[ep + len(SAUTHERE):]

        self.text_page.append(author)
        self.text_page.append('')
        self.text_page.append(AO_PB2)
        self.log_page.append(NVAUTH + author)
        if authurl:
            self.log_page.append(NVAURL + authurl)

        # ---- 前書き（あらすじ） ----
        body_nocrlf = ElimCRLF(body)
        m = re.search(r'"introduction":".*?",', body_nocrlf, re.S)
        if m:
            ts = m.group(0)
            ts = ts.replace('"introduction":"', '')
            ts = ts.replace('",', '')
            ts = ts.replace('\\n', CRLF)
            ts = ts.replace('\\"', '"')
            ts = ElimTag(ts)
            ts = ts.replace('…続きを読む', '')
            ts = ChangeImage(ts)
            ts = ChangeAozoraTag(ts)
            ts = Restore2RealChar(ts)
            self.text_page.append(AO_KKL)
            self.text_page.append(ts)
            self.text_page.append(AO_KKR)
            self.text_page.append(AO_PB2)
            self.log_page.append(NVSYNP)
            self.log_page.append(ts)

        # ---- 各話 URL ----
        self.page_list = [self.url + '/episodes/' + ep_id
                          for ep_id in re.findall(
                              r'\{"__typename":"Episode","id":"(\d+)","title":"',
                              body)]
        self._p('%d 話の情報を取得しました.' % len(self.page_list))

    # -- 実行 --------------------------------------------------------------
    def run(self) -> str:
        if 'https://kakuyomu.jp/works/' not in self.url:
            raise NovelNotAvailableError('小説のURLが違います.')

        self.text_page = []
        self.log_page = []
        self.chapter = ''
        self.page_list = []

        top = fetch_html(self.url)
        if not top:
            raise NovelNotAvailableError(
                self.url + ' からページ情報を取得できませんでした.')

        self.nvstat = self.get_novel_status(top)
        self.parse_chapter(top)

        if not self.page_list:
            raise NovelNotAvailableError(
                self.url + ' から小説情報を取得できませんでした.')

        if len(self.page_list) < self.start_n:
            raise NovelNotAvailableError(
                self.url + ' から小説情報を取得できませんでした.')

        if self._on_ready:
            self._on_ready(len(self.page_list), self.filename)

        self._load_each_page()

        # 保存（UTF-8 BOM 付き / 原作同様）
        os.makedirs(os.path.dirname(self.filename) or '.', exist_ok=True)
        with open(self.filename, 'w', encoding='utf-8-sig', newline='') as f:
            f.write(CRLF.join(self.text_page) + CRLF)
        log_name = os.path.splitext(self.filename)[0] + '.log'
        with open(log_name, 'w', encoding='utf-8-sig', newline='') as f:
            f.write(CRLF.join(self.log_page) + CRLF)

        self._p(self.filename + ' に保存しました.')
        return self.filename

    def _load_each_page(self):
        cnt = len(self.page_list)
        start = self.start_n - 1 if self.start_n > 0 else 0
        n = 1
        sc = cnt - start
        self.chapter = ''

        i = start
        while i < cnt:
            line = fetch_html(self.page_list[i])
            if line:
                self.parse_page(line)
                done = n
                pct = (n * 100) // sc if sc else 100
                self._p('各話を取得中 [%3d/%3d (%d%%)]' % (i + 1, cnt, pct))
                if self._progress:
                    self._progress(done, sc)
                time.sleep(0.4)   # サーバー負荷軽減（原作 400ms）
            i += 1
            n += 1


# ----------------------------------------------------------------------------
# 簡易セルフテスト（python kakuyomu_core.py <URL>）
# ----------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: python kakuyomu_core.py <https://kakuyomu.jp/works/...> '
              '[filename]')
        return 1
    url = argv[0]
    out_dir = argv[1] if len(argv) > 1 else os.getcwd()
    dl = Downloader(url, out_dir=out_dir, log=print)
    try:
        dl.run()
    except (NovelNotAvailableError, ValueError) as e:
        print(str(e))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
