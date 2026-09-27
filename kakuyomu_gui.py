#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kakuyomu_gui.py — カクヨム小説ダウンローダー + EPUB 変換（macOS GUI）

原作 kakuyomudl（Windows 専用 CLI）を Python で macOS 向けに移植した GUI。

  1) ダウンロード: 作品 URL → 青空文庫形式 .txt（kakuyomu_core.py）
  2) EPUB 変換   : .txt → 縦書き EPUB3（txt2epub.py）

依存: Python 標準ライブラリのみ（tkinter / urllib）
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kakuyomu_core as core     # noqa: E402
import txt2epub                  # noqa: E402

DEFAULT_DIR = os.path.join(os.path.expanduser('~'), 'Downloads')


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.last_dir = DEFAULT_DIR
        self.last_file = ''

        root.title('Kakuyomu 小説ダウンローダー & EPUB 変換')
        root.minsize(700, 720)

        self._build_ui()
        root.after(100, self._drain)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {'padx': 8, 'pady': 5}
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill='both', expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(7, weight=1)

        # ---------------- ダウンロード ----------------
        ttk.Label(frm, text='作品URL').grid(row=0, column=0, sticky='w', **pad)
        self.url_var = tk.StringVar()
        e = ttk.Entry(frm, textvariable=self.url_var)
        e.grid(row=0, column=1, columnspan=2, sticky='ew', **pad)
        e.focus_set()
        e.bind('<Return>', lambda _e: self._start())

        ttk.Label(frm, text='保存先').grid(row=1, column=0, sticky='w', **pad)
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        ttk.Entry(frm, textvariable=self.dir_var).grid(
            row=1, column=1, sticky='ew', **pad)
        ttk.Button(frm, text='参照…', command=self._pick_dir).grid(
            row=1, column=2, sticky='ew', **pad)

        ttk.Label(frm, text='ファイル名').grid(row=2, column=0, sticky='w', **pad)
        self.fname_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.fname_var).grid(
            row=2, column=1, columnspan=2, sticky='ew', **pad)

        ttk.Label(frm, text='開始話').grid(row=3, column=0, sticky='w', **pad)
        self.start_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.start_var, width=10).grid(
            row=3, column=1, sticky='w', **pad)
        ttk.Label(frm, foreground='#888',
                  text='※ 空欄でOK。ファイル名・開始話は省略可（原作 -s 相当）'
                  ).grid(row=3, column=2, sticky='w', **pad)

        self.run_btn = ttk.Button(frm, text='ダウンロード開始', command=self._start)
        self.run_btn.grid(row=4, column=0, sticky='ew', **pad)

        self.progress = ttk.Progressbar(frm, mode='determinate', maximum=100)
        self.progress.grid(row=4, column=1, sticky='ew', **pad)

        self.status_var = tk.StringVar(value='待機中')
        ttk.Label(frm, textvariable=self.status_var).grid(
            row=4, column=2, sticky='w', **pad)

        # ---------------- EPUB 変換 ----------------
        epub = ttk.LabelFrame(frm, text='EPUB 変換（縦書き）', padding=8)
        epub.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(10, 4))
        epub.columnconfigure(1, weight=1)

        ttk.Label(epub, text='テキスト(.txt)').grid(row=0, column=0, sticky='w', **pad)
        self.txt_var = tk.StringVar()
        ttk.Entry(epub, textvariable=self.txt_var).grid(
            row=0, column=1, sticky='ew', **pad)
        ttk.Button(epub, text='参照…',
                   command=lambda: self._pick_file(self.txt_var,
                                                   [('テキスト', '*.txt')])
                   ).grid(row=0, column=2, sticky='ew', **pad)

        ttk.Label(epub, text='表紙画像').grid(row=1, column=0, sticky='w', **pad)
        self.cover_var = tk.StringVar()
        ttk.Entry(epub, textvariable=self.cover_var).grid(
            row=1, column=1, sticky='ew', **pad)
        ttk.Button(epub, text='参照…',
                   command=lambda: self._pick_file(
                       self.cover_var,
                       [('画像', '*.jpg *.jpeg *.png *.gif *.webp')])
                   ).grid(row=1, column=2, sticky='ew', **pad)

        self.conv_btn = ttk.Button(epub, text='EPUB に変換', command=self._start_convert)
        self.conv_btn.grid(row=2, column=0, sticky='ew', **pad)

        self.conv_status = tk.StringVar(value='')
        ttk.Label(epub, textvariable=self.conv_status, foreground='#888').grid(
            row=2, column=1, columnspan=2, sticky='w', **pad)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(epub, text='ダウンロード完了後に自動変換する',
                        variable=self.auto_var).grid(
            row=3, column=0, columnspan=3, sticky='w', padx=8)

        # ---------------- ログ ----------------
        ttk.Label(frm, text='ログ').grid(row=6, column=0, sticky='w', **pad)
        self.log_box = ScrolledText(frm, height=14, wrap='word',
                                    state='disabled', font=('Menlo', 11))
        self.log_box.grid(row=7, column=0, columnspan=3, sticky='nsew', **pad)

        bottom = ttk.Frame(frm)
        bottom.grid(row=8, column=0, columnspan=3, sticky='ew', pady=(2, 0))
        self.open_btn = ttk.Button(bottom, text='出力フォルダを開く',
                                   command=self._open_dir, state='disabled')
        self.open_btn.pack(side='right')
        ttk.Button(bottom, text='ログを消す', command=self._clear_log).pack(
            side='right', padx=6)

    # ------------------------------------------------------------- helpers
    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or DEFAULT_DIR)
        if d:
            self.dir_var.set(d)

    def _pick_file(self, var, types):
        p = filedialog.askopenfilename(filetypes=types)
        if p:
            var.set(p)

    def _clear_log(self):
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.configure(state='disabled')

    def _log(self, msg: str):
        self.log_box.configure(state='normal')
        self.log_box.insert('end', msg + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def _open_dir(self):
        if self.last_file and os.path.exists(self.last_file):
            subprocess.Popen(['open', '-R', self.last_file])
            return
        if os.path.isdir(self.last_dir):
            subprocess.Popen(['open', self.last_dir])

    # --------------------------------------------------------- ダウンロード
    def _start(self):
        if self.busy:
            return
        url = self.url_var.get().strip()
        if 'kakuyomu.jp/works/' not in url:
            messagebox.showwarning(
                'URLエラー',
                'カクヨム作品のトップページURLを入力してください。\n'
                '例: https://kakuyomu.jp/works/xxxxxxxx')
            return
        out_dir = self.dir_var.get().strip() or DEFAULT_DIR
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror('保存先エラー', f'保存先を作成できません:\n{e}')
                return

        self.busy = True
        self.run_btn.configure(state='disabled')
        self.open_btn.configure(state='disabled')
        self._clear_log()
        self.progress.configure(mode='indeterminate', value=0)
        self.progress.start(15)
        self.status_var.set('情報取得中…')

        threading.Thread(
            target=self._worker,
            args=(url, out_dir, self.fname_var.get().strip(),
                  self.start_var.get().strip()),
            daemon=True,
        ).start()

    def _worker(self, url, out_dir, fname, start):
        try:
            dl = core.Downloader(
                url, out_dir=out_dir, filename=fname, start_page=start,
                log=lambda m: self.q.put(('log', m)),
                progress=lambda d, t: self.q.put(('prog', d, t)),
                on_ready=lambda total, path: self.q.put(('ready', total, path)),
            )
            path = dl.run()
            self.q.put(('done', path))
        except Exception as e:                      # noqa: BLE001
            self.q.put(('error', str(e)))

    # ----------------------------------------------------------- EPUB 変換
    def _start_convert(self, txt_path=None):
        if self.busy:
            return
        txt = (txt_path or self.txt_var.get()).strip()
        if not txt or not os.path.isfile(txt):
            messagebox.showwarning('ファイルエラー',
                                   '変換する .txt ファイルを選択してください。')
            return
        self.txt_var.set(txt)
        cover = self.cover_var.get().strip() or None
        self.busy = True
        self.conv_btn.configure(state='normal', text='変換中…')
        self.conv_btn.configure(state='disabled')
        self.conv_status.set('変換中…')
        self.status_var.set('EPUB 変換中…')
        threading.Thread(target=self._convert_worker,
                         args=(txt, cover), daemon=True).start()

    def _convert_worker(self, txt, cover):
        try:
            out = os.path.splitext(txt)[0] + '.epub'
            txt2epub.convert_one(
                txt, out_path=out, cover=cover,
                log=lambda m: self.q.put(('log', m)))
            self.q.put(('conv_done', out))
        except Exception as e:                      # noqa: BLE001
            self.q.put(('conv_error', str(e)))

    # --------------------------------------------------- queue → UI 反映
    def _drain(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == 'log':
                    self._log(msg[1])
                elif kind == 'prog':
                    _, done, total = msg
                    self.status_var.set(f'ダウンロード中 {done}/{total}')
                elif kind == 'ready':
                    _, total, path = msg
                    self.last_dir = os.path.dirname(path) or DEFAULT_DIR
                    self.progress.stop()
                    self.progress.configure(mode='determinate',
                                            maximum=max(total, 1), value=0)
                    self.status_var.set(f'全 {total} 話を取得します')
                elif kind == 'done':
                    self._finish_ok(msg[1])
                elif kind == 'error':
                    self._finish_err(msg[1])
                elif kind == 'conv_done':
                    self._conv_ok(msg[1])
                elif kind == 'conv_error':
                    self._conv_err(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _finish_ok(self, path):
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode='determinate', value=self.progress['maximum'])
        self.run_btn.configure(state='normal')
        self.open_btn.configure(state='normal')
        self.last_file = path
        self.status_var.set('完了')
        self._log('\n完了: ' + path)

        if self.auto_var.get():
            self._log('→ EPUB 変換を開始します…')
            self._start_convert(path)
            return
        if messagebox.askyesno('完了', f'保存しました:\n{path}\n\n'
                                       '出力フォルダを開きますか？'):
            self._open_dir()

    def _finish_err(self, err):
        self.busy = False
        self.progress.stop()
        self.progress.configure(mode='determinate', value=0)
        self.run_btn.configure(state='normal')
        self.status_var.set('エラー')
        self._log('\nエラー: ' + err)
        messagebox.showerror('エラー', err)

    def _conv_ok(self, path):
        self.busy = False
        self.conv_btn.configure(state='normal', text='EPUB に変換')
        self.conv_status.set('完了')
        self.status_var.set('完了')
        self.last_file = path
        self.open_btn.configure(state='normal')
        self._log('\nEPUB 完了: ' + path)
        if messagebox.askyesno(
                'EPUB 完了',
                f'縦書き EPUB を作成しました:\n{path}\n\n'
                'Apple Books で開きますか？'):
            subprocess.Popen(['open', '-a', 'Books', path])

    def _conv_err(self, err):
        self.busy = False
        self.conv_btn.configure(state='normal', text='EPUB に変換')
        self.conv_status.set('エラー')
        self.status_var.set('エラー')
        self._log('\nEPUB 変換エラー: ' + err)
        messagebox.showerror('EPUB 変換エラー', err)


def main():
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.2)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
