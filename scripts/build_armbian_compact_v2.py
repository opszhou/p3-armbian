#!/usr/bin/env python3
r"""Build the compact v2 Armbian image for the P3 (L8 bootloader chain).

Layout (all 16 MiB aligned, no holes, exactly 2 partitions):
  LBA 0            protective MBR (canonical full-disk entry)
  LBA 1..33        GPT header + 2-entry array
  LBA 34..18431    kit bootarea (zeros + idbloader @LBA64 + L9 u-boot)
  LBA 32768        p1 boot   384 MiB  (shrunk fs rebuilt from p7 content,
                                              UUID/label preserved)
  LBA 819200       p2 rootfs          (parts/p8_rootfs.img content, resize-on-
                   firstboot via native service; marker file already removed)
  LBA 30535647..79 backup GPT (synthesized from main, transform verified)

Outputs (E:/tvbox/armbian-new/v2/):
  p3_armbian_v2_full.img.gz   full-disk archival image (sparse raw)
  01_gpt_bootarea.img         flash @ 0x0        (LBA0..18297)
  02_boot.img                 flash @ 0x8000     (32768)
  03_rootfs.img               flash @ 0xC8000    (819200)
  04_backup_gpt.img           flash @ 0x1D1EFDF  (30535647)
  SHA256SUMS.txt
"""
import gzip
import hashlib
import os
import struct
import uuid
import zlib

KIT_DIR = os.environ.get('V2_KIT', r'E:/tvbox/p3-flash-kit-v2')
PARTS = os.environ.get('V2_PARTS', r'E:/tvbox/armbian-new/parts')
OUT_DIR = os.environ.get('V2_OUT', r'E:/tvbox/armbian-new/v2')
OUT_RAW = os.path.join(OUT_DIR, 'p3_armbian_v2_full.img')
OUT_GZ = OUT_RAW + '.gz'

TOTAL_LBA = 30535680            # 14.6 GiB eMMC
BACKUP_ARRAY_LBA = 30535647     # backup array (32 s) then header (1 s)
UBOOT_END_LBA = 18432           # kit bootarea covers LBA1..18297
P1_FIRST, P1_SIZE = 32768, 786432            # 384 MiB
P2_FIRST = 819200
P2_LAST = 30535646
DISK_UUID = uuid.uuid5(uuid.NAMESPACE_OID, 'p3-armbian-v2-disk')
P1_GUID = uuid.uuid5(uuid.NAMESPACE_OID, 'p3-armbian-v2-boot')
P2_GUID = uuid.uuid5(uuid.NAMESPACE_OID, 'p3-armbian-v2-rootfs')
LINUX_FS = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4')

os.makedirs(OUT_DIR, exist_ok=True)


def gpt_entry(type_guid, part_guid, first, last, name):
    e = bytearray(128)
    e[0:16] = bytes(type_guid.bytes_le)
    e[16:32] = bytes(part_guid.bytes_le)
    struct.pack_into('<QQQ', e, 32, first, last, 0)
    name_b = name.encode('utf-16-le')[:72]
    e[56:56 + len(name_b)] = name_b      # exact-length slice: a short slice
    return bytes(e)                      # would SHRINK the bytearray!


def make_gpt():
    # GPT header layout: sig@0 rev@8 hdrsize@12 crc@16 MyLBA@24 AltLBA@32
    # FirstUsable@40 LastUsable@48 DiskGUID@56 EntryLBA@72 nEntries@80
    # entrySize@84 arrayCRC@88
    hdr = bytearray(92)
    hdr[0:8] = b'EFI PART'
    struct.pack_into('<I', hdr, 8, 0x00010000)      # revision 1.0
    struct.pack_into('<I', hdr, 12, 92)             # header size
    struct.pack_into('<Q', hdr, 24, 1)              # MyLBA
    struct.pack_into('<Q', hdr, 32, TOTAL_LBA - 1)  # AlternativeLBA
    struct.pack_into('<Q', hdr, 40, 34)             # FirstUsableLBA
    struct.pack_into('<Q', hdr, 48, P2_LAST)        # LastUsableLBA
    hdr[56:72] = DISK_UUID.bytes_le
    struct.pack_into('<Q', hdr, 72, 2)              # PartitionEntryLBA
    struct.pack_into('<I', hdr, 80, 128)            # entry count
    struct.pack_into('<I', hdr, 84, 128)            # entry size
    arr = (gpt_entry(LINUX_FS, P1_GUID, P1_FIRST, P1_FIRST + P1_SIZE - 1, 'boot')
           + gpt_entry(LINUX_FS, P2_GUID, P2_FIRST, P2_LAST, 'rootfs'))
    arr += b'\x00' * (128 * 128 - len(arr))         # 128 entry slots
    struct.pack_into('<I', hdr, 88, zlib.crc32(arr) & 0xFFFFFFFF)
    return bytes(hdr), arr


