# TesNav 整体重构审计与蓝图

2026-09-22 当前补充：用户已明确接入导航变道、路口减速与转向灯。Android 实现、源失效后事件交接、148 项测试及当前车端离线联调见[接入记录](NAV_CONTROL_INTEGRATION_20260922.md)。已安装并验证空闲会话传输，实际导航待验证；下文仅预览与零预算描述保留为历史阶段证据。

版本：设计修订 v1.2，2026-09-19。设计复审阶段只修改文档与全局规则；用户随后授权开始实施，已完成文末记录的 P2a 展示、P2b 会话持有与 P3 停止后状态隔离修复，未修改 iOS/C3、参数或部署状态。

P0 审计与 P1 纯解析拆分已完成；P2a 的文案、超车能力边界与反馈显示期限已完成软件修复，真机显示/热点抖动验证仍待完成；P2b 已完成 Service 持有会话的局部修复，SDK 来源/源健康仍待实施；P3 已完成停止后状态隔离，解析与兼容项待实施；P4/P5 为有条件的后续范围。此前 75 项测试与 APK 构建结果只属于 P1；实施证据见文末。

设计依据：[城市 NOA 总体规划](../../C3_CITY_NOA_MASTER_PLAN.md)第 3、5–12 节，以及[变道统一优化计划](../../C3_LANE_CHANGE_CONSOLIDATED_PLAN.md)中的后续确认。总体规划保留了历史阶段描述；若旧版正授权规则、进度与统一计划的后续确认不同，以后续明确确认和实际运行版本证据为准，App 不另行复制或改写 C3 的正授权融合规则。

本文件负责功能边界、阶段和验收；[共享契约](NAVASSIST_SHARED_CONTRACT.md)负责时间、身份、回调归属与报文规则；[P1 记录](APP_REFACTOR_P1_RESULT.md)是历史实施证据。旧阶段顺序以本次修订为准。

## 最高工程约束与本次审查结论

所有修改必须遵照最小限度侵入原代码；正式全局规则位于 `C:\Users\panda\.codex\AGENTS.md`。本方案按“已确认问题 → 现有责任位置 → 必要局部修改 → 对应验证”实施，不能把目标职责表当作新建目录、模块、接口或状态机的任务清单。

v1.1 将完整 reducer、SDK adapter、FeedbackStore、settings repository 及诊断接口重建列入必经步骤，范围超过当前缺陷所需。v1.2 取消这些结构性前置要求，保留现有 Repository、Service、exporter、store 与 presenter。优先调整现有字段、函数及生命周期；只有局部方案确实无法解决已复现问题，才评估最小的新辅助函数或接口，并说明影响范围。目录整理、全量迁移和完整跨平台功能扩展不与缺陷修复绑定。

最小侵入同时检查行为影响：不能靠禁用全部正常导航、手动转弯或扩大速度限制来减少修改行数；证据不足时仅让相关事实/能力退出有效状态，保留不依赖该证据的正常功能。必要的正确性修复、兼容检查和回归验证仍须完成。

## 基线与保留方式

- 母本 `D:\C3\TesNav`，分支 `navassist-v2-track-p0`，HEAD `ca32055a7a5613071e0b7f6a48e84fea07032368`。
- 参考 `D:\C3\amapnavi`，HEAD `36fd481c36ffd6b683d4dce17704e90d5402ff0b`，只读。
- 实施基线是开始时的**完整工作树**，不是 Git HEAD。已有 9 个已跟踪修改文件，以及 OEM 反馈、超车建议、车道展示、测试和文档等未跟踪文件。
- 改动前备份：`D:\C3\.codex-tmp\tesnav-refactor-20260919`，包含 89 个源码、测试和文档文件、逐文件 SHA256、初始 Git 状态。备份不包含密钥/本地构建配置，不覆盖原文件。
- 现有工作树的 `testDebugUnitTest assembleDebug` 已成功，建立可编译基线。
- 未发现这两个仓库的项目级 AGENTS.md；全局 `C:\Users\panda\.codex\AGENTS.md` 适用，本次已增加最小侵入约束。未提交、推送或安装。

## 功能映射与源码依据

下表 T 路径根为 `app/src/main/kotlin/com/garan/tesnav/`；A 路径根为参考仓库 `app/src/main/java/com/carrot/amapnavi/`。函数名为稳定定位点。

| 能力 | TesNav 资产 / 参考资产 | 取舍与落点 |
|---|---|---|
| 地址搜索、定位、历史 | T `MainActivity.kt`、`search/AddressLookupController.kt`、`AmapAddressLookupGateway.kt`、`SearchHistory.kt`；A `MainActivityUi.kt:setupWebView`、`MainActivityAmap.kt:updateNaviState` 为网页/广播集成 | 保留 TesNav 原生搜索与独立测试；不搬参考 UI |
| 多路线选择、实时/模拟、语音 | T `data/NavigationRepository.kt:planRoute/selectRoute/startNavigation`、`RouteSelectionCoordinator.kt`、`config/SpeechMode.kt`；A `MainActivityAmap.kt` 消费导航状态 | 保留入口和行为；只在 Repository 修正来源关联、清理和线程边界；模拟不激活控制 |
| 路线/动作规范化 | T `util/NavigationMappers.kt`、Repository `onNaviInfoUpdate`；A `MainActivityNaviProcess.kt:AmapNavi` | 保留 TesNav 词汇、事件身份和现有 mapper；按复现问题局部修正，不为拆分移动其余转换 |
| 推荐与避选车道 | T Repository 两个 `showLaneInfo`、`model/LaneState`；A `MainActivityAmap.kt:parseDriveWay`（464 行起）读取 `trafficLaneAdvised` 并拼接 `*`/`X` | 继续使用现有结构化 LaneState 和 P1 normalizer，不另写解析器。F/255 是路线避选，不是物理/法规禁行 |
| 下一动作、道路层级、路线通知 | T 未提交的 `onNextManeuverInfoUpdate/notifyParallelRoad/onNaviRouteNotify` 与 v3 mapper | 保留新增资产；记录协议扩展尚待接收端兼容验证 |
| 相机车道检测、线型/车道定位 | A `LaneDetect.kt:infer`、`LaneLine.kt`、`JpegFrameFetcher.kt`、`OpState.kt:visionLaneCalc` | 不采用为 App 控制权威；C3 持有 0x239、视觉几何/实线/路缘 |
| 自动超车 | T `ui/AutoOvertakeDecider.kt:decide`；A `MainActivityLaneDecision.kt:evaluateOvertakeTrigger/evaluateOvertakeSide`、`MainActivityOvertake.kt` | 在现有 decider/presenter 补年龄、非法值和能力不足处理，保留可解释因素；不重写建议框架，不复制执行状态机 |
| 打灯、变道、转弯命令 | A `MainActivityLaneControl.kt:sendLaneCmd/sendBlinkerCtrlComm/sendLaneActionCmd`（56/66/75 行），发 carrotCmd/ctrl | 不采用；不发送方向盘、曲率、加减速、CAN 或旧遥控命令。实际执行归 C3 |
| 雷达/车辆状态页 | T `model/OemVehicleLaneState.kt`、`CommaState.kt`、`ui/NavigationStateDialog.kt`；A `MainActivityUi.kt:renderOvertakeDebugPage`、雷达卡片函数 | 保留现有只读模型和布局；修正来源/年龄展示，不另建反馈仓库或传感器融合 |
| 网络/设备发现 | T `export/HttpNavAssistV2Exporter.kt`、`UdpNavAssistV3Client.kt`、`NavAssistV2Discovery.kt`、`NavAssistIdentity.kt`；A `UdpService.kt`、`MainActivityUdp.kt`、`UdpDeviceManager.kt` | 保留现有类与传输接口；局部修正解析边界和停止后迟到返回；不重做发现流程或增加 UDP 通道 |
| 事件去重/重算 | T `NavAssistV2Session`、`StableManeuverEventId`、Repository `routeRevision`；A `laneChangeCmdIndex` 与 `NavRuntimeState.kt` 多套计时器 | 保留 session/revision/step/maneuver 事件键；不通过重复 command index 重试执行 |
| 设置、API Key、播报 | T `config/*`、`ui/SettingsDialog.kt`、`AmapKeyActivity.kt`；A `SettingActivity.kt`、`MainActivitySettings.kt` | 保留用户配置与存储；没有对应缺陷就不调整，不引入 settings repository 或参考驾驶控制参数 |
| 日志与诊断 | T Service `logNavAssistDiagnostics`、Repository `TesNav-AMap` 日志；A `AppLogger.kt:shareLogs`、`LogStorage.kt`、`OvertakeLogger.kt` | 在现有限频日志补本次问题必需的原因和时间；新导出功能列为可选，不重建日志框架 |
| 后台生命周期 | T `NavigationForegroundService.kt` 持有 SDK 与 exporter；A `KeepAliveService.kt`、`RestartReceiver.kt`、MainActivity 扩展 | 保留前台 Service 所有权，不照搬 Activity 全局状态或重启机制 |
| Android 特有集成 | T `homeassistant/HomeAssistantNavigationClient.kt`、Service Tesla 同步与 legacy WebSocket | 隔离保留；与主 NavAssist 会话分清状态和身份，不要求 iOS 同步复制 |
| 付费/远程网页等 | A `WxPayActivity.kt`、`WebViewActivity.kt`、`AppGlobalState.kt` 远端服务 | 不采用，不迁移签名、密钥、模型和资源 |

