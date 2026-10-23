# TesNav iOS

独立 iOS 15+ 客户端，不修改 Android 源码。Bundle ID 固定为
`com.garan.tesnav.ios`，便于高德 iOS Key 与签名配置保持稳定。

## 功能

- CLLocation 当前定位经 WGS84→GCJ-02 转换后用于高德逆地理编码；
- 300 ms 防抖的高德 Input Tips 模糊搜索，缺少坐标时回退到 POI 搜索；
- 最多三条驾车路线及时间、距离、收费、红绿灯信息；
- 高德实时/模拟导航视图、模拟暂停/继续、内置系统 TTS、静音/恢复和后台定位/语音；
- 车道建议、当前路段、转向、出口和匝道信息映射；
- 高德 GPS 弱标记仅用于诊断；路线仍由位置精度、数据新鲜度和匹配状态约束；
- UDP 4213 广播严格 v3 快照，收到相同 session/sequence 的确认后自动显示
  C3XL 地址；
- 每次开始实时或模拟导航都会立即继续广播，并从确认包学习当前 Wi-Fi/IP；
- 无共享 Token 或必需配对步骤，App 内显示地址和连接状态。

## 本地配置

创建 `Config.local.xcconfig`（该文件已被 Git 忽略）：

```xcconfig
AMAP_IOS_API_KEY = 绑定 com.garan.tesnav.ios 的高德 iOS Key
TESNAV_DEVELOPMENT_TEAM = Apple Developer Team ID
```

Android 高德 Key 不能作为 iOS Key 使用。请在高德控制台创建“iOS 平台 SDK”
Key，并把安全码 Bundle ID 设置为 `com.garan.tesnav.ios`。

## 生成与验证

```bash
./build.sh
```

脚本会运行 XcodeGen、CocoaPods 和无签名模拟器构建。真机无线安装要求：

1. Xcode 已登录 Apple ID，并存在 Apple Development 签名身份；
2. iPhone 曾通过 USB 信任并启用 Developer Mode；
3. Xcode 的 Devices and Simulators 中勾选 Connect via network；
4. Mac 与 iPhone 位于同一局域网；
5. `Config.local.xcconfig` 已填写 Team ID 和高德 iOS Key。

满足条件后：

```bash
TESNAV_IOS_DEVICE_ID=<Xcode device UDID> ./install-wireless.sh
```

应用首次启动会显示隐私说明；同意后才初始化高德 SDK、请求定位和启动 C3XL
自动发现。高德导航 SDK 使用 `isUseInternalTTS` 进行系统语音播报。

## 播报频次

首页设置和导航设置中均有“语音播报频次”：简洁（默认）、详细、静音。
选择会保存在本机，静音后恢复语音会回到此前的有声档位。Android 使用相同档位。
简洁／详细调用高德内置播报模式，不用固定秒数丢弃转弯提醒；按 SDK 约定在下次算路生效，
不会为了调整语音强制重算路线。静音立即停止全部语音。与发送 C3XL 的频率无关。

## Mac 自动续签

免费 Personal Team 描述文件只有 7 天有效期；重新安装使用同一旧描述文件的包不会延长到期日。
续签必须由 Mac/Xcode 获取新描述文件、签名并覆盖安装，不能由已过期的 iPhone App 自行完成。

```bash
python3 ios/renew-signing.py                 # 只检查本地到期记录
python3 ios/renew-signing.py --renew --device <paired-device-UDID>
```

可由定时任务调用第二条命令。成功安装后剩余有效期超过 48 小时则跳过；临近到期时才续签。
Mac 需开机，Xcode Apple 账号/证书有效，iPhone 已配对、开发者模式开启且在线。
手机离线或 TesNav 仍在运行时跳过；结束导航并关闭 App 后才能覆盖安装。不会卸载或主动启动 App。
脚本拒绝无人值守安装未提交的代码；不会自动购买开发者会员、存储 Apple 密码或绕过验证。

仅将本 App、同团队且包含目标设备的临期缓存描述文件移到 `ios/.renewal/profile-backups/`，
让 Xcode 请求新文件；失败时恢复可恢复的原位置，成功后保留备份。不会修改其他 App 的描述文件。
构建日志与成功安装的到期记录保存在忽略提交的 `ios/.renewal/`。
只有新包签名校验、有效期检查和设备安装全部成功，才报告续签完成。账号验证失败仍需在 Xcode 手动处理。