def fix_header_crc(hdr):
    h = bytearray(hdr)
    struct.pack_into('<I', h, 16, 0)
    struct.pack_into('<I', h, 16, zlib.crc32(bytes(h)) & 0xFFFFFFFF)
    return bytes(h)


def synth_backup(main_hdr, arr):
    """Main GPT -> backup GPT (same transform verified byte-exact against
    kit 02_backup_gpt.img in the v1 build): swap MyLBA/AlternativeLBA,
    point the array at the backup slot, recompute both CRCs."""
    bk_hdr = bytearray(main_hdr)
    struct.pack_into('<Q', bk_hdr, 24, TOTAL_LBA - 1)        # MyLBA
    struct.pack_into('<Q', bk_hdr, 32, 1)                    # AlternativeLBA
    struct.pack_into('<Q', bk_hdr, 72, BACKUP_ARRAY_LBA)     # PartitionEntryLBA
    struct.pack_into('<I', bk_hdr, 88, zlib.crc32(arr) & 0xFFFFFFFF)
    return fix_header_crc(bytes(bk_hdr)), arr


def parse_validate(img_path, label, offset):
    """Independent parse-back validation of a written GPT region."""
    with open(img_path, 'rb') as f:
        f.seek(offset)
        hdr = f.read(512)
        arr = f.read(128 * 128)
    assert hdr[:8] == b'EFI PART', '%s: bad signature' % label
    stored, = struct.unpack('<I', hdr[16:20])
    h = bytearray(hdr[:92])
    struct.pack_into('<I', h, 16, 0)
    assert stored == (zlib.crc32(bytes(h)) & 0xFFFFFFFF), '%s: header CRC' % label
    n = struct.unpack('<I', hdr[80:84])[0]
    esz = struct.unpack('<I', hdr[84:88])[0]
    ecrc = struct.unpack('<I', hdr[88:92])[0]
    body = arr[:n * esz]
    assert zlib.crc32(body) & 0xFFFFFFFF == ecrc, '%s: array CRC' % label
    parts = []
    for i in range(n):
        e = body[i * esz:(i + 1) * esz]
        if e[:16] == b'\x00' * 16:
            continue
        first, last = struct.unpack('<QQ', e[32:48])
        name = e[56:128].decode('utf-16-le').rstrip('\x00')
        parts.append((name, first, last))
    print('  %s OK: %s' % (label, parts))
    return parts


# --- inputs ---
print('=== 1. inputs ===')
bootarea = open(os.path.join(KIT_DIR, '01_bootarea.img'), 'rb').read()
assert len(bootarea) == UBOOT_END_LBA * 512
p1 = open(os.path.join(PARTS, 'p7_boot.img'), 'rb').read()
p2 = open(os.path.join(PARTS, 'p8_rootfs.img'), 'rb').read()
assert len(p1) == P1_SIZE * 512, 'boot part size drift'
assert len(p2) == 2999 * 1024 * 1024, 'rootfs part size drift'
print('  bootarea %d B, boot %d B, rootfs %d B' % (len(bootarea), len(p1), len(p2)))

