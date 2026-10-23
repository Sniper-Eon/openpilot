# Android / iOS 共享 NavAssist 行为契约

2026-09-22 语音扩展已配套安装：Android／UDP 增加可选 ACK `laneAnnouncement={id,sessionId,direction}` 与快照 `laneChangeSpeechCompletedId`。C3 必须收到本次实际播报完成回执才可继续原有自动变道资格判断；旧 ACK 保留。安装路径回归 1029 项及手机中文 TTS 实测通过；字段、时效、失败锁止、iOS／HTTP 边界和运行验证状态见[变道语音记录](LANE_CHANGE_SPEECH_20260922.md)。

2026-09-22 Android 实施补充：默认源预算与跨事件恢复规则见[导航控制接入记录](NAV_CONTROL_INTEGRATION_20260922.md)。用户已授权变道、减速和灯光接入；已安装并验证空闲会话传输，实际导航待验证，不改变 wire 字段或 iOS 行为。下文零预算、仅预览条目属于历史阶段。

设计修订 v1.2，2026-09-19。本轮只修改方案。“当前 Android 行为”描述 P1 工作树；“目标行为”是待实现要求，阶段与条件项以蓝图 v1.2 为准，不能混作已部署能力。

职责和阶段以[重构蓝图](APP_REFACTOR_BLUEPRINT.md)为入口，对齐[城市 NOA 总体规划](../../C3_CITY_NOA_MASTER_PLAN.md)与后续[变道统一优化计划](../../C3_LANE_CHANGE_CONSOLIDATED_PLAN.md)。协议字段不携带车辆执行权限；没有事件绑定的 C3 结果时，App 显示未知。

最高工程约束为最小侵入：本契约定义可观测行为，不规定新增架构。下文的 runtime、owner、上下文、状态维度都是责任描述，优先由现有 Service、Repository、store、client 和 presenter 表达；不要求新增同名类、包、服务或 wire 字段。扩展功能和完整 iOS 对齐不是局部缺陷修复的前置条件。

实施增量（2026-09-19）：Android 已完成 P2a 显示侧的文案、方向建议抑制与接收年龄失效。`OemVehicleLaneState.receivedAtElapsedMs` 为本机接收元数据，不在 ACK/wire schema 中；显示预算为实际配置发送间隔（至少 200 ms）加现有收包窗口 350 ms，默认 550 ms。期限由代码收发边界支持，不借用 239/399 或 snapshot TTL；真机调度抖动尚未测量。无新消息时现有 UI 订阅会按期限失效，渲染时再检查年龄；导航源活性、传输身份和 iOS 等下述目标仍未因此完成。

后续增量：P2b 已将现有 session 对象保留在 Android Service 实例中，生产 exporter 重建时复用同一 session/sequence。已验证 App 整包身份连续性；目标 C3 取消锁、跨通道 ownership 交接和进程重启恢复仍未验收。以下“冻结的当前 Android 行为”保留 P1 审计基线，session 的最新实现以本增量及蓝图实施记录为准。

P3 增量：exporter 已采用单次实例生命周期，停止后的 ACK、HTTP 和发现返回不再更新本地对外状态；发布与停止清理互斥，同实例不会重新启动。网络调用不在发布锁内，已发出/进行中的请求仍可能完成，发现内部的配对存储未在此轮调整。该修复不修改会话身份、wire、认证或接收端行为，不能替代下面的 ownership/取消锁验收。

## 冻结的当前 Android 行为

