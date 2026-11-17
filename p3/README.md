# p3/ — 蜂助手 P3 (RK3566) 专属内容

本目录集中存放 P3 板级资产，与上游 ophub/amlogic-s9xxx-armbian 的目录完全隔离，
`sync-upstream` workflow rebase 上游时不会冲突。内部权威仓：
`http://192.168.0.110:3000/zhouxiaochen/p3-image-builder`（结构更完整，含 ADR 文档）。

## kernel-config/rk35xx/ — 自编内核模板

`config-6.12` 基于 ophub `kernel-config/release/rk35xx/config-6.12`，**唯一改动**：

- `CONFIG_ARM_PSCI_CHECKER=y` → `# CONFIG_ARM_PSCI_CHECKER is not set`
  （psci_checker 每次开机热插拔全部 CPU 做自检，纯调试功能，裁掉）

配套 workflow：`.github/workflows/compile-kernel-p3.yml`（基于上游 compile-kernel.yml，
新增 `kernel_config` 输入透传给 `ophub/amlogic-s9xxx-armbian` action，
默认版本 6.12.y，产物上传到 Release tag `kernel_p3`）。

**出包流程**：Actions → "Compile P3 kernel (no PSCI checker)" → Run workflow
（kernel_source=ophub, kernel_version=6.12.y）→ Releases 的 `kernel_p3` tag
下载 boot 包 → 板上解包替换 `/boot`（局域网部署，无需重刷引导层）。

## flashkit/ — PC 刷机包（v2 / L9 + L10 双模式）

| 文件 | 写入地址 |
|---|---|
| `01_gpt_bootarea.img`（L9） | `0x00000000`（git 内） |
| `01_gpt_bootarea_l10h.img` / `_l10g.img`（L10 二选一） | `0x00000000`（git 内） |
| `04_backup_gpt.img` | `0x01D1EFDF`（git 内，两套共用） |
| `02_boot.img`（两套各一份，402 MB） | `0x00008000`（Releases 下载） |
| `03_rootfs.img`（L10，1.10 GB，内置 dtbfix 开机自愈） | `0x000C8000`（Releases，仅整盘重刷） |
| `p3_armbian_slim.img`（L10 U 盘整盘，1.56 GB） | Etcher 写 U 盘（Releases，首启自动扩满整盘） |
| `p3boot` | U 盘 / eMMC 启动目标切换脚本 |

刷写流程、校验铁律、真机验收记录见 [flashkit/README.md](flashkit/README.md)、
[flashkit/CHANGELOG.txt](flashkit/CHANGELOG.txt)（全 ASCII）与
`SHA256SUMS.txt`（含写入地址注释）。

## bootloader/ — 引导固件（L9 / L10）

**L9**：主线 U-Boot 2025.10，`u-boot.itb` 980,480 B（sha `9ffb363619742f6a`）+
`u-boot-rockchip.bin` 9,336,320 B（sha `bcf7a37dd647090f`）；全量板级补丁见
[bootloader/patches/](bootloader/patches/)（rk3568-p3 板级、LOADER BOS/BCDUSB、
串口 recovery、UMS 降噪、rockusb 芯片串号回填）。

**L10**：ophub 系双模式引导（G = rockusb 刷机 / H = U 盘启动，互斥，写入 `0x40`），
`u-boot-L10-H.bin` / `u-boot-L10-G.bin` 各 9,402,880 B +
`MiniLoaderAll_p3_l1.bin`（rockusb `db` 用 loader，不写盘）。

两条引导链独立，不共用 idbloader，不要混搭。详见 [bootloader/README.md](bootloader/README.md)。

## scripts/ — 构建与板上工具

整盘组装 `build_armbian_compact_v2.py`、DTB 补丁 `patch_dtb_delays.py`、
L4~L9 分层注入脚本、板上 GRF 直写扫描器 `board/rxdelay_scan.py`。
索引见 [scripts/README.md](scripts/README.md)。
