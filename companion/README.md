# C3 导航辅助 + 特会开手机视觉完整项目（R11）

> 当前分支已包含 [R12 流水线候选](releases/R12.md)，源码版本为 16 / 1.4-dual-pipeline-r12，已在原手机覆盖安装。双路实机性能尚待复测；下方公开下载及发布指纹仍对应 R11，不是 R12 安装包。

本仓库 `codex/egpu-jetlink-navassist` 分支包含 C3 工程、特会开 Android / 历史 iOS 工程、手机模型、构建配置、C3 相机桥接及验证工具。R11 在现有导航调整基线上增加双相机实验观察，不启用自动超车或新的车辆控制。

## 下载与源码

- [R11 测试发布与完整源码附件](https://github.com/Sniper-Eon/openpilot/releases/tag/navassist-phone-r11-20261024)
- [下载安装包](https://github.com/Sniper-Eon/openpilot/releases/download/navassist-phone-r11-20261024/TesNav-R11-dual-camera.apk)
- [Android / 历史 iOS 工程](tesnav/)、[C3 桥接](phone-vision/)、[双相机与标定工具](phone-vision/stereo/README.md)
- [R11 验证与部署状态](releases/R11.md)、[版本和文件指纹](release-manifest.json)
- [原模型训练入口](model-tools/)、[第三方来源](validation/THIRD_PARTY.md)

```sh
git clone --recurse-submodules --branch codex/egpu-jetlink-navassist https://github.com/Sniper-Eon/openpilot.git
```

完整源码 ZIP 包含本仓库的全部已提交文件。Git 子模块保留固定版本引用、不展开到 ZIP；需要全部依赖检出时使用上述递归克隆，或执行 `git submodule update --init --recursive`。`jetlink_repo` 固定于 `913734280c33a40061874ebd01cd005210f43024`。

## 匹配 App

显示名：**特会开·双相机测试R11**；包名 `com.garan.tesnav.tenengkai.lane`；版本 `15 / 1.3-dual-observer-r11`。保持原签名，可覆盖同签名 R10，不增加分身图标。APK 与本次已覆盖安装到测试手机的文件一致。签名私钥不随源码发布。

双相机开关默认关闭。开启实验双相机后会暂停原单路侧车回传，旧结果会超时为未知；新结果只供独立观察，不作为车道安全许可。原车 BSM、实线与车辆控制约束保持原逻辑。

## R11 新增能力与限制

- C3 按需提供广角、窄角画面，保留时间、尺寸、镜头身份及标定信息，检查同步和过期。
- 手机复用现有 320 车辆模型进行双路识别、同车匹配。原模型权重未更换、未宣称完成新训练。
- 完成了真实标定文件接入、纹理对应、去畸变、三角化及误差拒绝逻辑。没有本车真实双目标定时仅提供地面估计。
- 连续可靠样本才估计距离变化；缺少本车速度时不生成绝对车速。真实距离精度、速度精度、最大可靠距离及双路手机性能尚未验证。
- C3 仍承担图像转换、编码和传输；不是零算力开销。手机初始上限约 3 对画面/秒，实际需联调。
- 仓库保留 TeslaCam 录像离线导入工具。已取消原车摄像头实时接入方向，没有后车实时测速能力。

## 首次安装与自行构建

每台 C3 使用自己的连接码，首次安装生成，已有连接码保留。先读 [桥接说明](phone-vision/README.md) 和 [双路说明](phone-vision/stereo/README.md)。只装 APK 不能取得 C3 画面。

```sh
cd companion/tesnav
./build.sh assembleTenengkai
./build.sh testDebugUnitTest
```

配置 Android SDK API 37、Java 17 和本机 Gradle 私有配置；签名使用 `LANETEST_STORE_FILE` / `LANETEST_STORE_PASSWORD`，高德使用自己的 `LANETEST_AMAP_API_KEY`。自行构建者没有原私钥时不能覆盖原签名包。OpenCV 由 Maven 获取，ONNX Runtime AAR 和原模型保存在工程中。iOS 为历史工程，不包含 Android 双相机移植。

## 验证与部署状态（2026-10-24）

Python 53 项通过；Android Debug 公共源码 339 项测试，338 通过、1 项既有外部样本检查跳过。Tenengkai 安装包完成构建、签名和原生库静态校验，未宣称有独立变体单测或真机双路性能结果。

手机已覆盖安装并校验 APK；C3 桥接文件已安装备份，但桥接服务未重启。双相机仍关闭，等待驻车相机联调，没有实际双路测距、测速验证。

设备连接码、签名私钥、HA/API 私人令牌、手机设置备份、原始行驶日志与人工标注图片不进入公共仓库。历史 R10 记录保留于 `validation/`，不代表 R11 具有相同性能。