- 协议类名含 V2，但 `NavAssistV2Protocol.SCHEMA_VERSION=3`、`messageType=navigation_snapshot`；HTTP `/v3/snapshot`，默认广播 UDP 4213。
- 默认最小发送间隔 200 ms，实际循环包含收包耗时（最多 350 ms）；不是保证 5 Hz。默认 `validForMs=1200`，可配置范围 100–2000。现有旧文档的 500 ms 不是当前默认值。
- P1 时 session 为 exporter 生命周期 UUID；P2b 首批已改为生产 Service 持有并在重建时注入，sequence 继续使用原子递增。routeRevision 属于路线变更；事件键 `session:routeRevision:step:maneuver` 的 SHA256 前 8 字节按大端取值并清最高位，0 映射到 1。无有效事件为 0；哈希算法保留。
- 导航 active 条件：routePlanned、非重算、实时模式、匹配路线、位置和 guidance 有效。step 缺失或 maneuver 为 none/unknown 时事件 ID 为 0。模拟永不 active。
- 坐标 GCJ-02；位置经纬度、精度 0–200 m、bearing 0–360°、速度 0–300 km/h 做 finite/range 校验。距离 m，时间 ms，`advisorySpeedMps` 当前为空，测速限速不当作弯道建议速度。
- 观察时间来自回调；每次重发只更新 sourceWallTimeMs，不伪造新的观察时间。App mapper 不独立做观测 TTL 拒绝。本地 C3 `publisher.py` 用接收 TTL 而非 guidance 年龄作为主要有效性门槛，因此不能依赖它自动识别手机 SDK 停滞；本地实现不等同于实际部署版本。
- canonical JSON：递归对象 key 排序、数组保序、null 字段省略。数字格式跨语言应以 golden bytes 和签名向量验证，不能仅以 JSON 对象相等替代签名验证。
- lane index 0 基于回调顺序；wire 过滤 0..31、排序、最多 16 项；15/22/255 不推荐。保留 raw 类型以维持 UI 和 wire 历史不同映射。`routeAvoid` 表示路线避选，不是实线/法规禁行。
- guidance 当前工作树含 nextManeuver、道路层级和 routeNotice 扩展；这些是本任务开始前已有的未提交变化。
- UDP ACK 核心字段：messageType=navassist_udp_ack、schemaVersion=3、sessionId、sequence；允许可选 vehicleLane。Android 当前严格拒绝其它顶层字段，vehicleLane 要求完整 21 个键；错误反馈可降为无反馈（类型异常路径尚需改进）。
- Android snapshot 上限 8192 bytes、ACK 上限 2048 bytes；iOS snapshot 上限相同，但 ACK 为 512 bytes。用本地 C3 `OemLaneFeedback().snapshot(now_ns=1)`、36 字符 UUID、sequence=1 生成基础 ACK 为 592 bytes，尚未计入更长数值等变化，512 无法容纳。该离线测量未发送网络报文。
- vehicleLane 位置、许可、盲区、雷达、CarState 和 laneChange 状态仅用于显示/建议。传输 ACK ONLINE 不是“可安全执行”。UDP 未认证，HTTP 签名/配对模式是另一路径，不把 ACK 匹配叫作认证。

## 对齐差异与待办

| 项目 | Android 基线 | iOS 基线及下一步 |
|---|---|---|
| TTL | 1200 ms | `Protocol/NavAssistModels.swift` 同为 1200；修正文档，不自行改 TTL |
| ACK | 可选 vehicleLane；上限 2048 bytes | `NavAssistDiscovery.swift:UnauthenticatedNavAssistUDP.send` 恰好 4 keys 且上限 512 bytes；必须同时修正字段与长度处理，先共享 core-only/592-byte/超限样例。初期可仅识别 core ACK 而不展示 vehicleLane |
| 车道避选 | wire 有 routeAvoid | `Navigation/NavigationState.swift:LaneObservation` 缺字段；`NavigationTelemetry.swift` zip 截到短数组，需要确定 missing 与 sentinel 规则后补齐 |
| 未来动作/通知 | 已有扩展 | iOS nextManeuver 固定 nil，无层级和通知字段；按 SDK 能力映射，不能猜数据 |
| 动作事件 | guidanceStep 优先，缺失不生成事件 | iOS 使用 currentStepIndex，缺失用 -1 仍生成 ID；需共享事件测试向量 |
| 重算/到达 | mapper 明确排除重算，模式 ARRIVED 不 active | iOS active 表达式依赖 state.routeActive/mode 的上游清理，mapper 不直接检查 arrived/recalculating；补反例验证后统一 |
| 停止/路线版本 | Android stop 增 revision | iOS store stop 保持 revision；在 session 内事件生命周期契约中明确并对齐 |
| 浮点/范围/字段缺失 | Kotlin mapper 限制 road class/type、lane index | iOS 多个字段直接发送；共享非法输入向量后收敛 |

iOS ACK 已按实施记录局部修改，未在 Windows 上运行 XCTest/Xcode。已有 `PLATFORM_PARITY.md` 为产品目标而非上述差异已经消失的证明。

## 目标行为一：时间、数据源健康与降级

区分四个维度，不用一个 ONLINE 布尔值代表全部；可从现有状态与必要时间字段派生，不建立四套可写 store：

