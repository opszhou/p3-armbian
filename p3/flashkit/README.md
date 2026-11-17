# flashkit — PC 刷机包（与 bootloader/ 分开）

这里放**给 PC 侧使用的刷机包**；引导固件本体的说明在
[../bootloader/](../bootloader/)。

两套刷机包并行可用，二选一：

- **v2 套件**（L9 引导链，2026-11-12 真机验收启动）
- **L10 双模式套件**（ophub 系引导链，2026-11-17 真机验证）

历史版本（L8 刷机套件、v1.0 原始镜像备份）已由 git 版本管理保留：
git 标签 **`archive-l8`**。

## 刷机包文件（v2 / L9 引导链）

| 文件 | 大小 | 写入地址 | 用途 |
|---|---|---|---|
| `01_gpt_bootarea.img` | 9,437,696 B | `0x00000000`（LBA 0 起） | LBA0..18432：保护 MBR + 主 GPT(头+项) + idbloader + U-Boot(L9) + 扩容后的 bootarea |
| `02_boot.img` | 402,653,184 B | `0x00008000` | BOOT 分区（384 MiB）整分区镜像：内核 + initrd + **修复版 DTB**（RGMII 延迟 / SCMI 时钟 / PWM pinctrl / sdmmc0） |
| `03_rootfs.img` | 3,144,679,424 B | `0x000C8000` | rootfs 分区内容（首次启动自动扩容）；**仅整盘重刷时使用**，v2 相对板上现有系统未动 rootfs |
| `04_backup_gpt.img` | 16,896 B | `0x01D1EFDF` | 盘尾备份 GPT（可选；主 GPT 有效时根本不会被读） |
| `SHA256SUMS.txt` | — | — | sha256（含写入地址注释），写后读回比对用 |

> **体积原因**：`02_boot.img`（402 MB）、`03_rootfs.img`（3.1 GB）与整盘一体包
> `p3_armbian_v2_full.img.gz`（1.16 GiB）不入 git，在 **Releases** 下载。
> git 里只保留小件（01、04、校验和、文档）。

### 刷机（RKDevTool，2 行配置）

进入刷机模式（串口上电窗口按 `r`，或 `=>` 下敲 `recovery` / `rockusb 0 mmc 0`，
RKDevTool 显示**发现 LOADER 设备**），Download Image 页勾选**强制按地址写**：

| 勾选 | 地址 | 文件 |
|---|---|---|
| [x] | `0x00000000` | `01_gpt_bootarea.img` |
| [x] | `0x00008000` | `02_boot.img` |
| [ ] | `0x01D1EFDF` | `04_backup_gpt.img`（备份 GPT，可选） |

rootfs 未损坏时**只刷前两行**。命令行等价：

```bat
upgrade_tool.exe wl 0x0 01_gpt_bootarea.img
upgrade_tool.exe wl 0x8000 02_boot.img
```

### 写后校验（防假成功，必须做）

`wl` 报 100% ≠ 写入落地。读回比对 sha256，一致才断电重启：

```bat
upgrade_tool.exe rl 0 18432 dev_readback1.bin
upgrade_tool.exe rl 32768 786432 dev_readback2.bin
certutil -hashfile dev_readback1.bin SHA256   :: 应等于 01_gpt_bootarea.img 的 sha256
certutil -hashfile dev_readback2.bin SHA256   :: 应等于 02_boot.img 的 sha256
```

`dev_readback*.bin` 是一次性校验临时文件，比对完即删。详细流程见 `CHANGELOG.txt`。

## 刷机包文件（L10 双模式套件）

