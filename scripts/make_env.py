#!/usr/bin/env python3
"""从 64KB Hinas 基线 U-Boot env 镜像派生「只改 bootcmd」的 env 镜像。

格式（本机实测）：4 字节小端 CRC32(zlib) + 0xFFFC 字节数据，
数据是 NUL 分隔的 key=value，尾部用 0x00 填充。
除 bootcmd 外所有变量原样保留（含 xl_softmode / format_flag / second_image_load
等与工厂模式、按键检测相关的变量）。
"""
import argparse
import os
import struct
import sys
import zlib

ENV_SIZE = 0xFFFC
IMG_SIZE = 4 + ENV_SIZE


def load(path):
    with open(path, "rb") as fh:
        d = fh.read()
    if len(d) < IMG_SIZE:
        raise ValueError("env 镜像太短: %d < %d" % (len(d), IMG_SIZE))
    crc, = struct.unpack_from("<I", d, 0)
    body = d[4:4 + ENV_SIZE]
    calc = zlib.crc32(body) & 0xFFFFFFFF
    if crc != calc:
        raise ValueError("源 env CRC 不匹配: %08x != %08x" % (crc, calc))
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="Hinas 基线 64KB env 镜像")
    ap.add_argument("--bootcmd", default="", help="新的 bootcmd 值")
    ap.add_argument("--out", default="", help="输出路径")
    ap.add_argument("--list", action="store_true", help="只列出变量")
    args = ap.parse_args()

    body = load(args.base)
    filler = body[-1]
    pairs = [s for s in body.split(b"\x00") if s]

    if args.list:
        for s in pairs:
            print(s.decode("utf-8", "replace"))
        print("# %d vars, filler=0x%02x" % (len(pairs), filler))
        return

    if not args.bootcmd or not args.out:
        sys.exit("需要 --bootcmd 与 --out（或用 --list）")

    out = []
    found = False
    for s in pairs:
        if s.startswith(b"bootcmd="):
            out.append(b"bootcmd=" + args.bootcmd.encode())
            found = True
        else:
            out.append(s)
    if not found:
        sys.exit("源 env 里没有 bootcmd")

    data = b"\x00".join(out) + b"\x00"
    if len(data) > ENV_SIZE:
        sys.exit("env 数据溢出: %d > %d" % (len(data), ENV_SIZE))
    data += bytes([filler]) * (ENV_SIZE - len(data))
    img = struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF) + data
    with open(args.out, "wb") as fh:
        fh.write(img)

    # 回读校验
    with open(args.out, "rb") as fh:
        chk = fh.read()
    crc, = struct.unpack_from("<I", chk, 0)
    assert crc == (zlib.crc32(chk[4:4 + ENV_SIZE]) & 0xFFFFFFFF)
    assert len(chk) == IMG_SIZE
    print("%s: %d 字节 CRC=%08x bootcmd=%s" %
          (args.out, len(chk), crc, args.bootcmd))


if __name__ == "__main__":
    main()