## 工作树审计：资产与风险

以下保留 P1 工作树的静态审计发现，后续修复状态以文末实施记录为准；除构建/单元测试外，未声称已通过真机或 C3 回放。

1. **可保留资产**：StateFlow 最新快照、同步 store 更新、Service 持有引擎、纯 mapper、路由选择协调器、协议/发现/签名测试，以及新车道 presenter 与建议测试。Activity `onStop` 已取消两路订阅并解绑，`onDestroy` 取消 scope，不应误报为完全没有清理。
2. **导航状态仍分散**：Repository 的 `routeRevision` 与 State 内副本、`lastGuidanceStepIndex/nextManeuverIconType`、`routeCalculationPending/requestedNavigationMode` 形成隐式状态机。`clearRouteValues` 不清空这些字段；相同步索引的新路线可能携带旧 next icon。`routeSucceeded/selectRoute` 清观察时间但未一并清 `lanes`，wire 不发但 UI 可短暂显示旧路线车道。P2b 先补齐现有清理入口，并在现有回调入口校验 SDK 来源；不以全量 reducer 迁移为前提，也不能只给迟到回调盖上当前 generation。
3. **双映射行为是现状，不应顺手统一**：`NavigationMappers.laneActions` 与 `navAssistV2LaneActions` 对 5、13、17–20 等值不同。新版回调推荐走显示映射，旧版推荐走 wire 映射；wire 最终重新解析 raw 类型。旧版 F 与新版 255 标记避选，旧版字节 255 本身不标记避选。P1 原样冻结并测试，不猜测 SDK 语义。
4. **线程边界**：StateStore 的单次更新有锁，但 Repository 的字段与“读取→计算→更新”整体没有统一调度约束。Service 主线程调用与 SDK 回调线程需要验证；不能从 store 有锁推断整个仓库线程安全。P2b 根据实际线程证据将相关更新收敛到现有调度入口或小范围临界区；SDK 命令遵守主线程要求，新增期限逻辑只注入所需时间函数，不增加完整事件总线。
5. **反馈状态副本**：Exporter→Service 多个 MutableStateFlow 镜像→Activity 的 currentState/currentOemLaneState，两条 collect 依次 render 可能短暂组合不同时间快照。它们当前是显示缓存，并不是多个 CAN 真相源；优先在现有渲染入口校验年龄/代次，必要时局部组合现有 Flow，不以清除全部镜像或引入 FeedbackStore 为前提。
6. **生命周期网络竞态**：`HttpNavAssistV2Exporter.stop` 取消 job/scope，但阻塞 UDP 收包未立即中断，返回后仍可能发布 ONLINE；HTTP post 后也需 generation/isActive 检查。同实例 stop 后 scope/client 已关闭，start 无法可靠重用；现有 Service 重建实例规避了部分问题。P3 保留单次生命周期实例和 Service 重建方式，补取消后返回检查及关闭边界；不新增可重启框架，测试 stop 中迟到 ACK、切网络、重建实例。
7. **UDP 真实性与解析**：默认 Service `useUnauthenticatedUdp=true`。session/sequence/来源 IPv4 校验只关联请求，不能验证 C3 身份，也没有多设备拒选。ACK 顶层标量转换及 `getAsJsonObject(vehicleLane)` 在局部 runCatching 之外，类型错误可能使本轮发送失败而不是继续等待合法包。float 未限制 finite/range。精确 key 集合要求也需要协议演进策略。P3 在现有 client 中收紧解析边界，按需提取可测试的纯解析函数，补畸形包用例；不更换 JSON 库或静默更改认证方式。
8. **时间与建议**：UDP 超时会清反馈，但 `AutoOvertakeDecider` 自身不检查 receivedAtMs、finite 数值或 UNKNOWN position；pause/无新事件时 UI 没有独立 freshness tick。`LaneGuidancePresenter` 使用“安全门控通过/可变道”措辞，把部分 OEM 许可放大为安全结论。修正已前移至 P2a：只展示路线推荐/原车状态/待 C3 判断，过期反馈显式 UNKNOWN；缺少邻道前后覆盖时不生成主动超车方向建议。不得连到执行出口。
9. **协议命名与文档漂移**：V2 类名实际发送 schema 3；见单独契约。dirty diff 已扩展 wire，本轮只能保证不再改变它，不能把“与当前工作树相同”说成“与所有线上 C3 兼容”。`NAVASSIST_V2.md` 的 500 ms 与代码 1200 ms 不符，已有车道说明对 freshness 的断言也超过 App 当前实现。
10. **诊断不足**：Service 按变化 key 限频，但 key 不含全部车道/反馈原因，SDK 日志未统一限频。随对应修复在现有日志补 session/revision/event、来源时间和失效原因，验证日志增长；完整故障链平台、独立配额系统和导出均非本次必需。位置、地址、token 不默认写导出日志。
11. **发送心跳不证明 SDK 活着**：Exporter 每轮更新 sourceWallTimeMs，而 mapper 不因旧 location/guidance 自动撤销 active。本地 C3 `publisher.py` 明确以接收 TTL 而非 guidance 年龄作为主有效性条件。App 数据源健康规则在 P2a 准备证据，P2b 冻结相关预算并实现；不能把继续发包当成新导航观测，也不能对低频不变指令统一套短 TTL。
12. **传输对象寿命改变业务事件**：当前 exporter 自持 session，重建可能改变同一路口事件 ID；C3 按 session/revision/event 保存取消与阻塞。P2b 优先由现有 Service 持有现有 `NavAssistV2Session` 并传入 exporter，普通重连不清身份；不新建 runtime 框架，新会话启动/接管恢复另有约束，见共享契约。
13. **ACK 兼容不止 key 集合**：iOS 同时限制四个字段与 512 bytes；本地 C3 默认 21 字段 vehicleLane、UUID session 的基础 ACK 实测 592 bytes，Android 上限 2048。P2a 必须冻结完整报文样例和版本矩阵；不能只修改 iOS 字段允许表。这是本地候选代码证据，不代表已部署设备。
14. **Schema 也已漂移**：App 仓库 `protocol/navassist-v3.schema.json` 使用 additionalProperties=false，却缺当前发送的 routeAvoid 和道路层级/通知字段。P2a 核对 Schema、完整发送样例和固定接收端版本的差异，P3 同步已核验约束并验证整包；本轮不修改 Schema 文件，不将已有 lanes 断言视为整包 Schema 通过。

## 城市 NOA 分层与 App 交付边界

App 的目标是可靠的路线意图源和状态窗口。总体规划的 L1/L2/L3 是整车能力分级，不因 App 重构、导航在线或单元测试通过而获得。

