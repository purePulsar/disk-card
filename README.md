# 磁盘占用悬浮卡片

桌面常驻的小卡片，逐行显示各磁盘分区的占用率；面板上的托盘图标用来调整卡片外观。

```
┌──────────────────────────────┐
│ 磁盘占用              12:53  │
│                              │
│ 系统盘 (/)            ████ 94%│
│ /dev/nvme1n1p2 · ext4 103G/116G│
│                              │
│ /mnt/A8DA5126DA50F1D4  ███ 79%│
│ ...                          │
└──────────────────────────────┘
```

## 文件说明

| 文件 | 作用 |
|------|------|
| `disk_viewer.py` | 卡片本体：读分区、画占用条、处理拖动 |
| `disk_tray.py` | 托盘图标：置顶 / 透明度 / 可移动 三个开关 |

两个程序**互相独立**，通过设置文件通信，谁先启动都没关系：

```
disk_tray.py ──写──> ~/.config/disk-card/settings.json ──每 0.8s 读──> disk_viewer.py
```

托盘退出不影响卡片；卡片自己的退出在它右键菜单里。

## 运行

```bash
python3 disk_viewer.py    # 卡片
python3 disk_tray.py      # 托盘（需要下面的依赖）
```

开机自启已配置好，见 `~/.config/autostart/disk-card.desktop` 与 `disk-card-tray.desktop`。

## 打包成 .deb（装到别的电脑）

```bash
./build_deb.sh                          # 产物在 dist/disk-card_<版本>_all.deb
sudo apt install ./dist/disk-card_*.deb # 用 apt 装，会自动拉依赖；dpkg -i 不会
```

从 GitHub 克隆下来的 `build_deb.sh` 可能没有执行权限，这时用 `bash build_deb.sh` 运行即可。

装完后（无需重启）：

| 安装到 | 内容 |
|--------|------|
| `/usr/share/disk-card/` | 两个脚本本体 |
| `/usr/share/applications/` | 应用菜单项，可手动启动 |
| `/etc/xdg/autostart/` | 登录自启，**所有用户**都生效 |

依赖写在 `packaging/control` 里：硬依赖 `python3-tk`、`python3-gi`、`gir1.2-gtk-3.0`；`Recommends` 是托盘需要的 `gir1.2-ayatanaappindicator3-0.1` 和 `gnome-shell-extension-zorin-appindicator`（Zorin 专用，所以在别的发行版上装不上也不该让安装失败）。

改版本号只需改 `packaging/control` 里的 `Version:`，打包脚本会自动读取。

卸载：`sudo apt remove disk-card`。用户各自的 `~/.config/disk-card/` 不会被删。

> 注意：本机现在用的是 `~/.config/autostart/` 里的自启项。装了 deb 后会多出 `/etc/xdg/autostart/` 那两份，**同一台机器两处都有就会启动两次**。在本机装完 deb 记得删掉 `~/.config/autostart/disk-card*.desktop`；新电脑直接装 deb 则不存在这个问题。

## 托盘菜单

| 菜单项 | 说明 |
|--------|------|
| 置顶 | 勾选时压在其它窗口之上；取消后回到普通图层，会被窗口遮挡 |
| 可移动 | 取消后卡片锁定位置，鼠标指针变成箭头 |
| 透明度 ▸ | 50% / 70% / 85% / 95% / 100% |
| 退出托盘 | 只退出托盘，卡片继续运行 |

改动最多 0.8 秒后生效。卡片本身：按住任意位置拖动，右键菜单可刷新或退出。

## 运行时配置文件

| 路径 | 谁写 | 说明 |
|------|------|------|
| `~/.config/disk-card/settings.json` | 托盘写、卡片读 | 三项设置；删掉即恢复默认（置顶、95%、可移动） |
| `~/.config/disk-card/position.json` | 卡片写 | 拖动后记住位置，下次启动恢复 |

`settings.json` 采用「先写临时文件再改名」的方式，避免卡片读到写了一半的内容。

## 依赖

- `python3-tk`（tkinter）——系统已装
- 托盘需要 `gir1.2-ayatanaappindicator3-0.1`，并启用 `zorin-appindicator` 扩展：

  ```bash
  sudo apt install -y gir1.2-ayatanaappindicator3-0.1
  ```

- **不需要 psutil**：直接读 `/proc/mounts` 配合 `os.statvfs()`，算法与 `df` 一致

## 常见自定义

`disk_viewer.py` 顶部常量：

| 常量 | 含义 |
|------|------|
| `CARD_W` | 卡片宽度（像素） |
| `PAD` | 卡片四周留白 |
| `ROW_GAP` | 分区行之间的间距 |
| `CORNER_R` | 圆角半径 |
| `REFRESH_MS` | 自动刷新间隔 |
| `ALPHA` | 默认不透明度 |
| `BG_COLOR` / `FG_COLOR` / `DIM_COLOR` / `TRACK_COLOR` | 配色 |
| `bar_color()` | 占用率→颜色的映射（橙色系，≥90% 转红） |
| `SKIP_FSTYPES` | 忽略的文件系统类型 |

`disk_tray.py` 顶部：`ALPHA_CHOICES`（透明度档位）、`ICON_NAME`（托盘图标名）。

## 哪些分区会被显示

只显示挂载在 `/dev/` 下的真实分区，并跳过：

- `/boot`、`/boot/efi`、`/efi`（引导分区不算存储空间）
- `tmpfs`、`squashfs`、`overlay`、`nfs`、`cifs` 等虚拟/网络文件系统
- 同一设备重复挂载只显示一次

## 几个关键实现点

**为什么必须用 `-type dock`**
本机是 Zorin（GNOME 46）Wayland 会话。窗口若设成 `overrideredirect(True)`，它会变成「超覆重定向」窗口，窗口管理器根本不管它，`-topmost` 就完全失效——卡片会被别的窗口盖住。正确做法是保持受管理状态，再用：

```python
root.attributes("-type", "dock")     # 无边框，且停在 dock 图层（置顶）
root.attributes("-topmost", True)
```

实测这样窗口偏移为 0（没有标题栏），且 `_NET_WM_STATE_ABOVE` 被 Mutter 认可。
反之 `_MOTIF_WM_HINTS` 和直接用 xprop 写 `_NET_WM_WINDOW_TYPE_DOCK` 都会被 Mutter 忽略，只有 Tk 自带的 `-type` 生效。

**取消置顶时为什么换成 `splash` 而不是 `normal`**
Mutter 按窗口类型决定图层，类型为 `dock` 时永远待在 dock 图层。所以取消置顶必须换类型，否则卡片照样压着别的窗口。但**不能**换成 `normal`——`normal` 是「带装饰」的类型，Mutter 会给它补上标题栏（曾经就是这么写的，结果一取消置顶就冒出标题栏）。
`splash` 同样无边框，图层却是普通窗口，正好满足「不置顶、也不出标题栏」。

**圆角**
用 ctypes 直接调 `libX11` / `libXext` 的 Shape 扩展裁出圆角，不需要额外依赖。

**两个程序为什么不合并**
托盘用 GTK 主循环，卡片用 Tk 主循环。合并就要在一个进程里跑两套事件循环，容易出线程问题；拆开用文件通信简单可靠，代价是 0.8 秒的延迟。
