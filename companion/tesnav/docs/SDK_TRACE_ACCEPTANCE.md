# SDK 采集与证据核查

2026-09-22 更新：按用户授权，Android 已接入有界源健康检查后的导航事件，见[接入记录](NAV_CONTROL_INTEGRATION_20260922.md)；已安装并验证空闲会话传输，实际导航待验证。下文较早的默认 inactive/预算未设置记录属于当时版本。离线分析器仍只定位证据缺口，不解锁控制、不自动生成预算。普通导航、SDK 自发重算以及 App 已确认的路线应分别观察；地图显示新路线不能证明 App 已接受该结果。

## 采集现有日志

在 Windows PowerShell 使用已有 Android SDK。连接设备后先确认序列号，再为每次完整场景单独录制。不要清空设备日志；`-T 1` 从最近一条开始持续输出。命令不安装应用、不启动导航。

```powershell
$adb = 'D:\C3\.android-sdk\platform-tools\adb.exe'
& $adb devices -l
$serial = '<上一步的设备序列号>'
$capture = 'D:\C3\.codex-tmp\sdk-capture-01'
New-Item -ItemType Directory -Force $capture | Out-Null
& $adb -s $serial shell getprop log.tag.TesNav-AMap
# 记录上面的原值，采集结束后恢复。
& $adb -s $serial shell setprop log.tag.TesNav-AMap DEBUG
& $adb -s $serial logcat -v epoch -T 1 'TesNav-AMap:D' 'TesNavNavState:I' 'AndroidRuntime:E' 'libc:F' 'DEBUG:F' '*:S' |
    Out-File -FilePath "$capture\sdk.log" -Encoding utf8
# 场景结束后 Ctrl+C；若原值为空，恢复命令如下，否则将两个双引号替换为原值。
& $adb -s $serial shell 'setprop log.tag.TesNav-AMap ""'
```

从第一次规划之前开始采集，覆盖结束导航；保留原日志，多个设备/启动会话分别存文件。日志采集应由乘员或测试人员操作。现有日志按回调入口记录，可能含旧数据被拒绝的事件；不能把这些事件本身当成防护失效。

每次录制同时保存 `capture-notes.md`，填写：

- 真实设备或合成数据、设备型号/系统、应用版本及 APK SHA-256、源码 commit 与未提交补丁、SDK 版本/依赖 SHA-256、两个健康预算构建参数。
- 开始/结束时间、设备时间与自动校时设置、是否发生校时、导航模式、网络/GPS 条件、操作人与采集文件名。
- 每个操作的设备时间：首次规划、切换候选路线、停止后重规划、偏航/拥堵触发重算、前后台切换、网络切换、停止/重新启动、进程重启。
- 静止与移动、GPS 变弱与恢复的时间段；无法复现的场景标为“未覆盖”，不能写通过。
- 对应界面表现与原始导出/接收端证据位置。默认预览、源失效、恢复后仍需显式启动、重算后需重规划分别记录。

## 离线分析

只需要 Python 标准库，在仓库根目录执行：

```powershell
python -B protocol/analyze_sdk_trace.py D:/C3/.codex-tmp/sdk-capture-01/sdk.log --report D:/C3/.codex-tmp/sdk-capture-01/report.json
python -B -m unittest discover -s protocol -p test_analyze_sdk_trace.py -v
```

报告包含输入 SHA-256、各回调数量、Service 状态次数、请求绑定与结果关联、路径匹配、定位重复/倒退/未来时间，以及有问题的原日志行号（每类最多 10 个）。间隔统计提供样本数、最小值、下中位数、最大值，不推导阈值。PID/Repository/engine 分组；规划、停止、释放、重算时切断相关间隔，单调时间倒退时清除该组上下文。

退出码 0 仅表示读到了格式完整的 SDK 观察记录；缺少记录、格式残缺或无法读取 UTF-8 返回 2。任何报告的 `acceptance` 都是 `not_established`。`result_without_matching_observed_binding` 可能来自迟到回调、截断录制或日志/回调顺序；须结合原行确认，不能直接定为 SDK 错误。`result_with_matching_observed_binding` 也只证明录制中有对应 ID，不证明 Repository 接受成功。

## 必须补齐的验收证据