| 维度 | 判据与时钟 | 失效的后果 |
|---|---|---|
| linkStatus | 当前传输 generation 中匹配 session/sequence 的 ACK，按本机接收 monotonic 期限 | 离线提示；不伪造 C3 状态，不自行指挥车辆退出 |
| sourceHealth | 当前 SDK 引擎的有效新样本、引擎状态和回调/路线来源；本机 monotonic | 数据源 UNKNOWN/STALLED 时撤销 routeActive，继续发送 inactive 快照，不靠断网表达故障 |
| routeValidity | 已接受的 path/revision、路线匹配、实时模式、当前动作所属路线、来源健康 | 不产生新的导航动作意图；保留身份以便去重，不靠 revision/session 抖动清失败 |
| feedbackValidity | ACK 关联、合法类型/范围、各字段有效位、接收 monotonic 年龄 | 失效字段显示未知；缺反馈不反向证明导航源无效，也不把无报警当作安全 |

时间字段分工：sourceWallTimeMs 是编码时刻，用于跨端检查；observedAtMs 是真实源观察对应的 wall 时间；本机状态期限使用 elapsedRealtime 等包含休眠的单调时钟。不能用 App 渲染、轮询 SDK getter、网络重发、ACK 或相同源样本重送更新源观察时间。相同坐标/指令可以属于合法新样本，去重应依据经过验证的源时间/序号而不是数值是否变化。

数据源健康的逻辑状态为 UNCONFIRMED → HEALTHY → STALLED/INVALID → RECOVERING → HEALTHY；优先在现有更新入口表达转换，不强制新建状态机。初始化、进程恢复、引擎失败和无法确认核心路线/guidance 归属时不直接 active；停止/到达/模拟/重算也不 active。仅可选 lane/next-icon 来源不明时失效相应字段，不因此否定已经验证的主路线。进入 STALLED 的内部源事件身份保留，wire 在 inactive 时仍按现有算法输出 maneuverEventId=0；恢复原路线后恢复原非零 ID，不将恢复本身视为新事件或清锁。

guidance 的逻辑有效期与采样年龄分开：

- 停车等待、位置样本仍健康且路线/step/动作上下文不变时，不要求指导指令定期改变；旧 observedAtMs 不刷新。
- 车辆正在行进、step/path 改变、位置进度与旧 guidance 冲突，或超过待确认的进度证据预算时，旧 guidance 不能仅与新 location 拼接恢复 active。须获得当前路线关联的指导证据；不足标为 guidanceUnconfirmed。
- 整个 SDK 无有效样本、引擎错误或路线来源失配时，发送器仍活着不延长健康期。重复/乱序/未来样本不累计恢复；RECOVERING 必须获得当前引擎、当前路线且满足一致性的有效新证据。
- 健康恢复不自动重试 C3 已取消事件。sourceHealth 恢复与 routeValidity 重新使能分开；只有目标接收端的 inactive/恢复锁存行为已验证，才允许自动恢复同事件观察为 active，否则保持待重新使能。

T_source（SDK 源活性预算）、T_progress（行进中指导证据预算）须以定位回调频率、静止/行进/后台/弱 GPS 实际序列确定；T_feedback（展示预算）当前按上文代码时序设定保守上限，实际反馈发布/调度序列用于验证误失效。分别记录值、来源、适用 SDK/接收端版本和传播延迟证据。它们不是 validForMs，也不能复用 239/399 年龄常量。没有冻结相关预算与恢复判据不得宣称该能力完成；不能把显示预算的实现称为源健康阈值已标定。测试以参数化边界、长静止正常序列和真实冻结序列验证误拒绝与漏拒绝。现有记录足够就直接使用，仅为缺少证据的场景补最小采样，不先建设独立采集系统。

wall 时间回拨/源未来时间导致跨端时间关系不可信时，不能把负年龄钳到 0 当新鲜；记录原因并保守降级，等待可关联的新样本。客户端不伪造新 observedAtMs 来通过接收端时间检查。

vehicleLane 当前没有每个传感器的源时间。App 只能显示“C3 报告的有效状态”和本机接收年龄，不能声称精确的 239/399/雷达样本年龄。后续如果需要源年龄，须另做兼容字段设计；当前先按有限展示预算失效，UI 在无新消息时也要更新，不能等下个 ACK 才撤销旧显示。

