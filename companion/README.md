# C3 导航辅助 + 特会开手机视觉完整项目

本目录与本仓库 `codex/egpu-jetlink-navassist` 分支一起使用。C3 导航与定位恢复基线为 `34e2ff75d91e81b67bfc9274382b01713be6ce13`。本次发布补齐配套工程，未修改该提交的行车控制或导航代码，也未重新部署车辆。

| 内容 | 位置 |
| --- | --- |
| C3 完整工程与原有依赖布局 | 本仓库根目录、`openpilot/`、`opendbc_repo/` 等 |
| R10 Android / 历史 iOS 工程、Gradle wrapper、模型和 ONNX Runtime AAR | [`tesnav/`](tesnav/) |
| C3 广角桥接、服务、连接码初始化及测试 | [`phone-vision/`](phone-vision/) |
| APK、匹配源码 ZIP、C3 配套 ZIP、校验文件 | [本次 Release](https://github.com/Sniper-Eon/openpilot/releases/tag/navassist-phone-r10-20261023) |
| 原车辆模型的数据生成与训练入口（私有数据不上传） | [`model-tools/`](model-tools/) |
| APP / 模型 / 桥接指纹和版本 | [`release-manifest.json`](release-manifest.json) |
| 历史驻车验证汇总 | [`validation/r10-validation-summary.json`](validation/r10-validation-summary.json) |

## 获取完整 C3 + APP 工程

```sh
git clone --recurse-submodules --branch codex/egpu-jetlink-navassist https://github.com/Sniper-Eon/openpilot.git
```

本分支的 `jetlink_repo` 仍是固定提交 `913734280c33a40061874ebd01cd005210f43024` 的子模块。普通 GitHub 源码 ZIP 不展开子模块；需要完整检出时使用上面的命令，已有检出可运行 `git submodule update --init --recursive`。保留仓库原有依赖布局。

## 下载匹配 APP

[下载 TesNav-R10-phone-vision.apk](https://github.com/Sniper-Eon/openpilot/releases/download/navassist-phone-r10-20261023/TesNav-R10-phone-vision.apk)

显示名：**特会开·视觉帧率测试R10**；包名 `com.garan.tesnav.tenengkai.lane`；版本 `14 / 1.2-vision-fps-r10`。APK 是已经安装验证的原始签名文件，没有重新打包。与已安装同签名版本可覆盖安装；其他签名无法覆盖，先保留原应用数据并核对版本。

APK 较大，放在 GitHub Release 附件，不塞进 Git 历史。源码在分支中可直接查看，也可从 Release 下载整套 ZIP。当前 Release 标为测试版，手机视觉保持 shadow 观察模式。

## 朋友首次安装

先读 [`phone-vision/README.md`](phone-vision/README.md)。每台 C3 使用自己的连接码。代码首次部署时生成，已存在的连接码会保留；不会从发布包复制别人的连接码。只装 APK 还没有 C3 相机桥接。

## 自行构建 Android

Android SDK API 37，兼容本工程 Gradle / Android 插件的 Java 环境。设置 `ANDROID_HOME` 或本机 `local.properties` 后：

```sh
cd companion/tesnav
./build.sh assembleDebug
./build.sh testDebugUnitTest
```

构建匹配包名的测试变体：`./build.sh assembleTenengkai`。需要在你自己的 Gradle 私有配置中填写 `LANETEST_STORE_FILE`、`LANETEST_STORE_PASSWORD` 以及属于你自己的高德 SDK Key（`LANETEST_AMAP_API_KEY`）。未提供私钥的自行构建包不能冒充或覆盖原签名 APK。普通 debug 变体可先验证源码。iOS 子目录为原有项目，不包含 Android 手机视觉移植的 iOS 实现。

原始 APP 功能源码、模型、依赖 AAR 与匹配源码包逐字节核对。本次只把历史 `build.sh` / `install.sh` 的个人绝对路径改为可移植参数形式；C3 启动脚本增加自包含依赖和 ROI 路径。推理、导航、桥接和模型代码保持原指纹。

## 验证范围

原 R10 记录：329 项 Android 单元检查通过、1 项外部样本检查跳过；23 项桥接检查通过。真实驻车短窗口约 6.1 个有效结果/秒；8 Hz 是请求上限。长期稳定性、目标速度准确率和道路上的变道效果仍未完成验证。

本轮重新执行的发布校验见 `validation/publish-verification.json`。它不代表又做过一次实车验证。手机结果没有启用变道干预，原车盲区、实线、路沿等约束保持原逻辑。

## 发布范围

包含可分享工程与当前匹配模型、应用文件。设备连接码、签名私钥、高德 / HA 等私人凭据、手机设置备份、原始行驶日志和人工标注图片不进入公共仓库。已有第三方组件保留其文件与原有版权信息；模型和 AAR 的来源记录见 `validation/THIRD_PARTY.md`。
