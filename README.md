# 项目雷达 Project Radar

F 盘多 Agent 工作区项目查询工具：桌面双击 → 模糊搜索 → 一键链式启动对应 Agent；关闭窗口缩到任务栏托盘，随时呼出。

## 解决什么问题

F 盘同时有多个 Agent 工作区（`F:\Zcode`、`F:\CodeX`、`F:\WorkBuddy`、`F:\DSH`），各自按 `01-开发项目 / 02-创作项目 / 03-对话产出 / 99-归档` 规范存放项目。想找一个项目时经常记不清是哪个 Agent 做的、放在哪个工作区。本项目雷达把所有工作区的项目扫进一个索引，统一搜索并标注归属 Agent，并支持一键启动。

## 使用方式

- 桌面双击 **项目雷达** 快捷方式（图标为自制雷达 ico）：
  - 服务未运行 → 后台拉起 `pythonw project_radar.py`，弹出**原生窗口**（pywebview + WebView2）。
  - 服务已在运行（窗口关掉了）→ 自动**唤出**隐藏的主窗口。
- **任务栏 / 托盘**：
  - 任务栏上的窗口按钮、Alt+Tab、标题栏均为紫色雷达图标（启动时经 WinForms 设置）。
  - 托盘图标（Win11 默认折叠在 `^` 溢出区）：**单击 = 弹出速查小窗**（置顶、无边框、失焦自动收起，
    输入关键词后 `Enter` 直接在资源管理器定位到项目，条目右侧 🚀 一键启动）；
    **双击 = 打开主界面**；右键菜单 = 显示主窗口 / 快速搜索 / 重新扫描 / 退出。
  - 想让雷达图标常驻任务栏：设置 → 个性化 → 任务栏 → 其他系统托盘图标 → 打开 pythonw.exe 开关（一次性）。
- **关闭窗口 ≠ 退出**：主窗口点 X 只是缩到托盘；真正退出走托盘右键菜单。
- 搜索语法：空格分隔多关键词（AND）；支持中文子串、拼音全拼（`guancai`→棺材）、拼音首字母（`dfjk`→电费监控）、编号（`013`）、日期数字（`0927`）、英文子序列（`pwmx`→PowerMax）。
- 主窗口键盘：`↑↓` 选择，`Enter` 启动，`Esc` 清空。
- 主窗口卡片按钮：**🚀 启动** = 链式启动（启动 Agent 客户端 → 资源管理器定位项目）；**📂** = 仅定位；**📄** = 打开 README / 对话记录。

## 工作区与启动链配置

编辑 `config.json`：

- `workspaces`：每个工作区的 `root` / `agent` / `color` / `app`（Agent 客户端 exe，可空）。
  未登记的工作区若根目录含 `AGENTS.md` 会被自动发现（agent 名取自 `04-XX工作区` 目录名）。
- `launch_chain`：链式启动动作序列：`"app"`（启动客户端）、`"explorer"`（定位目录）、
  `"open:<路径模板>"`、`"cmd:<命令模板>"`（支持 `{dir}` `{workspace}` 占位符）。
- 改完杀掉 pythonw 进程（或托盘退出）后重新双击生效。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `project_radar.py` | 主程序：扫描索引 + 模糊搜索 + HTTP API + 内嵌前端 + 原生窗口/托盘 |
| `config.json` | 工作区、颜色、客户端路径、启动链配置 |
| `launcher.vbs` | 无黑窗启动器（纯 ASCII、CRLF；冷启动 / 唤出双路径） |
| `make_icon.py` | 图标生成脚本（Pillow 绘制雷达图标） |
| `radar.ico` / `radar_tray.png` / `radar_preview.png` | 图标产物（快捷方式 / 托盘 / 预览） |
| `test_search.py` | 搜索质量自测（12 组断言；服务运行时执行） |
| `radar.log` / `index_cache.json` | 运行日志与索引缓存（自动生成，可删） |

## 技术要点

- 窗口：pywebview（WebView2 运行时，Win11 自带）；`closing` 事件 `return False` + `hide()` 实现关窗缩托盘；
  任务栏图标经 `window.native.Icon`（WinForms）设置；速查小窗为 frameless + on_top 第二窗口，失焦收起靠页面 `onblur`。
- 托盘：自写 Win32 `Shell_NotifyIconW`（ctypes，`Win32Tray` 类），支持单击/双击/右键区分（SetTimer 防抖）、
  TrackPopupMenu 右键菜单；不依赖 pystray。
- 服务：stdlib `ThreadingHTTPServer`（daemon 线程），只绑 127.0.0.1；路径参数校验必须位于已登记工作区内。
  API：`/api/status`（ready 标志，不阻塞）、`/api/search`、`/api/projects?refresh=1`、`/api/launch|open|open_file`、
  `/api/show`（唤出主窗）、`/api/hide_mini`、`/api/quit`、`/mini`（速查窗页面）、`/favicon.ico`。
- 索引：启动即后台预热（daemon 线程 + `threading.Lock` 防并发重建）；TTL 600 秒缓存，托盘菜单或界面"↻ 重新扫描"强制刷新。

## 已验证（2026-09-27）

- 搜索 12/12 通过（含 README 内容索引、拼音、编号、多关键词、子序列）。
- 快捷方式冷启动全链路：lnk → wscript → vbs → pythonw → 原生窗口 + HTTP 200。
- 任务栏窗口按钮图标为紫色雷达（WinForms Form.Icon 设置生效）。
- 托盘：图标注册并显示（Win11 溢出面板内可见）；单击弹速查窗 → 搜"棺材"回车 → 资源管理器
  定位到 CNS-2026-001-棺材；双击唤出主界面；右键菜单四项正常。
- 关窗缩托盘（服务存活）→ `/api/show` 唤出 → `/api/quit` 优雅退出（进程清零、日志确认）。
- 链式启动 API 实测通过（资源管理器定位）。

## 已知边界

- Win11 编程方式无法可靠把托盘图标"常驻任务栏"（IsPromotable 0/1 实测均不改变折叠行为），
  默认折叠在 `^` 溢出区；要常显请手动：设置 → 个性化 → 任务栏 → 其他系统托盘图标 → 打开 pythonw.exe。
- Codex 客户端桌面快捷方式 target 为空，`config.json` 中其 `app` 暂留空（只做目录定位）；确认 exe 路径后补上。
- `F:\DSH` 尚未初始化，初始化出分类目录后会被自动发现。
- pywebview / Pillow / pypinyin 缺失时自动降级（无窗口开默认浏览器、无拼音），主功能不受影响。
- pythonw 下首次索引构建约 10-15 秒（pypinyin 字典冷读 + WebView2 初始化抢资源），
  已用启动预热 + `/api/status` ready 标志规避页面卡顿。
