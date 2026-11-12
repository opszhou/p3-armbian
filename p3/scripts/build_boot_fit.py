#!/usr/bin/env python3
"""
为蜂助手 P3 (RK3566) 构造 boot_fit 用的 FIT 镜像。

按Hinas 基线 boot 分区 (LBA 0x8000) 的 FIT 结构 1:1 复刻，只替换
fdt / kernel / ramdisk 的内容，保留 Rockchip 私有 data-position 外部数据格式。
boot_fit 按扇区偏移读数据，不经过 fs 层，绕开该 vendor U-Boot 被裁废的文件系统探测。

Hinas 基线实测（sha256 已反查确认 data-position 相对分区起点）:
  root: timestamp, version(空), totalsize(4KB 对齐的整体长度), description
  /images/fdt       data-position=0x1000     data-size=0x19ee9   load=0x0a100000
  /images/kernel    data-position=0x1b000    data-size=0x176f808 load/entry=0x00280000
  /images/ramdisk   data-position=0x178aa00  data-size=0x6084d3  load=0x0a200000
  /images/resource  data-position=0x1d93000  data-size=0x1a400   type=multi
  每个 image 子节点 /hash { value=<32B sha256>, algo="sha256" }
  /configurations { default="conf"; conf { rollback-index(空), fdt, kernel, ramdisk, multi } }
  Hinas 基线 conf 另有 /signature (sha256,rsa2048)，但 UART 实测 "## Verified-boot: 0"，
  secure boot 关闭，故本镜像不带签名节点。

输出: boot_fit.img —— 长度恰好等于 root.totalsize，整块写回 LBA 0x8000。
"""
import struct
import os
import argparse
import hashlib

FDT_BEGIN, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
FDT_MAGIC = 0xD00DFEED
ALIGN = 0x1000

# 与Hinas 基线 boot_fit 期望一致的装载地址
LOAD_KERNEL = 0x00280000
LOAD_FDT = 0x0A100000
LOAD_RAMDISK = 0x0A200000


def align4k(n):
    return (n + ALIGN - 1) & ~(ALIGN - 1)


class StrTab:
    def __init__(self):
        self.buf = bytearray(b"\x00")

    def add(self, s):
        if isinstance(s, str):
            s = s.encode()
        for i in range(len(self.buf)):
            if self.buf[i:].startswith(s + b"\x00"):
                return i
        off = len(self.buf)
        self.buf += s + b"\x00"
        return off

    def raw(self):
        return bytes(self.buf)


class FdtBuilder:
    def __init__(self):
        self.tokens = bytearray()
        self.strtab = StrTab()

    def _u32(self, v):
        self.tokens += struct.pack(">I", v)

    def begin(self, name):
        self._u32(FDT_BEGIN)
        n = name.encode() + b"\x00"
        self.tokens += n
        while len(self.tokens) % 4:
            self.tokens += b"\x00"

    def end_node(self):
        self._u32(FDT_END_NODE)

    def prop(self, name, val):
        if isinstance(val, str):
            val = val.encode() + b"\x00"
        elif isinstance(val, int):
            val = struct.pack(">I", val)
        elif val is None:
            val = b""
        self._u32(FDT_PROP)
        self._u32(len(val))
        self._u32(self.strtab.add(name))
        self.tokens += val
        while len(self.tokens) % 4:
            self.tokens += b"\x00"

    def blob(self):
        self._u32(FDT_END)
        strs = self.strtab.raw()
        hdr_size = 40
        rsv_off = hdr_size
        rsv = b"\x00" * 16                      # 空 reserve map 终结项
        off_struct = rsv_off + len(rsv)
        off_strings = off_struct + len(self.tokens)
        totalsize = off_strings + len(strs)
        hdr = struct.pack(
            ">10I",
            FDT_MAGIC, totalsize, off_struct, off_strings, rsv_off,
            17, 16, 0, len(strs), len(self.tokens))
        return hdr + rsv + bytes(self.tokens) + strs


def build_fdt(images, total_size, timestamp=0):
    f = FdtBuilder()
    f.begin("")
    f.prop("timestamp", timestamp)
    f.prop("version", None)                     # Hinas 基线: 空值
    f.prop("totalsize", total_size)             # 4KB 对齐的整体长度
    f.prop("description", "U-Boot FIT source file for arm")

    f.begin("images")
    for im in images:
        f.begin(im["name"])
        f.prop("data-size", im["size"])
        f.prop("data-position", im["pos"])
        f.prop("type", im["type"])
        f.prop("arch", "arm64")
        if im.get("os"):
            f.prop("os", im["os"])
        f.prop("compression", "none")
        if im.get("entry") is not None:
            f.prop("entry", im["entry"])
        if im.get("load") is not None:
            f.prop("load", im["load"])
        f.begin("hash")                         # Hinas 基线节点名就是 "hash"，不是 hash@1
        f.prop("value", im["sha256"])
        f.prop("algo", "sha256")
        f.end_node()
        f.end_node()
    f.end_node()

    f.begin("configurations")
    f.prop("default", "conf")
    f.begin("conf")
    f.prop("rollback-index", None)              # Hinas 基线: 空值
    f.prop("fdt", "fdt")
    f.prop("kernel", "kernel")
    f.prop("ramdisk", "ramdisk")
    if any(i["name"] == "resource" for i in images):
        f.prop("multi", "resource")
    f.end_node()
    f.end_node()
    f.end_node()
    return f.blob()


