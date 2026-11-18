#!/usr/bin/env python3
"""Fix L3 build conflict: g_dnl_bind_fixup already has a strong definition
in arch/arm/mach-rockchip/board.c. Put the bcdUSB fix there instead.
"""
import pathlib
import shutil

ROOT = pathlib.Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10'
BAK = ROOT / 'base_l2'

# ---------- 1. restore p3.c to the L2 state (no duplicate symbol) ----------
p3 = SRC / 'board/rockchip/p3/p3.c'
shutil.copy2(BAK / 'p3.c.orig', p3)
s = p3.read_text()
assert 'g_dnl_bind_fixup' not in s
print('  [1] p3.c restored to L2 (no g_dnl_bind_fixup)')

# ---------- 2. patch the existing strong implementation in board.c ----------
bc = SRC / 'arch/arm/mach-rockchip/board.c'
shutil.copy2(bc, BAK / 'board.c.orig')
s = bc.read_text()
assert 'P3_LOADER_BCDUSB' not in s, 'already patched: board.c'

old = '''int g_dnl_bind_fixup(struct usb_device_descriptor *dev, const char *name)
{
	if (!strcmp(name, "usb_dnl_ums"))
		put_unaligned(ROCKCHIP_G_DNL_UMS_PRODUCT_NUM, &dev->idProduct);
	else
		put_unaligned(CONFIG_USB_GADGET_PRODUCT_NUM, &dev->idProduct);

	return 0;
}'''
new = '''int g_dnl_bind_fixup(struct usb_device_descriptor *dev, const char *name)
{
	if (!strcmp(name, "usb_dnl_ums"))
		put_unaligned(ROCKCHIP_G_DNL_UMS_PRODUCT_NUM, &dev->idProduct);
	else
		put_unaligned(CONFIG_USB_GADGET_PRODUCT_NUM, &dev->idProduct);

	/* P3_LOADER_BCDUSB: rkdeveloptool / RKDevTool classify MASKROM vs
	 * LOADER by bcdUSB. Upstream defaults to 0x0200 (reported as Maskrom);
	 * the Rockchip vendor fork sets 0x0201 "Enumerate as a loader device".
	 * Only the rockusb gadget is affected; UMS/fastboot keep their PID path.
	 */
	if (!strcmp(name, "usb_dnl_rockusb"))
		dev->bcdUSB = cpu_to_le16(0x0201);

	return 0;
}'''
assert old in s, 'board.c fixup anchor not found'
bc.write_text(s.replace(old, new, 1))
print('  [2] board.c: rockusb -> bcdUSB 0x0201')

print('\nCONFLICT FIXED')