| 城市 NOA 能力 / 工作包 | App 提供或展示 | C3 独有职责 / 本任务限制 |
|---|---|---|
| L1、W0–W4：受限单次导航动作 | 实时路线、当前动作、距离、推荐/避选、稳定事件；展示已确认的 C3 状态 | C3 决定打灯窗口、实体灯反馈、一次开始资格、失败锁存与完成证据。App 不递增 requestId 重试执行，不把 ACK 视作动作接受 |
| L2、W5：连续选道 | 保持同一路线事件和更新推荐，区分重算与连续进度 | 每道完成确认、下一道许可和次数预算归 C3。App 不因箭头变化累计成功；完成不明不得宣称“已换道” |
| L2、W6：横纵向协同 | 路线动作/距离、明确来源的道路信息 | 跟车、停车、速度约束、控制权及制动可行性归 C3；App 不发曲率、转角、加减速，不从测速限速推导弯道速度 |
| L3、W7：城市路口 | 区分 turn/exit/ramp/merge 等地图语义，显示可用性限制 | 转弯走廊、来车/行人/骑行者、方向信号与让行资格归 C3；低速、绿灯、箭头和“已靠边”均不证明可通行 |
| 主动超车/自动回原道 | 当前仅展示慢车、传感器可用性和“能力未就绪/缺少覆盖”诊断 | lead + OEM 许可 + 无盲区报警不足以证明邻道前后安全；数据前提未满足时不启用方向建议或请求，更不自动执行 |
| 特殊车道/绝对第 N 道 | 显示地图原始动作、车道属性及未知项 | 239 middle 不是绝对索引；高德数量相同不证明对应。初期相对靠左/靠右目标由 C3 解析；公交/潮汐/可变/施工适用性不得猜测 |

以下不变量纳入 App 验收：

- 地图推荐是路线先验；routeAvoid 是路线避选。真正法规禁行须有明确类别、车辆/时段适用性和道路定位，不能由 F/255 推导。
- 239 的 position/邻道/几何不是跨线许可；399 是已有许可与危险信息之一；实线/路缘与可信危险由 C3 统一否决。App 不复制正授权 OR/AND 规则，不用自己的建议覆盖它们。
- 意图有效、灯光可执行、横向可开始、动作执行中、动作完成是不同概念。当前 ACK 没有完整事件绑定的执行结果，不补造 accepted/completed。
- 丢导航、重算或 App 退出只撤销新的导航意图；正在执行的轨迹、灯光归属和降级由 C3 处理。App 不发反向动作“回原道”，不取消驾驶员灯光；无导航不等于禁止驾驶员正常手动转弯。
- 错过出口/准备窗口接受重规划，不触发抢出口、追赶式急刹、跨实线或多道连续抢道。即使主路线仍 active，某个动作窗口是否过期也由 C3 判断。
- 不新增 C3 常驻进程、第二套规划器、相机推理、雷达副本或影子模式。App 诊断依附现有 Service 和 UI 生命周期，不用高频后台轮询代替 SDK 健康证据。

## 复审问题的设计闭环

| 编号 | 设计决定 | 对应验收 |
|---|---|---|
| R1 数据停滞 | 分开 linkStatus、sourceHealth、routeValidity、feedbackValidity；本机期限使用 monotonic，wire 保留 wall 时间。停滞期间发 routeActive=false，原事件身份不变；恢复必须有属于当前路线的新证据 | A01–A03 |
| R2 身份抖动 | 现有 Service 持有 session/sequence；socket/sender 重建不创建业务会话。revision 只因明确路线变化/失效改变，重复成功回调不变；进程重启默认不自动恢复 active。还须验证 inactive/event=0 不会解除目标 C3 的取消锁 | A04–A05 |
| R3 回调串线 | 请求代次与 SDK requestId/pathId 建立可核验关联；lane/next-icon 无独立 ID 时设来源不明状态，不能在回调接收时直接盖当前代次 | A06–A07 |
| R4 报文兼容 | 两端冻结 8 KiB snapshot / 2 KiB ACK 的目标上限、UTF-8 长度和 4/5 字段 ACK 样例；矩阵记录 App/接收端版本和内容哈希，未验证项明确阻断兼容声明 | A08 |
| R5 展示越权 | 在下一阶段首先移除安全许可式措辞，过期反馈显示未知；当前主动超车方向建议转为能力诊断，不等待整个 UI 重构 | A09–A10 |

具体时钟、恢复规则和来源关联限制见共享契约；代码实施与尚未启用的能力以本表及文末最新记录为准，不以历史“待实施”描述覆盖当前状态。

## 现有责任位置与最小修改范围

下表表示职责，不要求建立新包或 Gradle module。保持现有类名、目录、构建结构和公开接口；测试接缝优先采用现有入口或小范围纯函数。新增字段仅表达当前缺陷所必需且现有字段无法区分的信息，不为未来能力预建框架。

| 现有位置 | 对应问题与允许的局部修改 | 范围限制 |
|---|---|---|
| `data/NavigationRepository.kt` 与现有 store | R1/R3：补路线相关清理、有效来源时间、请求/path 关联及更新顺序 | 保留 SDK 调用与存储入口；不迁移为完整 reducer，不建立第二份可写导航状态 |
| `service/NavigationForegroundService.kt`、`NavAssistV2Session` | R2：延长现有 session 生命周期，向 exporter 提供同一对象；停止/重启保持既有入口 | Service 继续负责 SDK 与发送器；不另建 Runtime/SessionOwner 层，不持久化自动执行许可 |
| `AmapLaneNormalizer`、`NavigationMappers` | 复用 P1 纯算法及现有 active 映射，接入经过校验的状态 | 不顺手统一 UI/wire 历史映射，不复制参考算法 |
| `HttpNavAssistV2Exporter`、`UdpNavAssistV3Client` | R4/A11：解析类型/长度/finite 校验、取消检查、迟到返回隔离 | 保留发送、发现和签名结构；单次实例生命周期，不引入通用传输框架 |
| `OemVehicleLaneState`、Service 现有反馈 Flow | R5：明确有效性与本机接收年龄，必要时补最小元数据 | 导航与车辆事实保持各自来源；无独立 FeedbackStore，不把显示缓存当新业务 owner |
| `LaneGuidancePresenter`、`AutoOvertakeDecider`、现有 Activity 渲染入口 | R5：文案、期限重绘、非法值与缺少覆盖的诊断 | 复用生命周期和 Flow；局部组合不代表同帧，不新建 UI 架构或执行状态机 |
| 现有 Service/Repository 日志与测试 | 为上述问题增加可复现输入、必要原因和边界断言 | 复用现有测试框架与日志；不搭建新监控/回放平台，不以测试数量代替覆盖 |
| iOS 现有 UDP 接收函数与协议 mapper | 先修 ACK 字段和长度，再按已确认差异补映射 | 不要求复制 Android 类结构；不支持的 SDK 事实保持缺失 |
| `config/*`、设置/Key/播报、设备发现 | 本轮审查未确认必须重构的缺陷 | 不改设置存储、认证、搜索、Home Assistant、Tesla 同步架构和无关 UI |

上述局部方案若经复现证明不足，先在同一问题下记录具体原因、最小替代方案和受影响调用方；不能只以“更整洁”“更方便未来扩展”为理由扩大范围。

## 阶段、测试与退出条件

| 阶段 | 修改范围 | 验收与回滚边界 |
|---|---|---|
| P0（已完成） | 只读审计、备份、功能映射、契约差异 | 基线能测试/编译；明确 dirty diff 与本轮 delta |
| P1（已完成） | 两种 lane 回调算法抽到纯 normalizer；Repository 保留 SDK 与 store 入口 | 75 项测试和 debug 构建通过；历史协议语义不变。详见 P1 记录 |
| P2a（软件修复完成，真机待验） | 文案、能力诊断、monotonic 显示期限及无消息失效已实现；源未确认时显示仅预览 | A09/A10 软件用例通过，ACK/Schema 离线检查完成；真机布局和热点抖动未验收 |
| P2b（保护逻辑已实现，能力启用待证据） | 会话持有、路线清理、请求 ID/pathId/引擎代次关联、源健康与显式恢复、重启禁止自动同步均已接入 | 默认健康预算未配置，routeActive 保持 false；无 ID 可选事实和无关联自动重算结果不作为有效观测。A01–A07 本地边界已测，真实 SDK 序列、预算标定及设备验收未完成 |
| P3（Android 修复已验证，iOS ACK 已改待验） | exporter 生命周期隔离、严格 ACK、Schema 对齐、共享发送锁与 inactive 交接已完成；iOS ACK 已修改并补 XCTest | Android 单测和整包检查见最新记录；iOS 仅语法解析检查通过，未编译/运行 XCTest；接收端已测指定本地 owner/取消序列，不能扩大为全部设备验收 |
| P4（条件项） | 仅当 A09/A11 仍复现错帧或重绑问题时，局部调整现有 Flow/渲染入口 | 相应 A09/A11 与旋转/前后台/重绑；无缺陷则无代码改动，不整理设置或整体 UI |
| P5（后续范围） | 按产品需求逐项评估 iOS 剩余差异和诊断导出，不作为 Android 局部修复前置 | 每项另列必要差异与验收；不为功能对齐复制架构。性能、协议和相关回放随对应修改完成，不推迟到 P5 |

