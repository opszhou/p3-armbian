# bootloader/l9 — 当前可用引导固件（2026-11-12 真机验收启动）

主线 U-Boot 2025.10（L9 版），**当前交付版本**。随 v2 刷机包整链真机验收通过：
`U-Boot 2025.10-dirty (Nov 12 2026 - 23:54 构建, L9a)` 启动、rockusb recovery
5 秒窗口在、ITS 一次初始化成功（旧 ITS queue timeout 未复现）、
内核侧 RGMII TX/RX delay 新值生效、eth0 1Gbps 链路 Up。

## 文件

| 文件 | 大小 | sha256（前16） | 写入位置 |
|---|---|---|---|
| `u-boot.itb` | 980,480 B | `9ffb363619742f6a` | eMMC LBA `0x4000`（u-boot proper 槽） |
| `u-boot-rockchip.bin` | 9,336,320 B | `bcf7a37dd647090f` | eMMC LBA `0x40`（idbloader+SPL 起整包，内嵌上面的 itb） |

完整 SHA256 见 `SHA256SUMS.txt`。两个文件来自同一次构建，不要混搭其它版本的 idbloader。

## 构成

- TPL：Rockchip DDR blob `rk3566_ddr_1056MHz_v1.26_ddr4_v2.bin`（与 L8 相同）
- BL31：`rk3568_bl31_v1.46.elf`（与 L8 相同）
- U-Boot proper：主线 v2025.10 + P3 板级全量补丁

全量板级补丁见 [`patches/p3-uboot-v2025.10-full.patch`](patches/p3-uboot-v2025.10-full.patch)，
覆盖：`rk3568-p3.dts` / `board/rockchip/p3/`（Kconfig+board init）、
`P3_LOADER_BOS` / `P3_LOADER_BCDUSB`（Windows 枚举与 Loader 标签）、
串口 `r` 键 recovery（`boot_mode.c`）、`P3_UMS_QUIET` / `P3_UMS_DBG`、
rockusb LOADER 能力层（0x1A/0xAA/0x2A/0x2B）。

## L9 相对 L8 的差异

1. **bootarea 扩容**：u-boot.itb 从 979,968 B 增至 980,480 B，旧 bootarea
   （18297 LBA）差 512 B 装不下。v2 刷机包已把 bootarea 扩到 **18432 LBA**，
   扩容落在 BOOT 分区（LBA 32768）前的空地，GPT 分区表条目零变化。
   配套产物见 [flashkit/](../../flashkit/)。
2. **rockusb 芯片串号回填**（`f_rockusb.c` `cb_get_chip_version`）：
   BootROM 芯片串为空时回填静态串 `"320A" + 2026 + 1112 + V100`，
   rkdeveloptool `0x1B` 不再返回 16 字节全零。
3. **rockusb GET_VERSION 回填**（`f_rockusb.c` 新增 `cb_get_version`）：
   `0x0C` 命令以与 `0x1B` 相同的 16 字节串格式应答 `RK3566LoaderV100`——
   RKDevTool 的「Loader Ver」栏读的就是 0x0C，vendor 仅在闭源 usbplug 实现，
   主线/vendor U-Boot 均未实现，LOADER 模式下该栏一直空白。
4. L8 的全部 LOADER 能力补丁原样保留（详见 ADR-002）。

## 刷写方法

- **推荐**：直接刷 v2 两件套（01_gpt_bootarea.img @0x0 + 02_boot.img @0x8000），
  见 [flashkit/README.md](../../flashkit/README.md)。
- 单独换引导层：`upgrade_tool wl 0x40 u-boot-rockchip.bin`（idbloader 起整包）
  与 UMS 通道仍适用；写后必须读回比对。

**⚠️ 铁律**：与 L8 相同——写物理盘前核对盘号与 15,634,268,160 B 容量；
Windows 提示格式化一律拒绝；写完断电 ≥10 s；`wl` 报 100% 不算成功，必须读回比对。

## 历史版本

L1~L8 演进、事故与决策记录见 `ADR-002-uboot-upgrade.md`（§18 为 L7/L8 事件定案）。
L8 固件本体见 git 标签 `archive-l8`（`bootloader/l8/`）。
