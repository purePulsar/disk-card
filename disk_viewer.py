#!/usr/bin/env python3
"""磁盘占用悬浮卡片 —— 桌面常驻，一眼看清各分区的占用率。

- 无边框、始终置顶（窗口类型 dock + _NET_WM_STATE_ABOVE）
- 按住卡片任意位置即可拖动；退出时记住位置，下次启动恢复
- 右键 → 立即刷新 / 退出
- 每 5 秒自动刷新
运行: python3 disk_viewer.py
"""

import ctypes
import json
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

# 忽略的文件系统类型（snap 只读卷等；本地 NTFS/exFAT 盘以 fuseblk 挂载，需要显示）
SKIP_FSTYPES = {"squashfs", "overlay", "nfs", "nfs4", "cifs", "tmpfs"}

CARD_W = 320              # 卡片宽度
PAD = 16                  # 卡片内边距
ROW_GAP = 5               # 分区行之间留白
CORNER_R = 14             # 圆角半径
REFRESH_MS = 5000         # 自动刷新间隔（毫秒）
STATE_PATH = os.path.expanduser("~/.config/disk-card/position.json")
SETTINGS_PATH = os.path.expanduser("~/.config/disk-card/settings.json")
SETTINGS_POLL_MS = 800    # 检查托盘是否改了设置的间隔（毫秒）
ALPHA = 0.95              # 卡片整体不透明度（默认值）

# 由托盘程序写入、本程序读取；托盘不在时用这套默认值
DEFAULT_SETTINGS = {"topmost": True, "alpha": ALPHA, "movable": True}

# 占用率配色：以橙色为主（<75），紧张时转深橙、告急转红
def bar_color(pct):
    if pct < 75:
        return "#ff8c00"
    if pct < 90:
        return "#ff5e00"
    return "#e01b24"

BG_COLOR = "#1c1d21"
FG_COLOR = "#e8e8ea"
DIM_COLOR = "#8b8d94"
TRACK_COLOR = "#33353c"

# ---------- X11 圆角遮罩（ctypes 直调 libX11/libXext，无需额外依赖） ----------
try:
    _x11 = ctypes.CDLL("libX11.so.6")
    _xext = ctypes.CDLL("libXext.so.6")
except OSError:
    _x11 = _xext = None

_SHAPE_BOUNDING, _SHAPE_INPUT = 0, 1
_SHAPE_SET = 8
_GXCOPY = 3

# 防止个别 X 调用出错直接杀死进程（Xlib 默认 handler 会 abort）
_X_ERROR_IGNORE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(
    lambda d, e: None)
if _x11:
    _x11.XSetErrorHandler(_X_ERROR_IGNORE)


