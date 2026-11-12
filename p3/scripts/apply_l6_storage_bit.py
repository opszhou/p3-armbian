#!/usr/bin/env python3
"""L6: fix READ_STORAGE (0x2B) bitmap so RKDevTool sees EMMC instead of FLASH.

Evidence: rkdeveloptool master main.cpp:59
    "ChangeStorage: cs [storage: 1=EMMC, 2=SD, 9=SPINOR]"
  RKComm.cpp RKU_ReadStorage() returns the index of the FIRST set bit as the
  storage id. So EMMC (id 1) must be bit 1 => value 2.
  L5 returned bit 0 (value 1) => id 0 => GUI reported "device reports FLASH".

Only cb_read_storage() changes. Everything else stays L5.
"""
import pathlib
import shutil

ROOT = pathlib.Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10'
OUT = ROOT / 'uboot-out'
BAK = ROOT / 'base_l5'
BAK.mkdir(exist_ok=True)

for n in ('idbloader.img', 'u-boot.itb', 'u-boot-rockchip.bin',
          'u-boot.dtb', '.config', 'u-boot'):
    p = OUT / n
    if p.exists():
        shutil.copy2(p, BAK / n)
print('backed up L5 outputs ->', BAK)

C = SRC / 'drivers/usb/gadget/f_rockusb.c'
shutil.copy2(C, BAK / 'f_rockusb.c.orig')

s = C.read_text()
assert 'L6_STORAGE_BIT' not in s, 'already patched'
old = '\tu32 bits = 1;\t/* bit 0 = eMMC */'
new = ('\t/* L6_STORAGE_BIT: rkdeveloptool main.cpp:59 says 1=EMMC, 2=SD,\n'
       '\t * 9=SPINOR; RKU_ReadStorage() takes the first set bit index.\n'
       '\t * EMMC id 1 => bit 1 => value 2. bit 0 (value 1) reads as FLASH.\n'
       '\t */\n'
       '\tu32 bits = 1u << 1;\t/* bit 1 = EMMC */')
assert old in s, 'storage bits anchor not found'
C.write_text(s.replace(old, new, 1))
print('  f_rockusb.c: bits 1 -> 1u<<1 (EMMC)')

# force rebuild of the object
for rel in ('drivers/usb/gadget/f_rockusb.o',
            'drivers/usb/gadget/built-in.a'):
    q = OUT / rel
    if q.exists():
        q.unlink()
print('removed stale f_rockusb objects')
print('L6 STORAGE BIT PATCH APPLIED')
