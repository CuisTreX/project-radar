# 下一个 Agent 接手提示词 — DEV-2026-001-项目雷达

## 背景

F 盘多 Agent 工作区（Zcode / CodeX / WorkBuddy / DSH）的项目统一查询工具已完成并交付：
桌面快捷方式「项目雷达」→ `launcher.vbs` → `project_radar.py`（pythonw 常驻 127.0.0.1:8618）→ Edge App 窗口。

## 现状

- 功能完整可用：扫描索引（TTL 600s 缓存）、模糊搜索（中文/拼音/编号/子序列/多关键词）、
  链式启动（`config.json` 的 `launch_chain`：app → explorer，支持 `open:` / `cmd:` 自定义动作）。
- **GUI 为原生窗口 + 托盘**：pywebview 窗口（WebView2）+ pystray 托盘；点 X = 隐藏到托盘
  （`closing` 事件 return False + `hide()`），托盘左键/菜单"显示主窗口"呼出，菜单"退出"才真正退出；
  冷启动双击 / 服务在跑时双击（`/api/show` 唤出）双路径都在 `launcher.vbs`。
- 图标：`make_icon.py` 用 Pillow 生成 `radar.ico`（多尺寸）+ `radar_tray.png`（托盘），改风格跑一遍脚本即可。
- 搜索自测 `test_search.py` 12/12 通过（服务运行时执行 `D:\Programs\Python311\python.exe test_search.py`）。
- UI 已通过截图验收（深色单列卡片、agent 彩色标识、高亮、键盘导航、空态雷达动画）。

## 关键实现位置（project_radar.py）

- 工作区自动发现：`discover_workspaces()`（F 盘根含 AGENTS.md 的目录；agent 名取 `04-XX工作区`）
- 扫描与摘要：`build_index()` / `extract_doc()`（README、00_项目入口、对话记录.md 等前 4KB）
- 搜索算法：`search_items()` / `match_token()`（中文关键词不做子序列，仅 ASCII 走 fzf 式召回）
- 链式启动：`do_launch()`；路径安全：`inside_workspace()`（仅允许已登记工作区内路径）
- 窗口/托盘：`gui_run()`（pywebview + pystray）；`GUI` 字典存 window/tray；`/api/show`、`/api/quit` 走这里

## 常见改动入口

- 加工作区 / 换客户端路径 / 改启动链 → 只改 `config.json`，托盘退出后重新双击。
- 改 UI → `project_radar.py` 内嵌的 `HTML_PAGE` 字符串（单文件设计，无外部前端资源）。
- 改图标 → `make_icon.py` 重跑；快捷方式 IconLocation 已指向 `radar.ico` 无需重建。
- 改扫描范围 → `config.json` 的 `type_dirs`。

## 已知坑（务必先读）

1. **launcher.vbs 必须保持纯 ASCII + CRLF 换行**：cscript 对 LF-only 的 vbs 会报
   "Not enough memory resources are available"，遇到先查换行符。
2. ZCode CLI 的沙箱 Bash 会话里 `cscript` / `cmd start xxx.lnk` 会被拒绝（Access denied /
   内存资源错误），不代表真实桌面双击有问题；验证冷启动用 PowerShell
   `Start-Process pythonw ...` 或 Computer Use 真实 UI 路径（Win+R 输入 lnk 路径回车）。
3. Codex 的桌面快捷方式 target 为空，`config.json` 里 Codex 的 `app` 留空；拿到真实 exe 路径后补上。
4. 浏览器自动化里 IAB `screenshot({clip})` 有横向拼接伪影，验证布局一律用全页截图（DOM 计数为准）。
5. **Pillow 合成半透明**：`Image.paste` 是像素替换不是合成；`ImageDraw.Draw(img, "RGBA")`
   混合模式会破坏目标 alpha 通道。半透明元素要画在独立透明图层，最后 `Image.alpha_composite`。
6. pywebview 模式别忘 `server.serve_forever()` 要放进 daemon 线程（gui_run 不调它服务就不会 accept）。
7. 多行 `python -c "..."` 在本机 Bash 工具里偶尔静默不执行，复杂脚本一律写成 .py 文件再跑。
