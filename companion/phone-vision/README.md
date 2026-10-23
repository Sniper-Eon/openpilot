# C3 手机视觉桥接部署与连接码

手机运行车辆检测、跟踪和实验速度估算。C3 负责读取原有广角帧、按需缩放 / JPEG、认证和结果校验；这些工作会使用部分 C3 CPU。没有把检测网络搬回 C3。本项目保持 shadow，输出 `/dev/shm/phone_side_vehicles.json`，不启用新的变道干预。

## 首次配置自己的 C3

先把本分支工程准备在设备 `/data/openpilot`。实际启动、重启和手机安装在停车挂 P 时进行。

1. 检查 C3 `/usr/local/venv/bin/python` 和本分支的 `msgq.visionipc` 等原生依赖已可导入。
2. 在 C3 执行初始化，保留已存在的连接码、ROI 和辅助模式设置；已有脚本会备份：

```sh
cd /data/openpilot/companion/phone-vision
/usr/local/venv/bin/python install.py
```

3. 为独立桥接准备依赖。如果本机现有环境已经能导入 `cv2` 与 `numpy`，不需要重复安装。需要时用本机可用的 pip / uv 将 `c3/requirements.txt` 安装至 `/data/phone-vision/pydeps`，不要替换 C3 主环境依赖。例如本机 Python 提供 pip 时：

```sh
/usr/local/venv/bin/python -m pip install --target /data/phone-vision/pydeps -r c3/requirements.txt
PYTHONPATH=/data/phone-vision/pydeps:/data/wide-capture/pydeps:/data/openpilot /usr/local/venv/bin/python -c 'import cv2, numpy; from msgq.visionipc import VisionIpcClient; from openpilot.cereal import messaging'
```

4. 驻车启动服务。这个命令使用设备现有免密 sudo 将服务放在 `/run`，不改写系统只读分区：

```sh
/data/phone-vision/ensure_bridge.sh
sudo -n systemctl status phone-vision-bridge.service --no-pager
```

5. 本机读取自己的码：

```sh
cat /data/phone-vision/connection-code
```

APP → 手机侧方车辆识别：地址填自己 C3 的 IP 或本机可解析的主机名，连接码填上面的完整内容，选择开始手机运算。默认服务端口 8767，同一局域网下须可访问。这个码是本设备服务的随机密钥，不是无线 ADB 配对码。

## 重启后自动启动

`/run` 中的服务重启后会消失，需要设备持久启动入口在网络启动后调用 `/data/phone-vision/ensure_bridge.sh`。发布工具**没有自动改写 `/data/continue.sh`**。让维护 AI 先检查该文件现有流程并备份，在最终 `exec` 前加入这条有界启动调用；保留原启动内容、已有挂载与控制逻辑，不能盲目覆盖或把命令追加在永远到不了的 `exec` 后面。已配置的设备不要重复加入。

## 连接异常定位

- 401 / 403：检查手机连接码与当前这台 C3 文件一致。
- 连接超时：检查地址、Wi-Fi、8767 端口和服务是否运行。
- 等待相机：查看 camerad 与原生广角输出状态。不能用旧图、改时间戳或伪造点火信号让它显示在线。
- 结果失效：800 ms 时间门限保留；读取端把过期或缺失结果视作未知。

日志：`sudo -n journalctl -u phone-vision-bridge.service -n 80 --no-pager`。服务会自动重启，但相机没启动时仍需要等待真实新画面。原有 ROI 配置优先保留，缺失时的样例仅用于初始观察，须按本车相机安装位置复核。

回退前停止服务并恢复 `/data/phone-vision/backups/` 中同一批备份；不要通过删除个人连接码或清空手机数据排障。
