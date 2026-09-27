# -*- coding: utf-8 -*-
"""生成项目雷达图标 radar.ico（多尺寸）+ 托盘用 PNG。

风格与前端 UI 一致：深紫蓝渐变圆角方形 + 白色同心环 + 亮紫扫描扇形 + 粉红目标点。
半透明元素一律画在独立 overlay 层再 alpha_composite 合成：
Draw 的 "RGBA" 混合模式会破坏目标 alpha 通道，paste 是像素替换，都不能用。
"""
from PIL import Image, ImageDraw
import math
import os

BASE = os.path.dirname(os.path.abspath(__file__))
S = 256

# ---------- 背景层：对角渐变 + 圆角矩形 ----------
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
c1 = (105, 118, 255)   # 左上 #6976ff
c2 = (24, 28, 56)      # 右下 #181c38
gp = grad.load()
for y in range(S):
    for x in range(S):
        t = (x + y) / (2 * S - 2)
        gp[x, y] = (int(c1[0] + (c2[0] - c1[0]) * t),
                    int(c1[1] + (c2[1] - c1[1]) * t),
                    int(c1[2] + (c2[2] - c1[2]) * t), 255)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([8, 8, S - 8, S - 8], radius=56, fill=255)
bg.paste(grad, (0, 0), mask)

# ---------- overlay 层：所有半透明元素画在这里 ----------
ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(ov)  # 普通模式：透明层上直接写像素，无需混合

cx, cy = 128, 134
WHITE = (255, 255, 255)

# 扫描扇形：楔形 alpha 从前沿到尾部递减（右上方向）
start_deg, end_deg = -78, -6
LAYERS = 14
for i in range(LAYERS):
    a0 = start_deg + (end_deg - start_deg) * i / LAYERS
    a1 = a0 + (end_deg - start_deg) / LAYERS
    alpha = int(26 + 168 * (1 - i / LAYERS) ** 1.2)
    d.pieslice([cx - 84, cy - 84, cx + 84, cy + 84], a0, a1,
               fill=(178, 190, 255, alpha))

# 十字准线（画在环下面）
d.line([cx - 84, cy, cx - 62, cy], fill=WHITE + (130,), width=4)
d.line([cx + 62, cy, cx + 84, cy], fill=WHITE + (130,), width=4)
d.line([cx, cy - 84, cx, cy - 62], fill=WHITE + (130,), width=4)
d.line([cx, cy + 62, cx, cy + 84], fill=WHITE + (130,), width=4)

# 同心环
d.arc([cx - 84, cy - 84, cx + 84, cy + 84], 0, 360, fill=WHITE + (215,), width=7)
d.arc([cx - 56, cy - 56, cx + 56, cy + 56], 0, 360, fill=WHITE + (150,), width=5)
d.arc([cx - 30, cy - 30, cx + 30, cy + 30], 0, 360, fill=WHITE + (100,), width=4)

# 目标点（扇形前沿，右上）：光晕 + 核心
tx = cx + int(64 * math.cos(math.radians(-40)))
ty = cy + int(64 * math.sin(math.radians(-40)))
d.ellipse([tx - 26, ty - 26, tx + 26, ty + 26], fill=(255, 107, 129, 52))
d.ellipse([tx - 17, ty - 17, tx + 17, ty + 17], fill=(255, 107, 129, 100))
d.ellipse([tx - 10, ty - 10, tx + 10, ty + 10], fill=(255, 96, 120, 255))
d.ellipse([tx - 4, ty - 4, tx + 4, ty + 4], fill=(255, 255, 255, 255))

# 中心点
d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=WHITE + (235,))

# ---------- 顶部内高光（独立层） ----------
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
hd = ImageDraw.Draw(hl)
for i in range(64):
    a = int(30 * (1 - i / 64))
    hd.line([(8, 8 + i), (S - 8, 8 + i)], fill=(255, 255, 255, a))

# ---------- 合成（背景 → 高光 → 元素） ----------
img = Image.alpha_composite(bg, hl)
img = Image.alpha_composite(img, ov)

# ---------- 输出 ----------
img.save(os.path.join(BASE, "radar_tray.png"))
img.save(os.path.join(BASE, "radar.ico"),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save(os.path.join(BASE, "radar_preview.png"))
print("icon generated:", os.path.join(BASE, "radar.ico"))
