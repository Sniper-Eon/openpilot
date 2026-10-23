# NavAssist v2（Android P0）

> 历史文档：这里记录已经退役的 Android-only HMAC v2 设计，不再是当前配置
> 指南。2026-09-19 核对：当前默认链路为未认证 UDP 4213；P-256 身份、UDP 7765
> 发现和 HTTP `/v3/snapshot` 是保留的另一条链路。当前实现差异和后续设计见
> [`NAVASSIST_SHARED_CONTRACT.md`](NAVASSIST_SHARED_CONTRACT.md)。本次仅修正文档。

NavAssist v2 是独立于现有 WebSocket v1 的、默认关闭的单向导航数据出口。它只发送手机端的导航观测，不接收也不生成车辆控制命令。

历史 v3 Schema 位于 [`protocol/navassist-v3.schema.json`](../protocol/navassist-v3.schema.json)，其严格字段表尚未跟上当前工作树的 routeAvoid/路线通知扩展；不能据此宣称当前报文已通过验证。下一阶段须对齐固定版本的发送端、Schema 与接收端样例；下文其余 v2/HMAC 内容仅用于历史追溯。

## 启用方式与 App 内配置

不再要求为每台 C3XL 重新编译 URL。打开 TesNav 的“设置”，在 `NavAssist / C3XL` 区域输入与 C3XL 相同的共享 Token 并保存。Token 输入使用密码遮罩；保存后界面只显示“已配置”，不会回显完整内容。它存放在应用私有的 `MODE_PRIVATE` preferences 中，并通过 `android:allowBackup=false` 排除 Android Auto Backup；更改或清除成功后会立即重建 exporter，无需重装或重新编译 APK。若持久化写入失败，App 保留旧 Token 和旧连接 ownership 并显示错误。

Token 的 UTF-8 key material 至少为 16 bytes，且首尾不能有空白字符。推荐使用 32 bytes 随机值，例如 `openssl rand -hex 32` 的完整输出。当前测试 Token 不是硬件保护的秘密；不要记录、截屏或分发，测试完成后应轮换。

默认 Gradle 配置只需要留空 URL：

```properties
NAV_ASSIST_V2_URL=

# 可选；小于 200 ms 仍会被钳制为 200 ms（最高 5 Hz）
NAV_ASSIST_V2_INTERVAL_MS=200
```

兼容旧测试 APK：`NAV_ASSIST_V2_TOKEN` 若编译时非空，只会在 App 私有配置尚不存在时执行一次迁移；之后始终以 App 内保存值为准。`NAV_ASSIST_V2_URL` 若为空，使用下述认证 UDP 自动发现；若是合法 HTTP/HTTPS URL，仍作为手工 override，客户端固定 POST 到其根路径 `/v2/snapshot` 且不扫描。非空但非法的 URL 不会接管 legacy v1。

当 Token 有效，且 URL 为空或为合法 override 时，v2 接管手机到 C3XL 的出口，legacy v1 WebSocket 不启动，避免两条链路并行。Token 缺失/太短、URL 非空但非法或有效期 gate 不满足时，仍完全沿用原 v1 的 `EXPORT_ENABLED` 行为。

HTTP 与 HTTPS 都受支持，封闭场地若使用 HTTP，必须依靠隔离测试网络。更高信任边界应使用 HTTPS。

设置页状态含义：

- `未配置`：没有有效 Token；不会发送发现包。
- `正在扫描`：本轮 UDP 广播仍在收集响应。
- `多设备冲突`：同一轮出现多个不同的已认证源 IP；fail closed，不选择最快响应者。
- `已发现`：offer 已认证且 endpoint 已固定，但尚无成功的导航 HTTP POST。
- `HTTP 在线`：至少一个 `/v2/snapshot` POST 已成功；只有这个状态代表数据链在线。
- `错误`：发现或 HTTP 发送失败。自动发现得到的 endpoint 一旦 POST 失败会立即清除，下一轮重新发现。

## C3XL 自动发现

手机对最多 8 个本地、已启用、非 loopback 接口的 IPv4 broadcast 地址（另含 limited broadcast）发送 UDP，目标端口 `7765`，每轮使用新的 `SecureRandom` 16-byte nonce，接收窗口 750 ms，datagram 上限 512 bytes。它不会并发扫描 `/24` 的 HTTP 地址。

