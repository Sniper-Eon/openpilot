# 车载 GPS 与原车导航只读反馈（2026-09-20）

> 2026-09-23 最新安装：缺ACK保持补丁34de版本已在实时确认offroad及关键驾驶进程停止后保留数据安装。手机实际SHA-256 `34de8dc865b7608ec10a4c1a120ac629c801e305f3e435a8831488a16e4c75d2`，PID14118启动存活，无当前进程AndroidRuntime异常记录；C3未改动。184项测试是软件回归，实际短缺ACK连续性/手机切回/道路打灯仍待现场验收。证据在`D:/C3/.codex-tmp/gps-source-health-fix-20260923/ack-hold-install.json`、`ack-hold-post-install.log`。回滚上一版使用同目录`TesNav-source-health-fix.apk`。

> 2026-09-23 后续真机验证：01e0修正版在用户重新开始导航后已记录VEHICLE/external=true/phoneWeak=true，并出现healthy/controlAllowed=true。25秒118个新鲜抽样点仅23个有效导航、63个路线匹配，不能宣称稳定通过；vehicleTelemetry短暂缺失引起NONE/VEHICLE反复切换。最新本地补丁仅在原2.5秒期限内保留上一笔数据应对缺失ACK，不刷新观察时间、不重注入；明确无效反馈清缓存。184项测试通过（含缺ACK不续期、无效后不能复活），APK `gps-source-health-fix-20260923/TesNav-source-health-ack-hold.apk` hash `34de8dc865b7608ec10a4c1a120ac629c801e305f3e435a8831488a16e4c75d2`。复核车速约53km/h/onroad，最新补丁待停车安装，当前设备仍01e0。证据为同目录live-verify.json及active-phone-final.log。手机恢复切回、持续稳定及道路打灯效果仍待验收。

> 2026-09-23 安装更新：用户再次确认停车，实时核实offroad和所有关键驾驶进程停止后，弱信号修正版保留数据安装成功，手机实际hash `01e0cec92536e30579ee21ba6cb9f4d285dde91f109f7dcd586dccc98129f15e`，PID11075。C3本轮未修改或重启。已请求随车人员停车恢复原路线实时导航以验证切换；安装成功及182项测试不替代真机接替验收。下方“待停车安装”为修正候选阶段记录。

## 2026-09-23 弱信号来源修正候选（待停车安装）

