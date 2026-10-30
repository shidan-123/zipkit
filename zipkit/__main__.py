"""支持 `python -m zipkit ...` 直接运行。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
