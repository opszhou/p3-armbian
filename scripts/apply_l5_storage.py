#!/usr/bin/env python3
"""L5 = L4 + RKDevTool GUI compatibility (CHANGE_STORAGE / READ_STORAGE).

Formats come from rkdeveloptool master:
  RKComm.h:52  CHANGE_STORAGE = 0x2A, READ_STORAGE = 0x2B
  RKComm.cpp RKU_ChangeStorage(): dwCBWTransferLength stays 0, no data stage,
    device only needs to return CSW with ucCSWStatus == 0 (GOOD).
  RKComm.cpp RKU_ReadStorage(): dwCBWTransferLength = 4, device returns a
    4-byte storage bitmap, host takes the first set bit as the media index.
    bit 0 = eMMC on this board.

Backs up L4 outputs and the two source files before editing.
"""
import pathlib
import shutil

ROOT = pathlib.Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10'
OUT = ROOT / 'uboot-out'
BAK = ROOT / 'base_l4'
BAK.mkdir(exist_ok=True)

for n in ('idbloader.img', 'u-boot.itb', 'u-boot-rockchip.bin',
          'u-boot.dtb', '.config', 'u-boot'):
    p = OUT / n
    if p.exists():
        shutil.copy2(p, BAK / n)
print('backed up L4 outputs ->', BAK)

H = SRC / 'arch/arm/include/asm/arch-rockchip/f_rockusb.h'
C = SRC / 'drivers/usb/gadget/f_rockusb.c'
for p in (H, C):
    shutil.copy2(p, BAK / (p.name + '.orig'))

# ---------- 1. header: two opcodes ----------
s = H.read_text()
assert 'K_FW_CHANGE_STORAGE' not in s, 'already patched: header'
old = 'K_FW_LBA_ERASE_10 = 0x25,\n'
new = ('K_FW_LBA_ERASE_10 = 0x25,\n'
       'K_FW_CHANGE_STORAGE = 0x2A,\n'
       'K_FW_READ_STORAGE = 0x2B,\n')
assert old in s, 'header anchor not found'
H.write_text(s.replace(old, new, 1))
print('  [1] header: 0x2A / 0x2B')

# ---------- 2. two callbacks ----------
CALLBACKS = r'''
/*
 * RKDevTool GUI sends CHANGE_STORAGE (0x2A) before any LBA write.
 * rkdeveloptool's RKU_ChangeStorage() leaves dwCBWTransferLength at 0 and
 * only checks the CSW status, so a CSW_GOOD no-op is sufficient: this board
 * has eMMC only and the gadget is already bound to mmc 0.
 * READ_STORAGE (0x2B) returns a 4-byte bitmap; bit 0 = eMMC.
 * Without these the gadget falls through to the default branch at
 * f_rockusb.c:985, replies "FAILunknown command" and the GUI bulk read
 * fails with os error 31.
 */
static void cb_change_storage(struct usb_ep *ep, struct usb_request *req)
{
	ALLOC_CACHE_ALIGN_BUFFER(struct fsg_bulk_cb_wrap, cbw,
				 sizeof(struct fsg_bulk_cb_wrap));
	memcpy((char *)cbw, req->buf, USB_BULK_CB_WRAP_LEN);
	printf("rockusb: change storage -> %u (no-op, eMMC only)\n",
	       cbw->CDB[1]);
	rockusb_tx_write_csw(cbw->tag, 0, CSW_GOOD, USB_BULK_CS_WRAP_LEN);
}

static void cb_read_storage(struct usb_ep *ep, struct usb_request *req)
{
	ALLOC_CACHE_ALIGN_BUFFER(struct fsg_bulk_cb_wrap, cbw,
				 sizeof(struct fsg_bulk_cb_wrap));
	struct f_rockusb *f_rkusb = get_rkusb();
	u32 bits = 1;	/* bit 0 = eMMC */

	memcpy((char *)cbw, req->buf, USB_BULK_CB_WRAP_LEN);
	f_rkusb->tag = cbw->tag;
	f_rkusb->in_req->complete = tx_handler_send_csw;
	rockusb_tx_write((char *)&bits, sizeof(bits));
}

'''.lstrip('\n').replace(r'\t', '\t')

s = C.read_text()
assert 'cb_change_storage' not in s, 'already patched: f_rockusb.c'
anchor = 'static void cb_read_lba(struct usb_ep *ep, struct usb_request *req)\n{'
assert anchor in s, 'cb_read_lba anchor not found'
s = s.replace(anchor, CALLBACKS + anchor, 1)

tbl_anchor = ('\t{\n'
              '\t\t.cmd = K_FW_READ_CAPACITY,\n'
              '\t\t.cb = cb_read_capacity,\n'
              '\t},')
tbl_new = tbl_anchor + ('\n'
                        '\t{\n'
                        '\t\t.cmd = K_FW_CHANGE_STORAGE,\n'
                        '\t\t.cb = cb_change_storage,\n'
                        '\t},\n'
                        '\t{\n'
                        '\t\t.cmd = K_FW_READ_STORAGE,\n'
                        '\t\t.cb = cb_read_storage,\n'
                        '\t},')
assert tbl_anchor in s, 'command table anchor not found'
s = s.replace(tbl_anchor, tbl_new, 1)
C.write_text(s)
print('  [2] f_rockusb.c: cb_change_storage + cb_read_storage + 2 table rows')

# force rebuild of the changed object
for rel in ('drivers/usb/gadget/f_rockusb.o',
            'drivers/usb/gadget/built-in.a'):
    q = OUT / rel
    if q.exists():
        q.unlink()
print('removed stale f_rockusb objects')
print('L5 STORAGE PATCH APPLIED')
