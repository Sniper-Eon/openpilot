# 高德配置与搜索历史

Android 1.1（versionCode 2）与 iOS 0.3.0（build 4）提供同等功能。

## 首次配置

如果安装包没有有效格式的内置 Key，且本机也没有保存 Key，启动后会先显示高德配置页。iOS 保留原有的首次隐私说明，用户同意后进入配置页。配置前不会创建地图、搜索或导航 SDK 实例。

在高德开放平台控制台创建应用并添加平台 SDK Key，然后回到 App 粘贴：

- Android 选择 Android 平台 SDK；页面可复制包名及当前 APK 签名 SHA-1。调试、发布版本证书不同时，需要按安装版本填入对应安全码。
- iOS 选择 iOS 平台 SDK；页面可复制 Bundle ID。
- 两个平台 Key 不能互用；本页面不需要 Web 服务安全密钥或 C3XL Token。
- 本地检查完整的 32 位十六进制格式，不冒充服务端鉴权。若后续提示鉴权失败，检查平台、应用标识/证书和账号服务权限。

页面含直接打开控制台与官方指南的按钮：

- [Android 官方 Key 申请说明](https://lbs.amap.com/api/android-navi-sdk/guide/create-project/get-key)
- [iOS 官方 Key 申请说明](https://lbs.amap.com/api/ios-navi-sdk/guide/create-project/get-key)

已有内置或保存 Key 时直接进入 App；保存的 Key 优先于安装包内置 Key。设置中的「高德 Key 与配置指南」可再次进入。Android 在导航结束后允许更换，并在重新进入主页面时重建导航引擎；iOS 配置后重建主界面并更新 SDK Key。

Android Key 保存在应用私有偏好中（应用已禁用备份）；iOS Key 保存在本机 Keychain 中。Key 不会加入导航广播或调试日志。

## 最近搜索

搜索框为空时显示最近 20 条记录。记录包括主动提交的搜索词，以及选择的具体地点（名称、地址、POI/坐标）。不会保存每次尚未提交的输入片段。

- 点搜索词：再次搜索并显示候选地址。
- 点具体地点：重新选择该地点，后续仍需用户确认路线/开始导航。
- 重复记录移至顶部；关闭并重新打开 App 后保留。
- Android 长按删除单条，iOS 左滑删除单条；两端均可清空全部并有确认。

历史列表只保留在各自手机，不同步到 C3XL，也不在两部手机间自动同步。再次搜索会正常调用高德查询接口。
