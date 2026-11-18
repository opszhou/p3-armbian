#!/usr/bin/env python3
"""Apply the P3 rockusb LOADER patch to the U-Boot source tree (container side).

Idempotency: aborts if any marker already exists, so a re-run cannot double-patch.
Also backs up the L2 build outputs and the three source files before editing.
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10'
OUT = ROOT / 'uboot-out'
BAK = ROOT / 'base_l2'
BAK.mkdir(exist_ok=True)

# ---------- 0. backups ----------
for n in ('idbloader.img', 'u-boot.itb', 'u-boot-rockchip.bin',
          'u-boot.dtb', '.config', 'u-boot'):
    p = OUT / n
    if p.exists():
        shutil.copy2(p, BAK / n)
print('backed up L2 outputs ->', BAK)

FILES = {
    'f_rockusb.h': SRC / 'arch/arm/include/asm/arch-rockchip/f_rockusb.h',
    'f_rockusb.c': SRC / 'drivers/usb/gadget/f_rockusb.c',
    'p3.c': SRC / 'board/rockchip/p3/p3.c',
}
for k, p in FILES.items():
    shutil.copy2(p, BAK / (k + '.orig'))
print('backed up 3 source files')

# ---------- 1. f_rockusb.h: add 0xAA ----------
p = FILES['f_rockusb.h']
s = p.read_text()
assert 'K_FW_READ_CAPACITY' not in s, 'already patched: f_rockusb.h'
old = 'K_FW_SESSION = 0x30,\nK_FW_RESET = 0xff,'
new = 'K_FW_SESSION = 0x30,\nK_FW_READ_CAPACITY = 0xAA,\nK_FW_RESET = 0xff,'
assert old in s, 'enum anchor not found'
p.write_text(s.replace(old, new, 1))
print('  [1] f_rockusb.h: K_FW_READ_CAPACITY = 0xAA')

# ---------- 2. f_rockusb.c: struct + 2 callbacks ----------
CALLBACKS = r'''
/*
 * Rockchip RockUSB flash-info / capability replies.
 * Format taken from rockchip-linux/u-boot (release branch)
 * drivers/usb/gadget/f_rockusb.c, archived in /root/p3builder/refs/.
 * Mainline implements only LBA read/write, so upgrade_tool wl bails out at
 * its flash-info pre-check and RKDevTool fails at "Switch storage to EMMC".
 */
struct rk_flash_info {
	u32 flash_size;
	u16 block_size;
	u8  page_size;
	u8  ecc_bits;
	u8  access_time;
	u8  manufacturer;
	u8  flash_mask;
} __attribute__((packed));

static void cb_read_flash_info(struct usb_ep *ep, struct usb_request *req)
{
	ALLOC_CACHE_ALIGN_BUFFER(struct fsg_bulk_cb_wrap, cbw,
				 sizeof(struct fsg_bulk_cb_wrap));
	struct f_rockusb *f_rkusb = get_rkusb();
	struct rk_flash_info finfo = {
		.block_size = 1024, .ecc_bits = 0, .page_size = 4,
		.access_time = 40, .manufacturer = 0, .flash_mask = 0,
	};

	memcpy((char *)cbw, req->buf, USB_BULK_CB_WRAP_LEN);

	if (!f_rkusb->desc) {
		f_rkusb->desc = blk_get_dev(f_rkusb->dev_type,
					    f_rkusb->dev_index);
		if (!f_rkusb->desc ||
		    f_rkusb->desc->type == DEV_TYPE_UNKNOWN) {
			rockusb_tx_write_csw(cbw->tag, 0, CSW_FAIL,
					     USB_BULK_CS_WRAP_LEN);
			return;
		}
	}
	finfo.flash_size = (u32)f_rkusb->desc->lba;
	if (finfo.flash_size)
		finfo.flash_mask = 1;

	f_rkusb->tag = cbw->tag;
	f_rkusb->in_req->complete = tx_handler_send_csw;
	rockusb_tx_write((char *)&finfo, sizeof(finfo));
}

static void cb_read_capacity(struct usb_ep *ep, struct usb_request *req)
{
	ALLOC_CACHE_ALIGN_BUFFER(struct fsg_bulk_cb_wrap, cbw,
				 sizeof(struct fsg_bulk_cb_wrap));
	struct f_rockusb *f_rkusb = get_rkusb();
	u8 buf[8];

	memcpy((char *)cbw, req->buf, USB_BULK_CB_WRAP_LEN);

	memset(buf, 0, sizeof(buf));
	/* eMMC: Direct LBA | First 4M Access | New Vendor Storage API */
	buf[0] = 0x15;

	f_rkusb->tag = cbw->tag;
	f_rkusb->in_req->complete = tx_handler_send_csw;
	rockusb_tx_write((char *)buf, sizeof(buf));
}

'''

# raw strings keep C indentation as literal backslash-t; turn into real tabs
CALLBACKS = CALLBACKS.replace(r'\t', '\t')

p = FILES['f_rockusb.c']
s = p.read_text()
assert 'struct rk_flash_info' not in s, 'already patched: f_rockusb.c'
anchor = 'static void cb_read_lba(struct usb_ep *ep, struct usb_request *req)\n{'
assert anchor in s, 'cb_read_lba anchor not found'
s = s.replace(anchor, CALLBACKS.lstrip('\n') + anchor, 1)

old_tbl = ('\t{\n'
           '\t\t.cmd = K_FW_READ_FLASH_INFO,\n'
           '\t\t.cb = cb_not_support,\n'
           '\t},')
new_tbl = ('\t{\n'
           '\t\t.cmd = K_FW_READ_FLASH_INFO,\n'
           '\t\t.cb = cb_read_flash_info,\n'
           '\t},\n'
           '\t{\n'
           '\t\t.cmd = K_FW_READ_CAPACITY,\n'
           '\t\t.cb = cb_read_capacity,\n'
           '\t},')
assert old_tbl in s, 'command table anchor not found'
s = s.replace(old_tbl, new_tbl, 1)
p.write_text(s)
print('  [2] f_rockusb.c: struct + cb_read_flash_info + cb_read_capacity + table')

# ---------- 3. p3.c: g_dnl_bind_fixup override ----------
FIXUP = r'''
/*
 * Make the rockusb gadget enumerate as a LOADER instead of MASKROM.
 * rkdeveloptool / RKDevTool classify MASKROM vs LOADER by bcdUSB;
 * upstream g_dnl.c defaults to 0x0200 (reported as Maskrom), while the
 * Rockchip vendor fork sets 0x0201 ("Enumerate as a loader device").
 * The generic g_dnl_bind_fixup() is __weak, so the board can override it.
 */
int g_dnl_bind_fixup(struct usb_device_descriptor *dev, const char *name)
{
	if (!strcmp(name, "usb_dnl_rockusb"))
		dev->bcdUSB = cpu_to_le16(0x0201);

	return 0;
}
'''

FIXUP = FIXUP.replace(r'\t', '\t')

p = FILES['p3.c']
s = p.read_text()
assert 'g_dnl_bind_fixup' not in s, 'already patched: p3.c'
old_inc = '#include <stdio.h>\n'
new_inc = ('#include <stdio.h>\n'
           '#include <string.h>\n'
           '#include <g_dnl.h>\n'
           '#include <linux/usb/ch9.h>\n')
assert old_inc in s, 'p3.c include anchor not found'
s = s.replace(old_inc, new_inc, 1)
s = s.rstrip('\n') + '\n' + FIXUP
p.write_text(s)
print('  [3] p3.c: g_dnl_bind_fixup -> bcdUSB 0x0201')

print('\nPATCH APPLIED OK')
