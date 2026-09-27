#!/bin/bash
# Kakuyomu 小説ダウンローダー & EPUB 変換（GUI）をダブルクリックで起動します。
# Tkinter が使える Python 3 を自動で探します。

cd "$(dirname "$0")" || exit 1

CANDIDATES=(
    "$(command -v python3 2>/dev/null)"
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    /usr/bin/python3
)

PY=""
for C in "${CANDIDATES[@]}"; do
    if [ -n "$C" ] && [ -x "$C" ] && "$C" -c "import tkinter" >/dev/null 2>&1; then
        PY="$C"
        break
    fi
done

if [ -z "$PY" ]; then
    MSG="Tkinter が使える Python 3 が見つかりません。https://www.python.org/downloads/ からインストールしてください。"
    if ! osascript -e "display alert \"起動できません\" message \"$MSG\"" 2>/dev/null; then
        echo "エラー: $MSG"
        read -r -p "Enter キーで閉じます..."
    fi
    exit 1
fi

exec "$PY" kakuyomu_gui.py