为保持发现模块纯 JVM、可注入和最小侵入，当前枚举的是所有 `up && !loopback` 且绑定 RFC1918 IPv4 的接口，不等同于 Android `ConnectivityManager` 所指的单一 active Wi-Fi/Ethernet。封闭场地测试网络应关闭无关 VPN 和其他私网接口；若未来需要在复杂多网络环境使用，应再注入 Android active-network provider 收窄广播目标，而不是自动选择某个响应。

request 是 compact JSON，严格字段集合为：

```json
{"messageType":"navassist_discovery_request","schemaVersion":2,"nonce":"<32-lowercase-hex>","proof":"<64-lowercase-hex>"}
```

request proof 的 HMAC 原文精确为：

```text
navassist_discovery_request\n2\n<nonce>
```

C3XL offer 的严格字段集合为：

```json
{"messageType":"navassist_discovery_offer","schemaVersion":2,"nonce":"<same-nonce>","port":7766,"path":"/v2/snapshot","proof":"<64-lowercase-hex>"}
```

offer proof 的 HMAC 原文精确为：

```text
navassist_discovery_offer\n2\n<nonce>\n7766\n/v2/snapshot
```

两种 proof 都是上述固定 UTF-8 字符串的 HMAC-SHA256 lowercase hex，不是对 JSON 序列化文本签名。Android 严格拒绝未知/重复字段、错误 primitive 类型、无效 UTF-8、错误 schema/nonce/path/port/proof、超过 512 bytes 的响应和非 RFC1918 IPv4 来源。endpoint 只使用 UDP packet 的 source IP 构造为 `http://<source-ip>:7766/v2/snapshot`；不信任 payload host、不做 DNS 解析，并禁用 HTTP/HTTPS redirect。

同一轮来自同一个源 IP 的重复合法 offer 会去重；来自多个不同已认证源 IP 的 offer 会整轮拒绝。旧 offer 因 nonce 不匹配不会进入当前轮。request 本身没有 wall-clock 字段，抓到旧 request 的人可能使 C3XL 再发一次 offer，因此不能把 discovery 描述成 request freshness 协议；真正的导航 HTTP payload 仍另有 HMAC、session/sequence、wall-time 和接收端 monotonic TTL。

测试网络限定一台手机使用一个 Token；多个手机共享同一 Token 会形成相互竞争的导航 session，超出 P0 支持范围。

## 请求与认证

- Method：`POST`
- Path：`/v2/snapshot`
- Content-Type：`application/json; charset=utf-8`
- Header：`X-NavAssist-Signature: <64-char lowercase hex>`
- 最大频率：5 Hz；请求不并发，慢请求会自然降低频率
- 任意 2xx 响应视为成功

body 是无空白的 canonical JSON：所有 object key 递归按字典序排列，数组顺序保留，null 字段省略。签名算法：

```text
lower_hex(HMAC-SHA256(UTF8(raw_http_body), UTF8(NAV_ASSIST_V2_TOKEN)))
```

接收端必须对收到的原始 body bytes 验签，不能 parse 后重新序列化再验签。比较签名时应使用 constant-time comparison。

## 会话、顺序与有效期

- `sessionId`：Android 前台导航服务每次创建 v2 exporter 时生成新的 UUID；最长 64 字符，只允许 ASCII 字母、数字、`.`、`_`、`:`、`-`。
- `sequence`：同一 session 内从 1 开始严格递增；发送失败也不会复用序号。
- `routeRevision`：路线成功发布、清除或失败失效时递增。路线重算期间 `navigationMode=recalculating` 且 `routeActive=false`。
- `maneuverEventId`：对稳定 key `sessionId:routeRevision:stepIndex:maneuver` 做 SHA-256，取前 8 bytes、清除最高符号位，得到稳定的正 int64。同一 maneuver 的 5 Hz 快照复用同一个 ID；没有有效事件时固定为 `0`。
- `validForMs`：历史 v2 此处记录为 500 ms；2026-09-19 当前 Android/iOS 代码默认 1200 ms。C3XL 以自身 monotonic 接收时间执行快照 TTL，并用 `sourceWallTimeMs` 检查重放窗口；时钟容差需核对目标接收端版本。快照 TTL 不等于 SDK 源活性，后续失效规则见共享契约。

接收端还应拒绝重复或倒退的 sequence、已经关闭的 session、旧 routeRevision，以及验签失败的消息。丢包只会形成 sequence gap，不应导致接收端等待补包。

