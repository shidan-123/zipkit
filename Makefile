.PHONY: help test test-fast demo web clean lint

help:
	@echo "make test     - 跑全部测试"
	@echo "make demo     - 生成演示样例到 demo/"
	@echo "make web      - 启动网页版（不自动开浏览器）"
	@echo "make gui      - 打开桌面窗口版（大文件）"
	@echo "make icon     - 重新生成 macOS 应用图标"
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

lint:
	python3 -m compileall -q zipkit && echo "✅ 语法检查通过"

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache demo/*.zip
	@echo "✅ 已清理"
