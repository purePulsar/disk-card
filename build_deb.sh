#!/usr/bin/env bash
# 把 disk-card 打包成 .deb，方便装到别的电脑。
#
#   用法:  ./build_deb.sh
#   产物:  dist/disk-card_<版本>_all.deb
#
# 装到别的电脑:  sudo apt install ./dist/disk-card_*.deb
# （用 apt 而不是 dpkg，会自动装上 Depends 里列的依赖）
#
# 版本号只在 packaging/control 里改一处，这里自动读取。
set -euo pipefail

PKG=disk-card
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(awk '/^Version:/{print $2; exit}' "$HERE/packaging/control")"
ARCH="$(awk '/^Architecture:/{print $2; exit}' "$HERE/packaging/control")"

[ -n "$VERSION" ] || { echo "读不到 packaging/control 里的版本号" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# 程序本体（安装位置与脚本里的 ~/.config 路径无关，可任意换）
install -Dm755 "$HERE/disk_viewer.py"              "$STAGE/usr/share/$PKG/disk_viewer.py"
install -Dm755 "$HERE/disk_tray.py"                "$STAGE/usr/share/$PKG/disk_tray.py"
install -Dm644 "$HERE/README.md"                   "$STAGE/usr/share/doc/$PKG/README.md"

# 应用菜单项（手动启动/重启）
install -Dm644 "$HERE/packaging/disk-card.desktop"      "$STAGE/usr/share/applications/disk-card.desktop"
install -Dm644 "$HERE/packaging/disk-card-tray.desktop" "$STAGE/usr/share/applications/disk-card-tray.desktop"

# 登录自启（对所有用户生效）
install -Dm644 "$HERE/packaging/autostart/disk-card.desktop"      "$STAGE/etc/xdg/autostart/disk-card.desktop"
install -Dm644 "$HERE/packaging/autostart/disk-card-tray.desktop" "$STAGE/etc/xdg/autostart/disk-card-tray.desktop"

install -Dm644 "$HERE/packaging/control" "$STAGE/DEBIAN/control"

mkdir -p "$HERE/dist"
OUT="$HERE/dist/${PKG}_${VERSION}_${ARCH}.deb"
# --root-owner-group: 文件归 root 所有，不需要 fakeroot
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"

echo
echo "已生成: $OUT"
echo
dpkg-deb --info "$OUT"
echo "包内文件:"
dpkg-deb --contents "$OUT" | awk '{print "  " $6}'
