#!/usr/bin/env python3
"""
蜂助手 P3 (RK3566) 整盘镜像组装器 —— 实验性
============================================
⚠ 已在硬件上验收的是「增量刷写」路径，见 FLASH_CARD.md。
   本脚本生成的整盘镜像尚未在真机验证，烧写前先用增量路径确认引导链。

GPT 严格复刻源镜像实测的 8 槽布局（槽 6 必须是空槽）：
  slot1 uboot            0x4000  ~0x5FFF    4 MiB
  slot2 misc             0x6000  ~0x7FFF    4 MiB
  slot3 boot             0x8000  ~0x27FFF  64 MiB  ← boot_fit.img
  slot4 kernel           0x28000 ~0x47FFF  64 MiB
  slot5 env              0x48000 ~0x57FFF  32 MiB
  slot6 (空)
  slot7 (无名 BOOT)      0x258000~0x3577FF 511 MiB  ← ext2 兜底
  slot8 Linux filesystem 0x358000~0x757FFF 2 GiB    ← rootfs

用法:
  python3 scripts/assemble.py --rootfs rootfs.img --outdir out/
"""
import argparse
import os
import struct
import subprocess
import sys
import zlib

SECTOR = 512
MIB = 1024 * 1024

DISK_SECTORS = 0x758021
IDB_LBA = 0x0
UBOOT_LBA = 0x4000
MISC_LBA = 0x6000
BOOTFIT_LBA = 0x8000
KERNEL_LBA = 0x28000
ENV_LBA = 0x48000
BOOT_LBA = 0x258000
ROOTFS_LBA = 0x358000
BOOTFIT_SECTORS = 0x20000          # 64 MiB
BOOT_SECTORS = 0xFF800             # 511 MiB
ROOTFS_SECTORS = 0x400000          # 2 GiB

# None = 空 GPT 槽，必须保留，否则 U-Boot 的分区号会整体错位
PARTITIONS = [
    ("uboot",            UBOOT_LBA,   0x2000),
    ("misc",             MISC_LBA,    0x2000),
    ("boot",             BOOTFIT_LBA, BOOTFIT_SECTORS),
    ("kernel",           KERNEL_LBA,  0x20000),
    ("env",              ENV_LBA,     0x10000),
    None,
    ("",                 BOOT_LBA,    BOOT_SECTORS),
    ("Linux filesystem", ROOTFS_LBA,  ROOTFS_SECTORS),
]

BOOTCMD = "boot_fit"


def gpt_bytes():
    """Protective MBR + GPT 主头 + 分区项数组（含空槽 6）。"""
    pmbr = bytearray(SECTOR)
    # Protective MBR 分区项固定 16 字节：boot/起始CHS/type=0xEE/结束CHS/起始LBA/扇区数
    pmbr[0x1BE:0x1CE] = struct.pack(
        "<B3sB3sII", 0, b"\x00\x02\x00", 0xEE,
        b"\xfe\xff\xff", 1, DISK_SECTORS - 1)
    pmbr[0x1FE:0x200] = b"\x55\xaa"

    hdr = bytearray(92)
    hdr[0:8] = b"EFI PART"
    struct.pack_into("<I", hdr, 8, 0x00010000)          # revision
    struct.pack_into("<I", hdr, 12, 92)                 # header size
    struct.pack_into("<Q", hdr, 24, 1)                  # MyLBA
    struct.pack_into("<Q", hdr, 32, DISK_SECTORS - 1)   # AlternateLBA
    struct.pack_into("<Q", hdr, 40, 34)                 # FirstUsable
    struct.pack_into("<Q", hdr, 48, DISK_SECTORS - 34)  # LastUsable
    hdr[56:72] = b"P3" + b"\x00" * 14                   # disk GUID（确定性占位）
    struct.pack_into("<Q", hdr, 72, 2)                  # 分区项数组 LBA
    struct.pack_into("<I", hdr, 80, 128)                # 条目数
    struct.pack_into("<I", hdr, 84, 128)                # 条目大小

    entries = bytearray(128 * 128)

    def guid_at(i):
        b = bytearray(16)
        b[0] = i
        b[15] = 0x9A
        return bytes(b)

    for i, part in enumerate(PARTITIONS):
        if part is None:
            continue                                    # 槽 6 保持全零
        name, start, count = part
        e = i * 128
        entries[e:e + 16] = guid_at(i)
        entries[e + 16:e + 32] = guid_at(i + 100)
        struct.pack_into("<QQ", entries, e + 32, start, start + count - 1)
        nm = name.encode("utf-16-le")[:72]
        entries[e + 56:e + 56 + len(nm)] = nm

    struct.pack_into("<I", hdr, 16, zlib.crc32(bytes(hdr[:92])) & 0xFFFFFFFF)
    struct.pack_into("<I", hdr, 88, zlib.crc32(bytes(entries)) & 0xFFFFFFFF)
    return bytes(pmbr), bytes(hdr), bytes(entries)


