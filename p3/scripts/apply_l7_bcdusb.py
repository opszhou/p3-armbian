#!/usr/bin/env python3
r"""L7: let the rockusb gadget enumerate as LOADER (bcdUSB = 0x0201).

Rockchip tools classify MASKROM vs LOADER by (bcdUSB & 0x1)
(rkdeveloptool RKScan.cpp:395). board.c:g_dnl_bind_fixup() already sets
0x0201 for usb_dnl_rockusb, but mainline composite.c overwrites it with
0x0200 on every GET_DESCRIPTOR(USB_DT_DEVICE). This patch preserves the
board-set value; all other gadgets (UMS, fastboot, ether) keep 0x0200.

Run inside the container at /root/p3builder.
"""
import shutil
from pathlib import Path

ROOT = Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10' / 'drivers' / 'usb' / 'gadget' / 'composite.c'
BAK = ROOT / 'base_l7'
BAK.mkdir(parents=True, exist_ok=True)
orig = BAK / 'composite.c.orig'
if not orig.exists():
    shutil.copy2(SRC, orig)
    print('  backed up ->', orig)

s = SRC.read_text(encoding='utf-8')
LINE = 'cdev->desc.bcdUSB = cpu_to_le16(0x0200);'
if 'P3_LOADER_BCDUSB' in s:
    print('  already patched, nothing to do')
    raise SystemExit(0)

idx = s.index(LINE)
indent = s[s.rfind('\n', 0, idx) + 1:idx]
if not indent.strip() == '':
    raise SystemExit('unexpected indentation: %r' % indent)

replacement = (
    indent + '/* P3_LOADER_BCDUSB: Rockchip tools classify MASKROM vs LOADER\n'
    + indent + ' * by bcdUSB bit 0 (rkdeveloptool RKScan.cpp:395).\n'
    + indent + ' * g_dnl_bind_fixup() sets 0x0201 for usb_dnl_rockusb;\n'
    + indent + ' * keep it instead of forcing the standard 0x0200.\n'
    + indent + ' * Other gadgets (UMS/fastboot/ether) stay at 0x0200.\n'
    + indent + ' */\n'
    + indent + 'if (cdev->desc.bcdUSB != cpu_to_le16(0x0201))\n'
    + indent + '\t' + LINE
)
s = s.replace(indent + LINE, replacement, 1)
SRC.write_text(s, encoding='utf-8', newline='')
print('  patched:', SRC)
print('  occurrences of 0x0201 guard:', s.count('P3_LOADER_BCDUSB'))
