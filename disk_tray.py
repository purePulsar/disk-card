#!/usr/bin/env python3
"""磁盘占用卡片 —— 托盘设置入口

在 GNOME 面板（Zorin AppIndicators 扩展）提供一个托盘图标，用来调整卡片：
  1. 是否置顶
  2. 透明度
  3. 是否可移动

本程序只负责写设置文件，卡片每 0.8 秒读一次，所以改完立刻生效。
两个程序互相独立：托盘退出不影响卡片，卡片的退出仍在它自己的右键菜单里。
运行: python3 disk_tray.py
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk                                    # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ValueError, ImportError) as exc:
    sys.exit("缺少 AyatanaAppIndicator3，请先安装托盘库：\n"
             "    sudo apt install -y gir1.2-ayatanaappindicator3-0.1\n"
             f"（{exc}）")

APP_ID = "disk-card"
ICON_NAME = "drive-harddisk"
SETTINGS_PATH = os.path.expanduser("~/.config/disk-card/settings.json")

# 透明度可选值（菜单里是单选）
ALPHA_CHOICES = [("50%", 0.5), ("70%", 0.7), ("85%", 0.85),
                 ("95%", 0.95), ("100%", 1.0)]
DEFAULT_SETTINGS = {"topmost": True, "alpha": 0.95, "movable": True}


def load_settings():
    """读取现有设置；缺失或损坏时回退到默认值。"""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("内容不是 JSON 对象")
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError) as exc:
        print(f"[disk-card] 设置读取失败，用默认值: {exc}", file=sys.stderr)
        return dict(DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    for key in ("topmost", "movable"):
        if key in raw:
            settings[key] = bool(raw[key])
    try:
        settings["alpha"] = min(1.0, max(0.2, float(raw["alpha"])))
    except (KeyError, TypeError, ValueError):
        pass
    return settings


def save_settings(settings):
    """原子写入，避免卡片读到写了一半的文件。"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except OSError as exc:
        # 失败要看得见：否则用户以为设置生效了，其实没有
        print(f"[disk-card] 设置保存失败: {exc}", file=sys.stderr)


class TrayApp:
    def __init__(self):
        self.settings = load_settings()
        save_settings(self.settings)      # 首次运行时落下默认值，卡片才有文件可读

        menu = Gtk.Menu()

        self.item_top = Gtk.CheckMenuItem(label="置顶")
        self.item_top.set_active(self.settings["topmost"])
        self.item_top.connect("toggled", self._on_topmost)
        menu.append(self.item_top)

        self.item_move = Gtk.CheckMenuItem(label="可移动")
        self.item_move.set_active(self.settings["movable"])
        self.item_move.connect("toggled", self._on_movable)
        menu.append(self.item_move)

        menu.append(self._build_alpha_menu())
        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="退出托盘")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        menu.append(quit_item)

        menu.show_all()

        self.indicator = AppIndicator.Indicator.new(
            APP_ID, ICON_NAME,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("磁盘占用卡片")
        self.indicator.set_menu(menu)

    def _build_alpha_menu(self):
        """透明度子菜单：单选，默认选中与当前值最接近的那项。"""
        submenu = Gtk.Menu()
        items = []
        group = None
        for label, _ in ALPHA_CHOICES:
            item = Gtk.RadioMenuItem(label=label)
            if group is None:
                group = item
            else:
                item.join_group(group)
            submenu.append(item)
            items.append(item)

        # 先把选中的项定下来，再连信号，免得初始化时误写文件
        current = self.settings["alpha"]
        closest = min(range(len(ALPHA_CHOICES)),
                      key=lambda i: abs(ALPHA_CHOICES[i][1] - current))
        items[closest].set_active(True)
        for item, (_, value) in zip(items, ALPHA_CHOICES):
            item.connect("toggled", self._on_alpha, value)
        submenu.show_all()

        top = Gtk.MenuItem(label="透明度")
        top.set_submenu(submenu)
        return top

    # ---------- 菜单回调 ----------
    def _update(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)

    def _on_topmost(self, item):
        self._update("topmost", item.get_active())

    def _on_movable(self, item):
        self._update("movable", item.get_active())

    def _on_alpha(self, item, value):
        if item.get_active():      # 单选组里每次会触发两次，只认被选中的那次
            self._update("alpha", value)


def main():
    TrayApp()
    Gtk.main()


if __name__ == "__main__":
    main()
