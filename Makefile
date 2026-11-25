.PHONY: help test test-fast demo web clean lint app package release

help:
	@echo "make test     - 跑全部测试"
	@echo "make demo     - 生成演示样例到 demo/"
	@echo "make web      - 启动网页版（不自动开浏览器）"
	@echo "make gui      - 打开桌面窗口版（大文件）"
	@echo "make icon     - 重新生成 macOS 应用图标"
	@echo "make macapp   - 打包成独立 .app（内含 Python，无需安装）"
	@echo "make app      - 重建 ZipKit.app（代码 + 版本号）"
	@echo "make package  - 把 App 打成 Release 用的 zip + sha256"
	@echo "make release  - 测试 → 重建 App → 打包（发版一条龙）"
	@echo "make clean    - 清理缓存与生成物"

test:
	python3 -m pytest -q

test-fast:
	python3 -m pytest -q -x --ignore=tests/test_cli_web.py

demo:
	python3 scripts/make_demo.py demo

web:
	python3 -m zipkit web --no-browser

gui:
	python3 -m zipkit gui

icon:
	python3 scripts/make_icon.py

app:
	python3 scripts/build_app.py

package:
	python3 scripts/package_release.py

release: app test package

lint:
	python3 -m compileall -q zipkit && echo "✅ 语法检查通过"

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache demo/*.zip
	@echo "✅ 已清理"

macapp:
	PYINSTALLER_CONFIG_DIR="$$PWD/build/.pyinstaller-cache" \
	../.venv313/bin/python -m PyInstaller --name ZipKit --windowed \
	  --icon "ZipKit.app/Contents/Resources/AppIcon.icns" \
	  --osx-bundle-identifier com.shidan123.zipkit \
	  --add-data "zipkit/web/static:zipkit/web/static" --paths "." \
	  --noconfirm --clean --distpath dist --workpath build scripts/macos_entry.py
	ditto -c -k --sequesterRsrc --keepParent dist/ZipKit.app "dist/ZipKit-macOS-AppleSilicon.zip"
	@echo "✅ 产物：dist/ZipKit-macOS-AppleSilicon.zip"