## 目标行为二：身份、重连和重新使能

session 的唯一持有者优先采用现有 Android `NavigationForegroundService`：将现有 `NavAssistV2Session` 从 exporter 内部移到 Service 生命周期，向 sender 传入同一对象；iOS 在现有导航生命周期位置做等价处理，不要求新增 Runtime 或 SessionOwner 类。现有会话对象内的 sequence 分配覆盖该 session 所有通道；已有模式切换路径保证单一活动发送器，允许丢号、不允许重用或倒退，不为该用例新建模式切换功能。

| 事件 | session / revision / maneuverEventId | 执行含义 |
|---|---|---|
| 丢 ACK、socket 重建、同车网络地址变化、sender 重建 | session 不变；同路线 revision/event 不变，sequence 继续增长 | 不是新请求，不清 C3 取消/失败状态 |
| HTTP/UDP 模式切换、同一目标的普通连接配置调整 | 停旧 sender 并隔离迟到返回，沿用同一会话对象；先验证接收端 owner 转移 | 不允许两条链竞争发布不同状态；连接切换不等于重新使能，不能用新 session 绕过所有权拒绝 |
| 重复算路成功/重复 SDK 路线通知 | 已接受的同一请求/path 不再增加 revision | 不制造新事件 |
| 明确的新目的地、改选路径、确认的重算结果 | 同 runtime session 内按一次有效路线转换改变 revision；先失效旧路线观察 | 新路线身份不证明车辆可重新执行；不得以反复重算绕过原动作失败 |
| 短暂数据停滞后恢复 | 不变；inactive 暂时输出 0，满足恢复/重新使能条件后使用原事件键 | 必须验证 C3 不会因中间 0 清取消锁；否则不自动恢复 active |
| 停止/到达 | inactive；停止按现有路线失效策略变更 revision | C3 负责当前动作退出与灯光归属，不从 App 发反向控制 |
| App 进程/导航 runtime 重启 | 新 session 从 inactive/unconfirmed 开始，旧 active 不从缓存自动恢复 | 需要新路线证据和明确的用户启动；没有可信 C3 执行状态时不自动接续 |
| 确认更换车辆/身份 | 明确关闭旧上下文，再建立新 session，初始 inactive | 不把 UDP IP 或四字段 ACK 当作已验证车辆身份 |

P2b 首批已修正同一个 Service 中清配对/重建 exporter 改变 session 的问题，未更改现有签名算法或 wire 事件哈希。清配对不是“允许重试动作”的用户指令。自动 Tesla 同步属于自动来源，不能在异常重启后绕过恢复限制；该部分仍待实现和 A05 验证，不能从本次 session 持有修复推导其已满足。

App 不伪造跨进程持久化 ready，也不持久化未经 C3 确认的 completed。当前 ACK 仅确认快照被接受，无事件用途/动作实例/取消终态；不能把 laneChangeState 数字跳变独立解释为本次导航动作完成。若需要自动恢复、完整执行状态展示或建议请求闭环，先定义事件绑定反馈并验证 C3 版本，在此之前列为不支持。

两项接收端依赖需要单独验证：

1. 本地 C3 的取消锁有事件键变化时清除路径。保留 App session 不足以证明“取消→inactive/event=0→旧事件恢复”不重试；A05 未通过时，源恢复只能恢复预览/诊断，必须显式重新使能，不让 App 擅自新建事件解锁。是否需 C3 修正由独立任务处理。
2. 本地 UDP receiver 按来源 IP 派生 app key，HTTP 使用签名身份 key；其 SnapshotStore 会拒绝另一 owner 接管尚新鲜的 active 会话。因此切 IP/协议可能先被拒绝。模式切换应先通过旧通道发布 inactive 并确认或等待旧接收租约结束，隔离迟到返回；没有可靠交接证据时保持 inactive，不并行抢占，不将拒绝当作必须重置业务 session 的理由。此项不改变既有 wire 认证机制。

## 目标行为三：SDK 请求、路径与回调归属

已检查本地 SDK `11.2.100_3dmap11.2.100_loc11.2.100_sea9.8.1` 的 Java 接口：`AMapCalcRouteResult.getRouteRequestId()`、`getRouteid()`、`NaviInfo.getPathId()` 可用；当前 `AMapLaneInfo` 无 requestId/pathId。接口存在不代表已验证调用关联和回调顺序。

