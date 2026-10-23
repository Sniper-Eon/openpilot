# 第三方组件来源

- `tesnav/app/src/main/assets/side_vehicle320.onnx`：原交付模型，SHA256 `58ebd0451c4074ee8f54475eaf7be818517521f90eb47c1a15b481ea892a9231`。文件内原始元数据声明 Ultralytics 8.4.182、AGPL-3.0（https://ultralytics.com/license）、输入 1×3×320×320、输出 1×5×2100、单类 vehicle。元数据和模型均保留原样。训练入口在 `model-tools/`，使用的是自动车辆标签。
- `tesnav/app/libs/onnxruntime-android-1.23.2.aar`：原交付采用的 Maven ONNX Runtime Android 1.23.2，不是本项目重新编译产物。官方项目 https://github.com/microsoft/onnxruntime ，许可 MIT；官方许可与第三方通知位于该项目对应版本的 LICENSE / ThirdPartyNotices.txt。
- Android / iOS 工程其他依赖由 Gradle、CocoaPods 等原工程配置声明。各组件沿用自身许可；本项目根目录许可证不替换第三方模型或 SDK 的许可。
- R10 APK 保留其原始签名和依赖；高德 SDK 的构建 Key / 签名应由自行构建者按自己的应用配置，私钥不公开提供。
