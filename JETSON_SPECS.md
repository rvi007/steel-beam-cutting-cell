# Jetson specs (the user's local machine)

Read from the board on 2026-10-03. This is where the Arduino, servo, knob and 3D
windows run. Cloud sessions can't reach it, so write code that fits these limits.

## Hardware
| Part | Spec |
|---|---|
| Board | NVIDIA Jetson Orin Nano Developer Kit **Super** |
| CPU | 6-core Arm Cortex-A78AE, up to 1.73 GHz (aarch64) |
| GPU | NVIDIA Ampere, up to 1.02 GHz in Super mode |
| RAM | **4 GB** (3.4 GB usable), shared by CPU and GPU |
| Swap | 1.7 GB zram (compressed RAM) |
| Power mode | `MAXN_SUPER` (fastest) |

The 3.4 GB of usable RAM points to the 4 GB Orin Nano. NVIDIA's spec sheet for that
model lists 512 CUDA cores, 16 tensor cores and about 34 TOPS in Super mode
(spec-sheet figures, not measured on this board).

## Storage
| Item | Detail |
|---|---|
| Drive | 256 GB NVMe SSD, EDILOCA EN605 (238.5 GB usable) |
| Root `/` | `nvme0n1p1`, ext4, 233 GB: **30 GB used, 191 GB free (14%)** |
| `/boot/efi` | `nvme0n1p10`, vfat, 63 MB |
| Other partitions | 13 small NVIDIA boot/firmware partitions (under 0.5 GB each), no filesystem mounted |
| Space use | `/usr` 21 GB, `/opt` 4.5 GB, `/home/ravi` 2.8 GB, `/var` 1.5 GB |
| SD card | None |

## Software
| Item | Version |
|---|---|
| JetPack | 7.2.1 (Jetson Linux R39.2.1) |
| OS | Ubuntu 24.04.4 LTS, kernel 6.8.12-tegra |
| CUDA | 13.2 |
| TensorRT | 10.16 |
| Python | 3.12.3 |
| Python libs | numpy 1.26.4, matplotlib 3.6.3 (TkAgg), scipy 1.11.4, OpenCV 4.6.0, pyserial 3.5 |
| PyTorch | Not installed |
| arduino-cli | `~/.local/bin/arduino-cli`, board `arduino:avr:uno` |

## Connections
- Internet: Wi-Fi through a phone hotspot (`172.20.10.x`). **Avoid big downloads.**
- Ethernet: not connected.
- Arduino UNO: USB on `/dev/ttyACM0` (group `dialout`).

## Limits to design around
- **Memory is very tight.** When checked, only about 365 MB of RAM was free and the
  1.7 GB swap was full, with the desktop and a 3D window open. Run one GUI program at a
  time and keep scripts light: no big arrays, no heavy plotting loops.
- Only numpy, matplotlib, scipy, OpenCV and pyserial are available. Don't add
  dependencies that need `pip install`.
- matplotlib 3D redraws are the slowest part. The control loops run at about 20 Hz
  (`plt.pause(0.05)`), so don't add work that slows them down.
