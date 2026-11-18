#!/usr/bin/env python3
r"""L9 part 1: quiet dwc3 dequeue noise + UMS debug counters.

Run inside the container at /root/p3builder, then rebuild:
  make -C /root/p3builder/uboot-out CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)

1) drivers/usb/dwc3/gadget.c (P3_UMS_QUIET):
   dwc3_gadget_ep_dequeue() prints dev_err "request %p was not queued to
   %s" when the request being cancelled has already completed - a benign
   race that fires a few times during every rockusb session.  Demote to
   dev_dbg so it only shows at debug loglevel.

2) drivers/usb/gadget/f_mass_storage.c (P3_UMS_DBG):
   When env var ums_dbg is set, the bulk in/out completion callbacks
   increment counters and print every 16 completions.  Used to localise
   the ~16 MiB UMS write stall observed on this board (FSG_BUFLEN is
   128 KiB, so 16 MiB == ~128 completions).  Enable on the device with
   `setenv ums_dbg 1` before `ums 0 mmc 0`; absent env var costs nothing.
"""
from pathlib import Path

ROOT = Path('/root/p3builder')
BAK = ROOT / 'base_l9'
BAK.mkdir(parents=True, exist_ok=True)

# ---- 1) dwc3 dequeue noise -------------------------------------------------
f = ROOT / 'u-boot-v2025.10' / 'drivers' / 'usb' / 'dwc3' / 'gadget.c'
orig = BAK / 'gadget.c.l8'
if not orig.exists():
    orig.write_bytes(f.read_bytes())
s = f.read_text(encoding='utf-8')
if 'P3_UMS_QUIET' in s:
    print('  dwc3 gadget.c already patched')
else:
    needle = ('\t\tdev_err(dwc->dev, "request %p was not queued to %s\\n",\n'
              '\t\t\t\trequest, ep->name);')
    repl = ('\t\t/* P3_UMS_QUIET: benign race - the request already completed\n'
            '\t\t * and dequeueing it is a no-op.  Demoted from dev_err. */\n'
            '\t\tdev_dbg(dwc->dev, "request %p was not queued to %s\\n",\n'
            '\t\t\t\trequest, ep->name);')
    assert s.count(needle) == 1, 'dwc3 dev_err anchor not found'
    s = s.replace(needle, repl)
    f.write_text(s, encoding='utf-8')
    print('  dwc3 gadget.c: dev_err -> dev_dbg (P3_UMS_QUIET)')

# ---- 2) f_mass_storage debug counters --------------------------------------
g = ROOT / 'u-boot-v2025.10' / 'drivers' / 'usb' / 'gadget' / 'f_mass_storage.c'
orig2 = BAK / 'f_mass_storage.c.l8'
if not orig2.exists():
    orig2.write_bytes(g.read_bytes())
s = g.read_text(encoding='utf-8')
if 'P3_UMS_DBG' in s:
    print('  f_mass_storage.c already patched')
else:
    # env.h include (env_get)
    assert '#include <env.h>' not in s
    inc_anchor = '#include <g_dnl.h>'
    assert s.count(inc_anchor) >= 1
    s = s.replace(inc_anchor, inc_anchor + '\n#include <env.h> /* P3_UMS_DBG */', 1)

    helper = '''/* P3_UMS_DBG: completion counter, enabled by env ums_dbg=1, prints
 * every 16 completions to localise the ~16 MiB UMS write stall. */
static void p3_ums_tick(const char *dir)
{
\tstatic int in_n, out_n;
\tint *n = (dir[5] == 'i') ? &in_n : &out_n;

\tif (!env_get("ums_dbg"))
\t\treturn;
\tif (++*n % 16 == 0)
\t\tprintf("P3 ums_dbg: %d %s completions\\n", *n, dir);
}

'''
    anchor = 'static void bulk_in_complete(struct usb_ep *ep, struct usb_request *req)'
    assert s.count(anchor) == 1
    s = s.replace(anchor, helper + anchor, 1)

    # tick at the top of each completion callback (right after the brace)
    for name, arg in (('bulk_in_complete', 'bulk-in'), ('bulk_out_complete', 'bulk-out')):
        sig = 'static void %s(struct usb_ep *ep, struct usb_request *req)\n{' % name
        assert s.count(sig) == 1, 'anchor %s' % name
        s = s.replace(sig, sig + '\n\tp3_ums_tick("%s");' % arg, 1)

    g.write_text(s, encoding='utf-8')
    print('  f_mass_storage.c: ums_dbg counters added (P3_UMS_DBG)')

print('  backups in', BAK)