- 现有 Repository 的请求/选路入口维护待确认请求和已接受路线的最小上下文：App generation、目的地/请求信息、可关联的 SDK requestId、路由 ID/pathId、revision 与引擎实例。优先复用现有字段，必要时用小型值对象避免关联信息分散；不先拆独立 adapter。routeId 与 pathId 是不同字段，不能相互替代。
- 当前调用的 calculateDriveRoute 返回 Boolean，不能直接把它当 requestId。P2b 先验证 SDK 提供的请求级 listener/结果 ID 与实际调用如何关联；无法证明时序列化算路请求，保留“取消中/等待结果”边界，不让新旧请求并行覆盖。不能仅用目的地相同断言结果属于同一请求。
- 有身份的结果必须与待确认/已接受上下文匹配后才更新现有 state；重复成功只应用一次。`NaviInfo.pathId` 与已接受路径匹配才可更新 route-relative guidance；检查 location 步索引与该上下文的一致性。
- 没有身份的 lane/next-icon/路层通知，不能在收到时直接附上当前 generation 就视为来源可靠。引擎重建时用捕获实例代次的 listener 隔离旧实例回调；同实例换路需先清空旧值，并由 SDK 实际顺序/路径证据建立可接受的回调屏障。
- SDK 若无法为某类无身份回调证明同实例换路后的归属，仅将该类事实保留 unknown/缺失，不把隔离若干毫秒或连续两次相同值当成来源证明。该来源关联能力标为未验收；要恢复使用先补真实 SDK 序列。引擎销毁/重建仅在现有关联方式确实不足且隔离效果已验证时考虑，不为隔离可选车道字段默认重启整个导航引擎。
- 清理清单包括 lanes、next icon、last guidance step、route notice、road layer、指导/车道观察时间及匹配状态；不能只清时间而留 UI 旧车道。

模拟回调只能验证处理入口如何拒绝已标记的旧 generation；还必须有实际 SDK 调用/回调序列证明标签来自哪里。复用现有测试，不要求为此建立完整 fake engine 框架。A06/A07 都通过才能声称避免串线。

## 目标行为四：报文大小、解析与版本矩阵

保持 schema 3 及当前字段语义；目标两端 snapshot 最多 8192 UTF-8 bytes、ACK 最多 2048 bytes。收包缓冲至少上限加 1，以识别超限；超限丢弃，不能截断后尝试解析。592 是具体样例长度，不是新的协议固定长度。

core ACK 必须是 JSON 对象，含正确 messageType、整数 schemaVersion、字符串 sessionId、精确整数 sequence，匹配当前发送/传输代次；只支持四字段或加可选 vehicleLane 的已知形状。重复键、错误类型、布尔冒充数字、超范围序号和非有限数值需要明确拒绝，不能依赖宽松字符串强转。优先使用现有 JSON 库的类型/流式检查和有限的解析函数，不另造通用 JSON 解析器。当前 v3 未建立通用能力协商，不默认接受新增控制字段。

core ACK 合法只表示传输已确认。vehicleLane 缺失或不满足当前 21 字段 schema 时，反馈为 unavailable，不能补默认 false 当安全；应继续保持字段来源和有效性边界。iOS 初始兼容阶段可以只验证 core 并忽略 vehicleLane 的展示，但仍需能接收完整报文；完整反馈展示在后续阶段对齐。

2026-09-19 Android 实现记录：现有 UDP client 已按上述边界严格读取 ACK；core 合法而可选反馈类型/字段无效时保留链路确认，语法错误或重复键则拒绝整包并在剩余接收窗口内继续等待。新增 10 项解析测试，包含本地 C3 实际生成的 592-byte 默认反馈 fixture；报文与生产文件哈希见 `app/src/test/resources/navassist/c3-vehicle-lane-ack.provenance.json`。仅此 Android 样例与边界已验证，下表其余平台、Schema 和已部署接收端结论不随之升级。Repository 已补路线切换清理，但 SDK 回调的真实来源归属仍未验收。