def env_bytes(bootcmd=BOOTCMD):
    """最小可用 env（CRC32 + 0xFFFC）。地址必须与 FIT 的 load 属性一致。"""
    base = {
        "bootcmd": bootcmd,
        "bootdelay": "1",
        "baudrate": "1500000",
        "stdout": "serial,vidconsole",
        "stderr": "serial,vidconsole",
        "stdin": "serial,usbkbd",
        "arch": "arm",
        "board": "evb_rk3568",
        "board_name": "evb_rk3568",
        "soc": "rockchip",
        "vendor": "rockchip",
        "cpu": "armv8",
        "kernel_addr_r": "0x00280000",
        "fdt_addr_r": "0x0a100000",
        "ramdisk_addr_r": "0x0a200000",
        "scriptaddr": "0x00c00000",
        "second_image_load": "off",
        # 兜底路径用槽 7，不是槽 6
        "bootcmd_emmc": "sysboot mmc 0:7 any 0x00c00000 /extlinux/extlinux.conf",
    }
    data = b"\x00".join(
        ("%s=%s" % (k, v)).encode() for k, v in sorted(base.items()))
    data += b"\x00\x00"
    data += b"\x00" * (0xFFFC - len(data))
    return struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF) + data


def make_boot_tree(assets, outdir):
    """把 assets 铺成 build_boot_fit.py / mke2fs 需要的目录树。"""
    root = os.path.join(outdir, "boot-tree")
    os.makedirs(os.path.join(root, "extlinux"), exist_ok=True)
    os.makedirs(os.path.join(root, "dtb", "rockchip"), exist_ok=True)
    for name in ("Image", "uInitrd", "armbianEnv.txt"):
        dst = os.path.join(root, name)
        with open(os.path.join(assets, name), "rb") as s, open(dst, "wb") as d:
            d.write(s.read())
    for name in ("rk3566-oec-box-wxy4.dtb",):
        with open(os.path.join(assets, name), "rb") as s, \
             open(os.path.join(root, "dtb", "rockchip", name), "wb") as d:
            d.write(s.read())
    with open(os.path.join(assets, "extlinux.conf"), "rb") as s, \
         open(os.path.join(root, "extlinux", "extlinux.conf"), "wb") as d:
        d.write(s.read())
    return root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rootfs", default="", help="rootfs 分区镜像 (.img)")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--assets", default="assets")
    ap.add_argument("--env-base", default="",
                    help="可选：Hinas 基线 64KB env，用于保留全部Hinas 基线变量")
    ap.add_argument("--no-bootfit", action="store_true",
                    help="跳过 boot_fit.img 构建")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    A = args.assets

    need = ["rk356x-MiniLoaderAll.bin", "idb.bin", "uboot.itb", "Image",
            "uInitrd", "rk3566-oec-box-wxy4.dtb", "extlinux.conf",
            "armbianEnv.txt", "resource.img"]
    missing = [f for f in need if not os.path.exists(os.path.join(A, f))]
    if missing:
        sys.exit("缺少资产: %s" % ", ".join(missing))

    img = os.path.join(args.outdir, "p3-armbian.img")
    with open(img, "wb") as o:
        o.truncate(DISK_SECTORS * SECTOR)

    def put(lba, data):
        with open(img, "r+b") as o:
            o.seek(lba * SECTOR)
            o.write(data)

    # 1. IDB —— 复用已验证的 Hinas 基线 IDB 快照（RKSS），绝不重新生成
    idb = open(os.path.join(A, "idb.bin"), "rb").read()
    put(IDB_LBA, idb[:0x740 * SECTOR])
    print("[1/7] IDB Hinas 基线快照(RKSS) %d 字节" % len(idb))

    # 2. GPT（主 + 备）
    pmbr, hdr, entries = gpt_bytes()
    put(0, pmbr)
    put(1, hdr)
    put(2, entries)
    with open(img, "r+b") as o:
        o.seek((DISK_SECTORS - 33) * SECTOR)
        o.write(entries)
        hb = bytearray(hdr)
        struct.pack_into("<Q", hb, 24, DISK_SECTORS - 1)
        struct.pack_into("<Q", hb, 32, 1)
        struct.pack_into("<I", hb, 16, 0)
        struct.pack_into("<I", hb, 16, zlib.crc32(bytes(hb[:92])) & 0xFFFFFFFF)
        o.seek((DISK_SECTORS - 1) * SECTOR)
        o.write(bytes(hb))
    print("[2/7] GPT 主+备（8 槽，槽 6 空）")

    # 3. uboot.itb（含 check_reset_key / rockusb，RECOVERY 关键）
    ub = open(os.path.join(A, "uboot.itb"), "rb").read()
    put(UBOOT_LBA, ub[:0x2000 * SECTOR])
    print("[3/7] uboot.itb %d 字节" % len(ub))

    # 4. env
    if args.env_base:
        subprocess.run([sys.executable, "scripts/make_env.py",
                        "--base", args.env_base, "--bootcmd", BOOTCMD,
                        "--out", os.path.join(args.outdir, "p3_env_bootfit.img")],
                       check=True)
        env = open(os.path.join(args.outdir, "p3_env_bootfit.img"), "rb").read()
    else:
        env = env_bytes()
    put(ENV_LBA, env)
    print("[4/7] env bootcmd=%s" % BOOTCMD)

    # 5. boot_fit.img @0x8000
    tree = make_boot_tree(A, args.outdir)
    if not args.no_bootfit:
        fit_path = os.path.join(args.outdir, "boot_fit.img")
        subprocess.run([sys.executable, "scripts/build_boot_fit.py",
                        "--src", tree,
                        "--resource", os.path.join(A, "resource.img"),
                        "--out", fit_path,
                        "--desc-out", os.path.join(args.outdir, "fit_desc.dtb")],
                       check=True)
        fit = open(fit_path, "rb").read()
        assert len(fit) <= BOOTFIT_SECTORS * SECTOR
        put(BOOTFIT_LBA, fit)
        print("[5/7] boot_fit.img %d 字节 @0x%x" % (len(fit), BOOTFIT_LBA))
    else:
        print("[5/7] 跳过 boot_fit.img")

    # 6. ext2 BOOT 兜底分区（sysboot mmc 0:7 路径）
    boot_img = os.path.join(args.outdir, "boot.ext2")
    subprocess.run(["truncate", "-s", "511M", boot_img], check=True)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext2", "-I", "128",
                    "-b", "4096", "-L", "BOOT", "-d", tree,
                    boot_img, "511M"], check=True)
    with open(boot_img, "rb") as f:
        put(BOOT_LBA, f.read(BOOT_SECTORS * SECTOR))
    print("[6/7] boot.ext2 @0x%x" % BOOT_LBA)

    # 7. rootfs
    if args.rootfs:
        with open(args.rootfs, "rb") as f, open(img, "r+b") as o:
            o.seek(ROOTFS_LBA * SECTOR)
            remain = ROOTFS_SECTORS * SECTOR
            while remain > 0:
                chunk = f.read(min(remain, 16 * MIB))
                if not chunk:
                    break
                o.write(chunk)
                remain -= len(chunk)
        print("[7/7] rootfs <- %s" % args.rootfs)
    else:
        print("[7/7] 未指定 --rootfs，rootfs 区留空")

    print("\n完成: %s (%.2f GB)" % (img, os.path.getsize(img) / 1024 ** 3))
    print("⚠ 整盘镜像未经真机验证；量产前先按 FLASH_CARD.md 增量刷写确认引导链。")


if __name__ == "__main__":
    main()
