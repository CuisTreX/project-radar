#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目雷达 Project Radar
======================
F 盘多 Agent 工作区项目查询工具（ZCode / Codex / WorkBuddy / DSH ...）。

- 扫描 F 盘下所有符合规范的工作区（含 AGENTS.md + 分类目录），收集 01-开发项目 /
  02-创作项目 / 03-对话产出 / 99-归档 下的一级项目目录。
- 模糊搜索：子串 / 子序列 / 拼音全拼 / 拼音首字母 / 编号 / 多关键词 AND，加权打分排序。
- 链式启动：按 config.json 的 launch_chain 依次执行（启动 agent 客户端 → 资源管理器定位 → 自定义命令）。
- 桌面双击 launcher.vbs 即可使用（无黑窗，Edge App 模式打开）。

用法：
    pythonw project_radar.py             # 原生窗口 + 托盘（托盘单击=速查小窗，双击=主界面）
    python project_radar.py --console    # 前台输出日志（排错用）
    python project_radar.py --no-window  # 纯服务模式（无窗口，--no-browser 同义）
    python project_radar.py --port 8618
"""

import json
import os
import re
import sys
import time
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CACHE_PATH = os.path.join(BASE_DIR, "index_cache.json")
LOG_PATH = os.path.join(BASE_DIR, "radar.log")

# ---------------------------------------------------------------- 日志

def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + str(msg) + "\n")
    except OSError:
        pass

# ---------------------------------------------------------------- 配置

DEFAULT_CONFIG = {
    "port": 8618,
    "cache_ttl": 600,
    "drives": ["F:"],
    "workspaces": [
        {"root": "F:\\Zcode", "agent": "ZCode", "color": "#8b7cf6",
         "app": "D:\\Programs\\Zcode\\ZCode.exe"},
        {"root": "F:\\CodeX", "agent": "Codex", "color": "#f59e0b",
         "app": ""},
        {"root": "F:\\WorkBuddy", "agent": "WorkBuddy", "color": "#22c55e",
         "app": "D:\\Programs\\WorkBuddy\\WorkBuddy.exe"},
        {"root": "F:\\DSH", "agent": "DSH", "color": "#38bdf8",
         "app": "D:\\Programs\\DeepSeek Harness\\start-dsh.bat"}
    ],
    "launch_chain": ["app", "explorer"],
    "type_dirs": {
        "01-开发项目": "dev",
        "02-创作项目": "cns",
        "03-对话产出": "chat",
        "99-归档": "arch"
    }
}

CFG = dict(DEFAULT_CONFIG)


def load_config():
    global CFG
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if k != "type_dirs"})
            if "type_dirs" in user:
                cfg["type_dirs"] = user["type_dirs"]
        except Exception as e:  # 配置坏了就用默认并提示
            log("config.json 解析失败，使用默认配置: %s" % e)
    else:
        save_config(cfg)
    CFG = cfg
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log("config.json 写入失败: %s" % e)

# ---------------------------------------------------------------- 拼音

try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False
    log("pypinyin 未安装，拼音搜索已降级（可 pip install pypinyin 开启）")

_PY_CACHE = {}


def pinyin_of(text):
    """返回 (全拼, 首字母缩写)，非中文字符原样保留。"""
    if not HAS_PINYIN or not text:
        return "", ""
    if text in _PY_CACHE:
        return _PY_CACHE[text]
    try:
        full = "".join(lazy_pinyin(text)).lower().replace(" ", "")
        abbr = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower().replace(" ", "")
    except Exception:
        full, abbr = "", ""
    _PY_CACHE[text] = (full, abbr)
    return full, abbr

# ---------------------------------------------------------------- 扫描

RE_NUM = re.compile(r"(DEV|CNS)-(\d{4})-(\d+)", re.I)
RE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# 每种类型读摘要的候选文件顺序
DOC_CANDIDATES = {
    "dev": ["README.md", "00_项目入口.md", "01_项目总览与下一步.md", "AGENTS.md"],
    "cns": ["README.md", "00_项目入口.md", "01_项目总览与下一步.md"],
    "chat": ["对话记录.md", "README.md"],
    "arch": ["README.md"],
}

TYPE_LABEL = {"dev": "开发", "cns": "创作", "chat": "对话", "arch": "归档"}
TYPE_COLOR = {"dev": "#60a5fa", "cns": "#f472b6", "chat": "#2dd4bf", "arch": "#64748b"}


def read_head(path, limit=4096):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


def extract_doc(dirpath, doctype):
    """返回 (source_file, title, desc, index_text)"""
    for name in DOC_CANDIDATES.get(doctype, ["README.md"]):
        fp = os.path.join(dirpath, name)
        if os.path.isfile(fp):
            text = read_head(fp)
            if not text.strip():
                continue
            title, desc = "", ""
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                if not title and s.startswith("#"):
                    title = s.lstrip("#").strip()
                    continue
                if s.startswith(("|", ">", "-", "*", "```", "[", "!")):
                    continue
                desc = s
                break
            if not desc:
                for line in text.splitlines():
                    s = line.strip()
                    if s and not s.startswith(("#", "|", "```", "!", "[")):
                        desc = s
                        break
            return name, title, desc[:200], text[:2500]
    return "", "", "", ""


def scan_project(ws_info, dirpath, doctype):
    name = os.path.basename(dirpath.rstrip("\\/"))
    try:
        mtime = int(os.path.getmtime(dirpath))
    except OSError:
        mtime = 0
    src, title, desc, text = extract_doc(dirpath, doctype)

    files = []
    try:
        entries = sorted(os.listdir(dirpath))[:40]
        for e in entries:
            fp = os.path.join(dirpath, e)
            files.append(e + ("/" if os.path.isdir(fp) else ""))
    except OSError:
        pass

    m = RE_NUM.search(name)
    number = ("%s-%s" % (m.group(2), m.group(3))) if m else ""
    dm = RE_DATE.search(name)
    digits = re.sub(r"\D", "", name)[:12]

    py_full, py_abbr = pinyin_of(name)
    if title:
        t_full, t_abbr = pinyin_of(title)
        py_full += " " + t_full
        py_abbr += " " + t_abbr

    return {
        "name": name,
        "number": number,
        "digits": digits,
        "type": doctype,
        "type_label": TYPE_LABEL.get(doctype, doctype),
        "type_color": TYPE_COLOR.get(doctype, "#8b93a7"),
        "path": dirpath,
        "mtime": mtime,
        "agent": ws_info["agent"],
        "agent_color": ws_info.get("color", "#8b93a7"),
        "workspace": ws_info["root"],
        "doc_source": src,
        "title": title,
        "desc": desc,
        "files": files[:40],
        # 索引字段（不返回给前端，仅服务端搜索用）
        "_text": (text + " " + title + " " + desc).lower(),
        "_py": py_full.lower(),
        "_pyab": py_abbr.lower(),
    }


def discover_workspaces():
    """config 里登记的 + 自动发现的（F 盘根下含 AGENTS.md 的目录）。"""
    found = {w["root"].lower(): w for w in CFG["workspaces"]}
    for drive in CFG.get("drives", ["F:"]):
        try:
            names = os.listdir(drive + "\\")
        except OSError:
            continue
        for name in names:
            root = os.path.join(drive + "\\", name)
            if not os.path.isdir(root):
                continue
            if not os.path.isfile(os.path.join(root, "AGENTS.md")):
                continue
            if root.lower() in found:
                continue
            agent = name
            for sub in os.listdir(root):
                m = re.match(r"04-(.+?)工作区$", sub)
                if m and os.path.isdir(os.path.join(root, sub)):
                    agent = m.group(1)
                    break
            found[root.lower()] = {
                "root": root, "agent": agent, "color": "#94a3b8", "app": ""
            }
    return list(found.values())


def build_index():
    items = []
    ws_list = discover_workspaces()
    for ws in ws_list:
        root = ws["root"]
        if not os.path.isdir(root):
            continue
        for dirname, doctype in CFG["type_dirs"].items():
            base = os.path.join(root, dirname)
            if not os.path.isdir(base):
                continue
            try:
                subs = sorted(os.listdir(base))
            except OSError:
                continue
            for sub in subs:
                sub_path = os.path.join(base, sub)
                if sub.startswith((".", "$")) or not os.path.isdir(sub_path):
                    continue
                try:
                    if not next(os.scandir(sub_path), None):
                        continue  # 空目录不收录
                except OSError:
                    continue
                items.append(scan_project(ws, sub_path, doctype))
    index = {
        "built_at": int(time.time()),
        "workspaces": [
            {"root": w["root"], "agent": w["agent"], "color": w.get("color", "#94a3b8"),
             "app": w.get("app", ""), "registered": w["root"].lower() in
             [x["root"].lower() for x in CFG["workspaces"]]}
            for w in ws_list
        ],
        "has_pinyin": HAS_PINYIN,
        "items": items,
    }
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
    except OSError as e:
        log("缓存写入失败: %s" % e)
    log("索引完成：%d 个项目，%d 个工作区" % (len(items), len(ws_list)))
    return index

INDEX = {"built_at": 0, "items": []}
_INDEX_LOCK = threading.Lock()


def get_index(force=False):
    with _INDEX_LOCK:
        return _get_index_unlocked(force)


def _get_index_unlocked(force=False):
    ttl = CFG.get("cache_ttl", 600)
    if force or time.time() - INDEX.get("built_at", 0) > ttl:
        # 先尝试磁盘缓存
        if not force and os.path.isfile(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if time.time() - cached.get("built_at", 0) < ttl:
                    INDEX.clear()
                    INDEX.update(cached)
                    return INDEX
            except Exception as e:
                log("缓存读取失败: %s" % e)
        new_index = build_index()
        INDEX.clear()
        INDEX.update(new_index)
    return INDEX

# ---------------------------------------------------------------- 模糊搜索

SEPARATORS = set(" -_./\\:：，。、（）()[]【】|")
RE_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")


def substring_score(needle, hay):
    """子串命中：返回 (score, (start, end)) 或 (0, None)。"""
    idx = hay.find(needle)
    if idx < 0:
        return 0, None
    score = 100.0
    if idx == 0 or hay[idx - 1] in SEPARATORS:
        score += 30
    if idx + len(needle) == len(hay):
        score += 15
    score -= min(idx, 30)
    return score, (idx, idx + len(needle))


def subseq_score(needle, hay):
    """子序列命中（fzf 风格）：返回 (score, indices) 或 (0, None)。"""
    indices = []
    i = 0
    streak = max_streak = 0
    for j, ch in enumerate(hay):
        if i < len(needle) and ch == needle[i]:
            indices.append(j)
            streak += 1
            max_streak = max(max_streak, streak)
            i += 1
        else:
            streak = 0
    if i < len(needle):
        return 0, None
    span = indices[-1] - indices[0] + 1
    if span == len(needle):
        return substring_score(needle, hay)  # 实际是连续子串
    score = 40.0 + max_streak * 8 - (span - len(needle)) * 1.5
    return max(score, 5.0), indices


FIELD_WEIGHTS = [
    ("name", 10.0),
    ("number", 9.0),
    ("digits", 5.0),
    ("_py", 7.0),
    ("_pyab", 7.0),
    ("agent", 6.0),
    ("type_label", 5.0),
    ("title", 4.0),
    ("desc", 2.5),
    ("files", 2.0),
    ("_text", 1.2),
]


def match_token(token, item):
    """单个关键词对单个项目打分。返回 (score, {field: hl})。"""
    best = 0.0
    hls = {}
    for field, weight in FIELD_WEIGHTS:
        hay = item.get(field, "")
        if not hay:
            continue
        if field == "files":
            hay_l = " ".join(hay).lower()
        else:
            hay_l = str(hay).lower()
        s, hl = substring_score(token, hay_l)
        if not s and not RE_HAS_CJK.search(token):
            # 中文关键词不做子序列召回（噪声大）；ASCII 才允许 fzf 风格宽松匹配
            s, hl = subseq_score(token, hay_l)
        if s:
            s *= weight / 10.0
            if s > best:
                best = s
            if field in ("name", "title", "desc") and hl:
                hls[field] = hl
    return best, hls


def search_items(query, agent="all", item_type="all"):
    items = get_index()["items"]
    query = (query or "").strip().lower()
    pool = [it for it in items
            if (agent == "all" or it["agent"] == agent)
            and (item_type == "all" or it["type"] == item_type)]
    results = []
    if not query:
        results = [{"item": it, "score": 0, "hl": {}} for it in pool]
        results.sort(key=lambda r: (-r["item"]["mtime"], r["item"]["name"]))
        return results[:80]
    tokens = query.split()
    for it in pool:
        total = 0.0
        merged_hl = {}
        ok = True
        for tok in tokens:
            s, hls = match_token(tok, it)
            if s <= 0:
                ok = False
                break
            total += s
            for f, hl in hls.items():
                merged_hl.setdefault(f, [])
                if isinstance(hl, tuple):
                    merged_hl[f].append(list(hl))
                else:
                    merged_hl[f].append(list(hl))
        if ok:
            # 全部关键词命中名称本身 → 额外奖励
            if all(substring_score(t, it["name"].lower())[0] for t in tokens):
                total += 50
            results.append({"item": it, "score": round(total, 1), "hl": merged_hl})
    results.sort(key=lambda r: (-r["score"], -r["item"]["mtime"]))
    return results[:80]

# ---------------------------------------------------------------- 动作

def inside_workspace(path):
    path = os.path.abspath(path)
    for w in discover_workspaces():
        root = os.path.abspath(w["root"])
        if path == root or path.lower().startswith(root.lower() + os.sep):
            return w
    return None


def do_open_dir(path):
    w = inside_workspace(path)
    if not w:
        return False, "路径不在任何工作区内"
    subprocess.Popen("explorer /select,\"%s\"" % path, shell=True)
    return True, "已打开资源管理器"


def do_open_file(path):
    w = inside_workspace(path)
    if not w:
        return False, "路径不在任何工作区内"
    if not os.path.isfile(path):
        return False, "文件不存在"
    os.startfile(path)  # noqa
    return True, "已用系统默认程序打开"


def do_launch(path):
    w = inside_workspace(path)
    if not w:
        return False, "路径不在任何工作区内"
    root = w["root"]
    chain = w.get("launch_chain") or CFG.get("launch_chain", ["app", "explorer"])
    done = []
    for act in chain:
        try:
            if act == "app":
                app = w.get("app", "")
                if app:
                    if app.startswith("shell:"):
                        # MSIX/商店应用（如 Codex 桌面端）：shell:AppsFolder\<AUMID>
                        subprocess.Popen(["explorer.exe", app])
                        done.append("启动 %s 客户端" % w["agent"])
                    elif os.path.exists(app):
                        if app.lower().endswith(".bat"):
                            subprocess.Popen(["cmd", "/c", app], cwd=root)
                        else:
                            subprocess.Popen([app], cwd=root)
                        done.append("启动 %s 客户端" % w["agent"])
                    else:
                        log("客户端路径不存在: %s（%s）" % (app, w["agent"]))
                        done.append("%s 客户端路径无效，已跳过" % w["agent"])
            elif act == "explorer":
                subprocess.Popen("explorer /select,\"%s\"" % path, shell=True)
                done.append("资源管理器定位")
            elif act.startswith("open:"):
                os.startfile(act[5:].replace("{dir}", path).replace("{workspace}", root))  # noqa
                done.append("打开文件")
            elif act.startswith("cmd:"):
                cmd = act[4:].replace("{dir}", path).replace("{workspace}", root)
                subprocess.Popen(cmd, shell=True, cwd=path)
                done.append("执行命令")
        except Exception as e:
            log("启动链步骤失败 (%s): %s" % (act, e))
    if not done:
        msg = "未配置启动动作（config.json 的 app 与 launch_chain）"
        return True, msg
    return True, " → ".join(done)

# ---------------------------------------------------------------- GUI（托盘 + 原生窗口）

GUI = {"window": None, "mini": None, "mini_shown": False, "quitting": False}


def gui_show_window():
    w = GUI.get("window")
    if w:
        try:
            w.show()
            return True
        except Exception as e:
            log("show 窗口失败: %s" % e)
    return False


def gui_show_mini():
    w = GUI.get("mini")
    if not w:
        return False
    try:
        w.show()
        GUI["mini_shown"] = True
        try:
            w.evaluate_js('var q=document.getElementById("q"); if(q){q.focus();q.select();}')
        except Exception:
            pass
        return True
    except Exception as e:
        log("show 速查窗失败: %s" % e)
        return False


def gui_hide_mini():
    w = GUI.get("mini")
    if not w:
        return False
    try:
        w.hide()
        GUI["mini_shown"] = False
        return True
    except Exception as e:
        log("hide 速查窗失败: %s" % e)
        return False


def gui_toggle_mini():
    if GUI.get("mini_shown"):
        gui_hide_mini()
    else:
        gui_show_mini()


def gui_quit():
    GUI["quitting"] = True
    w = GUI.get("window")
    if w:
        try:
            w.destroy()
        except Exception:
            pass


def gui_run(server):
    """主线程运行：原生主窗口 + 速查小窗 + Win32 托盘（自绘，区分单击/双击）。"""
    try:
        import webview
    except ImportError as e:
        log("GUI 依赖缺失，回退浏览器模式: %s" % e)
        webbrowser.open("http://127.0.0.1:%d/" % CFG["port"])
        server.serve_forever()
        return

    url = "http://127.0.0.1:%d/" % CFG["port"]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    window = webview.create_window(
        "项目雷达", url, width=1000, height=780,
        min_size=(720, 560), background_color="#0b0e14", hidden=True,
    )
    GUI["window"] = window

    # 速查小窗：无边框、置顶，屏幕右下角（托盘附近）
    try:
        import ctypes
        sm = ctypes.windll.user32.GetSystemMetrics
        mx, my = sm(0), sm(1)
    except Exception:
        mx, my = 1920, 1080
    mini = webview.create_window(
        "雷达速查", url + "mini", width=420, height=540,
        x=max(mx - 440, 0), y=max(my - 620, 0),
        frameless=True, on_top=True, hidden=True,
        background_color="#0b0e14",
    )
    GUI["mini"] = mini

    def on_main_closing():
        # 主窗口点 X：不退出，缩到托盘
        if not GUI["quitting"]:
            try:
                window.hide()
            except Exception:
                pass
            return False
        return None

    def on_mini_closing():
        if not GUI["quitting"]:
            try:
                mini.hide()
                GUI["mini_shown"] = False
            except Exception:
                pass
            return False
        return None

    def on_mini_blurred():
        if not GUI["quitting"]:
            try:
                mini.hide()
                GUI["mini_shown"] = False
            except Exception:
                pass

    window.events.closing += on_main_closing
    mini.events.closing += on_mini_closing
    try:
        mini.events.blurred += on_mini_blurred  # 点击别处自动收起（旧版无此事件则降级）
    except Exception as e:
        log("blurred 事件不可用（改用页面 onblur）: %s" % e)

    # ---- Win32 托盘：原生 radar.ico，单击=速查，双击=主界面，右键=菜单 ----
    try:
        tray = Win32Tray(
            ico_path=os.path.join(BASE_DIR, "radar.ico"),
            tip="项目雷达 — 单击速查 · 双击主界面",
            on_single=gui_show_mini,
            on_double=gui_show_window,
            on_menu={"显示主窗口": gui_show_window,
                     "快速搜索": gui_toggle_mini,
                     "重新扫描": lambda: _rescan_async(url),
                     "退出": gui_quit},
        )
        threading.Thread(target=tray.run, daemon=True).start()
    except Exception as e:
        log("托盘初始化失败: %s" % e)

    def _after_gui():
        # GUI 就绪：显示主窗口并设置任务栏图标
        try:
            window.show()
        except Exception:
            pass
        try:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Icon as DIcon
            window.native.Icon = DIcon(os.path.join(BASE_DIR, "radar.ico"))
        except Exception as e:
            log("任务栏图标设置降级: %s" % e)

    try:
        webview.start(_after_gui, debug=False)
    except Exception as e:
        log("GUI 启动失败，回退浏览器模式: %s" % e)
        webbrowser.open(url)
        server.serve_forever()
        return
    server.shutdown()
    log("项目雷达已退出")


def _rescan_async(url):
    threading.Thread(
        target=lambda: _do_rescan(url), daemon=True
    ).start()


def _do_rescan(url):
    try:
        urllib.request.urlopen(url + "api/projects?refresh=1", timeout=20).read()
        log("托盘触发重新扫描完成")
    except Exception as e:
        log("托盘重新扫描失败: %s" % e)


class Win32Tray:
    """自写 Shell_NotifyIcon 托盘：单击 / 双击 / 右键菜单全自定义。"""

    def __init__(self, ico_path, tip, on_single, on_double, on_menu):
        self.ico_path = ico_path
        self.tip = tip[:127]
        self.on_single = on_single
        self.on_double = on_double
        self.on_menu = on_menu
        self._hwnd = None
        self._nid = None

    # -- 常量 --
    WM_APP_TRAY = 0x8001
    NIM_ADD, NIM_DELETE = 0, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205
    WM_TIMER, WM_COMMAND, WM_DESTROY, WM_CLOSE = 0x0113, 0x0111, 0x0002, 0x0010

    def run(self):
        try:
            self._run()
        except Exception as e:
            log("托盘线程异常: %r" % e)
        except BaseException as e:
            log("托盘线程致命: %r" % e)

    def _run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        LRESULT = ctypes.c_longlong
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", ctypes.c_wchar * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_ubyte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        nid = NOTIFYICONDATAW()
        self._nid = nid
        tray = self

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == tray.WM_APP_TRAY:
                ev = lparam & 0xFFFF
                if ev == tray.WM_LBUTTONUP:
                    # 延迟判定，避免双击时先触发单击
                    user32.SetTimer(hwnd, 1, 400, None)
                elif ev == tray.WM_LBUTTONDBLCLK:
                    user32.KillTimer(hwnd, 1)
                    tray.on_double()
                elif ev == tray.WM_RBUTTONUP:
                    tray._popup_menu(hwnd)
                return 0
            if msg == tray.WM_TIMER:
                user32.KillTimer(hwnd, 1)
                tray.on_single()
                return 0
            if msg == tray.WM_DESTROY:
                shell32.Shell_NotifyIconW(tray.NIM_DELETE, ctypes.byref(nid))
                user32.PostQuitMessage(0)
                return 0
            if msg == tray.WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)  # 防 GC

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.lpszClassName = "ProjectRadarTray"
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError("RegisterClassW failed")

        self._hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, "ProjectRadarTray", 0,
            0, 0, 0, 0, None, None, wc.hInstance, None)
        if not self._hwnd:
            raise OSError("CreateWindowExW failed")

        hicon = user32.LoadImageW(
            None, self.ico_path, tray.IMAGE_ICON, 0, 0, tray.LR_LOADFROMFILE)
        if not hicon:
            log("LoadImageW 加载 ico 失败 err=%d" % ctypes.GetLastError())
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = tray.NIF_MESSAGE | tray.NIF_ICON | tray.NIF_TIP
        nid.uCallbackMessage = tray.WM_APP_TRAY
        nid.hIcon = hicon
        nid.szTip = self.tip
        if not shell32.Shell_NotifyIconW(tray.NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIconW failed, err=%d" % ctypes.GetLastError())
        log("托盘已注册 hwnd=%s hicon=%s" % (self._hwnd, hicon))

        msg = MSG()
        pmsg = ctypes.byref(msg)
        while user32.GetMessageW(pmsg, None, 0, 0) > 0:
            user32.TranslateMessage(pmsg)
            user32.DispatchMessageW(pmsg)

    def _popup_menu(self, hwnd):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MF_STRING, MF_SEPARATOR = 0x0, 0x800
        TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        hmenu = user32.CreatePopupMenu()
        ids = {}
        mid = 1001
        for label in self.on_menu:
            ids[mid] = label
            user32.AppendMenuW(hmenu, MF_STRING, mid, label)
            mid += 1
            if label == "重新扫描":
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(hmenu)
        user32.PostMessageW(hwnd, self.WM_COMMAND, cmd, 0)
        if cmd in ids:
            try:
                self.on_menu[ids[cmd]]()
            except Exception as e:
                log("托盘菜单动作失败: %s" % e)


# ---------------------------------------------------------------- HTTP

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>项目雷达</title>
<style>
:root{
  --bg:#0b0e14; --panel:#11151f; --card:#151a26; --card-hover:#1a2030;
  --border:#232a3a; --border-lit:#33405c;
  --text:#e7eaf2; --muted:#8b93a7; --dim:#5c6478;
  --accent:#7c8cff; --accent-soft:rgba(124,140,255,.16);
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{
  background:var(--bg); color:var(--text);
  font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
  font-size:14px; overflow:hidden;
}
#app{display:flex;flex-direction:column;height:100vh}

/* ---- 顶栏 ---- */
header{
  padding:18px 22px 10px; flex:0 0 auto;
  background:linear-gradient(180deg,rgba(124,140,255,.05),transparent);
}
.hrow{display:flex;align-items:center;gap:12px}
.logo{display:flex;align-items:center;gap:10px;user-select:none}
.radar{
  width:26px;height:26px;border-radius:50%;position:relative;flex:0 0 auto;
  border:1.5px solid var(--accent);
  background:radial-gradient(circle,rgba(124,140,255,.25) 0%,transparent 70%);
  overflow:hidden;
}
.radar::before{content:"";position:absolute;inset:6px;border-radius:50%;
  border:1px solid rgba(124,140,255,.4)}
.radar::after{content:"";position:absolute;left:50%;top:50%;width:50%;height:50%;
  transform-origin:0 0;
  background:conic-gradient(from 0deg,rgba(124,140,255,.65),transparent 70deg,transparent);
  animation:sweep 2.4s linear infinite; border-radius:0 100% 0 0}
.radar i{position:absolute;left:50%;top:50%;width:3px;height:3px;border-radius:50%;
  background:#ff6b81;transform:translate(-50%,-50%);animation:blink 2.4s ease infinite}
@keyframes sweep{to{transform:rotate(360deg)}}
@keyframes blink{0%,55%{opacity:1}60%,100%{opacity:.15}}
.logo h1{font-size:17px;font-weight:600;letter-spacing:.5px}
.logo h1 span{color:var(--accent);font-weight:700}
.spacer{flex:1}
.btn{
  background:var(--panel);border:1px solid var(--border);color:var(--muted);
  border-radius:9px;padding:7px 13px;cursor:pointer;font-size:13px;
  transition:all .15s;user-select:none;white-space:nowrap;
}
.btn:hover{color:var(--text);border-color:var(--border-lit);background:var(--card-hover)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary:hover{filter:brightness(1.1)}

/* ---- 搜索框 ---- */
.searchbox{margin-top:14px;position:relative}
.searchbox svg{position:absolute;left:15px;top:50%;transform:translateY(-50%);
  width:17px;height:17px;stroke:var(--dim);pointer-events:none}
#q{
  width:100%;background:var(--panel);border:1px solid var(--border);
  border-radius:13px;padding:13px 92px 13px 44px;font-size:15px;color:var(--text);
  outline:none;transition:border .15s, box-shadow .15s;font-family:inherit;
}
#q::placeholder{color:var(--dim)}
#q:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.kbd{
  position:absolute;right:14px;top:50%;transform:translateY(-50%);
  font-size:11px;color:var(--dim);border:1px solid var(--border);
  border-radius:5px;padding:2px 6px;user-select:none;
}

/* ---- 筛选 chips ---- */
.filters{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center}
.chip{
  display:inline-flex;align-items:center;gap:6px;
  background:transparent;border:1px solid var(--border);color:var(--muted);
  border-radius:999px;padding:5px 13px;font-size:12.5px;cursor:pointer;
  transition:all .15s;user-select:none;
}
.chip:hover{border-color:var(--border-lit);color:var(--text)}
.chip.on{background:var(--accent-soft);border-color:var(--accent);color:var(--text)}
.chip .dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto}
.sep{width:1px;height:16px;background:var(--border);margin:0 4px}

/* ---- 结果列表 ---- */
#list{
  flex:1 1 auto;overflow-y:auto;padding:10px 22px 16px;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent;
}
#list::-webkit-scrollbar{width:8px}
#list::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.card{
  background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:13px 16px;margin-bottom:9px;cursor:pointer;
  transition:border .12s, background .12s, transform .12s;
}
.card:hover,.card.sel{border-color:var(--border-lit);background:var(--card-hover)}
.card.sel{box-shadow:0 0 0 1px var(--accent-soft), 0 4px 16px rgba(0,0,0,.25)}
.card .r1{display:flex;align-items:center;gap:9px}
.badge{
  font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:5px;
  letter-spacing:.5px;flex:0 0 auto;
}
.name{font-size:14.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;flex:1;min-width:0}
.agent-tag{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;
  color:var(--muted);flex:0 0 auto;user-select:none}
.agent-tag .dot{width:8px;height:8px;border-radius:50%}
.card .r2{display:flex;gap:7px;align-items:center;margin-top:5px;
  font-size:12px;color:var(--dim);overflow:hidden}
.path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.card .r3{display:flex;align-items:center;gap:10px;margin-top:6px}
.desc{font-size:12.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;flex:1;min-width:0}
.time{font-size:11.5px;color:var(--dim);flex:0 0 auto}
mark{background:rgba(124,140,255,.28);color:#d3dbff;border-radius:3px;padding:0 1px}
.acts{display:flex;gap:6px;flex:0 0 auto}
.mini{
  font-size:11.5px;padding:4px 10px;border-radius:7px;cursor:pointer;
  background:var(--panel);border:1px solid var(--border);color:var(--muted);
  transition:all .15s;user-select:none;white-space:nowrap;
}
.mini:hover{color:var(--text);border-color:var(--accent)}
.mini.go{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.mini.go:hover{filter:brightness(1.12)}
.mini.ok{background:#22c55e;border-color:#22c55e;color:#fff}

/* ---- 空态 / 底栏 ---- */
#empty{display:none;text-align:center;padding:70px 0;color:var(--dim)}
#empty .radar{margin:0 auto 18px;width:56px;height:56px}
#empty .radar::before{inset:13px}
#empty p{font-size:13.5px;line-height:2}
footer{
  flex:0 0 auto;border-top:1px solid var(--border);padding:8px 22px;
  display:flex;gap:14px;font-size:11.5px;color:var(--dim);user-select:none;
  background:var(--panel);
}
footer .ok{color:#34d399}
#toast{
  position:fixed;bottom:52px;left:50%;transform:translateX(-50%) translateY(16px);
  background:#1c2434;border:1px solid var(--border-lit);color:var(--text);
  padding:9px 18px;border-radius:10px;font-size:13px;opacity:0;pointer-events:none;
  transition:all .25s;box-shadow:0 8px 24px rgba(0,0,0,.4);max-width:80vw;
}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<div id="app">
  <header>
    <div class="hrow">
      <div class="logo">
        <div class="radar"><i></i></div>
        <h1>项目<span>雷达</span></h1>
      </div>
      <div class="spacer"></div>
      <button class="btn" id="refresh" title="重新扫描 F 盘工作区">↻ 重新扫描</button>
    </div>
    <div class="searchbox">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round">
        <circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>
      </svg>
      <input id="q" type="text" autofocus autocomplete="off" spellcheck="false"
        placeholder="搜索项目名 / 关键词 / 拼音 / 编号 / agent，空格分隔多关键词…">
      <span class="kbd">Enter 启动</span>
    </div>
    <div class="filters" id="agents"></div>
    <div class="filters" id="types"></div>
  </header>
  <div id="list"></div>
  <div id="empty">
    <div class="radar"><i></i></div>
    <p>雷达没有发现匹配的项目<br>试试更短的关键词，或按空格拆成多个词</p>
  </div>
  <footer>
    <span id="f-count"></span>
    <span id="f-index"></span>
    <span class="spacer"></span>
    <span>↑↓ 选择 · Enter 启动 · 点 X 缩到托盘：单击速查 / 双击主界面</span>
  </footer>
</div>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const TYPE_CHIPS=[["all","全部类型"],["dev","开发"],["cns","创作"],["chat","对话"],["arch","归档"]];
let all={},curAgent="all",curType="all",sel=-1,curItems=[],agentList=[];

const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function hl(text,hls){
  if(!hls||!hls.length) return esc(text);
  let marks=[];
  for(const h of hls){ if(Array.isArray(h)&&h.length===2) marks.push(h);
    else if(Array.isArray(h)&&h.length>0) marks.push([h[0],h[0]+1]); }
  marks.sort((a,b)=>a[0]-b[0]);
  const merged=[];
  for(const m of marks){ const last=merged[merged.length-1];
    if(last&&m[0]<=last[1]) last[1]=Math.max(last[1],m[1]); else merged.push([...m]); }
  let out="",pos=0;
  for(const [s,e] of merged){ out+=esc(text.slice(pos,s))+"<mark>"+esc(text.slice(s,e))+"</mark>"; pos=e; }
  return out+esc(text.slice(pos));
}
function fmtTime(ts){
  if(!ts) return "";
  const d=new Date(ts*1000), now=Date.now()/1000, diff=(now-ts)/86400;
  const pad=n=>String(n).padStart(2,"0");
  const day=d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate());
  if(diff<1) return "今天 "+pad(d.getHours())+":"+pad(d.getMinutes());
  if(diff<2) return "昨天";
  if(diff<30) return parseInt(diff)+" 天前 · "+day.slice(5);
  return day;
}
function toast(msg){
  const t=$("#toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),2200);
}

async function api(path){
  const r=await fetch(path);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderAgents(){
  const box=$("#agents");
  let html=`<span class="chip ${curAgent==="all"?"on":""}" data-a="all">● 全部工作区</span>`;
  for(const a of agentList){
    html+=`<span class="chip ${curAgent===a.agent?"on":""}" data-a="${esc(a.agent)}">
      <span class="dot" style="background:${esc(a.color)}"></span>${esc(a.agent)}</span>`;
  }
  box.innerHTML=html;
  box.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{curAgent=c.dataset.a;sel=-1;renderAgents();doSearch();});
}
function renderTypes(){
  const box=$("#types");
  box.innerHTML=TYPE_CHIPS.map(([v,l])=>
    `<span class="chip ${curType===v?"on":""}" data-t="${v}">${l}</span>`).join("");
  box.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{curType=c.dataset.t;sel=-1;renderTypes();doSearch();});
}

function cardHTML(r,i){
  const it=r.item, rhl=r.hl||{};
  const badgeBg=it.type_color+"22", badgeFg=it.type_color;
  return `<div class="card ${i===sel?"sel":""}" data-i="${i}">
    <div class="r1">
      <span class="badge" style="background:${badgeBg};color:${badgeFg}">${esc(it.type_label)}</span>
      <span class="name">${hl(it.name,rhl.name)}</span>
      <span class="agent-tag"><span class="dot" style="background:${esc(it.agent_color)}"></span>${esc(it.agent)}</span>
    </div>
    <div class="r2"><span class="path" title="${esc(it.path)}">${esc(it.path)}</span></div>
    <div class="r3">
      <span class="desc">${it.title?hl(it.title,rhl.title):""}${it.title&&it.desc?" · ":""}${hl(it.desc,rhl.desc)}</span>
      <span class="time">${fmtTime(it.mtime)}</span>
      <span class="acts">
        <span class="mini go" data-act="launch" data-i="${i}" title="启动 ${esc(it.agent)} 并定位到项目">🚀 启动</span>
        <span class="mini" data-act="open" data-i="${i}" title="资源管理器中定位">📂</span>
        ${it.type==="chat"||it.doc_source?`<span class="mini" data-act="file" data-i="${i}" title="打开 ${esc(it.doc_source||"对话记录.md")}">📄</span>`:""}
      </span>
    </div>
  </div>`;
}

function render(){
  const list=$("#list");
  if(!curItems.length){
    list.style.display="none"; $("#empty").style.display=$("#q").value?"block":"none";
  }else{
    $("#empty").style.display="none"; list.style.display="block";
    list.innerHTML=curItems.map(cardHTML).join("");
    list.querySelectorAll(".card").forEach(c=>{
      c.ondblclick=()=>launch(+c.dataset.i);
      c.onclick=e=>{
        if(e.target.closest(".mini")) return;
        const i=+c.dataset.i; sel=(sel===i?-1:i); render(); scrollSel();
      };
    });
    list.querySelectorAll(".mini").forEach(m=>{
      m.onclick=async e=>{
        e.stopPropagation();
        const i=+m.dataset.i, act=m.dataset.act;
        try{
          const it=curItems[i].item;
          let res;
          if(act==="launch") res=await api("/api/launch?path="+encodeURIComponent(it.path));
          else if(act==="open") res=await api("/api/open?path="+encodeURIComponent(it.path));
          else res=await api("/api/open_file?path="+encodeURIComponent(it.path+"\\"+(it.doc_source||"对话记录.md")));
          toast(res.message||res.ok);
          if(act==="launch"){ m.classList.add("ok"); m.textContent="✓ 已启动";
            setTimeout(()=>{m.classList.remove("ok");m.textContent="🚀 启动";},1600); }
        }catch(err){ toast("失败："+err.message); }
      };
    });
  }
  $("#f-count").textContent=`共 ${all.total??0} 个项目 · 当前显示 ${curItems.length} 个`;
}
function scrollSel(){
  const el=$("#list .card.sel"); if(el) el.scrollIntoView({block:"nearest"});
}

async function doSearch(){
  const q=$("#q").value;
  const data=await api(`/api/search?q=${encodeURIComponent(q)}&agent=${encodeURIComponent(curAgent)}&type=${curType}`);
  curItems=data.results; sel=-1; render();
}
async function refresh(){
  $("#refresh").textContent="⟳ 扫描中…";
  try{ await api("/api/projects?refresh=1"); await loadMeta(); await doSearch(); toast("扫描完成"); }
  catch(e){ toast("扫描失败："+e.message); }
  $("#refresh").textContent="↻ 重新扫描";
}
async function launch(i){
  if(!curItems[i]) return;
  const it=curItems[i].item;
  try{ const res=await api("/api/launch?path="+encodeURIComponent(it.path)); toast(res.message||"已启动"); }
  catch(e){ toast("启动失败："+e.message); }
}

async function loadMeta(){
  all=await api("/api/status");
  if(!all.ready){
    $("#f-count").textContent="正在扫描 F 盘工作区，请稍候…";
    agentList=all.workspaces||[]; renderAgents();
    setTimeout(loadMeta,1500);
    return;
  }
  agentList=all.workspaces.filter(w=>w.agent);
  $("#f-index").textContent="索引时间 "+(all.built_at?new Date(all.built_at*1000).toLocaleTimeString():"-")
    +(all.has_pinyin?"":" · 未装 pypinyin，拼音搜索降级");
  renderAgents();
}

$("#q").addEventListener("input",()=>{clearTimeout($("#q")._h);$("#q")._h=setTimeout(doSearch,110);});
$("#q").addEventListener("keydown",e=>{
  if(e.key==="ArrowDown"){e.preventDefault();sel=Math.min(sel+1,curItems.length-1);render();scrollSel();}
  else if(e.key==="ArrowUp"){e.preventDefault();sel=Math.max(sel-1,-1);render();scrollSel();}
  else if(e.key==="Enter"){
    if(sel<0&&curItems.length) sel=0;
    if(sel>=0) launch(sel);
  }
  else if(e.key==="Escape"){ $("#q").value=""; doSearch(); }
});
$("#refresh").onclick=refresh;

loadMeta().then(doSearch).catch(e=>{
  $("#list").innerHTML=`<div style="text-align:center;padding:60px;color:var(--dim)">加载失败：${esc(e.message)}</div>`;
});
</script>
</body>
</html>
"""