| 组合 | 本地已知情况 | 设计要求 / 状态 |
|---|---|---|
| 当前 Android + 当前本地 C3 候选 | 实际 mapper 生成的 7 种状态整包、6 个扩展字段及默认 21 字段 ACK fixture | 已通过 59 组 snapshot Schema/解析器检查及 Android ACK 测试，文件哈希见本轮验证报告；未覆盖接收端 Store 的时效、owner 和目标设备版本，不宣称整链验收 |
| 当前 iOS + 带 vehicleLane 的本地 C3 候选 | 上限已改为 2048 bytes，支持四字段/可选 vehicleLane；已补严格 core token、重复键和长度用例 | 代码与 4 组 XCTest 已落地，复用同一 592-byte fixture；仅 Swift 语法解析检查通过，待 Xcode 编译和 XCTest，尚不能声明兼容验收完成 |
| 两平台 + 任一已部署 C3 | 本轮未读取部署版本 | 未验证；发布前记录接收端版本/哈希，不用本地 HEAD 代替 |
| 旧 v3 接收端 + 当前 Android 扩展字段 | 是否拒绝未知字段取决于该版本 | 未验证；不静默删除字段或推测兼容，先获取 schema/fixture |
| App 仓库 Schema + 当前 Android 扩展字段 | 已补 routeAvoid、道路层级/通知共 6 个可选字段，保留未知字段拒绝 | 与本地 C3 Schema 的完整 JSON 内容一致；合法值、错误类型、枚举、距离越界及缺省整包检查通过 |
| 未来字段/执行结果/建议请求 | 当前没有能力协商或完整事件结果 | 单独版本设计，不能夹带进本轮结构重构 |

协议修复复用现有测试，逐项补 core-only ACK、21 字段 ACK、有效/失效/null 反馈、UTF-8 边界报文、完整导航快照与缺少的签名/事件 ID 向量。P2a 先固定能复现差异的样例；各项修复前补对应边界，不要求先建设全量跨平台测试框架。样例记录生产者/消费者/Schema 文件哈希、session/clock 输入、预期解析和状态；比较完整 JSON/字节契约与业务结果，不只比较 lanes 子对象。端口、TTL、频率未变不等于整体兼容。

## App 状态展示约束

地图：“路线建议靠左/靠右”“当前路线避选”；OEM：“原车报告左侧许可”“原车车道位置未知”；最终执行：“等待 C3 判断”“C3 执行状态未提供”。不要显示“安全门控通过”“可安全变道”，也不要把链路 ACK 显示为动作已接受。

只在反馈确有事件关联和可靠状态语义时展示 started/completed/aborted/takeover；否则只显示原始状态与未确认含义。数据过期退出有效展示但可保留明确标记的历史诊断，不保留绿色许可暗示。现有有限雷达/盲区字段仅用于观测与能力诊断，缺邻道前后覆盖时不输出自动超车方向建议。

## 安全责任与未来共享用例

App 输出高层路线先验与可选建议意图，不输出实际控制命令。C3 唯一负责 0x239 车道位置/邻道/几何、0x399 既有许可与盲区、视觉实线/路缘硬否决、雷达/CarState、打灯/变道/转弯/纵向控制与安全状态机。不要把地图避选升级成物理否决，亦不要把地图推荐升级成车辆许可。

未来跨平台 fixtures 至少覆盖：idle/planned/realtime/simulation/recalculating/arrived、位置缺失和 NaN、routeMatched unknown/false、重复回调、同 step 重算、hidden/empty lanes、F/255、routeAvoid、未知字段、旧 session/sequence、缺反馈和超时恢复。固定 session/clock/revision，比较事件 ID 与规范化 JSON；签名另用完整 bytes 向量。

新建议契约若未来启用，应包含 request/event 身份、原因、过期时间与 C3 的 accepted/rejected/started/completed/aborted/takeover 状态，不能用“收到 ACK”冒充许可，也不能把 abort 计为完成。本轮无此新增发送功能。


## 2026-09-19 补充验证状态

iOS ACK 的 2 KiB 上限、可选 vehicleLane 和严格 core token/重复键检查已在原文件实现，新增 4 组 XCTest；仅语法解析检查通过，尚无 Xcode 运行结果。Android 已补受 DEBUG tag 控制的 SDK 关联日志，日志中的 App requestContext 不作为回调归属证明，真实 SDK 序列及 T_source/T_progress 仍待确定。

本地 C3 现有协议/意图测试 35 项通过；额外连续进程探针确认取消后经历 inactive/event=0 再恢复原事件仍为 blockedEvent、signalRequested=false。这一项由“未测”更新为“指定本地序列通过”，不扩大到重启、所有 owner 交接或已部署版本。具体序列、代码哈希和报告路径见 APP_REFACTOR_BLUEPRINT.md 本轮记录。