| 文件 | 大小 | 写入地址 | 用途 |
|---|---|---|---|
| `01_gpt_bootarea_l10h.img` | 9,437,696 B | `0x00000000` | 分区表 + 引导段内嵌 **L10-H**（日常用，可 U 盘启动） |
| `01_gpt_bootarea_l10g.img` | 9,437,696 B | `0x00000000` | 分区表 + 引导段内嵌 **L10-G**（要 rockusb 反复刷机用） |
| `02_boot.img`（L10 版） | 402,653,184 B | `0x00008000` | BOOT 分区整镜像：6.12.81-rk35xx-flippy 内核（MPP 硬解全开）+ **RGMII 魔数已修 dtb**（tx=0x22 / rx=0x15） |
| `03_rootfs.img`（L10 版） | 1,180,696,576 B | `0x000C8000` | rootfs（首次启动自动扩容），配套 6.12.81 模块，**内置 dtbfix 开机自愈**（eth0 拿不到 IP 时自动重扫魔数并重启，最多尝试 2 次） |
| `p3_armbian_slim.img` | 1,678,770,176 B | — | U 盘整盘镜像（Rufus / Etcher 写 U 盘做 U 盘系统）；rootfs 分区首启自动扩满整盘 |
| `p3boot` | 1,521 B | — | U 盘 / eMMC 启动目标切换脚本（`p3boot usb` / `emmc` / `clear` / `status`，跑在盒子 U-Boot 环境里） |
| `04_backup_gpt.img` | 16,896 B | `0x01D1EFDF` | 与 v2 共用同一份盘尾备份 GPT |

> **体积原因**：L10 版 `02_boot.img`（402 MB）、`03_rootfs.img`（1.10 GB）与
> `p3_armbian_slim.img`（1.56 GB）不入 git，在 **Releases**（tag `flashkit_l10`）下载。
> git 里只保留小件。

### 01 两个版本的区别（二选一）

分区表部分完全相同，区别只在引导段（`0x40` 起）内嵌 L10-H 还是 L10-G：

| 刷完想怎么用 | 用哪个 |
|---|---|
| 日常使用、以后可能从 U 盘启动 / 双系统 | `01_gpt_bootarea_l10h.img`（默认） |
| 以后还要经常用电脑 rockusb 刷机 | `01_gpt_bootarea_l10g.img` |

选好 01 后一般无需再单独刷引导；单独刷 `u-boot-L10-*.bin` 也不会动分区表
（详见 [../bootloader/](../bootloader/)）。

### 刷机（upgrade_tool，3 行配置）

进入刷机模式：G 模式下盒子接 USB 到电脑，串口 3 秒内按 `r` 看到
`Entering rockusb loader`，`upgrade_tool.exe ld` 出现 `... Loader` 即就绪：

```bat
upgrade_tool.exe db  ..\bootloader\MiniLoaderAll_p3_l1.bin
upgrade_tool.exe wl  0x0      01_gpt_bootarea_l10h.img   :: 要 rockusb 反复刷机换 _l10g
upgrade_tool.exe wl  0x8000   02_boot.img
upgrade_tool.exe wl  0xC8000  03_rootfs.img
```

- 顺序不能乱：`0x0 → 0x8000 → 0xC8000`；只刷引导和内核时刷前两行即可。
- 03_rootfs.img 1.10 GB，读回校验约 1 分钟。

### 写后校验

读回比对 sha256，一致才断电重启（读回长度 = 镜像字节数 / 512 个扇区）：

```bat
upgrade_tool.exe rl 0      18433 dev_readback1.bin
upgrade_tool.exe rl 32768  786432 dev_readback2.bin
upgrade_tool.exe rl 819200 2306048 dev_readback3.bin
certutil -hashfile dev_readback1.bin SHA256   :: 应等于 01_gpt_bootarea_l10h.img 的 sha256
certutil -hashfile dev_readback2.bin SHA256   :: 应等于 02_boot.img（L10）的 sha256
certutil -hashfile dev_readback3.bin SHA256   :: 应等于 03_rootfs.img（L10）的 sha256
```

### 铁律

- 写入过程绝对不能断电；刷完断电 ≥10 s 再上电（不是 reset）
- 写物理盘前核对盘号与 15,634,268,160 B 容量；Windows 提示格式化一律拒绝
- 校验不一致就留在刷机模式重写，不要上电

---
