#!/usr/bin/env python3
# RK3566 GMAC1 rx_delay 运行时扫描器（无需重启）
# 原理: 直写 PHP_GRF+0x0388 CON0 的 rx_delay[14:8]，高16位写使能只动 rx 字段；
#       刺激 = P3 广播 ARP(请求192.168.10.1) -> OpenWrt 单播回复；
#       计数 = /sys/class/net/eth0/statistics/rx_packets 增量(即 MAC 层好帧)。
# 用法: python3 /root/rxdelay_scan.py
import os, sys, time, mmap, struct, socket

IFACE = "eth0"
DT = "/sys/firmware/devicetree/base"
GMAC1_CON0 = 0x0388          # PHP_GRF 偏移: rx_delay[14:8], tx_delay[6:0]
RX_SHIFT, RX_MASK = 8, 0x7F  # 7bit 延迟线
TX_EXPECT = 0x4f

def rd(path):
    with open(path, "rb") as f:
        return f.read()

# --- 通过运行时设备树定位 GRF 基址，不猜 ---
ph = struct.unpack(">I", rd(DT + "/ethernet@fe010000/rockchip,grf"))[0]
base = grf_name = None
for name in os.listdir(DT):
    node = os.path.join(DT, name)
    pf = os.path.join(node, "phandle")
    if os.path.isdir(node) and os.path.exists(pf) and \
       struct.unpack(">I", rd(pf))[0] == ph:
        reg = rd(os.path.join(node, "reg"))
        base = struct.unpack(">QQ", reg[:16])[0] if len(reg) >= 16 \
               else struct.unpack(">II", reg[:8])[0]
        grf_name = name
        break
if not base:
    sys.exit("!! 找不到 GRF 节点")

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
mm = mmap.mmap(fd, 0x1000, offset=base & ~0xFFF)
OFF0 = (base & 0xFFF) + GMAC1_CON0

con0 = struct.unpack_from("<I", mm, OFF0)[0]
rx_cur = (con0 >> RX_SHIFT) & RX_MASK
tx_cur = con0 & 0x7F
print("GRF=%s @0x%08x  CON0=0x%08x  rx=0x%02x tx=0x%02x" %
      (grf_name, base, con0, rx_cur, tx_cur))
if tx_cur != TX_EXPECT:
    sys.exit("!! tx_delay=0x%02x 与预期 0x4f 不符, 寄存器定位可疑, 中止" % tx_cur)

def set_rx(v):
    # 高16位 = 写使能掩码，只动 rx 字段，tx 字段保持原值
    struct.pack_into("<I", mm, OFF0,
                     (RX_MASK << (RX_SHIFT + 16)) | (v << RX_SHIFT))

# --- ARP 自激刺激 ---
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
s.bind((IFACE, 0))
SMAC = bytes.fromhex(
    rd("/sys/class/net/%s/address" % IFACE).decode().strip().replace(":", ""))

def arp():
    return (b"\xff" * 6 + SMAC + struct.pack(">H", 0x0806) +
            struct.pack(">HHBBH", 1, 0x0800, 6, 4, 1) + SMAC +
            socket.inet_aton("192.168.10.9") + b"\x00" * 6 +
            socket.inet_aton("192.168.10.1"))

def rxpkts():
    return int(open("/sys/class/net/%s/statistics/rx_packets" % IFACE).read())

def probe(v, n=20):
    set_rx(v)
    time.sleep(0.2)
    idle0 = rxpkts(); time.sleep(0.4)
    noise = rxpkts() - idle0          # 背景流量扣除
    b = rxpkts()
    for _ in range(n):
        s.send(arp()); time.sleep(0.02)
    time.sleep(0.5)
    return max(rxpkts() - b - noise, 0)

res = {}
print("扫描 0x00..0x7f ...", flush=True)
for v in range(0x80):
    g = probe(v)
    res[v] = g
    print("rx_delay=0x%02x  %2d/20 %s" % (v, g, "#" * g), flush=True)

top = sorted(res, key=lambda k: -res[k])[:6]
print("复测候选:", " ".join("0x%02x" % v for v in top), flush=True)
final = {}
for v in top:
    g = probe(v, n=50)
    final[v] = g
    print("rx_delay=0x%02x  %2d/50" % (v, g), flush=True)

best = max(final, key=lambda k: final[k])
print("== 最佳 rx_delay = 0x%02x (%d/50) ==" % (best, final[best]))
print("固化: python3 /root/fixdelay.py rx_delay 0x%02x && reboot" % best)