### 验收矩阵

| 编号 | 输入与故障序列 | 必须证明的结果 |
|---|---|---|
| A01 | UDP 持续 ACK，但 SDK 不再提供有效新观测；跨源健康期限 | App 不再续发 active；link 可在线、source 显式停滞；C3 收到 inactive。已有轨迹由 C3 处理 |
| A02 | 停车等待、同一路线/同 step 指令不变，但定位样本持续有效 | 不把“不变 guidance”误判为全源断流；不刷新旧观察时间；车道、通知按各自有效性处理 |
| A03 | 时钟回拨/未来样本、重复源时间、冻结后恢复、行进中 step 改变而 guidance 不变 | monotonic 期限不被 wall 回拨延长；重复包不算恢复；恢复需当前路线关联，不能用旧 guidance 搭新 location 激活 |
| A04 | 同一导航事件中断网、切 Wi-Fi、sender 重建、HTTP/UDP 模式切换 | session/revision 与有效时非零 event 稳定（inactive 按 v3 输出 0），sequence 不倒退；单 sender；验证接收端 ownership 交接与取消/阻塞不被解除 |
| A05 | C3 中止后 App sender 重建；进程重启；真正新路线/显式重新使能 | 普通重连不清事件锁；重启默认为 inactive，不从缓存自动接续；无法取得可信执行状态时不自动恢复；真实新路线改变与清锁分开验收 |
| A06 | 请求 A 未完成又请求 B；B 生效后 A 成功/失败迟到；成功双回调 | A 不覆盖 B，不复活已停止路线，不重复增加 revision；记录请求 ID/pathId 与拒绝原因 |
| A07 | 路线切换后旧 lane/next-icon 到达；新旧路线 step 相同；选路、重算、隐藏 | 清除旧 lanes/icon/notice/观察时间；来源不明不标成 B 的新观测。若 SDK 无法证明关联，明确限制而非仅靠计时器声称解决 |
| A08 | 四字段 ACK、带 21 字段反馈 ACK、512/592/2048/2049 bytes、坏类型/旧 session/乱序 | 在统一上限内按契约解析，超限拒绝；core ACK 与反馈有效性分开；Android/iOS 与固定版本 C3 golden 样例对照 |
| A09 | 新鲜 OEM 许可但 C3 最终结果缺失；超时、NaN、UNKNOWN、C3 中止 | 无“安全通过/可执行/已完成”误报；显示原车状态或未知；不将中止或反馈断流计作成功 |
| A10 | lead 较慢、OEM 允许、无盲区报警，但缺邻道前后覆盖 | 仅显示数据/能力诊断，不生成主动超车方向请求，不把无报警解释为全空间安全 |
| A11 | stop 与阻塞收包交错、旧实例迟到 ACK、持续旧包、service 重新绑定 | 旧 generation 不写新状态、不发送新业务动作；停止后不复活 ONLINE；无多 sender 和无界队列 |
| A12 | 模拟、错过出口、路口停车/起步、无导航手动转弯、连续选道完成不明 | 模拟永不 active；App 不抢出口、不释放停车约束、不接管手动转弯、不累计未经证明的跨道成功 |

期限、恢复样本判据和来源关联需要在 P2a/P2b 的夹具与 SDK 记录中冻结；没有验证依据时状态为 UNKNOWN，不把阈值未定解释为无限有效。单测用预算参数的边界值验证规则，真机 SDK 记录确定适用数值；不得借用 C3 239/399 TTL 作为手机 SDK 默认期限。

App 单侧无法保证 C3 的事件锁跨 inactive 或重启保留。本地 `lane_intent.py` 存在事件键变化时清除 cancelled key 的路径，而 v3 inactive 会输出 event=0；因此 A05 必须含“取消→inactive/0→同事件恢复”，不能只测试 sender ID 相等。目标 C3 未通过该用例时，App 故障后保持 routeValidity 待重新使能，只显示路线预览，禁止自动恢复导航意图；需要车端语义调整的能力单列依赖，本任务不顺带修改 C3。

兼容策略：P1 冻结 schema、序列化、端口、TTL、频率和事件 ID 算法。后续保持 v3 字段、单位、哈希算法；source health 导致 active 撤销、runtime session 生命周期调整是明确的行为变化，须单独验收，不称为“纯结构兼容”。新增 wire 字段先核对固定接收端版本允许列表；能力协商当前不存在，不能假定已具备。必要时另做版本升级，不能用缺字段默认值伪造许可或结果。

### 交付与回滚门槛

本次文档修改不授权立即执行 P2a–P5。下一次实现前，保存当时脏工作树、文档版本和相关文件哈希；每阶段只改所列 App 范围。实现可分步，面向车辆的候选交付需统一通过共同验收，不逐项追加并部署。

每项修复在差异说明中列出问题编号、必要修改位置、保留的行为和针对性验证。与问题无关的搬移、格式化、改名及测试框架建设不进入同一差异；结构整理不作为修复完成条件。A01–A12 是总体行为验收目录，局部修改运行相关用例及项目必需检查；新增失败或未决风险才扩大验证范围。

任何真机候选交付前至少完成 R1–R5 对应行为、Android 单测/构建、SDK 序列验证、与目标 C3 版本的离线协议检查；未提供版本/录制证据的项目保持未验收。iOS ACK 缺口未修复时不得声称同一接收端兼容两平台；完整 iOS 发布另需 XCTest/Xcode。

代码回滚与运行时回滚分开：按阶段 delta 恢复源文件、保留用户原改动；已 active 时不热切旧 sender、不通过重置 session 清除失败，也不在 App 中取消驾驶员灯或指挥横向回退。若行为状态格式不兼容，停止新增导航意图并通过既定人工重新使能流程处理，由 C3 继续承担正在执行动作的安全退出。

P1 回滚：只对照本轮实现记录中的文件恢复到备份版本，删除本轮新增文件前先确认没有后续编辑。绝不能 `reset --hard`、checkout 整个工作树或覆盖用户后来改动。备份中的 protocol/service/UI 原文件应保持哈希相同。

后续面向车辆的 Android 候选验收包含真机 SDK 回调、后台存活、目标 C3 接收端兼容及相关状态机回放；iOS 发布再完成其编译、XCTest 和对应集成验证，不将完整 iOS 迁移绑定到 Android 局部修复。本轮不安装 APK、不连接控制设备，也不以单元测试代替上述验收。

## P2a 首批实施记录（2026-09-19）

用户在方案复审后授权开始工作，先实施不依赖未知 SDK 时序的 R5 局部修复。上文“本次文档修改不授权实施”描述此前设计轮次，不能覆盖后续授权。

- 仅修改两个运行文件：`ui/LaneGuidancePresenter.kt` 去除“可向左/右变道”“安全门控通过”及原车位置代表路线已就位的推断，区分路线建议、原车许可/未知与等待 C3 判断；`ui/AutoOvertakeDecider.kt` 保留现有输入/返回接口和诊断入口，缺邻道前后覆盖时始终返回 KEEP、不具备方向建议资格，增加 UNKNOWN 位置与 NaN/Infinity 检查。
- 修改两个现有测试文件；覆盖左右许可有效/无效、位置与许可/盲区组合、非有限输入、无地图车道时的能力诊断，以及地图箭头保留。
- `testDebugUnitTest assembleDebug --console=plain` 成功，80 项测试，0 失败/错误/跳过。未安装 APK、未修改协议/Service/C3、未提交或推送。
- 实施前备份与工作树哈希：`D:\C3\.codex-tmp\tesnav-p2a-display-20260919`。回滚只按这次文件差异进行，保留已有用户改动。

这不是完整 P2a 或车辆候选交付：反馈年龄仍沿用既有接收路径，尚无独立 monotonic 期限重绘；不能声称旧反馈必然及时退出展示，也未验证真机布局。下一步核对既有收发周期与反馈清理路径，补 T_feedback 的证据和最小期限失效实现；SDK 源活性及会话恢复仍按 P2b 的独立依赖推进。