MINI_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>雷达速查</title>
<style>
:root{--bg:#0b0e14;--card:#151a26;--card-hover:#1a2030;--border:#232a3a;
  --text:#e7eaf2;--muted:#8b93a7;--dim:#5c6478;--accent:#7c8cff;--accent-soft:rgba(124,140,255,.16)}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
  font-size:13px;overflow:hidden;border:1px solid #2a3350;border-radius:10px;height:100vh;
  display:flex;flex-direction:column}
.bar{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#11151f;
  border-bottom:1px solid var(--border);user-select:none;flex:0 0 auto}
.bar .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 8px var(--accent)}
.bar b{font-size:12.5px;letter-spacing:1px;color:var(--muted);flex:1}
.bar button{background:none;border:none;color:var(--dim);cursor:pointer;font-size:14px;
  padding:2px 6px;border-radius:5px}
.bar button:hover{color:var(--text);background:var(--card-hover)}
.sbox{padding:10px 12px 6px;flex:0 0 auto}
#q{width:100%;background:var(--card);border:1px solid var(--border);border-radius:9px;
  padding:9px 12px;font-size:14px;color:var(--text);outline:none;font-family:inherit}
#q:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
#list{flex:1 1 auto;overflow-y:auto;padding:6px 8px 8px;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
#list::-webkit-scrollbar{width:7px}
#list::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}
.it{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:8px;
  cursor:pointer;border:1px solid transparent}
