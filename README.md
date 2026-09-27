# kakuyomu-downloader-mac

カクヨム（[kakuyomu.jp](https://kakuyomu.jp/)）の小説をダウンロードして、
**縦書きの EPUB3** まで作れる macOS ツール。

Windows 専用の [minouejapan/kakuyomu-downloader](https://github.com/minouejapan/kakuyomu-downloader)
（`kakuyomudl`、Object Pascal / Delphi・Lazarus）を **Python で macOS 向けに移植**したものです。

- **ダウンロード**：作品 URL → 青空文庫形式 `.txt`（UTF-8 BOM）+ `.log`　※原作 4.97 と出力完全一致
- **EPUB 変換**：`.txt` → **縦書き・右綴じ EPUB3**（Apple Books でそのまま読める）
- **依存ゼロ**：Python 標準ライブラリのみ（`tkinter` / `urllib` / `zipfile`）。`pip install` 不要

> ⚠️ カクヨムネクスト等の**有料作品はダウンロードできません**（原作と同様）。

---

## 動作環境

| 項目 | 要件 |
|---|---|
| OS | macOS（Apple Silicon / Intel） |
| Python | 3.9 以上（`tkinter` 同梱のもの） |

macOS 標準の `/usr/bin/python3` は Tkinter を含まないことがあるため、
[python.org](https://www.python.org/downloads/) か Homebrew の Python を推奨します。

```bash
brew install python-tk     # Homebrew の場合
```

---

## 使い方

### 1. ダウンロード + EPUB 変換（GUI）

`启动 Kakuyomu 下载器.command` をダブルクリック、または:

```bash
python3 kakuyomu_gui.py
```

1. 作品 URL を貼り付け（例: `https://kakuyomu.jp/works/16816700426129496803`）
2. 保存先を選ぶ（既定 `~/Downloads`）
3. 「ダウンロード開始」→ 進捗バーとログが表示される
4. 下の「EPUB 変換（縦書き）」で表紙画像を選んで「EPUB に変換」
   （「ダウンロード完了後に自動変換する」にチェックすれば一発で完成）

> 初回起動時に「開発元を確認できないため開けません」と出たら、
> 右クリック →「開く」で許可してください。

### 2. コマンドライン（ダウンロード）

```bash
python3 kakuyomu_cli.py https://kakuyomu.jp/works/XXXXXXXX
python3 kakuyomu_cli.py https://kakuyomu.jp/works/XXXXXXXX 保存したいファイル名
python3 kakuyomu_cli.py -s100 https://kakuyomu.jp/works/XXXXXXXX   # 100 話目から
```

引数は原作 `kakuyomudl` と同じ：`[-s開始ページ番号] URL [保存するファイル名]`

### 3. コマンドライン（EPUB 変換）

```bash
python3 txt2epub.py 作品.txt                        # 同名 .epub を出力
python3 txt2epub.py 作品.txt --cover 表紙.jpg        # 表紙付き
python3 txt2epub.py 作品.txt -o out.epub --title "書名" --author "作者"
python3 txt2epub.py *.txt --cover cover.jpg         # まとめて変換
```

---

## 縦書き EPUB の仕様

| 項目 | 処理 |
|---|---|
| 排版 | `writing-mode: vertical-rl`（縦書き）+ `page-progression-direction="rtl"`（右綴じ） |
| 分章 | 「話」(`［＃中見出し］`) ごとに 1 XHTML。「章」(`［＃大見出し］`) は目次の第 1 レベルにグループ化 |
| 青空文庫注記 | ルビ（`｜漢字《かんじ》` / `漢字《かんじ》`）、丸傍点、罫囲み、改ページ、字下げ、挿絵リンク |
| 目次 | EPUB3 `nav.xhtml` + EPUB2 `toc.ncx` の両方を生成（古いリーダー互換） |
| フォント | 明朝体優先（Hiragino Mincho ProN → Yu Mincho → Noto Serif JP） |
| 表紙 | 任意の画像を `properties="cover-image"` として埋め込み |
| 挿絵 | `［＃リンクの図（URL）入る］` を自動ダウンロードして埋め込み（失敗時はリンク表示） |

書名の `【連載中】` などの接頭辞は既定で除去します（`--keep-status` で保持）。

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `kakuyomu_core.py` | 中核：取得 + HTML 解析 + 青空文庫変換 + 保存（原作 Pascal ロジックを 1:1 移植） |
| `kakuyomu_gui.py` | Tkinter GUI（ダウンロード + EPUB 変換） |
| `kakuyomu_cli.py` | コマンドライン入口（原作互換の引数） |
| `txt2epub.py` | 青空文庫 txt → 縦書き EPUB3 変換器 |
| `启动 Kakuyomu 下载器.command` | macOS 用ダブルクリック起動ランチャー |

---

## 原作（Windows 版）との違い

| 項目 | 原作 | 本移植版 |
|---|---|---|
| 対応 OS | Windows 10/11 | macOS |
| UI | コマンドプロンプト | Tkinter GUI + CLI |
| 通信 | WinINet | `urllib`（原作 `unihtml.pas` の非 Windows 分岐を踏襲） |
| Naro2mobi 進捗通知 | `WM_COPYDATA` ハンドル | **削除**（macOS に該当機構なし） |
| 出力形式 | 青空文庫 `.txt` + `.log` | **完全一致**（BOM・CRLF・タグすべて） |
| 話ごとの間隔 | 400ms | 400ms（サーバー負荷軽減のため維持） |
| バージョンリソース / アイコン | `verinfo.res` / `.ico` | 対象外 |
| EPUB 出力 | なし（naro2mobi 等を併用） | **内蔵**（縦書き EPUB3） |

---

## 原作に合わせた挙動

- タイトルに「完結」が含まれない場合、先頭に `【連載中】`／`【完結】`／`【短編】` を付加
- 保存ファイル名はタイトル先頭 **26 文字**、使用不可文字は `-` に置換
- 完結かつ 1 話のみの作品は `【短編】` と判定し、話タイトルに作品名を使用
- 章／話、ルビ、傍点、挿絵リンクを青空文庫タグへ変換

---

## 免責事項（原作より継承）

1. 本ツールで Web 小説サイトからダウンロードしたテキストの第三者への販売・不特定多数への配信
2. ダウンロードした作品を著作者の了解なく加工しての再公開
3. その他、著作者の権利を侵害する行為

**これらを禁止します。** ダウンロードした作品は**個人で楽しむ範囲**に留めてください。

---

## クレジット

- 原作: [minouejapan/kakuyomu-downloader](https://github.com/minouejapan/kakuyomu-downloader)（MIT License）
  — 抽出ロジック・青空文庫変換仕様・識別タグはすべて原作に基づいています。
- 移植・EPUB 変換: [michiru233](https://github.com/michiru233)

## License

[MIT](LICENSE)
