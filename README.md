# ZipKit

> 一个"说人话"的压缩 / 解压小工具。
> 会上网就能用：**一个网页界面 + 一条命令**，Windows / macOS / Linux 都能跑，不需要装显卡驱动那种依赖。

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Tests](https://img.shields.io/badge/tests-55%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 先说实话（比功能表更重要）

### ① "压缩"和"解压"不是对称的，这决定了工具能做成什么样

| 你想要的 | 实际能做到 | 为什么 |
|---|---|---|
| 压缩 `.txt .log .csv .json` | ✅ 效果很好，常见 70%~95% | 文本重复度高，ZIP 天生擅长 |
| 压缩 `.bmp .wav .tiff` | ⚠️ 能压，但通常只省 5%~30% | 这三种本身就是"高密度"二进制，ZIP 对它们没辙 |
| 解压 `.zip .7z .gz` | ✅ 标准操作 | 就是压缩包的逆过程 |
| 解压 `.docx .xlsx .pptx` | ⚠️ 技术上可行，但**对你没用** | 它们是 ZIP 套壳，解开后是 XML；而且**改完再压回去，文档大概率打不开** |

所以本工具对 Office 文档做的是**"读文字"**，不是"解压"——那才是你真正想要的东西。

### ② 微信小程序这一版**没有**，而且不能简单加进去

微信小程序有三条硬限制：主包 ≤ 2MB、没有本地进程、不能随便读写磁盘。7z 解压这类操作在小程序里要靠 WASM 重编译，体积和内存都顶不住。

**正确做法**是"小程序调云端 API"，但这需要你自己的服务器 + 域名 + 备案，是一笔持续成本。完整分析见 [docs/小程序方案.md](docs/小程序方案.md)。

### ③ 本项目对 Office 文件的压缩收益很低是正常的

`.docx/.xlsx/.pptx` 内部已经是 DEFLATE 压缩过的 XML，再压一遍只能挤出 6%~20%。这不是 bug。

---

## 支持矩阵

| 格式 | 压缩 | 解压 | 提取文字 | 实测收益（本项目样例） | 备注 |
|---|:---:|:---:|:---:|---|---|
| `.txt` | ✅ | — | — | **90.8%** | 纯文本 |
| `.log` | ✅ | — | — | **96.2%** | 日志重复度极高 |
| `.csv` | ✅ | — | — | **84.9%** | 表格文本 |
| `.json` | ✅ | — | — | **92.9%** | 结构化文本 |
| `.bmp` | ✅ | — | — | 7.2% | 位图；换 PNG 才有效 |
| `.wav` | ✅ | — | — | 98.1%¹ | PCM 音频；真实录音约 10%~40% |
| `.tiff` | ✅ | — | — | 5.8% | 常已 LZW 压缩 |
| `.zip` | — | ✅ | — | — | 支持中文名、目录结构 |
| `.7z` | — | ✅ | — | — | 需 `pip install py7zr` |
| `.gz` | — | ✅ | — | — | 单文件流 |
| `.tar.gz` / `.tgz` | — | ✅ | — | — | 多文件归档 |
| `.docx` | — | ✅ | ✅ | — | 解包看结构 / 直接读正文 |
| `.xlsx` | — | ✅ | ✅ | — | 按工作表导出 |
| `.pptx` | — | ✅ | ✅ | — | 按页导出 |

¹ 样例是合成的纯正弦波，重复度极高所以能压 98%；真实录音不会这么夸张。

---

## 快速开始

### 前置：只要有 Python 3.9+ 就行

| 系统 | 检查命令 | 没有的话 |
|---|---|---|
| Windows | `python --version` | 到 [python.org](https://www.python.org/downloads/) 下载，安装时**勾选 Add Python to PATH** |
| macOS | `python3 --version` | `brew install python`（或从 python.org 下载） |
| Linux | `python3 --version` | `sudo apt install python3 python3-pip`（Debian/Ubuntu） |

### 方式一：网页界面（推荐新手，零学习成本）

```bash
git clone https://github.com/shidan-123/zipkit.git
cd zipkit
python3 -m zipkit web
```

终端会打印一个带 token 的地址，浏览器自动打开。界面上只有三个标签页：

- **压缩** —— 拖文件进去 → 选级别 → 下载 zip
- **解压** —— 拖 zip/7z/gz/docx 进去 → 下载解压结果
- **读文档** —— 拖 docx/xlsx/pptx → 直接看到纯文字，可一键复制

关掉终端窗口，服务就停了，不会有后台进程残留。

### 方式二：命令行（可脚本化，适合批量/大文件）

```bash
# 压缩：把整个 demo 目录打包
python3 -m zipkit pack demo -o demo.zip

# 解压
python3 -m zipkit unpack demo.zip -d 输出目录

# 只看里面有什么，不解压
python3 -m zipkit list demo.zip

# 把 Word 里的文字抽出来
python3 -m zipkit text 报告.docx

# 压缩前先"体检"，看值不值得压
python3 -m zipkit check *.wav *.bmp
```

### 方式三：装成系统命令（可选）

```bash
pip install -e .
zipkit web          # 之后不用再写 python -m
```

---

## 真实试用结果

我用 `scripts/make_demo.py` 生成了 10 个真文件（不是空壳），跑了一遍完整往返：

```text
📦 已生成：demo.zip
   10 个文件  879.1 KB → 339.6 KB  节省 61.5%  （耗时 0.01s）

  文件                     原始      压缩后      节省
  ----------------------------------------------------
  app-2026-10-30.log    443.0 KB   16.9 KB   96.2%
  config.json            10.2 KB    741 B    92.9%
  会议纪要.txt             6.8 KB    645 B    90.8%
  成绩表.csv              11.7 KB    1.8 KB   84.9%
  扫描件.tiff            88.0 KB   82.9 KB    5.8%
  提示音.wav             62.5 KB    1.2 KB   98.1%
  演示幻灯片.pptx         28.6 KB   22.5 KB   21.3%
  演示文档.docx          35.9 KB   33.5 KB    6.7%
  演示表格.xlsx           4.9 KB    4.3 KB   11.3%
  示意图.bmp            187.6 KB  174.0 KB    7.2%

  ⚠️ 扫描件.tiff、示意图.bmp 几乎压不动（节省不足 15%）…
```

解压回来后，10 个文件的 SHA-256 **逐字节一致**（这也是测试用例 `test_pack_then_extract_roundtrip` 断言的内容）。

---

## 安全设计

一个能被别人下载使用的解压工具，必须假设"压缩包是恶意的"。

| 威胁 | ZipKit 的应对 |
|---|---|
| **路径穿越**（`../../.ssh/authorized_keys`） | 成员名在黑名单（绝对路径 / 盘符 / `..` / 控制字符 / Windows 保留名）直接拒绝；拼路径后再用 `commonpath` 二次校验 |
| **压缩炸弹**（1 KB 解出 10 GB） | 四道闸：成员数 ≤ 20000、总量 ≤ 2 GB、单文件 ≤ 1 GB、压缩比 > 200:1 拒绝 |
| **半成品文件** | 先全校验成员名，再统一落盘；写入失败自动删除半截文件 |
| **静默覆盖** | 默认遇到同名文件自动改名 `a (1).txt`；必须显式 `--force` 才覆盖 |
| **网页被跨站调用** | 只监听 `127.0.0.1`；每次启动生成随机 token；请求必须带 `X-ZipKit-Token` |
| **符号链接逃逸** | tar 里的 symlink / 硬链接 / 设备文件一律跳过并提示 |

以上每一条都有对应测试（`tests/test_safety.py`）。

---

## 项目结构

```
zipkit/
├── zipkit/
│   ├── core/                # 与界面无关的业务逻辑，可单独调用
│   │   ├── compress.py      # 压缩 + 收益预估
│   │   ├── extract.py       # 解压（zip/7z/gz/tar.gz/ooxml）
│   │   ├── office.py        # docx/xlsx/pptx 正文提取
│   │   ├── safety.py        # 路径穿越 / 炸弹 / 覆盖防护
│   │   └── formats.py       # 格式知识库（哪些能压、压得动吗）
│   ├── web/                 # 本地网页界面（标准库 http.server）
│   ├── cli.py               # 命令行入口
│   └── errors.py            # "发生了什么 + 该怎么办"的统一错误
├── tests/                   # 55 个测试，含真实文件往返与攻击用例
├── scripts/make_demo.py     # 一键生成演示样例
└── docs/                    # 使用 / 排错 / 维护 / 技术决策 / 小程序方案
```

---

## 文档

| 文档 | 什么时候看 |
|---|---|
| [使用手册](docs/使用手册.md) | 第一次用，想知道每个按钮/参数干什么 |
| [故障排查](docs/故障排查.md) | 报错了、文件被覆盖了、解压出来是乱的 |
| [维护指南](docs/维护指南.md) | 你想长期维护这个仓库（发版、升级依赖、处理 Issue） |
| [技术决策](docs/技术决策.md) | 想知道为什么这么设计，以及哪些需求被我改掉了 |
| [小程序方案](docs/小程序方案.md) | 想做微信小程序版本，先看这里需要付出什么 |

---

## 路线图

- [x] **v1.0** —— 压缩 8 类文件、解压 5 类归档、Office 读文、网页界面、安全防护、三平台
- [ ] **v1.1** —— 拖拽整目录、压缩包内预览、`--password` 支持加密 zip
- [ ] **v1.2** —— Windows/macOS 单文件打包（PyInstaller），双击即用
- [ ] **v2.0** —— 微信小程序（云端 API + 小程序前端，见 [小程序方案](docs/小程序方案.md)）

## 许可

[MIT](LICENSE) —— 随便用、随便改，出问题别找我（笑）。