### P2a 第二批：反馈显示期限（2026-09-19）

接续首批记录，已补独立显示期限。依据为当前 exporter 的最小/默认发送间隔 200 ms 和 UDP 单次收包窗口 350 ms；T_feedback 定义为有效配置发送间隔加 350 ms，默认 550 ms。这是“下一轮 ACK 最迟预期到达前”的本机显示上限，使用代码时序证据；不是传感器源年龄、导航 TTL 或实际热点调度延迟测量。超过上限优先显示未知，真机抖动造成的短暂未知仍需记录评估，不宣称期限已完成道路标定。

最小修改限于四个运行文件：UDP 接收入口在 socket 返回时记录 `SystemClock.elapsedRealtime()`；现有反馈模型增加本机时间、年龄检查和基于现有 Flow 的可取消期限转换；Activity 将转换接入原有订阅，停止观察时清显示缓存、恢复前台时重绘；原有 View 每次渲染再按单调时间检查，防止挂起后缓存或排队消息重新显示旧许可。期限不更新原始 Service 状态、不改 wire 字段，也不控制 C3。

新增一个测试文件覆盖精确到期边界、缺失/未来/负时间、wall 回拨、无消息到期、新样本替换旧期限、重新订阅旧缓存、取消订阅和路线箭头保留。`testDebugUnitTest assembleDebug --console=plain` 成功，87 项测试，0 失败/错误/跳过。Android 真机 Activity 生命周期和画面未实测，主线程阻塞时只能在恢复调度/渲染后撤销显示；不把测试通过解释为硬实时保证。

备份：`D:\C3\.codex-tmp\tesnav-p2a-feedback-expiry-20260919`。未安装、部署、提交或推送。P2b 的 SDK 源健康/回调归属/会话身份、P3 的停止后迟到 ACK 等问题仍独立存在，显示期限不能代替这些修复。

## P2b 首批：Service 持有导航会话（2026-09-19）

根因是 `clearNavAssistPairing → rebuildDataExporters` 会替换 exporter，原 session 随之重建。现将已有 `NavAssistV2Session` 持有位置提升到同一个 `NavigationForegroundService` 实例，首次按现有配置 TTL 创建，以后向重建的 exporter 传入同一对象；没有新建 runtime/owner 类、状态仓库或持久化机制。exporter 保留未注入时的既有默认行为，生产 Service 明确注入。`NavAssistV2Protocol.kt` 只改生命周期注释，事件哈希、wire 字段与 TTL 算法不变。

在原有 exporter 测试中增加五项用例，通过实际发送入口捕获整包：重建前后同一 active 事件、UDP 失败后重试、UDP/HTTP/UDP 实例复用同一对象、inactive/event=0 后原事件身份，以及新会话对象配 idle 输入。验证 session/revision/event 的预期关系与单调序号，并验证自定义 500 ms TTL 保留。最后一项仅测试新 owner 加 idle 输入，不是 Android Service 重启或自动 Tesla 同步恢复的集成验证。

`testDebugUnitTest assembleDebug --console=plain` 成功，92 项测试，0 失败/错误/跳过。两个运行文件有逻辑变化，协议文件仅改注释，测试改一个现有文件；备份与差异位于 `D:\C3\.codex-tmp\tesnav-p2b-session-owner-20260919`。未安装、部署、提交或推送。

本次仅关闭 R2 中 exporter 重建导致身份抖动的问题。未验证目标 C3 的 owner 交接、取消锁跨 inactive/0 的保留，未实现异常重启后的完整恢复限制；停止后阻塞 ACK/HTTP 返回仍可能更新旧实例状态，属于 P3 待修复项。不能以本次跨传输实例的离线发送测试宣称 active 模式热切换已安全，也不能把原事件身份稳定等同于取消状态保留。

## P3 首批：停止后迟到返回的状态隔离（2026-09-19）

接续上次记录，已修复 UDP ACK/超时/错误、HTTP 成功/错误及设备发现返回后覆盖停止状态的问题。实现限于 `HttpNavAssistV2Exporter.kt`：发布结果与 stop 清理共用同一实例的短锁，网络调用和关闭资源放在发布锁外；stateProvider 返回及 HTTP 签名后再次检查运行状态，停止后不继续该轮后续发送。实例停止是终态，start 不再复用已取消的 scope，重复 stop 只关闭资源一次；Service 保持新建 exporter、复用导航 session 的方式，不新增生命周期框架。

在现有测试文件新增五组回归，修复前五组全部失败，修复后通过。通过可注入 dispatcher（生产默认仍为 Dispatchers.IO）、单线程执行器和闩锁固定交错顺序，等待当前回调处理完成后检查停止状态、端点、错误、反馈及发送次数；未添加测试库。覆盖 UDP 成功/超时/抛错、HTTP 成功/抛错、发现成功/无结果/多设备/失败、取状态时停止以及停止后重启/重复关闭。

`testDebugUnitTest assembleDebug --console=plain` 成功，97 项测试，0 失败/错误/跳过。仅一个运行文件和一个现有测试文件有代码变化；备份与逐文件差异：`D:\C3\.codex-tmp\tesnav-p3-stop-isolation-20260919`。未安装、部署、提交或推送。

本次保证旧实例的迟到返回不再发布在线、端点、错误或车辆反馈。已经进入网络调用的请求仍可能完成，不能撤回已发报文，也未改变设备发现内部配对存储逻辑；不把本地发布隔离等同于 C3 owner 交接完成。SDK 源健康/回调归属、接收端取消锁、ACK 严格解析/平台兼容及真机验证继续保持未完成状态。

## P3 ACK 解析与 P2b 路线清理补漏（2026-09-19）

Android 在现有 `UdpNavAssistV3Client.kt` 内增加可单测的 ACK 解析入口，复用 Gson 严格读取模式，不新增依赖。严格检查 UTF-8、完整 JSON、重复/未知字段、标量类型、精确整数及 session/sequence；错误包返回 null，收包循环在原剩余窗口内继续等待。core 合法而可选反馈缺失或字段不合格时保留链路 ACK，反馈 unavailable；JSON 语法或重复键不合法则拒绝整包。反馈只接受现有 21 字段，检查有限浮点数、距离/自车速度非负及已核验的枚举范围。接收窗口、端口、snapshot 上限和未认证 UDP 方式均不变。

新增 10 项 ACK 测试覆盖 core-only、21 字段、512/592/2048/2049 bytes、UTF-8 字节边界、错误类型、Long 精度、重复/未知键、尾随内容、非法 UTF-8、可选反馈降级、有限数及枚举。592-byte fixture 由本地 C3 `OemLaneFeedback().snapshot(now_ns=1)` 实际生成；资源目录内 provenance 记录生产文件和报文 SHA-256。它证明这一默认反馈样例兼容，不代表目标设备版本或所有 C3 状态已经验证。

`NavigationRepository.kt` 直接补齐既有清理入口：选择新路线与接受新 revision 时清空车道数组、道路/转向显示，清空 next icon 和 last guidance step 私有缓存；重算开始及原有 clearRouteValues 同样清理缓存。重复成功回调不清空当前有效数据。未拆 Repository、迁移状态仓库或引入 SDK 测试框架；清理逻辑经入口代码检查及编译，尚无真实 SDK 生命周期回放，不能宣称跨路线迟到回调归属已修复。

`testDebugUnitTest assembleDebug --console=plain` 成功，107 项测试，0 失败/错误/跳过；仅有既存 SDK 废弃接口覆盖警告。本轮两个运行文件、一个新增测试文件、两个 fixture 资源及两份文档发生变化。备份和范围核对位于 `D:\C3\.codex-tmp\tesnav-ack-and-route-fixes-20260919`。源健康预算、SDK 回调关联、接收端取消/owner 验证、Schema 与 iOS 兼容及真机验收继续保留为未完成项。


## P3 Schema 整包对齐（2026-09-19）

已确认 Android mapper 和本地 C3 Schema/解析器都支持、而 App Schema 漏列的 6 个字段：lane.routeAvoid，guidance.parallelRoadStatus、elevatedRoadStatus、routeNoticeType、routeNoticeDistanceM、routeNoticeObservedAtMs。本次只补其定义，全部保持可选，不改运行代码、wire 版本、控制语义或未知字段拒绝规则。修改后两份 Schema 的完整 JSON 内容相同。