`routeActive=true` 只会在实时导航运行中、路线已规划、非重算/结束状态、`routeMatched=true`，且完整的 `location` 与 `guidance` 对象都存在时产生。GPS weak 只作为诊断字段，不单独关闭已匹配路线。任一必要观测缺失时发送 `routeActive=false`，并将 `maneuverEventId` 归零。location 对象存在时，坐标、精度、方向、速度和观测时间均为必填；无效或非有限数值会使整个 location 缺省。

C3XL 的实车控制 gate 只接受 Android/iOS 的 `realtime` 快照；`simulation` 即使 `routeActive=true` 也只可用于协议诊断，不能形成纵向目标。

## 字段新鲜度

不同高德回调的观测时间彼此独立：

| 字段 | 唯一更新时间来源 |
| --- | --- |
| `location.observedAtMs` | `onLocationChange` |
| `guidance.observedAtMs` | `onNaviInfoUpdate` |
| `lanes.observedAtMs` | `showLaneInfo` / `hideLaneInfo` |

5 Hz exporter 只重复发送最新快照，不会刷新上述观测时间。这样位置高频更新不会让旧 maneuver 或旧车道推荐看起来仍然新鲜。

`sourceWallTimeMs` 是本次快照生成时间，不等同于任何字段的观测时间。

## Android 高德字段映射

| NavAssist 字段 | Android SDK 来源 | 处理规则 |
| --- | --- | --- |
| `routeMatched` | `AMapNaviLocation.isMatchNaviPath()` | 定位回调前省略 |
| step/link/point index | `AMapNaviLocation.curStepIndex/curLinkIndex/curPointIndex` | 负值省略 |
| `guidance.maneuver` | `NaviInfo.iconType` | 映射为共享的小写 snake_case enum；未识别值为 `unknown` |
| `guidance.maneuverDistanceM` | `NaviInfo.curStepRetainDistance` | 负值省略 |
| `roadClass/roadType` | `naviPath.steps[curStep].links[curLink]` | 仅索引有效且值在高德文档范围内时发送，否则省略 |
| lane actions | `AMapLaneInfo` | 沿用现有 `LaneAction` 大写 enum；推荐车道不代表自车当前所在车道 |

每个快照最多发送 16 条 lane item，lane index 限制为 0–31，每个 action 数组最多 16 项；mapper 与 schema 同时执行这些上限。

坐标系固定标注为 `gcj02`。当前 SDK 没有可靠的结构化“下一个 maneuver”或建议弯道速度来源，因此 `nextManeuver`、`nextManeuverDistanceM`、`advisorySpeedMps` 目前省略。摄像头限速不会被误当作建议弯道速度。

`NaviInfo.exitDirectionInfo` 提供出口名称与文字方向，但没有可安全映射为左右出口的结构化方向 enum。本版本不会解析文字猜测 `exit_left/exit_right`。当前 link 的 `roadType` 若为 6/9，可分别表示已经处于匝道/出口 link，但不能被解释成“前方应立即向该方向变道”。

字段和常量以高德官方 Android Navi Javadoc 为准：[`AMapNaviLocation`](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/model/AMapNaviLocation.html)、[`NaviInfo`](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/model/NaviInfo.html)、[`AMapNaviLink`](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/model/AMapNaviLink.html)、[`IconType`](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/enums/IconType.html) 和 [`LaneAction`](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/enums/LaneAction.html)。v2 从原始 lane code 独立映射；legacy v1 的既有 mapper 语义保持不变。

## 与 v1 的隔离

- 原 `EXPORT_ENABLED`、`WEBSOCKET_URL`、`API_TOKEN`、`EXPORT_INTERVAL_MS` 默认值与运行路径不变；仅在有效 Token 配合 discovery 或合法显式 URL 时抑制 v1 启动。非法显式 URL 不抢占 v1。
- 新增的 `NavigationState` v2 字段均为 JVM `transient`，不会进入 legacy Gson v1 payload。
- v2 使用独立 UDP/OkHttp client、coroutine 和连接状态；未配置时不会发 UDP 或 HTTP。
- v2 没有 route geometry POST，也不接收 C3XL 回包。
- v2 配置生效后 legacy v1 不启动，因此原 v1 回传的 `is_tesla_nav_active` 也不可用；依赖该回传 gate 的 Tesla/Home Assistant 自动同步不会自动进入 ready。v2 P0 不伪造该入站状态。
- v2 没有方向盘角度、曲率、加速度、CAN 或其他车辆控制字段。