def _c_types(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = list(argtypes)


if _x11:
    _c_types(_x11.XOpenDisplay, ctypes.c_void_p, ctypes.c_char_p)
    _c_types(_x11.XCloseDisplay, ctypes.c_int, ctypes.c_void_p)
    _c_types(_x11.XCreatePixmap, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
             ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
    _c_types(_x11.XFreePixmap, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
    _c_types(_x11.XCreateGC, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
             ctypes.c_ulong, ctypes.c_void_p)
    _c_types(_x11.XFreeGC, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    _c_types(_x11.XSetFunction, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
    _c_types(_x11.XSetForeground, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    _c_types(_x11.XFillRectangle, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
             ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint)
    _c_types(_x11.XFillArc, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
             ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int)
    _c_types(_x11.XFlush, ctypes.c_int, ctypes.c_void_p)
    _c_types(_xext.XShapeCombineMask, None, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
             ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int)


def apply_round_shape(win_id, w, h, r):
    """把 X 窗口裁剪成圆角矩形。失败时静默返回 False（保持直角）。"""
    if not _x11 or w < 2 or h < 2:
        return False
    r = max(1, min(r, w // 2, h // 2))
    d = _x11.XOpenDisplay(None)
    if not d:
        return False
    try:
        pm = _x11.XCreatePixmap(d, win_id, w, h, 1)      # 1 位遮罩图
        gc = _x11.XCreateGC(d, pm, 0, None)
        _x11.XSetFunction(d, gc, _GXCOPY)
        _x11.XSetForeground(d, gc, 0)
        _x11.XFillRectangle(d, pm, gc, 0, 0, w, h)        # 全清为“不可见”
        _x11.XSetForeground(d, gc, 1)                     # 之后画的都是“可见”
        _x11.XFillRectangle(d, pm, gc, 0, r, w, h - 2 * r)          # 中央横带
        _x11.XFillRectangle(d, pm, gc, r, 0, w - 2 * r, h)          # 中央纵带
        for cx, cy in ((0, 0), (w - 2 * r, 0), (0, h - 2 * r), (w - 2 * r, h - 2 * r)):
            _x11.XFillArc(d, pm, gc, cx, cy, 2 * r, 2 * r, 0, 360 * 64)  # 四角圆弧
        _xext.XShapeCombineMask(d, win_id, _SHAPE_BOUNDING, 0, 0, pm, _SHAPE_SET)
        _xext.XShapeCombineMask(d, win_id, _SHAPE_INPUT, 0, 0, pm, _SHAPE_SET)
        _x11.XFreePixmap(d, pm)
        _x11.XFreeGC(d, gc)
        _x11.XFlush(d)
        return True
    finally:
        _x11.XCloseDisplay(d)


def human_size(nbytes):
    """把字节数格式化成 df -h 风格的字符串，如 117G、6.2M"""
    units = ["B", "K", "M", "G", "T", "P"]
    v = float(nbytes)
    for u in units:
        if v < 1024 or u == units[-1]:
            if v >= 10 or u == "B":
                return f"{v:.0f}{u}"
            return f"{v:.1f}{u}"
        v /= 1024
    return f"{nbytes}B"


def read_partitions():
    """从 /proc/mounts 读取真实磁盘分区的用量，返回字典列表。

    算法与 df 一致：已用 = blocks - bfree，百分比按 已用/(已用+可用) 计算。
    """
    seen_dev = set()
    parts = []
    with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
        for line in f:
            fields = line.split()
            if len(fields) < 3:
                continue
            dev, mnt, fstype = fields[0], fields[1], fields[2]
            mnt = mnt.replace("\\040", " ")  # /proc/mounts 里空格转义为 \040
            if not dev.startswith("/dev/"):
                continue  # 跳过 tmpfs 等虚拟文件系统
            if fstype in SKIP_FSTYPES:
                continue
            if mnt in ("/boot", "/boot/efi", "/efi"):
                continue  # 引导分区不算“存储空间”，不显示
            if dev in seen_dev:
                continue  # 同一设备重复挂载只显示一次
            try:
                st = os.statvfs(mnt)
            except OSError:
                continue
            total = st.f_frsize * st.f_blocks
            if total == 0:
                continue
            used = st.f_frsize * (st.f_blocks - st.f_bfree)
            avail = st.f_frsize * st.f_bavail
            denom = used + avail
            pct = round(used * 100 / denom) if denom else 0
            seen_dev.add(dev)
            parts.append({
                "device": dev,
                "mount": mnt,
                "fstype": fstype,
                "total": total,
                "used": used,
                "avail": avail,
                "pct": pct,
            })
    return parts


def pick_font(root):
    """选一个能正常显示中文的字体，避免方块字。"""
    fams = set(tkfont.families(root))
    for cand in ("Noto Sans CJK SC", "Source Han Sans SC", "Noto Sans SC",
                 "Noto Sans CJK HK", "WenQuanYi Micro Hei", "微软雅黑",
                 "Microsoft YaHei", "DejaVu Sans", "Sans"):
        if cand in fams:
            return cand
    return "Sans"


class DiskCardApp:
    def __init__(self, root):
        self.root = root
        self.parts = []
        self._mounts = []          # 上次绘制时的挂载点顺序，用于判断是否需要重建
        self._rows = {}            # 挂载点 -> 该行控件
        self._shape = (0, 0)
        self._drag_widgets = []    # 绑定了拖动事件的控件，用于切换鼠标指针样式
        self._font = pick_font(root)
        self._settings = self._read_settings()
        self._settings_mtime = None

        root.overrideredirect(False)          # 必须保持“受窗口管理器管理”，否则置顶会失效
        root.title("磁盘占用")
        root.configure(bg=BG_COLOR)
        self._apply_settings(reshaping=False)

        self._build()
        root.update_idletasks()                     # 先让控件完成布局，reqheight 才准确
        root.geometry(f"{CARD_W}x{root.winfo_reqheight()}{self._start_pos()}")
        root.bind("<Configure>", self._reshape)
        root.protocol("WM_DELETE_WINDOW", self._quit)

        self.refresh()
        root.after(REFRESH_MS, self._tick)
        self._poll_settings()

    # ---------- 位置记忆 ----------
    def _start_pos(self):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                d = json.load(f)
            return f"+{int(d['x'])}+{int(d['y'])}"
        except (OSError, ValueError, KeyError, TypeError):
            pass  # 首次运行或状态文件损坏 → 用默认位置
        sw = self.root.winfo_screenwidth()
        return f"+{sw - CARD_W - 16}+24"      # 默认右上角

    def _save_pos(self):
        try:
            os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
        except OSError as e:
            print(f"[disk-card] 位置保存失败: {e}", file=sys.stderr)

    # ---------- 托盘设置（置顶 / 透明度 / 可移动） ----------
    def _read_settings(self):
        """读取托盘写入的设置；文件不存在或损坏时回退到默认值。"""
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("内容不是 JSON 对象")
        except FileNotFoundError:
            return dict(DEFAULT_SETTINGS)      # 还没装托盘，用默认值
        except (OSError, ValueError) as e:
            print(f"[disk-card] 设置读取失败，用默认值: {e}", file=sys.stderr)
            return dict(DEFAULT_SETTINGS)

        s = dict(DEFAULT_SETTINGS)
        for key in ("topmost", "movable"):
            if key in raw:
                s[key] = bool(raw[key])
        try:
            s["alpha"] = min(1.0, max(0.2, float(raw["alpha"])))
        except (KeyError, TypeError, ValueError):
            pass
        return s

    def _poll_settings(self):
        """轮询设置文件；托盘一改，卡片最多 0.8 秒内生效。"""
        try:
            mtime = os.stat(SETTINGS_PATH).st_mtime
        except OSError:
            mtime = None
        if mtime != self._settings_mtime:
            self._settings_mtime = mtime
            new = self._read_settings()
            if new != self._settings:
                self._settings = new
                self._apply_settings()
        self.root.after(SETTINGS_POLL_MS, self._poll_settings)

    def _apply_settings(self, reshaping=True):
        s = self._settings
        try:
            self.root.attributes("-topmost", s["topmost"])
            # 置顶靠 dock 窗口类型：无边框，且停在 dock 图层。
            # 取消置顶必须换类型，否则仍留在 dock 层、压不住其它窗口；
            # 但**不能**用 normal —— 那是「带装饰」的类型，Mutter 会补上标题栏。
            # splash 同为无边框，且归属普通图层，正好满足「不置顶也不出标题栏」。
            self.root.attributes("-type", "dock" if s["topmost"] else "splash")
            self.root.attributes("-alpha", s["alpha"])
        except tk.TclError as e:
            print(f"[disk-card] 应用设置失败: {e}", file=sys.stderr)
        for w in self._drag_widgets:
            try:
                w.configure(cursor="fleur" if s["movable"] else "arrow")
            except tk.TclError:
                pass
        if reshaping:
            self.root.after(150, self._apply_shape)   # 窗口类型变了，圆角要重新裁一次

    # ---------- 界面 ----------
    def _build(self):
        f_title = (self._font, 11, "bold")
        f_name = (self._font, 10)
        f_dim = (self._font, 8)
        f_pct = (self._font, 13, "bold")
        self._fonts = (f_name, f_dim, f_pct)

        # 上下留白保持一致，卡片下沿才不会空出一块
        head = tk.Frame(self.root, bg=BG_COLOR)
        head.pack(fill="x", padx=PAD, pady=(PAD - 2, 4))
        tk.Label(head, text="磁盘占用", font=f_title, bg=BG_COLOR,
                 fg=FG_COLOR, bd=0).pack(side="left")
        self.time_lbl = tk.Label(head, text="", font=f_dim, bg=BG_COLOR,
                                 fg=DIM_COLOR, bd=0)
        self.time_lbl.pack(side="right")

        self.body = tk.Frame(self.root, bg=BG_COLOR)
        self.body.pack(fill="x", padx=PAD, pady=(0, PAD - 2))

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="立即刷新", command=self.refresh)
        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        self._menu = menu

        # 整张卡片都能拖动、都能右键
        self._bind_drag(self.root)
        self._bind_drag(head)
        self._bind_drag(self.body)
        self._bind_drag(self.time_lbl)

    def _bind_drag(self, w):
        w.bind("<Button-1>", self._drag_start)
        w.bind("<B1-Motion>", self._drag_move)
        w.bind("<ButtonRelease-1>", lambda e: self._save_pos())
        w.bind("<Button-3>", lambda e: self._menu.tk_popup(e.x_root, e.y_root))
        w.configure(cursor="fleur" if self._settings["movable"] else "arrow")
        self._drag_widgets.append(w)

    def _drag_start(self, e):
        if not self._settings["movable"]:
            return
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        if not self._settings["movable"]:
            return
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _reshape(self, e):
        if e.widget is self.root:
            self._apply_shape()

    def _apply_shape(self):
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w > 1 and (w, h) != self._shape and apply_round_shape(
                self.root.winfo_id(), w, h, CORNER_R):
            self._shape = (w, h)

    def _quit(self):
        self._save_pos()
        self.root.destroy()

    # ---------- 数据刷新 ----------
    def _tick(self):
        self.refresh()
        self.root.after(REFRESH_MS, self._tick)

    def refresh(self):
        self.parts = read_partitions()
        # 占用率高的排前面，方便一眼看到紧张的盘
        self.parts.sort(key=lambda p: -p["pct"])
        mounts = [p["mount"] for p in self.parts]
        if mounts != self._mounts:
            self._rebuild()          # 分区数量/顺序变了，重画整张卡片
        else:
            self._update()           # 只是数值变化，就地更新，避免闪烁
        self.time_lbl.config(text=time.strftime("%H:%M:%S"))

    def _rebuild(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._rows = {}
        self._mounts = [p["mount"] for p in self.parts]

        if not self.parts:
            tk.Label(self.body, text="未发现可用的磁盘分区", font=self._fonts[0],
                     bg=BG_COLOR, fg=FG_COLOR, bd=0).pack(pady=12)
        for p in self.parts:
            self._rows[p["mount"]] = self._draw_row(p)
        rows = self.body.winfo_children()
        if rows:
            # 末行不再留底部间距，否则卡片下沿会空出一块
            rows[-1].pack_configure(pady=(0, 0))

        self.root.update_idletasks()                # 先布局，再按内容高度调整窗口
        self.root.geometry(f"{CARD_W}x{self.root.winfo_reqheight()}")
        self._apply_shape()

    def _draw_row(self, p):
        f_name, f_dim, f_pct = self._fonts
        row = tk.Frame(self.body, bg=BG_COLOR)
        row.pack(fill="x", pady=(0, ROW_GAP))     # 只在行下方留白，首行紧贴顶部
        row.columnconfigure(1, weight=1)

        # 左列：名称 + 设备
        left = tk.Frame(row, bg=BG_COLOR)
        left.grid(row=0, column=0, sticky="w", padx=(0, 12))
        name = p["mount"] if p["mount"] != "/" else "系统盘 (/)"
        tk.Label(left, text=name, font=f_name, bg=BG_COLOR,
                 fg=FG_COLOR, bd=0).pack(anchor="w")
        tk.Label(left, text=f"{p['device']} · {p['fstype']}", font=f_dim,
                 bg=BG_COLOR, fg=DIM_COLOR, bd=0).pack(anchor="w")

        # 中列：占用条（Canvas 手绘，方便控制颜色）
        canvas = tk.Canvas(row, height=14, bg=BG_COLOR, highlightthickness=0)
        canvas.grid(row=0, column=1, sticky="we", pady=4)
        canvas.bind("<Configure>", lambda e, c=canvas, p=p: self.draw_bar(c, p["pct"]))

        # 右列：百分比 + 已用/总量
        right = tk.Frame(row, bg=BG_COLOR)
        right.grid(row=0, column=2, sticky="e", padx=(12, 0))
        pct_lbl = tk.Label(right, text=f"{p['pct']}%", font=f_pct,
                           fg=bar_color(p["pct"]), bg=BG_COLOR, bd=0)
        pct_lbl.pack(anchor="e")
        info = tk.Label(right, text=f"{human_size(p['used'])} / {human_size(p['total'])}",
                        font=f_dim, bg=BG_COLOR, fg=DIM_COLOR, bd=0)
        info.pack(anchor="e")

        for w in (row, left, right, pct_lbl, info):
            self._bind_drag(w)
        return {"canvas": canvas, "pct": pct_lbl, "info": info}

    def _update(self):
        for p in self.parts:
            r = self._rows.get(p["mount"])
            if not r:
                continue
            r["pct"].config(text=f"{p['pct']}%", fg=bar_color(p["pct"]))
            r["info"].config(text=f"{human_size(p['used'])} / {human_size(p['total'])}")
            self.draw_bar(r["canvas"], p["pct"])

    def draw_bar(self, canvas, pct):
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if w < 2:
            return
        canvas.create_rectangle(0, 4, w, h - 4, fill=TRACK_COLOR, outline="", width=0)
        used_w = max(0, min(w, w * pct / 100))
        if used_w >= 1:
            canvas.create_rectangle(0, 4, used_w, h - 4, fill=bar_color(pct),
                                    outline="", width=0)


def main():
    root = tk.Tk()
    DiskCardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
