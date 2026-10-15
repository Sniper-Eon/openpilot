# 特会开明确车道编号接口（测试版）

本修改接通“Comma → 特会开”的明确编号与未知状态接口，不代表多车道视觉定位已经实现。位置只供手机显示和推荐车道对照，不进入 Comma 控制、CAN 或原车变道许可。

## 手机源码与兼容

手机修改基于 `onemiless/TesNav:navassist-v2-track-p0` 的 `c9e541f3551c67893b6d513a0332fa2dc198876d`，包含已部署特会开 1.2 的高德车机广播与导航观察页面。源码补丁保存在本目录的 `patches/tesnav-lane-position.patch`。

新手机仍发送原 canonical v3 导航报文，再发送单独、最多 512 字节的 UDP 查询：

```json
{"messageType":"lane_position_request","sessionId":"当前导航会话","sequence":42}
```

Comma 只响应最近已接受的同一手机地址、同一有效导航会话与序号。旧手机不发查询，继续收到完全不变的旧回执；旧 Comma 忽略新查询，原导航报文不受影响。扩展仍使用现有未经认证的局域网 UDP，不将其用于控制授权。

新回执与原回执使用相同 sessionId 和 sequence，增加独立 `lanePosition`：

```json
{"version":1,"valid":true,"laneIndex":2,"laneCount":4,"numbering":"leftToRight","source":"commaCamera","ageMs":400,"validForMs":2000,"routeRevision":2}
```

编号从左向右，从 1 开始。未知时 valid=false、laneIndex=null；总数独立未知时 laneCount=null。手机还计入本轮收发时间，以本地单调时钟持续累计年龄，两秒有效期耗尽即清空。旧/异会话、序号错配、乱序、路线版本错配、与高德总数不符，不能产生有效的本车车道对照。

摄像头字段与 vehicleLane 原车位置及左右许可分离；可选回执乱序时合并独立信息，不用摄像头结果覆盖原车许可。

## 视觉生产者接口与当前限制

Comma 从 `/dev/shm/road_lane_position.json` 读取未来绝对车道生产者的确认结果，文件最大 4096 字节。字段须包含 version=1、valid=true、absolute_confirmed=true、numbering=leftToRight、nav_session_id、route_revision、capture_mono_ns、stable_samples>=3，以及 lane_index（1 到 12）和可选 lane_count。

需要证据确认绝对编号、与当前会话及路线匹配、年龄小于两秒，才能回传数字。缺文件、歧义、过期、坏数据一律回传未知。当前 YOLOPv2 外接观察器只产生可见车道估计，absolute_confirmed=false，不能作为绝对编号来源。**此修改没有创建一个假定绝对编号正确的视觉生产者，也没有把路测中的可见 1/1 转为本车第 1 条。**

多车道感知与地图约束仍需后续开发和真实标注验证。接口测试中的第 2／4 条是隔离测试数据，不是路测结论。

## 构建手机测试包

在手机源码应用补丁后，使用 JDK 17、Gradle 9.5.0 和对应 Android 37 SDK：

```sh
./gradlew -PLANE_FEEDBACK_TEST_APP=true :app:testDebugUnitTest :app:assembleTenengkai
```

测试包的应用 ID 为 `com.garan.tesnav.tenengkai.lanefeedback`，名称为“特会开车道测试”，可与原应用并存。测试包使用本机调试签名，不能继承原版的配置、权限和高德签名注册。高德 SDK 需要为测试应用包名/签名配置合法 API Key；高德车机广播接收入口仍保留。不要同时让两个应用发送不同导航会话。

本修改不包含原应用的私密 API Key 或签名密钥，不自动安装或覆盖手机原应用。
