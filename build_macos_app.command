#!/bin/bash
set -euo pipefail

APP_NAME="台股資產與股息管理"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

printf '\n========================================\n'
printf '  %s｜macOS App 建立工具\n' "$APP_NAME"
printf '========================================\n\n'

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "錯誤：macOS App 必須在 Mac 上建立。"
  read -r -p "按 Enter 關閉……"
  exit 1
fi

if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x "/opt/anaconda3/envs/shopee-auto/bin/python" ]]; then
  PYTHON="/opt/anaconda3/envs/shopee-auto/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "錯誤：找不到 Python 3。"
  read -r -p "按 Enter 關閉……"
  exit 1
fi

echo "使用 Python：$PYTHON"
"$PYTHON" -c "import sys; print('Python 版本：', sys.version)"

printf '\n[1/5] 安裝／更新執行與打包套件……\n'
"$PYTHON" -m pip install --upgrade -r requirements.txt -r requirements-build.txt

printf '\n[2/5] 檢查程式語法……\n'
"$PYTHON" -m compileall -q main.py app

printf '\n[3/5] 清除舊的打包結果……\n'
rm -rf build dist

printf '\n[4/5] 建立 macOS App（第一次可能需要數分鐘）……\n'
"$PYTHON" -m PyInstaller --clean --noconfirm macos_app.spec

APP_PATH="$SCRIPT_DIR/dist/$APP_NAME.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "錯誤：找不到建立完成的 $APP_PATH"
  read -r -p "按 Enter 關閉……"
  exit 1
fi

# 使用本機 ad-hoc 簽章，適合自己電腦使用；公開發佈仍需 Apple Developer 簽章與公證。
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 || true
fi

printf '\n[5/5] 安裝至使用者的 Applications 資料夾……\n'
INSTALL_DIR="$HOME/Applications"
INSTALLED_APP="$INSTALL_DIR/$APP_NAME.app"
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALLED_APP"
ditto "$APP_PATH" "$INSTALLED_APP"

# 第一次建立 App 時，自動沿用目前專案內的資料；已存在的使用者資料不覆蓋。
APP_SUPPORT="$HOME/Library/Application Support/$APP_NAME"
mkdir -p "$APP_SUPPORT"
for filename in portfolio_yfinance.db app_settings.json name_overrides.csv; do
  if [[ -f "$SCRIPT_DIR/data/$filename" && ! -f "$APP_SUPPORT/$filename" ]]; then
    cp "$SCRIPT_DIR/data/$filename" "$APP_SUPPORT/$filename"
    echo "已沿用資料：$filename"
  fi
done

# 本機自行建立的 App 不需要保留下載檔案的 quarantine 標記。
xattr -dr com.apple.quarantine "$INSTALLED_APP" 2>/dev/null || true

printf '\n建立完成！\n'
printf 'App：%s\n' "$INSTALLED_APP"
printf '資料：%s\n' "$APP_SUPPORT"
printf 'LOG：%s\n\n' "$HOME/Library/Logs/$APP_NAME/app.log"

open "$INSTALLED_APP"

read -r -p "App 已啟動。按 Enter 關閉這個建立視窗……"