现有 NavAssistV2ProtocolTest 增加整包 golden 断言，复用 activeState，固定 session/sequence/clock，覆盖 idle、planned、realtime、simulation、recalculating、arrived、unmatched。`app/src/test/resources/navassist/android-snapshots.json` 来自实际 mapper 的 canonical JSON 输出，后续测试逐字节比较完整输出，不手工重写生产映射。

新增 `protocol/verify_snapshot_contract.py`，使用 jsonschema 4.26.0 和指定本地 C3 protocol.py；59 组检查覆盖 7 个实际整包、扩展枚举与数值边界、错误类型、未知字段及省略可选扩展，并断言解析后的 routeAvoid、道路层级、通知、active 和 event 值。修复前实际整包出现 App Schema 拒绝、C3 Schema/解析器接受的失败，补齐后全部通过。此检查只调用 parse_snapshot，不测试 Store 的 source age、重放、owner 或控制资格；JSON Schema 也不能代替解析器的重复键、整数字面量、重复车道 index 等检查，双方 Schema 仍未表达全部运行时上限。

复现：先执行 `gradlew.bat testDebugUnitTest assembleDebug --console=plain`；在独立 Python 环境安装 `jsonschema==4.26.0` 后执行 `python -B protocol/verify_snapshot_contract.py --c3-root D:/C3/openpilot-navassist-track-p0 --report <报告路径>`。Android 108 项测试通过，Debug 构建成功；59 组离线检查通过。备份、源文件/fixture 哈希和结果在 `D:/C3/.codex-tmp/tesnav-schema-contract-20260919/contract-verification.json`。

继续检查了 Repository 请求/回调入口及现有记录：未找到可支撑 T_source/T_progress 或无 ID lane/next-icon 归属的真实 SDK 序列，不能据接口存在或回调到达时间自行补成来源证明。当前环境未找到 swift/xcodebuild，iOS ACK 修复及 XCTest 验收仍未完成。本轮未修改 C3、iOS 或 Android 运行代码；未安装或部署。


## iOS ACK 修复与 SDK 关联证据入口（2026-09-19）

已在原 `ios/TesNavIOS/Protocol/NavAssistDiscovery.swift` 中完成 ACK 局部修复：只把 snapshot ACK 接收上限改成 2048 bytes，发现报文仍为 512 bytes；既有 socket 缓冲区保持上限加 1，超限继续丢弃。新增同文件纯匹配入口，接受四字段和可选 vehicleLane，不展示反馈，也不把 core ACK 当动作接受。Foundation 校验 JSON，受 2 KiB 限制的成员扫描保留整数原始 token、拒绝顶层及 flat vehicleLane 的重复解码键与尾随逗号；不修改发现协议的 StrictFlatJSON。未知顶层字段、错误 session/sequence、非整数或越界序号、非法 UTF-8 等拒绝。

现有 NavAssistTests 增加 4 组 XCTest，覆盖 core-only、同一 C3 592-byte fixture、512/592/2048/2049-byte 边界、缺失/不可用的反馈、错误类型/小数/指数/布尔/溢出、Long 上限、重复与转义重复键、尾随内容。fixture 与 Android 资源字节相同；ios/project.yml 已包含整个测试目录，沿用其资源收集方式。使用 tree-sitter 0.26.0 / tree-sitter-swift 0.7.3 对两个 Swift 文件做语法解析，无 ERROR/missing 节点；这不检查 Swift 类型、资源打包或 Foundation 运行时行为，不能替代 Xcode/XCTest。当前无 swift、xcodebuild 或可用 WSL 发行版，未安装大型工具链。

SDK 后续工作没有停留在缺少录制：在原 NavigationRepository 的请求、成功/失败、选路、停止/释放、重算、定位、指导及 lane/next-icon 入口补可开关 DEBUG 关联日志。记录 elapsedRealtime、Repository 实例、App 请求上下文计数、revision、pending、当前 pathId，并保留 SDK 回传 requestId、route IDs、NaviInfo.pathId、step、距离等。lane/next-icon 明确记录 sourceId=unavailable；requestContext 只是接收时上下文，不作为来源证明。复用原 TAG，不新增采集框架；DEBUG 未开启时不读取附加 SDK 字段，诊断异常不会改变回调处理。仅补日志，没有更改导航有效性、控制资格或推测源健康阈值。

采样准备已可复用：在授权的测试设备上开启 `adb shell setprop log.tag.TesNav-AMap DEBUG`，再用 `adb logcat -v threadtime TesNav-AMap:D '*:S'` 保存日志；结束后将 tag 恢复为此前配置。本轮未执行这些设备命令。需要的序列为连续两次算路、选路/重算、stop 后迟到回调，以及静止/行进/后台/弱 GPS；先核对 requestId/pathId 的真实关联，再确定无法归属回调的降级边界和源健康预算。

Android `testDebugUnitTest assembleDebug --console=plain` 再次通过，108 项单测、0 失败/错误/跳过。iOS 运行验证、SDK 实测及目标 C3 owner/取消状态验证仍独立未完成。备份与本轮差异核对：`D:/C3/.codex-tmp/tesnav-ios-ack-20260919`。没有提交、推送或部署。


### 本地 C3 接收端补充验证

在只读参考目录 `D:/C3/openpilot-navassist-track-p0` 执行现有 `test_protocol.py` 与 `test_lane_intent.py`，35 项通过；使用独立 Python 环境、关闭 pytest cache、禁止写 pyc，临时目录和 JUnit 报告均放在本轮备份目录。此范围覆盖已有的 owner 拒抢占、session/重放/checkpoint 等用例，不等于实际 App 与设备之间的交接测试。

另对现有 NavLaneIntentCoordinator 做了连续进程序列探针：stabilizing → signaling → finishing/none 取消 → 同事件 → invalid/event=0 → 恢复原事件 → 稳定等待。结果依次为 stabilizingLaneAlignment、signaling、laneChangeCancelled、laneChangeCancelled、health、blockedEvent、blockedEvent，最后两步 signalRequested 均为 false。确认这一条 inactive/0 序列没有使原事件重新请求打灯；未覆盖重启持久化、owner 切换或所有中断组合。证据与被测文件 SHA-256 在 `D:/C3/.codex-tmp/tesnav-ios-ack-20260919/c3-cancel-zero-probe.json`，现有测试报告为同目录 `c3-protocol-intent.xml`。C3 源码保持只读。


## 剩余保护逻辑实施与验收边界（2026-09-19）

本轮接入了剩余三组 Android 保护逻辑。默认构建的 NavAssist v3 导出保持 inactive/event=0，导航界面显示“仅预览”：健康预算没有真实 SDK 标定证据，因此 `NAV_ASSIST_SOURCE_BUDGET_MS`、`NAV_ASSIST_PROGRESS_BUDGET_MS` 默认均为 0。普通地图、语音和模拟不因此变成 C3 控制输入；未新增 CAN、灯光或横纵向控制。要启用后续能力，必须先取得相应 SDK/目标接收端证据，再填已验证的构建参数，不能照抄测试中的数字。

**源健康与恢复。** 在现有 NavigationState 中补 transient 的接收单调时间、接受路径与指导路径、源状态和出口许可；legacy v1 Gson 字段不扩展。Repository 使用 AMapNaviLocation.time 作为定位源时间，拒绝缺失、未来、重复和倒退样本，不再拿回调到达时间替换定位源时间。指导路径必须同时匹配已接受路径和引擎路径；重复的 path/step/link/icon/距离内容不刷新观察时间。NavigationSourceGate 只负责导出检查，要求显式启动、已配置预算、路径/step 对应、定位新鲜及可信时钟；车辆仍在移动时还要求指导进度证据。静止且定位仍新鲜时允许同一步指导不变。曾有效后失效会锁住自动恢复；新样本或中间 inactive 不自行解除，须显式重新启动。界面同时撤销方向箭头，显示预览或重新启动提示。

**请求和旧回调。** 检查本地 SDK jar 及 `core.h$b` 字节码后，改用带 NaviPoi 和 AMapCalculateRouteListener 的现有算路重载。该 listener 接收 native 算路返回的 int，失败路径返回 0；只将正 ID 绑定到本次调用 token，结果还需匹配 getRouteRequestId 和返回 route IDs 对应的实际 pathId。正在算路时拒绝并发请求，stop/release 作废 token；旧 listener 迟到绑定、旧结果和重复成功不会接管当前请求。无 ID 的 legacy 成功/失败回调不承担接受职责，invocation 返回 0 会终止自己的请求并显示失败。引擎注册 listener 时固定代次，释放后的排队回调不能再转发进 Repository；这需要增加一个同文件转发边界，因为只清字段无法拦截已排队的旧实例回调，没有拆 Repository 或另建 SDK 框架。

