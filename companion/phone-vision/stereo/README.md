# R11 双相机观察与标定工具

状态：本地候选，尚未安装/实机联调，不能用于自动超车或判定邻道安全。

## 手机端

同一个特会开测试包，版本 15 / `1.3-dual-observer-r11`，显示名“特会开·双相机测试R11”，沿用 `com.garan.tesnav.tenengkai.lane` 和既有测试签名，不新增包名。双相机开关默认关闭；正常单路仍用原 320 模型，未替换成新训练候选。

- 无本车真实双目标定文件时：双路检测，基于各自地面投影做互相唯一的同车候选关联；距离取像素扰动敏感性较低的一路，通常是窄角。此结果明确标为地面估计，不冒充立体深度。
- 有通过质量检查的标定文件时：手机使用 SIFT 纹理匹配、比值和双向一致性筛选、去畸变、双射线三角化、几何/敏感性筛选，再用实时窄角相机姿态换算到车辆标定坐标。至少 8 个一致纹理点才确认一个车辆候选，不使用车辆框中心直接三角化。
- 连续关联使用拍摄时间拟合距离趋势；缺失本车速度时不生成绝对车速。画面过期、目标丢失、主机/流切换、距离突变均清空相关历史。趋势尚无真实速度误差验证。
- 车辆模型沿用现用权重；ONNX 用 2 个线程，标定立体匹配用 1 个 OpenCV 线程，双路会话请求上限约 3 对/秒。这是预算上限，不是实测有效帧率或持续负载结论。

**双路观察与原单路侧车回传是互斥模式。** 开双路时只回传独立观察文件，旧单路结果会按原超时规则变成未知；原车 BSM 和实线检查不被替换。本轮未把新的双路结果接入变道辅助控制，因此此模式仅用于驻车/受控采集，不应作为行驶变道辅助。

## C3 配套

`c3/phone_vision_bridge.py` 新增 `/v2/pair` 与 `/v2/observation`，原 `/v1` 保留。新代码要同时放置同目录的 `dual_camera_store.py`。需显式启用 `--dual-camera`，窄角读取器只在首次双路请求时启动；无人请求时不持续 JPEG 编码。两路原生 IPC 均只读，不启动/修改 camerad，不在 C3 运行新识别模型。

真实设备接口已只读核实为 `narrowRoadCameraState` / `VISION_STREAM_NARROW_ROAD`，候选也支持旧的 `roadCameraState` / `VISION_STREAM_ROAD` 命名。

既有安装器已加入双路辅助文件，仍不启动服务、不改连接码、不创建开启标志。使用既有启动脚本联调时，须在确认条件后显式创建 `/data/phone-vision/dual-camera.enabled`；移除此文件并按驻车流程重启后回到默认单路。该文件存在时，启动脚本才会读取同目录的真实 `stereo-calibration.json`。本轮没有创建这些设备文件。

输出固定独立为 `/dev/shm/phone_dual_vehicles.json`，包含 `control_eligible=false`、`clearance_authorized=false`。使用随机请求/流身份和原始拍摄时间，不用收到数据的时间延长原图寿命。两路传输配对门限 50 ms；地面关联最大 20 ms；立体计算最大 5 ms，且还要通过运动误差/基线检查，5 ms 并不保证距离可用。

C3 仍承担两路图像拷贝、NV12 转色、JPEG 与传输，负载需要实测。初次联调保持现有 960 宽、JPEG 75、请求不超过 3 对/秒，不直接提高到原始尺寸。新版启动示例（本轮未执行）：

```sh
python phone_vision_bridge.py --token-file /data/phone-vision/connection-code \
  --roi /data/phone-vision/roi.json --dual-camera --hz 4 \
  --frame-width 960 --jpeg-quality 75
```

## 标定与离线验证

