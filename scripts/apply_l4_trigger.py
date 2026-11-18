#!/usr/bin/env python3
"""L4: fix the recovery TRIGGER layer (capability layer stays L3).

  1. UART 'r' window 1.5 s -> 5 s
  2. ADC log prints the threshold, so a real RECOVERY-key press can be judged
  3. register a `recovery` command alias for `rockusb 0 mmc 0`

Backs up L3 outputs and p3.c before editing. Idempotent via marker checks.
"""
import pathlib
import shutil

ROOT = pathlib.Path('/root/p3builder')
SRC = ROOT / 'u-boot-v2025.10'
OUT = ROOT / 'uboot-out'
BAK = ROOT / 'base_l3'
BAK.mkdir(exist_ok=True)

for n in ('idbloader.img', 'u-boot.itb', 'u-boot-rockchip.bin',
          'u-boot.dtb', '.config', 'u-boot'):
    p = OUT / n
    if p.exists():
        shutil.copy2(p, BAK / n)
print('backed up L3 outputs ->', BAK)

p3 = SRC / 'board/rockchip/p3/p3.c'
shutil.copy2(p3, BAK / 'p3.c.orig')

s = p3.read_text()
assert 'UART_RECOVERY_POLLS\t50' not in s, 'already patched'
assert 'do_p3_recovery' not in s, 'already patched'

# 1. widen the window
s = s.replace('/* UART recovery window: 15 polls x 100 ms = 1.5 s */',
              '/* UART recovery window: 50 polls x 100 ms = 5 s */', 1)
s = s.replace('#define UART_RECOVERY_POLLS\t15',
              '#define UART_RECOVERY_POLLS\t50', 1)
s = s.replace("press 'r' within 1.5s for rockusb loader...",
              "press 'r' within 5s for rockusb loader...", 1)
s = s.replace('   *   1. UART (primary, "own" recovery): press \'r\' / \'R\' during the short',
              '   *   1. UART (primary, "own" recovery): press \'r\' / \'R\' during the 5s', 1)

# 2. ADC diagnostics: show the decision threshold next to the sample
old_adc = 'printf("dnl key: adc=%u\\n", *val);'
new_adc = 'printf("dnl key: adc=%u (press if <= %u)\\n", *val, KEY_DOWN_MAX_VAL);'
assert old_adc in s, 'adc printf anchor not found'
s = s.replace(old_adc, new_adc, 1)

# 3. command alias
s = s.replace('#include <stdio.h>\n',
              '#include <stdio.h>\n#include <command.h>\n', 1)

ALIAS = r'''
/*
 * Short alias for the rockusb LOADER. The gadget loop runs until Ctrl+C;
 * this only saves the operator from typing "rockusb 0 mmc 0" every time.
 */
static int do_p3_recovery(struct cmd_tbl *cmdtp, int flag, int argc,
			  char *const argv[])
{
	printf("Entering rockusb loader (Ctrl+C to exit)...\n");
	return run_command("rockusb 0 mmc 0", 0);
}

U_BOOT_CMD(recovery, 1, 0, do_p3_recovery,
	   "enter rockusb LOADER for PC flashing",
	   "");
'''
ALIAS = ALIAS.replace(r'\t', '\t')
s = s.rstrip('\n') + '\n' + ALIAS
p3.write_text(s)

# force rebuild (copy2 preserved old mtimes on backups, but p3.c is rewritten
# here so its mtime is fresh; still drop stale objects to be safe)
for rel in ('board/rockchip/p3/p3.o', 'board/rockchip/p3/built-in.a'):
    q = OUT / rel
    if q.exists():
        q.unlink()
print('removed stale p3 objects')

print('L4 TRIGGER PATCH APPLIED')
