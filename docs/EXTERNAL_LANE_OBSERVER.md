# Mac 外接车道观察器（显示验证版）

Comma 每秒导出一张经过尺寸限制的广角彩色图像；Mac 的独立 Python 服务运行 YOLOPv2 车道线/可行驶区域分割，再返回可见车道的本车相对位置。该结果仅供 HUD 显示，不进入 DesireHelper、导航变道协调器、规划器、CAN 或 Panda。

**本版输出的是“外接可见 2/4”等局部估计，不是整幅道路的绝对第几车道。** 分割模型没有可靠区分道路边界、对向车道和路肩的能力，因此 `absolute_confirmed` 恒为 false。四条主模型线的限制不再限制外接观察器的检测条数，但不能把检测到的最外侧车道线直接当作道路边界。尚未完成本车广角行驶数据的标注准确率验证或与大驾驶模型并行的时延验证。

## 数据与运行条件

- 原 Jetlink 协议、图像尺寸、推理响应和子模块版本保持不变。此组件使用单独的局域网 HTTP 通道，要求 Mac 和 Comma 在同一可互通的 WiFi/手机热点下。USB Jetlink 连接本身不提供此通道。
- 配对后通过 UDP 7789 的新鲜随机挑战和 HMAC 签名发现 Mac，避免热点切换后的固定 IP 问题。HTTP 7788 使用独立随机配对密钥；广播不会发送密钥。热点如隔离客户端或禁止广播，需要先解决局域网互通，或使用已确认可达的私有 IP 并明确设置 `discovery=false`。自动发现模式不会回退到可能已被其他设备占用的旧 IP。
- C3XL、Tesla、行驶状态、有效广角标定和健康主模型同时满足时才启动发送。未配对（没有配置文件）时不启动。
- 默认 CPU 两个线程、较低进程优先级，最多 1 Hz；不在 Comma 上安装 Torch。
- Comma 先缩小 NV12 图像再转彩色/JPEG，最长边宽 960，JPEG 至多 250 KB。处理带 stride 和 UV padding 的真实 VisionBuf 布局。
- 主模型执行时间超过 45 ms、掉帧百分比超过 5%、图像老于 250 ms 或标定不可用时暂停发送并清除额外观察结果。这是附加负载保护，不代表已证明并行运行没有影响。
- 主机只允许一个识别请求执行；繁忙时返回 429，不堆积图像。HTTP 连接和读取超时分别为 250 ms、1 s。
- 返回值必须与当前 session、sequence、相机帧编号、拍摄单调时钟、标定参考点和相机类型一致。拍摄到展示超过 2 s 即失效，跨电脑时钟不参与判断。
- 连续三次可见编号一致后才显示。外接识别范围比本地可靠结果窄时保留本地结果；左右虚实线仍来自原本的本地观察。置信分数是启发式质量分数，不是已校准概率。

## Mac 安装与启动

在仓库根目录、独立 Python 3.12 环境中执行：

```sh
python -m pip install -r openpilot/sunnypilot/lane_topology/external/requirements-host.txt
python -m openpilot.sunnypilot.lane_topology.external.fetch_model /path/to/yolopv2.pt
python -m openpilot.sunnypilot.lane_topology.external.server \
  --weights /path/to/yolopv2.pt --token-file /path/to/private-token \
  --bind 0.0.0.0 --threads 2
```

密钥文件包含随机 256 bit 十六进制密钥，权限 0600。Comma 的 `/data/navassist/external_lane.json`（0600）配置为：

```json
{"url":"http://192.168.1.2:7788","discovery":true,"token":"与主机相同的独立随机密钥"}
```

配置只在观察进程启动时读取。不得把密钥文件、设备配置或模型权重提交到 Git。删除 Comma 配置后，进程管理器会停止额外观察器；界面中的额外观察在两秒内失效。

`GET /health` 返回服务就绪、累计处理帧数和最近一次推理耗时，不包含配对密钥、道路图像或定位坐标。

## 回放验证

```sh
python tools/replay_external_lanes.py /path/to/image.jpg \
  --weights /path/to/yolopv2.pt --output /path/to/replay \
  --ego-x 0.5 --ego-y 0.65
```

也支持视频文件，最多取 30 帧（约每秒一帧）。输出标注图、逐帧 JSON 和推理耗时统计。离线参考点由参数显式指定，不能作为真实相机标定。真实运行从标定旋转、相机内参和道路高度估计投影十米前的本车中心。

先检查清晰多车道、近车遮挡、道路增减、弯道、夜间、雨天，以及断网、Mac 休眠、主模型忙等场景。当前只验证显示路径；任何未来控制接入都需要单独设计和实际数据验证。

## 模型来源

上游：[CAIC-AD/YOLOPv2](https://github.com/CAIC-AD/YOLOPv2)，TorchScript 发布版本 `V0.0.1/yolopv2.pt`。上游项目 MIT 许可证副本见 `docs/third_party/YOLOPv2-LICENSE.txt`。权重由上游下载，不随本仓库分发。

- 字节数：156380200。
- SHA-256：`f2a8c8374203ae3e67ff9c184e931f763957de92a993b23269e4e721627f1f8c`。

此摘要在从上游 HTTPS 发布地址获取后计算并固定，用于后续下载一致性校验，并非上游发布的签名。