[高德官方接口说明](https://a.amap.com/lbs/static/unzip/Android_Navi_Doc/com/amap/api/navi/AMapNaviListener.html)明确onGpsSignalWeak描述手机卫星定位信号。局部修正为：Repository保存手机弱标志，控制器接收该状态，手机弱时排除手机候选以便使用合格原车观察；外部源有效时有效弱状态不继承手机标志，外部源不可用则保持无效。每次来源变化清除旧路线匹配和定位接收时间，等待新SDK输出，不能通过清弱标志复用旧手机输出取得控制资格。手机仍弱时独立原始GPS心跳不触发切回，手机强且独立测量连续健康才沿用既有2秒恢复条件。源年龄、路由匹配、语音与控制约束均保留。

来源变化和每5秒诊断同时写入NavigationTrace持久日志，含source/reason/external/phoneWeak及手机/原车年龄，不依赖可能不可见的Logcat。Android182项通过，新增4项覆盖弱信号持续回调不能阻止接替、弱信号禁止回切/恢复后允许、原车有效时不继承手机弱状态、原车缺失/过期不能使用。APK归档`D:/C3/.codex-tmp/gps-source-health-fix-20260923/TesNav-source-health-fix.apk`，SHA-256 `01e0cec92536e30579ee21ba6cb9f4d285dde91f109f7dcd586dccc98129f15e`；同目录before.apk为已安装1b0c版本。本修正无需改C3。安装前车辆车速近零但仍started=true、控制/模型/变道进程运行，已请求offroad后安装，当前记录时尚未部署。

## 2026-09-23 安装后被动验证：导航有效性未通过

App PID7374、C3导航/控制/模型/变道进程持续运行，独立手机GPS监听已注册且定位权限已授予。车辆在行驶，本轮只读，无主动中断定位、重启或故障注入。25秒C3记录2980个新鲜读取点（含重复消息），routeMatched全部true，locationObservedAtMs有101个不同值，但valid与routeActive均为false；有效车速53.58～74.83km/h。手机日志尾部312条位置回调均gpsWeak=true，58条导航诊断均sourceInvalid，最新位置/引导年龄仍很小。

已确认GPS弱标志使现有NavigationSourceGate拒绝导航资格；Bridge当前手机候选资格不包含该弱标志，且Repository的SDK弱信号状态没有按来源区分。现有源切换Logcat记录未取得，不能确认是否真正进入原车接替，也不能断言弱标志必然来自手机或是接替后的残留。需要补足来源证据并局部处理来源健康状态，不能直接删除GPS弱信号检查。安装/进程检查通过不代表此项验收通过，本轮没有修改设备。证据见`D:/C3/.codex-tmp/gps-bridge-verification-summary-20260923.json`及对应live、phone-final原始记录。

## 2026-09-23 配套安装结果

用户确认停车后，实时核实C3 offroad及关键驾驶进程停止，再保留数据安装App和替换一份C3诊断文件。手机实际APK SHA-256为`1b0c1f73f9656dd3e114883f1126d87c250c78d0273df1b8f12a47a7bc60f198`；C3 oem_navigation_feedback.py为`eb0520d73f464a9d5df1a50ab4186331a0da8eb3ff522d591a976ff20e381716`。管理器按原环境重启，navassistd新PID625033持续逾1分钟；App PID7374存活，安装路径下39项解码/UDP测试通过。后检已onroad，模型/控制/变道等应运行进程正常、导航状态发布存活，未在后检继续修改运行版本。此次安装与启动验证不等于真机手机断更/切回、路线匹配和高速打灯验收，尚未人为注入定位故障。

回滚与证据：手机旧包`D:/C3/.codex-tmp/gps-location-bridge-install-20260923/before.apk`（旧hash `0f477595456cc410e042df4081985fa8e7324b159448cde473f5f22dfe6207aa`）；C3旧文件`/data/gps-location-bridge-install-q_myhn4x/oem_navigation_feedback.py.before`（旧hash `fa7f127c887c13405db1c01db33833485ae80d3c6d3dafb8da197b6ddf5dfe47`）。本地安装目录保留脚本、remote-stage.json、c3-deployment.txt、installed-tests.txt及post-state.json。下方“本地候选/未部署”为此前阶段记录。

## 2026-09-23 备用定位调用链已接通（本地候选，未部署）

用户要求“那接吧”后，Service每200ms调用现有Repository外部定位入口；仅实时导航、有路线且未重算时运行，停止/释放清理。手机高德位置源过期后，采用C3反馈的原车坐标、米制精度、km/h转m/s速度和航向，经现有选择器/控制器送入高德type2（本车静态核对支持GCJ02）。未添加34F索引、运动积分或底盘位移试验门槛，原有导航匹配、语音和车辆控制资格保持。

时间策略明确改变：不再将“已验证原车GNSS测量时间”作为此候选接入前提，也不伪造该验证结果。`observationTimeOnly=true`标识CAN观测时间；以手机当前时间减去C3时间/位置/速度报文中最大年龄，再减ACK本地持有年龄，形成保守观测时间。324只用于识别推进和去重，不当作位置测量时间。每个324值只固定一次观察，重复ACK不刷新其时间；仍受原有2.5秒报文时效与3秒选择器期限约束。此策略不能识别源端旧位置以新报文重发，也不证明精确同fix，保留此前实测限制。

手机恢复使用独立Android GPS监听，注入后的高德回调不能作为手机恢复证据；复用现有连续健康2秒且源时间推进的切回条件。切回后最多一个现有3秒定位预算内，以独立手机观察等待首个高德手机回调，避免旧SDK观察立即触发反复切换。独立GPS监听失败时不会假装手机恢复。来源切换记录`NavigationLocation`日志，停止与销毁释放监听。Android178项测试通过，APK构建成功；新增5项覆盖时间基准、重复ACK不续期/不重注入、断连/过期/旧版字段缺失、倒退/停止重置和控制器切回。Service及真机高德的完整切换尚未验收，本轮未安装到手机或C3。

配套部署必须包含此前C3报文年龄诊断更新；旧C3缺少年龄字段时不会使用原车备用定位。候选归档`D:/C3/.codex-tmp/gps-location-bridge-candidate-20260923/`，APK为`TesNav-location-bridge.apk`，SHA-256 `1b0c1f73f9656dd3e114883f1126d87c250c78d0273df1b8f12a47a7bc60f198`；同目录保留对应`oem_navigation_feedback.py`。C3候选本轮未改运行逻辑，沿用此前39项原生隔离测试证据，不写成重新执行。下方“未接通”是历史阶段状态。

## 2026-09-23 位置与运动一致性核对

只读补采30秒CAN和独立carState，离线核对旧、新两段记录，无设备安装、SDK定位注入或控制发送。算法按接收单调时间使用当时已收到的速度/航向分段积分，与经纬度换算的局部东/北位移比较；不以未来速度配对，不把接收时间当作已验证测量时间。旧样本28个逐秒区间残差中位0.994m、最大2.118m，方向差最大1.510°；26个约3秒区间残差中位2.120m、最大5.118m。新样本26个约3秒区间残差中位1.489m、最大4.046m。独立底盘有效速度283点、范围72.34～93.70km/h；30对GPS速度与此前0.5秒内最近底盘速度的差值中位0.486km/h、最大2.242km/h。差值包含不同传感器时效和滤波，不能反推GPS测量时间。

离线试验阈值仅用于可行性筛查：约3秒窗口，积分行程至少15m、二维残差大于max(10m,3×两端报告精度之和)时标为运动不一致。新旧正常记录各26个窗口未触发。旧样本第11个位置起重复前一位置，仍保持速度/时间更新，20个故障窗口触发；首次在最后原始位置后约1006ms，即第一帧重复位置到达时发现。这不是通用的一秒检出保证。合成停车及0.3m/s低速不触发。

再把新记录位置冻结，GPS速度自故障开始伪造成零：只依赖GPS自身运动会逐渐失去检出依据；利用独立底盘积分行程至少15m且位置位移小于2m的额外试验诊断，18个窗口检出，首次为第一帧冻结位置后约2005ms。独立底盘缺失/过期时不能沿用旧速度。此规则尚未在小半径回环、长隧道、定位漂移等工况标定，不能直接作为生产授权；路径长度与首尾位移本来也不相等。

确认仍有盲区：整条位置轨迹整体平移约111m、保持相对变化时，运动一致性检查不触发。因而这些检查只能增加拒绝坏数据的证据，不能证明绝对位置正确、04F与324同fix，或替代原始测量时间核实。现有运行解码未增加这些试验逻辑，未启用原车GPS自动接替。证据位于`D:/C3/.codex-tmp/`：`gps-motion-live-20260923.json`、`gps-motion-probe-20260923.py`、`gps-motion-consistency-20260923.py`、`gps-motion-consistency-result-20260923.json`；旧输入为`gps-current-frames-trial-20260923.json`。

## 2026-09-23 仅用现有报文的只读与离线测试

用户确认CAN4未接，要求用当前报文测试。本轮没有改白名单、生产代码、App或车端进程，仅订阅CAN再离线回放。30秒采样：bus1的04F/2F8/324各30帧，bus2的34F共276帧、32B共64帧。末次deviceState有效且started=true，carState有效车速12.388m/s（约44.6km/h）；这些是采样末次状态，不代表整个窗口车速。34F索引完整周期中位999.6ms；04F比最近索引推进晚214.3～292.9ms，仍只证明到达相位。

回放复用本地候选`OemNavigationFeedback`实际解码；34F只在独立测试脚本增加索引诊断，不是已经接入生产的备用源选择器。离线索引诊断只接受bus2的DLC7/8、非全FF、及时且递增的事件，重复索引不刷新推进时间，模8加1且至少连续推进两次才建立可观测状态，超过2.5秒间隔后重新建立连续性。位置/速度/时钟的现有检查与索引诊断共同组成`diagnosticReady`，此标志不等于测量有效或导航授权。

14种场景的预期断言通过：正常输入持续可观测；全停、位置/速度/时间/索引分别停供、时钟数值冻结、索引冻结、无效位置、位置延迟600ms、仅bus0索引、无效CAN事件，在故障3秒后的所有回放观察点均不可观测；索引断供8秒后不沿用旧连续性，待重新推进恢复。另一个场景特意保留并确认缺口：旧位置负载持续重发、时间/索引继续推进时，诊断仍会通过。此处“断言通过”是复现已知漏检，不是安全用例全部合格；不能用停车坐标不变的规则解决，因为行驶数据回放也能重现。需要进一步的位置变化与运动一致性约束及定位源时间依据，不能把34F推进直接当作04F更新证明。

未向高德注入原车定位，未测试或启用实际手机断更自动接替，未产生控制动作。证据：`D:/C3/.codex-tmp/gps-current-frames-trial-20260923.json`、`gps-current-frames-replay-20260923.py`、`gps-current-frames-replay-result-20260923.json`。结果中的`measurementTimeVerified=false`和`sdkInjectionAllowed=false`为测试明确边界，不是实际运行选择器调用结果。

## 2026-09-23 定位更新索引与时间来源追查

找到并实测新的只读线索：TCAN的[0x34F APP_gnssReceiverRaw定义](https://tcan.latency.is/data/frames/0x34F__APP_gnssReceiverRaw.json)包含bit44起3位`APP_gnssReceiverRawDistinctDataIndex`。本车30秒窗口bus2收到290帧、DLC7，bus0也有290帧，统计只用bus2避免双计。观察到索引连续按模8加1，共30次变化；剔除采样开头的截断周期后，29个完整周期924.5～1045.4ms、中位1003.6ms。卫星数字段按候选布局为23～24。DLC7覆盖定义最高bit55，未发生字段截断。该索引是判断原始GNSS数据更新的候选证据，但04F中没有共同索引，不能直接绑定04F位置；只有3位、约8秒回绕，也不能单独作为绝对时间或跨断连唯一标识。04F比最近索引变化晚约160～280ms仅是接收相位。

[0x2CA APP_gpsTime定义](https://tcan.latency.is/data/frames/0x2CA__APP_gpsTime.json)有32位秒和32位纳秒，ModelY来源标为PARTY，是另一条时间线索；本窗口bus0/1/2均未观察到2CA。它与04F同次定位的关系仍无定义证明。未改网关白名单；网关GET state返回connected=false且缓存无2CA规则，缓存不能作为当前硬件回读，也不能据此断言PARTY上的2CA被网关过滤。

继续追到[上游CAN Explorer](https://github.com/bruvv/tesla-can-explorer)：其MCU3数据来自固件库提取，324仅列单个数值字段，04F仅列经纬度/精度，没有关联规则；这里的`message_index`是静态目录索引，不能当成运行中的fix编号。检索VAPI别名未发现可建立324/04F对应关系的映射。[Tesla官方LocationState协议](https://github.com/teslamotors/vehicle-command/blob/main/pkg/protocol/protobuf/vehicle.proto)在同一响应内提供坐标、`gps_as_of`、`timestamp`和定位有效性等字段，但没有将其映射到CAN 324；该响应结构也不等于已证明全部字段同fix。当前App未找到该官方定位协议的接入，不能假装现有CAN链路已具备。

本轮结论：找到了实车可见的更新索引34F和未见的时间候选2CA，但仍不能确定324是位置测量时间还是独立时钟。继续验证应针对原车源端的定位日志/协议关联，或取得2CA后核对时间含义及关联；仅放行一个同名时间报文仍不足以启用替代。没有部署或注入，不扩大自动变道资格。证据在`D:/C3/.codex-tmp/`：`gps-fix-index-live-20260923.json`、`gps-fix-index-summary-20260923.json`、`gps-fix-index-probe-20260923.py`、`0x2CA__APP_gpsTime-research-20260923.json`、`0x34F__APP_gnssReceiverRaw-research-20260923.json`、`gps-upstream-time-position-extract-20260923.json`、`gps-vapi-aliases-mcu3-20260923.csv`及`gps-gateway-state-20260923.json`。摘要内初始100ms间隔是采样从已有索引开始的截断周期，不是完整定位周期。

## 2026-09-23 精度与定位时间核实

本轮只读核实，未更新App/C3运行文件、未注入定位或发送控制。30秒采样时deviceState有效且offroad，关键进程均停止；carState未收到，不能将默认speedMps=0作为实际停车证据。

`0x04F`的精度字段找到了直接对应Model 3/Y的单位依据：[joshwardell/model3dbc固定版本](https://github.com/joshwardell/model3dbc/blob/c56c113c353d09b1a5dd57677461f02fe8b7c6ca/Model3CAN.dbc)的`GPSAccuracy04F`位57、7位无符号、小端、比例0.2，单位明确为米。与现有TCAN字段及解码的精度布局一致。本轮30帧原始值均为5，即按该定义为1.0米。此为社区解码定义及原车报告值，不能作为实测误差、水平精度置信区间或所有固件适用性的证明；该DBC的经度位宽与TCAN不同，本次只交叉核对精度字段，不替换整帧定义。旧Model S的0x3D8无需作为本车单位证明。备用定位可以优先复用04F已有精度，不必为了单位问题依赖32B。

时间关联仍未核实。bus1的04F、2F8、324各30帧，324值每次递增935～1089ms。按Cereal接收单调时间，2F8比最近04F晚249.4～251.2ms；最近的324比04F晚439.9～452.3ms，而上一帧324比04F早550.3～564.6ms。这是总线发送/转发的相位，不能证明哪帧324对应哪笔位置测量，也不能将442ms写成固定GNSS补偿。324到达墙钟减其数值777～907ms包含设备时钟偏差和传输，不能直接作为位置测量延迟。当前定义没有找到跨帧共享fix编号；持续推进的时钟并不能证明缓存位置是新测量。现有独立年龄字段仍不足以设置`measurementTimeVerified=true`。

32B在bus0和bus2各64帧、均DLC5；既有采集继续只采用bus2，避免重复计数。定义中的最后字段结束于bit37，5字节足以容纳这些字段，DLC5本身不等于字段截断；但定义没有单位，不能据此宣称其水平精度已经核实。按候选比例解码水平字段为0.8～1.0，与04F量级接近仅作辅助观察。

证据位于`D:/C3/.codex-tmp/`：`gps-coherence-live-20260923.json`为218帧原始记录，`gps-coherence-summary-20260923.json`为统计；`gps-coherence-probe-20260923.py`是无写入的可复用探针；`gps-reference-model3-20260923.dbc`及`gps-reference-model3-source-20260923.json`保留定义和版本。后续接入仍需能把位置/速度和测量时间关联起来的源定义或独立定位记录，仅重复接收时序采样不能解决语义缺口。原车自动接替未启用。

## 2026-09-23 源诊断候选（未部署）

用户要求修改原车GPS接入后，最小增补现有C3解码/ACK和App解析：bus1的324按小端uint64保留时间数值，bus2的32B接受实测DLC5及资料DLC8，仅保留原始十六进制，尚不宣称米制精度或已验证位定义。bus128回显不接收。原04F/2F8定位可观测状态不被新增诊断字段授予或撤销。

六个可选扁平字段：`gpsTimeMs`、`gpsTimeAgeMs`、`gpsPositionAgeMs`、`gpsMotionAgeMs`、`gpsAccuracyRaw`、`gpsAccuracyAgeMs`。年龄来自C3单调时钟，在生成ACK时计算，跨手机传输后仍需另加传输及持有时间；不能直接视为GNSS测量年龄或导航资格。`gpsTimeAgeMs`自324数值最后推进算起，重复帧及重复snapshot不续期；2.5秒边界过期置空。时间倒退、0、全FF、错误DLC拒绝；无效CAN事件清除缓存。324与坐标帧是否同一fix未确认，不把时间值用于给坐标续期。

新App接受不含这些字段的旧遥测；新字段类型、范围、成对存在关系错误时只丢遥测，保留合法车道ACK。旧版严格遥测解析器不认识这六字段会丢弃遥测，但原车道ACK不受影响，因此部署时应配套更新App。导航snapshot、控制资格和语音确认规则不变，尚未调用高德外部定位接口，未实现自动源切换。

验证：Android163项通过、APK构建成功；C3隔离目录`/data/gps-diagnostics-test-sgq0frii`使用候选解码运行39项解码/UDP测试通过（2.74秒），未替换生产文件。Windows端解码34项通过，UDP测试因缺少本机capnp改在C3隔离环境完成。覆盖DLC5/8、错误总线/回显、过期、重复/倒退时钟、无效数据不影响现有定位及旧ACK兼容。候选APK在`D:/C3/.codex-tmp/tesla-gps-diagnostics-candidate-20260923/TesNav-gps-source-diagnostics.apk`。

本轮接入 0x04F、0x2F8、0x247、0x24A：C3 解码，Android 接收只读摘要并在导航页车道组件下显示。没有将车载 GPS 提供给高德，没有修改导航快照、C3 定位、控制授权或网关白名单。0x25D 既有红绿灯能力和 0x399 权限保持不变。

## 来源与边界

布局依据是当天早上保存的 TCAN `ModelY_CH` 查询结果；0x24A 还与本地 `tesla_modely_hw4_perception.dbc` 一致。完整原查询输出在 `D:/C3/.codex-tmp/tesnav-oem-telemetry-20260920/layout-evidence.json`，不能用旧 Model S 的单位直接证明本车单位。

当前网关物理 CAN3 转发至 Cereal bus 1；解码只接收 bus 1、指定四 ID、DLC8、valid CAN event。此映射以当前网关配置为前提。没有经验证的校验和、计数器或 GNSS fix 时间，不能把“收到有效 Cereal 事件”写成“已验证 GPS 测量完整性”。

- 经纬度保留 Double；2026-09-23静态手机参考对比支持本车本地点为GCJ02数值，未外推所有固件/地区，详见统一计划中的25对样本记录。
- accuracyValue 的米制社区定义依据见上方核实记录，实际误差与置信含义未标定；speedValue 在本车行驶采样中与 C3 km/h 速度匹配，App 已显示 km/h。原 wire 字段名 speedValue 保留，避免无必要改名。
- HDOP 无量纲，航向按 1/128 度解码；无效／未知航向和速度用 null，不冒充零。
- 0x247 原车控制器健康、ALC、分叉及退出码只作诊断，未验证枚举直接显示数值，不转换成 C3 授权。
- 0x24A 原车导航可用位、导航使用状态和健康／规划码分别保留。navDistanceM 步长 100 米，距离对象未验证，不代替高德转向距离；255 和 navAvailable=false 时距离为 null。

## 时效与异常

接收时拒绝未来、源时间为零、延迟超过 500 ms、乱序和重复 Cereal 事件时间。GPS 各帧 2.5 秒过期，调试帧 500 ms 过期；边界即过期。报文缺失与过期、格式错误、GPS 故障位、位置跳变分开报告，原车状态不可用时置 null。

GPS 经纬度必须在地理范围内，accuracy 原始值 0/127、HDOP 0/255、NMEA MIA／天线断开、全 FF 均不采用。GPS 输出坐标需要两帧均可观测。位置变化超过 `100 m + 100 m/s × dt` 且与上一接受位置间隔不超过 10 秒时，暂时隐藏坐标；异常点不替换锚点。超过 10 秒失去连续性后下一范围合法点重新建立基线。这只是明显跳变筛查，不是定位完整性保证，也不实现坐标融合。

App 沿用原 OEM 反馈的本地单调时钟显示期限；过期或断连后移除摘要。GPS 故障不会撤销原车车道反馈，原车导航不可用也不会阻断高德路线。

## 兼容契约

导航 snapshot v3 完全不变。C3 对同一合法 snapshot 先发送带顶层 `vehicleTelemetry` 的扩展 ACK，再发送原样 legacy ACK（含原有 vehicleLane）。扩展 ACK 限制 1400 bytes；生成失败／超长仍发送 legacy ACK。旧 Android/iOS 严格解析器会跳过扩展 ACK，接受原包。新 Android 如果先收到原包，最多额外等待 30 ms 接受同来源的扩展包，以容忍乱序；总等待不超过原 350 ms。

vehicleTelemetry 为严格扁平对象：gpsStatus、latitude、longitude、accuracyValue、hdop、headingDeg、speedValue、mapAvailable、controllerHealth、alcState、forkState、abortReason、navAvailable、navUsage、autosteerHealth、plannerState、navDistanceM；另有可选 roadEstimator（0..3）和 oemLaneChangeState（0..63）。新 App 可接收没有这两个字段的原 C3 摘要，显示未知。GPS 状态为 missing/stale/invalid/jump/observed，observed 仅表示可观测。数值、布尔、范围及空值严格校验；遥测字段值错误时仍保留合法车道 ACK。重复 JSON 键按原严格规则拒绝整包。

## 首版验证与部署（后续版本见下节）

- Android 全部 139 个单元测试通过，debug APK 安装成功。
- C3 临时目录使用实际运行依赖执行 78 项测试通过，覆盖解码、错误总线、DLC、GPS 故障、符号位、跳变、时效、乱序、旧 ACK 回退、异常提供器及原有协议／车道测试。
- 实车只读 6 秒：04F/2F8 各 6 帧，247/24A 各 60 帧，Cereal src1、DLC8；595 个 CAN 事件 valid=true。
- 手机实机探针通过现有 service/exporter 接收 udp://192.168.8.101:4213，验证实时摘要刷新、组件渲染和过期撤下。截图是临时挂在 MainActivity 的同一个 LaneGuidanceView 组件，不代表完成道路导航 UI 验收。探针源码和测试 APK已移除，构建配置按原字节恢复。
- 真实样本完整扩展 ACK 919 bytes；字段保留经纬度六位小数。回包仍使用既有未认证 UDP，只确认收到的来源地址和 session/sequence，不提供身份认证。
- C3 在实时 deviceState offroad 且 IsOffroad=1 时部署三份运行文件，运行文件与本地基线核对一致后备份。管理器普通 PythonProcess 不会自动重启退出的 navassistd，因此安全重启管理器重新纳管；最终输出回到原有 tmux 控制台，避免临时日志持续写盘。
- C3 回滚文件：`/data/oem-telemetry-61u522xl/backup`；本地测试、截图、位定义证据：`D:/C3/.codex-tmp/tesnav-oem-telemetry-20260920`。

后续行驶观测已支持速度单位 km/h，并记录移动场景的坐标差与时间偏移；尚未确认 GPS 坐标系、精度单位或固定测量延迟。原车未核验枚举及完整道路导航页 UI 仍保留验证边界。0x298/0x2A7 等无实际样本的候选尚未接入，0x400 语义未验证亦未消费。本轮不宣称具备新的自动驾驶能力。当前汇总结论见[验收记录](ACCEPTANCE_20260920.md)。


## 停车后诊断显示更新（2026-09-20，后续版本）

已依据 MOVING_TEST_RESULT.md 和 LANE_CROSSCHECK_RESULT.md 更新：速度显示 km/h；增加原车道路估计码与 247 变道状态码。已现场对照的 2/3/8/9/10 分别显示车速限制、无可用车道、仅左侧候选、仅右侧候选、双侧候选；其他未核验码仍显示数值及待核验。道路估计按原车枚举显示，非 C3 健康结论。全行明确“仅诊断，非变道许可”。

两个新增字段沿用 247 的来源、DLC 和 500 ms 时效，过期置 null。没有修改 399 授权、盲区拦截、239 几何判断、控制逻辑、导航 snapshot 或高德定位输入。

兼容范围：本次 App 支持旧 17 字段和新 19 字段遥测；没有遥测能力的旧客户端仍接收 legacy ACK。上一版严格限定 17 字段的 Android 会丢弃新遥测对象，但保留原车道反馈；其诊断显示需要随本次 APK 升级，不宣称旧 APK 也能完整显示新增摘要。

验证：Android 141 项、C3 85 项通过；手机真实 C3 ACK 新字段、km/h 文案、渲染、刷新和过期撤下均通过。截图是临时挂载在 MainActivity 的同一显示组件，临时测试 APK/源码已清理，构建配置字节恢复。手机安装包哈希 a2b087555ad9af7376d925296c55fab5c851c07b4181fcd082e449559bd498f3。

部署前后都实时确认 P 挡、车速零、横纵控制未激活。C3 仅替换 oem_navigation_feedback.py 一份运行文件，通过管理器重启加载；navassistd/ui/pandad 均恢复运行。备份 /data/oem-telemetry-labels-gu0eiaxr/backup；本地证据 D:/C3/.codex-tmp/tesnav-oem-telemetry-labels-20260920。