## 当前实现覆盖与默认能力（2026-09-19，优先于上文历史待办状态）

Android 已接入源健康出口检查、显式恢复、重启不恢复自动同步、请求 ID/pathId 与引擎代次校验，以及共享发送锁和 inactive 交接。`NAV_ASSIST_SOURCE_BUDGET_MS` / `NAV_ASSIST_PROGRESS_BUDGET_MS` 默认 0，表示未标定而非零毫秒健康期；默认 v3 routeActive=false、maneuverEventId=0，UI 显示仅预览。所有新本机元数据均 transient，不增加 wire 字段。

本轮原 calculateDriveRoute(List, List, List, int) 调用已换为 SDK 现有的 NaviPoi + AMapCalculateRouteListener 重载。使用调用 token 绑定 listener 返回的正请求 ID，typed 结果再对照 requestId 与 pathId；0/旧 token/无 ID legacy 结果不作为新路线。当前无 ID lane/next-icon/通知及 SDK 自发重算来源仍不可信，分别保持缺失或待重新规划，不假设“当前回调”等于“当前路线”。相关源码与 jar 字节码支持此实现选择，真实 SDK 顺序仍未验证。

本地 C3 的 source age 2000 ms 与 future skew 1000 ms 推导出交接确认窗口：在旧发送结束后等待严格超过 3000 ms，再取得 inactive 确认；失败后重新等待。该值仅绑定当前已记录的接收端实现，不替代源健康预算，也不增加 UDP 身份认证。8 步 Store 探针覆盖 inactive 后旧包迟到回抢与最终过期，不扩大为目标设备实测。

当前 125 项 Android 单测、Debug 构建与 59 组整包检查通过。真实 SDK 录制/标定、禁用能力的来源证明、设备验收及 iOS XCTest 尚未完成；完整限制、测试和回滚证据见 APP_REFACTOR_BLUEPRINT.md 最新记录。


## 2026-09-19 真机请求关联修正

实际设备上普通算路调用 ID=101、全局成功结果 ID=0，旧请求比较不能工作。现改用 independentCalculateRoute 每次调用的独立 listener，捕获固定 token/engine generation，主线程一次性完成该请求；路径组 ID 仍可能为 0，不以该值证明归属。预览/候选选择使用返回组，导航用 startNaviWithPath。全局路线成功/失败仅诊断，不接管 pending 请求；30 秒期限仅终止等待，不提供控制许可。停止/过期/旧回调不得完成新请求。已交给引擎的路径组保留到引擎销毁，避免停止导航后仍有地图原生引用时提前释放。

实施依据、128 项 Android 单测与真机结果边界见 APP_REFACTOR_BLUEPRINT.md 的“真机请求关联修复”及 D:/C3/.codex-tmp/tesnav-request-fix-20260919。定位/指导健康预算仍默认 0；无 ID lane/next-icon 及自发重算没有因此开放。此前“待真实 SDK 请求 ID 验证”现已得到不兼容证据，并由独立调用 listener 关联替代；其余外部验收仍按原范围执行。


## 目标 C3 扩展字段兼容更新已完成（2026-09-19）

已在实际设备 192.168.10.34 上仅更新 protocol.py、publisher.py、nav-assist-v3.schema.json、cereal/custom.capnp 四个文件，补齐 5 个 guidance 扩展字段和 lane.routeAvoid。保留原字段编号及控制判断；目标设备原有 22 个其他 tracked 改动文件哈希不变。设备端和本机均保存四文件更新前备份、精确哈希及回滚脚本。

在 offroad 状态重启后 scons 构建完成，NavAssist 服务恢复。下载实际部署文件再次完成 59 项整包校验；7 种状态真实 Cereal 消息构造通过。现场 inactive UDP 测试获得 ACK，六字段正确出现在 navAssistStateSP，过期后 stale=true。手机重开后接收 225/225、零拒绝，idle、stale=false、routeActive=false/event=0。此前“目标旧协议不接受扩展字段”的阻塞已解决；App 仅预览、真实行驶/健康预算、OEM 反馈、active owner/取消及 iOS 验收边界保持。

详细部署及回滚证据：[C3 更新记录](D:/C3/.codex-tmp/c3-protocol-update-20260919/RESULT.md)。设备端备份目录 /data/navassist-protocol-update-20260919/before。