**明确的能力降级。** 当前 SDK lane/next-icon/道路层级/通知没有已证实的独立来源关联，`unkeyedRouteFactsConfirmed` 默认 false 且当前生产路径不设置为 true，因此不接受为有效路线事实。下一动作仍可来自已匹配路径的 step 信息。SDK 自发重算没有与 App 发起调用绑定的请求 ID，结果不被冒认为新路线；界面提示结束后重新规划。SDK 自带地图/导航呈现与 App 已确认路线是不同状态，不能以界面已出现新路就恢复 v3 active。上述是实际功能限制，不是“仅差测试但已开放”。将来若 SDK 证据能支持这些能力，需按该证据局部接入，当前不以等待固定时长或盖当前 generation 的方式恢复。

**重启与交接。** Service 创建时不依据持久化 Tesla 同步偏好自动恢复，同步须在本次运行显式开启；新的源检查器也不继承 active 授权。显式启动/停止接入 arm/disarm，普通 exporter 重建不重新授权。Service 始终启用 requireOwnerHandshake：新实例、重发失败或重新发现后先发 inactive，不用新 session 绕过 owner 拒绝。现有 NavAssistV2Session 中的发送锁覆盖整次 HTTP/UDP 调用，替换实例在旧调用退出后才发送；已进入网络的请求不能撤回。

仅一次 inactive ACK 不足以排除旧网络包。当前本地 C3 protocol.py 接收源年龄上限 2000 ms、未来偏差上限 1000 ms，因此在共享发送锁内开始交接后等待严格超过 3000 ms，并在之后取得成功确认，才开放后续有效快照；发送失败重置确认和窗口。此 3 秒来自固定接收端的报文接收边界，不是 T_source/T_progress 标定，也不代表 UDP 已认证设备身份。8 步本地 Store 探针证实：新 owner 接收 inactive 后，仍在源时间窗口内的旧 active 包可回抢；超过源窗口后旧包被拒绝，等最后旧租约结束、再取得新 inactive 确认后，可保留 session/event 恢复。证据为 `owner-handover-probe.json`，未修改 C3 代码。

**验证。** `testDebugUnitTest assembleDebug --console=plain` 成功，125 项单测、0 失败/错误/跳过；59 组 App/C3 Schema 与实际解析器整包检查通过。新增用例覆盖请求序列化与旧绑定、path 三方匹配、invocation 失败、源重复/未来/停滞/静止/进度/重启与重新启动、源状态对实际 wire active/event 的影响、HTTP/UDP 失败后的 inactive 确认、旧 HTTP 与替换 UDP 的交错，以及 3000/3001 ms 交接边界。此前的本地 C3 35 项协议/意图测试及取消→inactive/0→原事件探针仍作为限定范围证据，未用测试数量代替真机结论。

当前未完成的是外部验收与能力证据：真实 SDK 请求 ID/路径/回调顺序、定位源时间语义和健康预算；默认禁用的无 ID 事实/自发重算关联；Android 真机布局、后台及网络切换；iOS Xcode 编译和 4 组 XCTest；目标设备版本及相应交接/取消测试。没有设备会话、Swift/Xcode 工具链或已冻结录制，不能在当前 Windows 环境完成这些验收，也没有静默填入阈值、安装 APK 或部署。P4 仍只在真实复现问题时局部修改；P5 的产品扩展仍不属于本轮必做重构。

备份与证据：`D:/C3/.codex-tmp/tesnav-remaining-20260919`，包括本轮基线 SHA-256、SDK jar/字节码记录、Android 构建日志、整包验证与 owner 探针。现有用户改动保留，未提交或推送。


## SDK 离线日志核查工具（2026-09-19）

新增 `protocol/analyze_sdk_trace.py`，只读取现有 TesNav-AMap / TesNavNavState 日志，不改运行代码与控制授权。报告保留输入 SHA-256、请求绑定与结果的观察关联、路径匹配、定位源时间异常、回调间隔、Service 状态及原日志行号。按 PID/Repository/engine 隔离，路线转换切断间隔；未知来源回调不补造来源证明。现有日志位于校验之前，路径/请求匹配不代表状态接受；指导字段不足以重建完整去重键，Service 状态日志也不是周期采样。因此报告始终标记 acceptance=not_established，不输出推荐健康预算。

采集命令、场景记录及逐项证据缺口见 [SDK_TRACE_ACCEPTANCE.md](SDK_TRACE_ACCEPTANCE.md)。新工具 10 项合成测试通过，覆盖跨进程/引擎/上下文、停止与重算后的旧结果、重复/倒退/未来源时间、日志时钟倒退、切换路线、无 epoch 日志、残缺输入和 CLI 退出码/输入保护。合成测试不计为 SDK 验收。只新增工具、测试与说明并补本记录，未修改 App/C3/iOS 运行代码，也未重跑无关构建。

本轮 adb devices -l 未列出设备，真实采集、健康预算标定、目标 C3 联调与 Mac/Xcode 验证仍未完成；默认仅预览保持。测试输出与文件指纹保存于 D:/C3/.codex-tmp/tesnav-sdk-trace-20260919。


## 真机请求关联修复（2026-09-19）

真机 VRD-AL09 / Android 10 首次规划暴露旧假设不成立：调用返回 ID=101，但全局成功结果 getRouteRequestId()=0，导致 pending 持续且无法进入导航。SDK 11.2.100 的 core.u 成功处理从底层路线更新回调取第四个 int 写入结果请求 ID；这次为 0，不能把存在 getter 等同于可关联。旧“只有全局成功 ID 匹配才接收”的实现说明由本节覆盖。

局部改用官方 independentCalculateRoute：为每次调用创建独立 listener，闭包固定请求 token 和 engine generation；回调统一投递到主线程，只有该 pending token 能一次性结束请求。匹配依据是传入该次 SDK 调用的独立回调对象，而非回调到达时盖当前代次。结果组的 SDK ID 在真机仍为 0，仅作诊断。停止、释放、超时、旧请求成功/失败均不能完成后续新请求；全局成功/失败不再接受 App 算路结果。

