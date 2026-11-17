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

## flashkit/ — PC 刷机包（v2 / L9 引导链）

| 文件 | 写入地址 |
|---|---|
| `01_gpt_bootarea.img` | `0x00000000`（git 内） |
| `04_backup_gpt.img` | `0x01D1EFDF`（git 内） |
| `02_boot.img`（402 MB） | `0x00008000`（Releases 下载） |
| `03_rootfs.img` | `0x000C8000`（仅整盘重刷） |

刷写流程、校验铁律、真机验收记录见 [flashkit/CHANGELOG.txt](flashkit/CHANGELOG.txt)
（全 ASCII）与 [flashkit/README.md](flashkit/README.md)。

## bootloader/l9/ — 引导固件

主线 U-Boot 2025.10（L9），`u-boot.itb` 980,480 B（sha `e2062ff9c4612c70`）+
`u-boot-rockchip.bin` 9,336,320 B（sha `abcb3d3c862fb73e`）；全量板级补丁见
[bootloader/l9/patches/](bootloader/l9/patches/)（rk3568-p3 板级、LOADER BOS/BCDUSB、
串口 recovery、UMS 降噪、rockusb 芯片串号回填）。

## scripts/ — 构建与板上工具

整盘组装 `build_armbian_compact_v2.py`、DTB 补丁 `patch_dtb_delays.py`、
L4~L9 分层注入脚本、板上 GRF 直写扫描器 `board/rxdelay_scan.py`。
索引见 [scripts/README.md](scripts/README.md)。
