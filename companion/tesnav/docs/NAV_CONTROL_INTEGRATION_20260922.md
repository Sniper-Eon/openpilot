# 导航变道、路口减速和转向灯接入

后续修正：下文“同一个中断事件不恢复”的早期策略在现场造成恢复后一直不打灯，已由[同一路口恢复修复](NAV_SOURCE_RECOVERY_FIX_20260922.md)替代；原版本和测试数字保留为历史证据。

2026-09-22，按用户明确范围完成 Android 实现，随后按「试一下」要求安装手机并完成空闲会话真机传输检查。此次车端无需修改运行文件；复用当前车端导航变道、NavigationSpeedController 与 NavTurnSignalCoordinator。此前 SCC-V 退弯保持修复仍是另一个未部署候选。

## 改动与行为

默认构建使用定位 3000 ms、行进中有效指导进度 6000 ms 的有界超时。显式将任一预算设为 0 仍可生成仅预览版本。必须显式开始真实导航或开启同步，并收到开始后的定位与指导；路线、路段归属一致且匹配有效，才发送 active/event。模拟、停止、重算未确认、源失效都不产生有效事件。

源失效立即发送 inactive/event=0。同一个中断事件不会因重新收到定位自动恢复。只有通过全部健康检查、定位与指导均在失效后重新收到，且同一路线进入后续 step 或接受更高 routeRevision，才允许新事件接入。停止或进程重启仍需显式开始。沿用既有 session、sequence、事件 ID 和 1200 ms 报文有效期，不改变 C3 的接管与控制资格。

没有路线身份的 SDK 车道数组仍不启用。当前选道复用 C3 基于转弯方向和车端车道信息的靠左／靠右策略，逐次请求原有变道；不承诺导航绝对车道号。路口速度目标、灯光时机与模型转弯资格由既有车端逻辑决定。灯光请求不等于允许跨线或模型已经获准转弯；本次没有改写方向盘控制或放宽转弯入口资格。

## 证据与限制

历史 SDK 日志提取 12610 条定位，同一路线且源时间递增的间隔 12604 个：P95=801 ms、P99=1902 ms、最大 60092 ms，其中 45 个超过 3000 ms。3 秒策略能容纳观测到的常见约 2 秒更新和投递抖动，并拒绝长断更。6 秒指导进度策略是有界运行策略，尚未完成全场景道路标定；不修改分析器的 acceptance 结论，也不把周期发送当成新定位或新进度。

- Android 单测 148 项通过，Debug APK 构建成功。
- App/C3 双 schema 与本地 C3 parser 的 59 项整包校验通过。
- Android 测试调用真实 gate、session、mapper 生成左右转 12 份报文。通过 SSH 在当前车端 Python 环境离线调用实际已部署 parser、publisher、变道／灯光／减速模块；没有向总线发布或发送车辆命令。左右转分别覆盖默认 18 km/h 和当前设备 25 km/h 目标策略，验证车道方向、物理灯确认后的变道准备、边界否决、减速目标、司机接管、源失效、相同事件不重启、报文过期。
- 设备现有三个开关均为 true，普通转弯速度设置为 25 km/h；本次未修改。这是既有速度上限设置，最终仍应与视觉弯速、跟车、停车目标合并，不能作为所有弯道的合理速度保证。

已安装 APK 归档：`D:/C3/.codex-tmp/nav-integration-20260922/deployment/installed.apk`，SHA-256 `7cbad57a648816d65bd87ea7025496c0cf737733c2d236f42d5995bd3ec31cfa`。构建输出目录随后用于 GPS 回调诊断候选，不能将后续构建混作已安装版本。

复现：运行 `gradlew.bat :app:testDebugUnitTest :app:assembleDebug`，再用 C3 Python 环境运行 `protocol/verify_control_integration.py app/build/navassist/control-integration.json`。协议检查见 `protocol/verify_snapshot_contract.py`。本次构建、原文件备份、定位统计、车端离线结果位于 `D:/C3/.codex-tmp/nav-integration-20260922/`，最后通过的设备隔离目录为 `/data/nav-integration-m0tehaus`。

13:11 在 C3 deviceState.started=false、手机导航已结束时，将 APK 覆盖安装至设备 `3VU6R21914002522` 并启动。安装前 APK 保存在证据目录的 `deployment/before.apk`；手机安装后 SHA-256 与上文一致。新 App 日志确认 sourceBudgetMs=3000、progressBudgetMs=6000，无本次 AndroidRuntime 崩溃。C3 收到新 session `73a53311-aa77-4bde-ae69-f7c7180d5c28`，sequence 持续增长、stale=false，mode=idle、routeActive=false、event=0 符合未开始导航的状态。只检查接收，没有注入控制报文。

13:15 用户开始真实导航，C3 实际收到 realtime、routeMatched=true、turnRight、130 m，报文持续更新且 stale=false。但 SDK gpsWeak=true，App source=sourceInvalid、controlAllowed=false，routeActive=false/event=0；车端灯光请求=false、变道准备=false、reason=turnUnavailable。车辆 P 挡静止，辅助驾驶未启用。13:17:33 至 13:18:33 的 SDK 定位回调间隔约 60 秒；Android 系统显示 App 前台且仍请求 1 秒 GPS 更新，不能把 SDK 弱信号标记直接等同于定位权限关闭或网络断开。原始记录在 `deployment/navigation-live.json`、`deployment/navigation-app.txt`。

真实导航方向／距离传输已验证，源健康恢复后的 active/event 与道路执行仍待验证。软件链路验证不是道路转弯成功率验证；未绕过源健康门控。后续应核对 healthy、有效 event 及三个模块输出，并继续保留 sourceStalled/progressUnconfirmed 和模型转弯资格日志。
