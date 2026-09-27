# -*- coding: utf-8 -*-
"""搜索质量自测：跑一组典型查询，断言期望项目出现在结果前列。"""
import json
import urllib.request
import urllib.parse

BASE = "http://127.0.0.1:8618"


def search(q, agent="all", typ="all"):
    url = "%s/api/search?q=%s&agent=%s&type=%s" % (
        BASE, urllib.parse.quote(q), urllib.parse.quote(agent), typ)
    with urllib.request.urlopen(url) as r:
        return json.load(r)["results"]


# (查询, 期望命中的项目名关键词, 应出现在前 N 名)
CASES = [
    ("电费", "sgcc电费监控", 3),          # 中文子串
    ("guancai", "棺材", 3),               # 拼音全拼
    ("dfjk", "sgcc电费监控", 5),          # 拼音首字母
    ("013", "我在yfy想下班", 3),          # 编号
    ("小说 pdf", "小说PDF转图片", 3),     # 多关键词 AND（跨名称+文件索引）
    ("pwmx", "PowerMax", 3),              # 名称子序列
    ("0927", "2026-09-27", 5),            # 紧凑日期数字
    ("codex 桌面宠物", "codex-desktop-pet", 3),  # agent 词 + 英文关键词
    ("StartupCleanup", "StartupCleanup", 1),     # 完整英文名
    ("雷达", "项目雷达", 3),              # 拼音目录自举（本工具若已被索引）
    ("宠物", "desktop-pet", 3),           # 中文词命中英文项目（经 README/摘要索引）
    ("VD", "DEV-2026-010-ds-vision-skill", 8),  # 英文缩写子序列
]

fails = 0
for q, expect, topn in CASES:
    res = search(q)
    names = [r["item"]["name"] for r in res[:topn]]
    hit = any(expect.lower() in n.lower() for n in names)
    status = "PASS" if hit else "FAIL"
    if not hit:
        fails += 1
    print("%s  q=%-16r top%d=%s" % (status, q, topn, names[:4]))
    if not hit:
        allnames = [r["item"]["name"] for r in res[:10]]
        print("      全部结果: %s" % allnames)
print("\n%d/%d 通过" % (len(CASES) - fails, len(CASES)))
