# p3-armbian — 蜂助手 P3 (RK3566) 专属仓库

**设备**：蜂助手 P3 / 网心云 OEC-turbo-4g（RK3566 / 2GB DDR4 / 16GB eMMC）
**当前系统**：Armbian 26.11 noble，自编补丁内核 `6.12.81-ophub`（真机全项验证：显示 / HDMI 音频 / CEC / 千兆网络 / MPP 硬解）

本仓库从 ophub/amlogic-s9xxx-armbian fork 而来，已按 P3 为本重构：只保留内核构建框架
（`compile-kernel/`）和 GPL 许可来自上游，其余 ophub 构建框架（armbian 镜像构建、rebuild
工具、文档）已移除。固件流水线完全自研，不再依赖 ophub 的 rebuild 工具链。

## 目录结构

| 目录 | 内容 | 来源 |
|---|---|---|
| `.github/workflows/` | 四条流水线（见下） | 自研 |
| `flashkit/` | PC 刷机包：01 引导二选一、p3boot、README、校验清单 | P3 |
| `bootloader/` | 引导固件 L9（主线 U-Boot 2025.10）/ L10 双模式 + MiniLoader | P3 |
| `kernel-config/` | 自编内核配置模板（rk35xx，裁 psci_checker） | P3 |
| `kernel-patches/` | 三个内核补丁（dts 魔数/运行时应用/开机自检） | P3 |
| `scripts/` | bootloader 构建辅助脚本 | P3 |
| `board/` | 板卡数据库（P3-WXY4 条目，KERNEL_TAGS 白名单等） | 从 ophub 取需 |
| `compile-kernel/` | 内核 CI 构建框架（docker 工具链） | 上游保留 |
| `LICENSE` | GPL 许可 | 上游保留 |

## 流水线（全部中文名，链式触发）

```
合并官方 (Sync Upstream)   合并 ophub 上游变更 → 自动派发构建固件
编译内核 (Build Kernel)    rockchip 树 + kernel-config + 三补丁 → kernel_stable Release
                           → 成功后自动派发构建固件
构建固件 (Build Firmware)  自研：kernel_stable 内核包注入基座（02/03）→ flashkit 布局重组
                           → 01/02/03/slim + SHA256SUMS → firmware_YYYY.MM Release
清理历史 (Cleanup)
```

- **内核出包**：Actions → 编译内核 → Run（默认 `unifreq/linux-6.12.y-rockchip@main`）
- **固件出包**：Actions → 构建固件 → Run（默认自动取 kernel_stable 最新版本；基座默认 `flashkit_l10`）
- 内核变更 → 编译内核 → 自动触发构建固件，全程无需本地打包

## flashkit — 刷机包

| 文件 | 写入地址 |
|---|---|
| `01_gpt_bootarea_l10h.img` / `_l10g.img`（二选一） | `0x00000000` |
| `02_boot.img` | `0x00008000` |
| `03_rootfs.img` | `0x000C8000` |
| `p3_armbian_slim.img.gz` | Etcher 写 U 盘 |
| `p3boot` | U 盘 / eMMC 启动切换 |

刷写流程与校验铁律见 [flashkit/README.md](flashkit/README.md)。
（完整刷机教程在用户侧仓库，含 G/H 模式判断、串口排错等。）

## 内核补丁（kernel-patches/common-kernel-patches/）

1. **0001 板级 dts**：启用 HDMI / display-subsystem / i2s0_8ch，gmac1 魔数 0x22/0x15 出厂即对
2. **0002 dwmac-rk-tool**：`phy_lb_scan` 扫描后运行时应用最优 delayline（无需重启）
3. **0003 开机自检**：回环测试 dtb delayline，失败自动 cross-scan 自愈（不依赖外部网络）

## 板卡数据库（board/model_database.conf）

P3-WXY4 条目：`KERNEL_TAGS = stable/6.12.y_6.18.y`（内核版本白名单，新增内核系列时要同步放行）、
`BOARDFAMILY = rk3566`、extlinux 引导。