def parse_props(blob):
    """回读 FIT 描述，返回 {节点路径: {属性名: 原始字节}}"""
    (magic, total, off_struct, off_strings, off_rsv,
     ver, lastcomp, cpuid, sz_strings, sz_struct) = struct.unpack_from(">10I", blob, 0)
    assert magic == FDT_MAGIC, "FDT magic 错误"
    assert off_struct + sz_struct == off_strings, "结构块/字符串块不连续"
    assert off_strings + sz_strings == total, "totalsize 与块长度不符"
    strs = blob[off_strings:off_strings + sz_strings]
    pos, path, out = off_struct, [], {}
    while pos < off_struct + sz_struct:
        tok = struct.unpack_from(">I", blob, pos)[0]
        pos += 4
        if tok == FDT_BEGIN:
            end = blob.index(b"\x00", pos)
            name = blob[pos:end].decode()
            pos = (end + 1 + 3) & ~3
            path.append(name)
            out.setdefault("/".join(path), {})
        elif tok == FDT_END_NODE:
            path.pop()
        elif tok == FDT_PROP:
            ln, no = struct.unpack_from(">II", blob, pos)
            pos += 8
            v = blob[pos:pos + ln]
            pos = (pos + ln + 3) & ~3
            end = strs.index(b"\x00", no)
            out.setdefault("/".join(path), {})[strs[no:end].decode()] = v
        elif tok == FDT_END:
            break
        elif tok == FDT_NOP:
            pass
        else:
            raise ValueError("非法 FDT token 0x%x @0x%x" % (tok, pos - 4))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="bootfiles 目录")
    ap.add_argument("--resource", default="", help="Hinas 基线 resource.img（可选）")
    ap.add_argument("--out", required=True, help="输出 boot_fit.img")
    ap.add_argument("--desc-out", default="", help="额外导出 FIT 描述段供 dtc 校验")
    ap.add_argument("--max-mb", type=int, default=64, help="boot 分区上限 MB")
    args = ap.parse_args()

    def rd(rel):
        with open(os.path.join(args.src, rel), "rb") as fh:
            return fh.read()

    dtb = rd("dtb/rockchip/rk3566-oec-box-wxy4.dtb")
    kernel = rd("Image")
    ramdisk = rd("uInitrd")
    resource = open(args.resource, "rb").read() if args.resource else None

    pos_fdt = 0x1000
    pos_kernel = align4k(pos_fdt + len(dtb))
    pos_ramdisk = align4k(pos_kernel + len(kernel))
    pos_resource = align4k(pos_ramdisk + len(ramdisk))
    total_size = align4k(pos_resource + (len(resource) if resource else 0))

    spec = [
        ("fdt", pos_fdt, dtb, dict(type="flat_dt", load=LOAD_FDT)),
        ("kernel", pos_kernel, kernel,
         dict(type="kernel", os="linux", load=LOAD_KERNEL, entry=LOAD_KERNEL)),
        ("ramdisk", pos_ramdisk, ramdisk,
         dict(type="ramdisk", os="linux", load=LOAD_RAMDISK)),
    ]
    if resource:
        spec.append(("resource", pos_resource, resource, dict(type="multi")))

    images, chunks = [], []
    for name, pos, data, extra in spec:
        d = dict(name=name, pos=pos, size=len(data),
                 sha256=hashlib.sha256(data).digest())
        d.update(extra)
        images.append(d)
        chunks.append((pos, data))

    fit = build_fdt(images, total_size)
    assert len(fit) <= 0x1000, "FIT 描述超过 4KB: %d" % len(fit)
    assert total_size <= args.max_mb * 1024 * 1024, \
        "超出 boot 分区: %d > %d MB" % (total_size, args.max_mb)

    out = bytearray(total_size)
    out[0:len(fit)] = fit
    for pos, data in chunks:
        out[pos:pos + len(data)] = data
    with open(args.out, "wb") as fh:
        fh.write(bytes(out))

    if args.desc_out:
        with open(args.desc_out, "wb") as fh:
            fh.write(fit + b"\x00" * (0x1000 - len(fit)))

    # ---- 回读校验 ----
    with open(args.out, "rb") as fh:
        chk = fh.read()
    assert len(chk) == total_size
    props = parse_props(chk[:len(fit)])
    assert struct.unpack(">I", props[""]["totalsize"])[0] == total_size
    for name, pos, data, _ in spec:
        p = props["/images/" + name]
        assert struct.unpack(">I", p["data-position"])[0] == pos
        assert struct.unpack(">I", p["data-size"])[0] == len(data)
        assert chk[pos:pos + len(data)] == data
        h = props["/images/" + name + "/hash"]
        assert h["algo"] == b"sha256\x00"
        assert h["value"] == hashlib.sha256(data).digest()
    assert props["/configurations"]["default"] == b"conf\x00"
    print("=== boot_fit.img 构造完成 ===")
    print("  输出       : %s" % args.out)
    print("  长度       : %d 字节 (%.2f MiB)，root.totalsize=0x%x" %
          (total_size, total_size / 1048576, total_size))
    print("  FIT 描述   : %d 字节 @0x0 (前 4KB)" % len(fit))
    for name, pos, data, extra in spec:
        print("  %-9s : @0x%08x  %9d 字节  type=%-9s %s" %
              (name, pos, len(data), extra["type"],
               ("load=0x%x" % extra["load"]) if extra.get("load") else ""))
    print("  写入地址   : LBA 0x00008000 (boot 分区, 0x8000~0x27FFF)")
    print("  占用扇区   : %d (结束 LBA 0x%x)" %
          (total_size // 512, 0x8000 + total_size // 512))
    print("  sha256     : %s" % hashlib.sha256(bytes(out)).hexdigest())
    print("  ✅ FDT 结构 / totalsize / data-position / data-size / sha256 回读全部通过")


if __name__ == "__main__":
    main()
