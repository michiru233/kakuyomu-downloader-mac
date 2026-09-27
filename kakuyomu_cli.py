#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kakuyomu_cli.py — カクヨム小説ダウンローダー macOS 版（コマンドライン）

原作 kakuyomudl と同じ引数仕様:
    kakuyomu [-s DL開始ページ番号] 小説トップページのURL [保存するファイル名]

出力は原作 4.97 と同一（青空文庫形式 .txt + .log, UTF-8 BOM）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kakuyomu_core as core  # noqa: E402

USAGE = """kakuyomu (macOS/Python port of kakuyomudl)

  使用方法
  kakuyomu [-sDL開始ページ番号] 小説トップページのURL [保存するファイル名]

  例:
  kakuyomu https://kakuyomu.jp/works/1234567890
  kakuyomu https://kakuyomu.jp/works/1234567890 my_novel
  kakuyomu -s100 https://kakuyomu.jp/works/1234567890
"""


def parse_args(argv):
    url = ''
    filename = ''
    start_page = ''
    i = 0
    while i < len(argv):
        op = argv[i]
        if op.startswith('-s'):
            start_page = op[2:]
            if not start_page and i + 1 < len(argv):
                i += 1
                start_page = argv[i]
        elif op.startswith('http'):
            url = op
        else:
            filename = op
        i += 1
    return url, filename, start_page


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(USAGE)
        return 0 if argv else 1

    url, filename, start_page = parse_args(argv)
    if 'https://kakuyomu.jp/works/' not in url:
        print('小説のURLが違います.')
        return 1

    dl = core.Downloader(
        url, out_dir=os.getcwd(), filename=filename,
        start_page=start_page, log=print,
    )
    try:
        dl.run()
    except (core.NovelNotAvailableError, ValueError) as e:
        print(str(e))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
