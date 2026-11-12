# flashkit — PC 刷机包（与 bootloader/ 分开）

这里放**给 PC 侧使用的刷机包**；引导固件本体的说明在
[../bootloader/l9/](../bootloader/l9/)。

**当前唯一推荐刷机包是本目录根下的 v2 套件**（L9 引导链，2026-11-12 真机验收启动）。
历史版本（L8 刷机套件、v1.0 原始镜像备份）已由 git 版本管理保留：
git 标签 **`archive-l8`**。

## 刷机包文件（v2 / L9 引导链）

| 文件 | 大小 | 写入地址 | 用途 |
|---|---|---|---|
| `01_gpt_bootarea.img` | 9,437,696 B | `0x00000000`（LBA 0 起） | LBA0..18432：保护 MBR + 主 GPT(头+项) + idbloader + U-Boot(L9) + 扩容后的 bootarea |
| `02_boot.img` | 402,653,184 B | `0x00008000` | BOOT 分区（384 MiB）整分区镜像：内核 + initrd + **修复版 DTB**（RGMII 延迟 / SCMI 时钟 / PWM pinctrl / sdmmc0） |
| `03_rootfs.img` | 3,144,679,424 B | `0x000C8000` | rootfs 分区内容（首次启动自动扩容）；**仅整盘重刷时使用**，v2 相对板上现有系统未动 rootfs |
| `04_backup_gpt.img` | 16,896 B | `0x01D1EFDF` | 盘尾备份 GPT（可选；主 GPT 有效时根本不会被读） |
| `SHA256SUMS.txt` | — | — | 四件 sha256（含写入地址注释），写后读回比对用 |

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

### 铁律

- 写物理盘前核对盘号与 15,634,268,160 B 容量；Windows 提示格式化一律拒绝
- 写完断电 ≥10 s（不是 reset）
- 校验不一致就留在刷机模式重写，不要上电

---