| 核查项 | 现有日志支持 | 仍需确认 |
| --- | --- | --- |
| 请求与结果 | 正请求 ID、App 上下文、回调顺序 | 真机成功与失败均能正确终止；停止/重规划后旧结果不接管；日志缺失是否影响结论 |
| 路径 | accepted/current/callback 三方 ID | 回调入口日志早于校验，须核对后续状态与实际导出；routeIds 不是 pathId |
| 定位源时间 | sourceMs 变化、epoch 日志时刻与源时间之差 | SDK 时间的真实语义、校时和日志延迟；不能把到达时间冒充源采样时间 |
| 指导进度 | 指导回调间隔、step、distance | 日志缺少 link/icon/剩余路径距离，无法重建完整去重键；需可复现调试证据核对真正接受的进度变化 |
| 无 ID 回调 | lane/next-icon 到达次数 | 独立来源归属未证明，继续禁用；等待时长与当前 generation 不构成证明 |
| 源状态 | 状态变化记录 | 此日志不是定时采样；静止/移动、后台、弱 GPS、失效与显式恢复需逐场景核对 |
| 控制交接 | 此工具不验证接收端 | 目标 C3 版本/接收窗口、旧包迟到、租约、取消与重启实际行为 |

健康预算要依据足够场景的真实源/接受进度观测、可接受失效响应时间以及接收端约束共同评审。合成测试、少量最大间隔、回调数量与本地单测不能单独作为预算依据。iOS 编译、资源打包与 XCTest 仍须在 Mac/Xcode 上执行。

本工具测试全部是合成输入，只验证报告不会混淆进程/引擎、延续失效绑定、遗漏时间异常或声称已经验收。工具没有写入 Gradle 参数或修改 App/C3 状态的入口。


独立算路修复后，新增 independent_success / independent_failure 与 route_accepted 日志。工具分别报告固定调用 token 的观察关联、SDK ID 与调用 ID 的差异以及 Repository 已接受路线；这些都不代表控制权限。全局路线更新回调仍不等于独立请求的结果。采集同时保留 AndroidRuntime、libc 和 DEBUG 的崩溃输出；分析报告不替代崩溃缓冲区检查。


## Debug 版 App 内采集（2026-09-20）

该版本 traceSdk 在 Debug 构建自动将事件写到应用私有 files/navigation-trace/sdk.log，与 Android logcat 同时输出。重连后用 adb shell run-as com.garan.tesnav ls files/navigation-trace 列出文件，取回 sdk.log 和全部 sdk.log.N，不能再仅取 .1 至 .3。按数字后缀从大到小、最后 sdk.log 合并；单个文件格式兼容现有分析器。traceDropped>0 表示队列丢行，日志缺失不能解释为事件未发生。

2026-09-21 改为按时间保留：每片约 8 MiB，轮转时仅清理最后写入时间早于当前时间两小时的已关闭分片，完整保留边界文件。分片数量随实际流量增长，取消固定四片限制；原日志继续参与轮转，停止 App 不清空日志。正常设备时钟及写入成功条件下保留最近两小时事件，磁盘占用可能超过 32 MiB。轮转时才清理，空闲期间可能保留更久。该策略不能补回回调缺失、进程停止、写入失败或旧版已覆盖的数据，不等于完整行程轨迹或系统崩溃记录。

2026-09-20 候选同时补记 guidance 的 link/icon/pathDistance 和校验通过后的 guidance_accepted。progressChanged=false 表示收到了合法归属的回调，但进度未变化；不得把它当作新的进度时间。导航源状态变化（TesNavNavState）也写入同一组文件，包含 controlAllowed、实际构建预算及源失效原因；状态变化日志仍不是定时健康采样。本次没有修改 source gate、进度去重、控制授权或自动恢复条件，当时没有安装候选 APK；2026-09-21 随两小时日志更新一起构建安装。

此前通过 nohup logcat 在本机手机采集只保留 24 秒，无法保证拔线后存活；不再以 shell 进程存在作为持续采集保证。新方式已验证锁屏时写入增长，拔线后完整道路日志连续性尚未独立建立，保留为采集能力边界。

## 本轮用户验收补记（2026-09-20）

用户已确认完成自然偏航重规划实测，不再将该项列为待用户重复验证。三分钟行驶日志实际覆盖的是结束后重新规划，未独立绑定用户确认的自然偏航事件；两类证据分别记录。功能确认不改变分析器 `acceptance=not_established`，也不补齐健康预算或控制交接证据。各项结果及保留边界见[验收记录](ACCEPTANCE_20260920.md)。