.it:hover,.it.sel{background:var(--card-hover);border-color:var(--border)}
.it .badge{font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px;flex:0 0 auto}
.it .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-weight:600;font-size:12.5px}
.it .ag{display:flex;align-items:center;gap:4px;font-size:10.5px;color:var(--dim);flex:0 0 auto}
.it .ag i{width:7px;height:7px;border-radius:50%;display:inline-block}
.it .go{flex:0 0 auto;font-size:10.5px;padding:2px 8px;border-radius:6px;cursor:pointer;
  background:var(--accent);color:#fff;border:none}
.it .go:hover{filter:brightness(1.15)}
.ft{flex:0 0 auto;border-top:1px solid var(--border);padding:6px 12px;font-size:10.5px;
  color:var(--dim);background:#11151f;user-select:none}
#empty{display:none;text-align:center;padding:36px 0;color:var(--dim);font-size:12px}
</style>
</head>
<body>
<div class="bar pywebview-drag-region">
  <span class="dot"></span><b>雷 达 速 查</b>
  <button onclick="fetch('/api/hide_mini')" title="收起">✕</button>
</div>
<div class="sbox"><input id="q" autofocus autocomplete="off" spellcheck="false"
  placeholder="关键词 / 拼音 / 编号，回车定位…"></div>
<div id="list"></div>
<div id="empty">没有匹配的项目</div>
<div class="ft">↑↓ 选择 · Enter 定位 · 点击 🚀 启动 · 失焦自动收起</div>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let cur=[],sel=-1;

function render(){
  const box=$("#list");
  $("#empty").style.display=cur.length?"none":"block";
  box.innerHTML=cur.map((it,i)=>`<div class="it ${i===sel?"sel":""}" data-i="${i}">
    <span class="badge" style="background:${it.type_color}22;color:${it.type_color}">${esc(it.type_label)}</span>
    <span class="nm" title="${esc(it.path)}">${esc(it.name)}</span>
    <span class="ag"><i style="background:${esc(it.agent_color)}"></i>${esc(it.agent)}</span>
    <button class="go" data-i="${i}">🚀</button>
  </div>`).join("");
  box.querySelectorAll(".it").forEach(el=>el.onclick=e=>{
    if(e.target.classList.contains("go")) return;
    act("open",+el.dataset.i);
  });
  box.querySelectorAll(".go").forEach(b=>b.onclick=e=>{
    e.stopPropagation();act("launch",+b.dataset.i);
  });
}
async function search(){
  const q=$("#q").value.trim();
  const r=await fetch("/api/search?q="+encodeURIComponent(q)+"&agent=all&type=all");
  const d=await r.json();
  cur=d.results.slice(0,15).map(x=>x.item);
  sel=-1;render();
}
async function act(kind,i){
  const it=cur[i];if(!it)return;
  await fetch((kind==="open"?"/api/open":"/api/launch")+"?path="+encodeURIComponent(it.path));
  if(kind==="launch") fetch("/api/hide_mini");
}
$("#q").addEventListener("input",()=>{clearTimeout($("#q")._h);$("#q")._h=setTimeout(search,110);});
$("#q").addEventListener("keydown",e=>{
  if(e.key==="ArrowDown"){e.preventDefault();sel=Math.min(sel+1,cur.length-1);render();}
  else if(e.key==="ArrowUp"){e.preventDefault();sel=Math.max(sel-1,-1);render();}
  else if(e.key==="Enter"){if(sel<0&&cur.length)sel=0;act("open",sel);}
  else if(e.key==="Escape"){fetch("/api/hide_mini");}
});
window.onblur=()=>fetch("/api/hide_mini");
search();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默，日志走 log()

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            path = u.path
            if path == "/":
                self._send(200, HTML_PAGE, "text/html; charset=utf-8")
            elif path == "/mini":
                self._send(200, MINI_PAGE, "text/html; charset=utf-8")
            elif path == "/api/hide_mini":
                gui_hide_mini()
                self._json({"ok": True})
            elif path == "/favicon.ico":
                fp = os.path.join(BASE_DIR, "radar.ico")
                if os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        self._send(200, f.read(), "image/x-icon")
                else:
                    self._json({"ok": False}, 404)
            elif path == "/api/show":
                ok = gui_show_window()
                self._json({"ok": True, "message": "窗口已唤出" if ok else "服务运行中（无窗口模式）"})
            elif path == "/api/status":
                # 索引未就绪时立即返回，不阻塞（前端轮询等 ready）
                if INDEX.get("built_at", 0) == 0:
                    ws_meta = [
                        {"root": w["root"], "agent": w["agent"],
                         "color": w.get("color", "#94a3b8"), "app": w.get("app", ""),
                         "registered": True}
                        for w in discover_workspaces()
                    ]
                    self._json({"ok": True, "app": "Project Radar",
                                "port": CFG["port"], "ready": False,
                                "built_at": 0, "total": 0,
                                "workspaces": ws_meta, "has_pinyin": HAS_PINYIN})
                else:
                    idx = INDEX
                    self._json({
                        "ok": True, "app": "Project Radar", "port": CFG["port"],
                        "ready": True,
                        "built_at": idx.get("built_at", 0),
                        "total": len(idx.get("items", [])),
                        "workspaces": idx.get("workspaces", []),
                        "has_pinyin": HAS_PINYIN,
                    })
            elif path == "/api/projects":
                idx = get_index(force=q.get("refresh") == "1")
                self._json({"ok": True, "built_at": idx["built_at"],
                            "items": idx["items"]})
            elif path == "/api/search":
                results = search_items(q.get("q", ""),
                                       q.get("agent", "all"), q.get("type", "all"))
                self._json({"ok": True, "total": len(results), "results": results})
            elif path == "/api/open":
                ok, msg = do_open_dir(q.get("path", ""))
                self._json({"ok": ok, "message": msg})
            elif path == "/api/open_file":
                ok, msg = do_open_file(q.get("path", ""))
                self._json({"ok": ok, "message": msg})
            elif path == "/api/launch":
                ok, msg = do_launch(q.get("path", ""))
                self._json({"ok": ok, "message": msg})
            elif path == "/api/quit":
                self._json({"ok": True, "message": "正在退出"})
                threading.Timer(0.3, gui_quit).start()
            else:
                self._json({"ok": False, "message": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:
            log("API 错误: %r" % e)
            try:
                self._json({"ok": False, "message": str(e)}, 500)
            except Exception:
                pass


def main():
    args = sys.argv[1:]
    port = CFG.get("port", 8618)
    console = "--console" in args
    no_window = "--no-window" in args or "--no-browser" in args  # 兼容旧参数
    if "--port" in args:
        try:
            port = int(args[args.index("--port") + 1])
        except (ValueError, IndexError):
            pass
    if console:
        try:
            os.remove(LOG_PATH)
        except OSError:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    log("项目雷达已启动: %s" % url)

    # 启动即预热索引（pythonw 下首次构建较慢，别让首个请求干等）
    threading.Thread(target=get_index, daemon=True).start()

    if no_window:
        # 纯服务模式：无窗口，可选打开默认浏览器（供排错 / 脚本场景）
        if "--no-browser" not in args:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        # 默认：原生窗口 + 任务栏托盘（关闭窗口 = 缩到托盘）
        gui_run(server)


if __name__ == "__main__":
    load_config()
    main()
