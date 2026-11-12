# scripts — 构建与维护脚本（2026-11-12 自容器 /root/p3builder 同步入库）

## 当前主力

| 脚本 | 用途 |
|---|---|
| `build_armbian_compact_v2.py` | **v2 整盘组装**：GPT + bootarea 扩容（18297→18432 LBA，扩在 BOOT 分区前空地）+ boot 分区 + rootfs 拼装，输出 01/02/03/04 四件切片与 `SHA256SUMS.txt`、整盘 `p3_armbian_v2_full.img.gz`。v2 套件即由它生成，已真机验收 |
| `patch_dtb_delays.py` | DTB u32 属性原地补丁（RGMII tx_delay/rx_delay 等），自动处理 FDT 结构并备份 `.orig` |
| `build_boot_fit.py` | 手搓 FIT 构建与结构校验（vendor 时代遗产，现为参考实现） |

## 历史分层注入脚本（L4~L9 演进记账，ADR-002）

| 脚本 | 层 |
|---|---|
| `apply_l4_trigger.py` | L4 |
| `apply_l5_storage.py` | L5 |
| `apply_l6_storage_bit.py` | L6 |
| `apply_l7_bcdusb.py` | L7（bcdUSB/BOS 事件） |
| `apply_l9_part1.py` | L9（bootarea 扩容 + 新 itb 拼接） |
| `apply_rockusb_patch.py` / `fix_l3_conflict.py` | rockusb 能力层 / L3 冲突修复 |

U-Boot 全量板级补丁的权威源在 [../bootloader/l9/patches/](../bootloader/l9/patches/)。

## board/ — 板上运行的工具

| 脚本 | 用途 |
|---|---|
| `board/rxdelay_scan.py` | GRF 直写（`/dev/mem` + mmap）+ 128 档 RGMII 延迟扫描器：自造 ARP 广播刺激 + 计数差判据，先钉 TX 再扫 RX。本仓版本为本地备档同步 |
| `board/fixdelay.py`（未入库） | 板上 DTB 原地改 `rx_delay`/`tx_delay`（ext4 写入无需重刷引导层），自动备份 `.orig`。与 `patch_dtb_delays.py` 逻辑同源，原始副本留在板上 `/root/`，如需回收经串口取出 |

## 遗留说明

`assemble.py` / `make_env.py` 为早期实验实现，保留作参考；
整盘组装的当前权威路径是 `build_armbian_compact_v2.py`。