1. 先停止手机视觉会话，让采集器独占画面请求。`collect_pairs.py` 只取两路同步 JPEG，不发控制；默认每对间隔 2 秒以便挪动棋盘，每一对曝光期间棋盘保持静止。连接码从文件读取，不写进数据集。
2. `calibration-board-25mm.svg` 为 A4 横向棋盘图，9×6 内角点。名义方格 25 mm，但必须量打印后的实际边长；缩放或裁剪会改变尺度。每一对采集时棋盘保持静止，至少 20 个不同位置/角度的可用双路视图。
3. `calibrate_pairs.py` 分别拟合广角 fisheye / 窄角 radtan 内参，再估计相对旋转和平移；每四张留一张作为独立姿态验证。至少 15 张拟合、5 张验证，分布、误差、米制单位、合理基线和旋转都要通过。
4. 标定结果仍需用未参与标定的已知距离目标检验，之后再采集同步速度真值。棋盘重投影通过不等于车辆测距测速已经准确。

示例（方格边长必须改成实测值）：

```sh
python collect_pairs.py --url http://C3-IP:8767 --token-file LOCAL-CODE-FILE \
  --output paired-board-frames --pairs 30
python calibrate_pairs.py paired-board-frames --columns 9 --rows 6 \
  --square-metres 0.025 --output stereo-calibration.json
```

没有构造或提供可用于本车的假标定文件。板标定可在静态画面采集；C3 未提供实时车辆标定姿态时，手机不输出车辆坐标中的双目距离/速度，离线参考工具仍可检查相机坐标深度。不能通过伪造点火或复用过期姿态绕过此限制。

真实文件经核查后，C3 使用 `--stereo-calibration PATH` 批准其文件 SHA-256，手机使用同一字节内容的应用私有 `files/stereo-calibration.json`。设备与镜头 profile 必须一致；缺质量字段、镜头/设备变化、单位/基线错误或两端文件不一致均拒绝。不允许把测试里的 synthetic 数据当成真实标定。

离线 `stereo_geometry.py` 支持独立的真实特征匹配/三角化。其合成测试只能验证数学与拒绝条件；其中 6 cm、30 cm 等基线都是测试参数，不是本车测量。当前没有真实双路标定结果，也没有可声称的“最大可靠距离”或 km/h 误差。

## 特斯拉原车侧后摄像头

已加入 `import_teslacam.py`，可从本地 `left_repeater`、`right_repeater`、`back` 视频按约 1 Hz 导出标注图片，默认最多 300 帧，去重并保留来源。文件名时间与容器时间都标为未验证同步，不生成距离/速度标签，不授权后方安全。

```sh
python import_teslacam.py LOCAL-TESLACAM-DIRECTORY --output rear-review \
  --timezone Asia/Shanghai --max-frames 300
```

本轮未发现本地此类录像。公开 [Fleet API 车辆接口](https://developer.tesla.com/docs/fleet-api/endpoints/vehicle-endpoints) 未见行驶中车身摄像头实时流接口；[官方行车记录仪说明](https://www.tesla.com/ownersmanual/modely/en_cl/GUID-3BCC07CE-5EA2-4F40-99D1-27690898FF3C.html)描述了 USB 保存和官方 App 查看。因此没有实现或宣称已接通原车摄像头实时流；官方 App 的观看能力不能直接当作第三方模型的数据接口。USB 存档适合离线训练，不可替代低延迟后车测速输入。

## 构建与运行库检查

Android 引用官方 OpenCV 4.13.0。构建时重新打包该 AAR，剔除其 libc++ 与不属于原导航 SDK 的 ABI，保留原导航 SDK 的 libc++ 字节。`verify_native_runtime.py` 逐 ABI 核对原运行库及 OpenCV 所需动态符号；这个静态检查不能代替真机导航并行运行、JNI 兼容性和温度/延迟测试。

工具依据 [OpenCV 标定与三角化文档](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)和 [fisheye 模型](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html)实现。新增立体处理只提供观察数据，不发送转向、油门、变道或灯光命令。

Mac 工具依赖 numpy、opencv-python、Pillow；运行库核查另需 pyelftools。可在仓库根目录运行 `python -m pytest companion/phone-vision/tests`，不依赖本机工作目录名称。