# --- synthesize GPT ---
print('=== 2. synthesize GPT (2 entries, 16MiB aligned) ===')
main_hdr, main_arr = make_gpt()
main_hdr = fix_header_crc(main_hdr)
bk_hdr, bk_arr = synth_backup(main_hdr, main_arr)
print('  p1 boot   LBA %d..%d (%d MiB)' % (P1_FIRST, P1_FIRST + P1_SIZE - 1, P1_SIZE * 512 // 2**20))
print('  p2 rootfs LBA %d..%d (%.2f GiB)' % (P2_FIRST, P2_LAST, (P2_LAST - P2_FIRST + 1) * 512 / 2**30))

# --- assemble full raw ---
print('=== 3. assemble full raw -> %s ===' % OUT_RAW)
lba0 = bytearray(512)
lba0[446:446 + 16] = bytes.fromhex('00000200eeffffff01000000ffefd101')
lba0[510:512] = b'\x55\xaa'
if os.path.exists(OUT_RAW):
    os.remove(OUT_RAW)
h_full = hashlib.sha256()
with open(OUT_RAW, 'wb') as out:
    out.write(bytes(lba0))                          # LBA0
    out.seek(512)
    out.write(main_hdr.ljust(512, b'\x00'))         # LBA1 (pad to sector)
    out.write(main_arr)                             # LBA2..33
    out.seek(34 * 512)
    out.write(bootarea[33 * 512:])                  # LBA34..18297
    out.seek(P1_FIRST * 512)
    out.write(p1)
    out.seek(P2_FIRST * 512)
    out.write(p2)
    out.seek(BACKUP_ARRAY_LBA * 512)
    out.write(bk_arr)                               # LBA 30535647..78
    out.write(bk_hdr.ljust(512, b'\x00'))           # LBA 30535679
    out.truncate(TOTAL_LBA * 512)
h_full = hashlib.sha256()
with open(OUT_RAW, 'rb') as fin:
    while True:
        b = fin.read(32 * 1024 * 1024)
        if not b:
            break
        h_full.update(b)
print('  raw sha256: %s' % h_full.hexdigest())

# --- self-checks on the assembled raw ---
print('=== 4. self-checks ===')
with open(OUT_RAW, 'rb') as f:
    f.seek(64 * 512)
    assert f.read(4) == b'RKNS', 'idbloader magic not at LBA64'
    f.seek(34 * 512)
    seg = f.read((UBOOT_END_LBA - 33) * 512)
assert seg == bootarea[33 * 512:33 * 512 + len(seg)], 'bootarea off-by-one!'
parts = parse_validate(OUT_RAW, 'main GPT', 512)
assert parts == [('boot', P1_FIRST, P1_FIRST + P1_SIZE - 1),
                 ('rootfs', P2_FIRST, P2_LAST)], 'partition table mismatch'
# backup GPT parse
with open(OUT_RAW, 'rb') as f:
    f.seek(BACKUP_ARRAY_LBA * 512)
    bk_written = f.read(33 * 512)
assert bk_written[:16384] == bk_arr[:16384], 'backup array mismatch'
assert bk_written[16384:16384 + 92] == bk_hdr, 'backup header mismatch'
print('  RKNS @LBA64, bootarea byte-exact, backup GPT matches synthesis')

# --- flash pieces ---
print('=== 5. flash pieces ===')
pieces = [
    ('01_gpt_bootarea.img', None, '0x0', 'GPT + u-boot chain (LBA0..18432)'),
    ('02_boot.img', (P1_FIRST, P1_SIZE * 512), hex(P1_FIRST), 'p1 boot 384MiB'),
    ('03_rootfs.img', (P2_FIRST, len(p2)), hex(P2_FIRST),
     'p2 rootfs fs content (first-boot auto-resize)'),
    ('04_backup_gpt.img', (BACKUP_ARRAY_LBA, 33 * 512), hex(BACKUP_ARRAY_LBA), 'backup GPT'),
]
sums = []
with open(OUT_RAW, 'rb') as src:
    for name, span, addr, desc in pieces:
        path = os.path.join(OUT_DIR, name)
        if span is None:
            src.seek(0)
            data = src.read((UBOOT_END_LBA + 1) * 512)
        else:
            src.seek(span[0] * 512)
            data = src.read(span[1])
        with open(path, 'wb') as f:
            f.write(data)
        sha = hashlib.sha256(data).hexdigest()
        sums.append('%s  %s  # @%s %s' % (sha, name, addr, desc))
        print('  %-22s %9d B  @%-9s %s' % (name, len(data), addr, desc))

# --- gz + sums ---
print('=== 6. gzip ===')
with open(OUT_RAW, 'rb') as fin, gzip.open(OUT_GZ, 'wb', compresslevel=6) as fz:
    while True:
        b = fin.read(32 * 1024 * 1024)
        if not b:
            break
        fz.write(b)
print('  gz: %.2f GiB' % (os.path.getsize(OUT_GZ) / 2**30))
os.remove(OUT_RAW)
with open(os.path.join(OUT_DIR, 'SHA256SUMS.txt'), 'w') as f:
    f.write('\n'.join(sums) + '\n')
print('BUILD OK -> %s' % OUT_DIR)
