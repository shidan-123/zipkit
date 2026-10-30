#!/bin/bash
# ============================================================
#  双击我 → 启动 ZipKit 大文件版（原生窗口，无 64MB 限制）
#  如果 macOS 提示"无法打开"，右键它 → 打开 → 再点"打开"
# ============================================================
cd "$(dirname "$0")" || exit 1

find_python() {
  for candidate in \
    /usr/local/bin/python3 \
    /opt/homebrew/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    /usr/bin/python3 \
    python3
  do
    if command -v "$candidate" >/dev/null 2>&1; then
      # 必须 Tk >= 8.6，8.5 在 macOS 26 上会直接报错
      if "$candidate" -c "import tkinter,sys; sys.exit(0 if tkinter.TkVersion>=8.6 else 1)" >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PY=$(find_python)
if [ -z "$PY" ]; then
  echo "────────────────────────────────────────────"
  echo " 没找到带图形库（Tk 8.6）的 Python"
  echo
  echo " 办法一：装一个官方 Python 3.13"
  echo "        https://www.python.org/downloads/"
  echo " 办法二：先用命令行，功能完全一样"
  echo "        python3 -m zipkit unpack 你的文件.zip"
  echo "────────────────────────────────────────────"
  read -r -p "按回车键关闭…" _
  exit 1
fi

# 优先用 App 内置的代码副本（和 .app 保持同一份逻辑）
BUNDLED="$(pwd)/ZipKit.app/Contents/Resources/lib"
if [ -d "$BUNDLED/zipkit" ]; then
  export PYTHONPATH="$BUNDLED${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$(pwd)${PYTHONPATH:+:$PYTHONPATH}"
fi
echo "使用 Python：$PY"
exec "$PY" -m zipkit gui