Repository 保存独立路径组用于既有路线预览、候选选择与 startNaviWithPath；没有拆包或重写界面。此版本 selectRouteWithIndex 内部减 12，候选 ID 沿用 12 起始，getPath 使用 0 起始索引。普通全局回调缺少关联证据，不能只修一条 ID 比较；因此路径组的预览/启动适配是完成本次修复所必需的局部扩大。官方依据：[独立路径规划](https://lbs.amap.com/api/android-navi-sdk/guide/route-plan/independentcalculateroute)。

增加 30 秒规划请求退出期限：仅以原 token 结束等待并提示重试，不自动放行路线，不作为定位/指导健康预算。成功、失败、停止、释放会移除定时回调；旧定时任务也无法结束新请求。

第一次独立算路复测完成选路和模拟，但停止约 23 秒后 libAMapOpenNaviJNI.so 地图线程 SIGSEGV。修复代码中发现 stopNavi 后立即 destroy 路径组的生命周期风险；改为不手工 destroy SDK 路径组，将交给 startNaviWithPath 的组保留到 AMapNavi.destroy 后解除引用，未使用的组由 SDK 包装器自身 finalize 回收。避免导航停止被误当成地图/原生引用已解除。暂时保留引擎生命周期内所有已提交路线组，内存占用会随该生命周期中的启动次数增长，服务释放时解除引用；后续若需提前释放，必须取得 SDK 引用释放语义的证据。原生堆栈未符号化，不能仅凭此推断唯一崩溃根因。

Android 128 项单测通过，Debug 构建成功；日志工具新增独立 token 与 SDK ID 区分，11 项合成测试通过。新增请求测试覆盖成功先于调用 ID 通知、重复结果、超时/旧失败与后续请求隔离，以及实际 101/0 差异。默认健康预算仍为 0，真实移动、弱 GPS/后台、C3 控制交接和 iOS 验收不由本轮模拟替代。真机最终结果与文件指纹见 D:/C3/.codex-tmp/tesnav-request-fix-20260919/verification.json 及 RESULT.md。

真机最终复测：三次规划被接受，候选切换、导航启动、结束和重规划已观察到；最后停止后约 54 秒 PID 2947 保持，crash buffer 未新增记录。128 项 Android 单测及 11 项日志工具测试通过。30 秒超时仅完成 token 隔离单测与实现检查，未做真机断网超时；引擎销毁/重启原生生命周期、长期大量规划的内存表现仍待验证。证据：D:/C3/.codex-tmp/tesnav-request-fix-20260919/RESULT.md。


## 目标 C3 连接与版本差异（2026-09-19）

实际 C3 192.168.10.34（19.6 / a75100460 + 既有工作区修改）收到手机 192.168.10.83 的报文。抓到 6 组匹配快照/595-byte ACK；接收统计 5902/5902，无拒绝。断开 App 后 stale=true，重启后新 session/idle 被接收，仍 routeActive=false/event=0。设备 offroad，意图服务未发布，未进行车辆动作验收。

发现目标 protocol.py 缺少本地新增的 5 个 guidance 字段与 lane.routeAvoid：目标解析器对 7 组 App golden snapshot 仅 idle 通过，6 组拒绝；当前线上包未携带扩展字段，因此现场链路成功与完整契约兼容必须分开。目标接收窗口仍为 2000+1000 ms。须对齐目标解析/发布/Schema 后再验收扩展字段，本轮没有改写 C3 或放开控制。设备差异与测试证据见 D:/C3/.codex-tmp/tesnav-c3-link-20260919/RESULT.md。


## 目标 C3 扩展字段兼容更新已完成（2026-09-19）

已在实际设备 192.168.10.34 上仅更新 protocol.py、publisher.py、nav-assist-v3.schema.json、cereal/custom.capnp 四个文件，补齐 5 个 guidance 扩展字段和 lane.routeAvoid。保留原字段编号及控制判断；目标设备原有 22 个其他 tracked 改动文件哈希不变。设备端和本机均保存四文件更新前备份、精确哈希及回滚脚本。

在 offroad 状态重启后 scons 构建完成，NavAssist 服务恢复。下载实际部署文件再次完成 59 项整包校验；7 种状态真实 Cereal 消息构造通过。现场 inactive UDP 测试获得 ACK，六字段正确出现在 navAssistStateSP，过期后 stale=true。手机重开后接收 225/225、零拒绝，idle、stale=false、routeActive=false/event=0。此前“目标旧协议不接受扩展字段”的阻塞已解决；App 仅预览、真实行驶/健康预算、OEM 反馈、active owner/取消及 iOS 验收边界保持。

详细部署及回滚证据：[C3 更新记录](D:/C3/.codex-tmp/c3-protocol-update-20260919/RESULT.md)。设备端备份目录 /data/navassist-protocol-update-20260919/before。


## 不上车真机回归（2026-09-19）

断网主动失败、确认联网后同实例重规划、待处理重复拒绝与取消后旧结果隔离通过。等待旧请求结束后连续 8 轮规划/选路/模拟/结束成功，停止后 50 秒及服务释放后 5 秒未见新崩溃。C3 100 条抽样均未激活控制。临时测试包和配置已清理，生产代码未修改。

仍有两项限制：取消后立即重规划出现 SDK 错误 2999；PSS 从约 210 MiB 升至第 8 轮约 485 MiB，停止 50 秒后约 415 MiB，原生已分配内存仍高于基线。等待后重试通过不等于立即重试通过，8 轮成功不等于长期内存验收。真机 30 秒超时、后台/锁屏、长期与多次引擎释放仍待验证。详细证据：[本轮测试记录](D:/C3/.codex-tmp/tesnav-bench-20260919/RESULT.md)。


## 规划取消与路线组保留局部修复（2026-09-19）

只调整 NavigationRepository、RouteRequestAssociation：取消后新请求等待旧 SDK 在途回调结束，再执行已排队请求；仍由独立 token 决定能否接受结果，等待计入原 30 秒期限。路线组在下一组成功安装后解除旧引用，不再保留全部历史旅程；当前已安装组在 stop 时仍保留，不手工 destroy。此策略覆盖此前“全部保留到引擎销毁”的临时处理。

131 项单测与 Debug 构建通过；真机立即取消重规划、16 轮导航（后 8 轮主动 GC）、停止 50 秒与释放 30 秒通过。第 8 轮 native allocated 由前次约 244 MiB 降至约 181 MiB，第 16 轮约 166 MiB，释放后约 87 MiB。排队 30 秒超时由故障注入验证；短时后台/熄屏模拟、排队取消、断网恢复和 3 次已确认 SDK 真正销毁后的重建通过。不能据此宣称长期稳定。主页地图仍占用 SDK 时的 destroy 可能无效，第一次探针的较高内存占用仍记录为限制，不将接口调用成功当作实际销毁。

已澄清 amapnavi 采纳范围：功能对照数不等于迁移完成数；车道/下一动作/道路层级/通知的无来源键回调仍被门控拦截，超车仍仅诊断。详见 AMAP_LANE_GUIDANCE.md。手机已安装修复版，测试包与临时配置已清理。完整结果与回滚备份：[本轮记录](D:/C3/.codex-tmp/tesnav-bench-fix-20260919/RESULT.md)。


## SDK 超时恢复与共享实例生命周期复审修复（2026-09-19）

针对两个 P2，局部修改请求关联、Repository、服务配置刷新与主页提示。SDK 无终态回调时，30 秒后提示在系统设置中强行停止应用再重开，重复请求立即返回；旧终态回调若迟到可解除在途状态，但不能接收过期路线。该规则覆盖前文“超时后普通重试”的说明。

物理请求与已安装路径引用按真实 SDK 实例保存；release 只有在 isDestroyed 确认销毁后才重置。地图/定位占用导致销毁无效时，重新绑定或更换 Repository 仍等待旧物理请求，旧回调可以唤醒新所有者；逻辑路线接收仍检查原 token 与代次。配置无法生效则明确提示重启，连续返回主页不重复初始化。未扩展 C3 或 CAN 控制职责。

134 项单测与构建通过；真机共享占用使用 SDK 公开定位占用接口注入，验证两种 Repository 重绑定与配置重复刷新。无回调故障注入在 30087 ms 提示超时，三次重试立即返回。冷启动后 8 轮规划/选路/模拟/结束通过。共享条件的自然复现失败及注入边界均保留，不将注入记作 SDK 自发故障复现。最终观察、断网恢复、包指纹与回滚备份见 [本轮记录](D:/C3/.codex-tmp/tesnav-recovery-fix-20260919/RESULT.md)。不上车验证不替代实车安全或 iOS 验收。


## 实车偏航后的导航续接与 App 内日志（2026-09-20）

首轮道路片段证实 SDK 已有新路径和同 ID 指导，但 App acceptedPathId 被重算保护清空，无法续接。现局部调整：偏航/拥堵重算开始清掉旧指引并保留原 SDK 终点与原路径 ID；仅在导航仍运行、没有独立规划请求、新指导 pathId 与引擎当前 pathId 一致且不同于旧路径、终点与已确认终点一致（经纬各 1e-5 度容差）时接纳 SDK 已安装的新路线。无 ID 全局结果仍不接受独立请求；车道等无来源键回调仍禁用。换目的地、停止、释放使重算凭据失效，重复通知不延长 30 秒期限；无法确认时停止导航并提示重新规划。C3 SourceGate 不自动重新 arm，预算仍为 0。

Debug 版 SDK 证据改为 App 内异步有界日志，不依赖 adb shell 子进程。写入 files/navigation-trace，当前文件和 3 个备份各约 1 MiB，队列最多 128 条，丢弃计数记录在后续行。轮转失败停止该次写入。停止 App 或系统杀进程期间不能继续记录，已有文件保留。

135 项单测与构建通过。真机由测试注入重算通知并调用真实 SDK 重算，两轮新路径接纳、重算路径再次启动、取消、重复通知不延长超时和锁屏日志增长通过。不是对自然行驶偏航的再次验收；下轮仍需实际偏航复测。测试早期再次启动断言失败因夹具只注入结束回调而未停止 SDK，已修正夹具后通过。证据及备份见 D:/C3/.codex-tmp/tesnav-reroute-fix-20260920/RESULT.md。
