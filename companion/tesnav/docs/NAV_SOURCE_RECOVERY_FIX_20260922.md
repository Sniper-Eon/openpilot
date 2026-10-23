# 同一路口恢复导航事件

13:28–13:30 现场诊断确认 SDK 确实发出 weak=true，再发出 weak=false；并非恢复回调被 Repository 漏掉。恢复后原 SourceGate 仍因同一个路口拒绝导出，停留 requiresNewManeuver，直至左转距离 10 m，C3 一直 event=0、灯光请求=false。这是先前接入实现的恢复策略缺陷。

修复保留源失效时 inactive/event=0、3 秒定位和 6 秒进度时效检查。恢复同一路口需要失效后的新定位及新指导、连续健康至少 1 秒、且定位源时间再次推进；期间再次失败会重新等待。接受新路线／后续 step 的逻辑保持。恢复不改变 session、routeRevision 或 maneuverEventId，不伪造新动作；C3 继续负责距离准入、执行资格与司机取消。显式停止／进程重启仍需开始导航。

同时修复 Service 只把 sourceStatus 写回状态、未写回实际 controlAllowed，导致日志出现 healthy/controlAllowed=false 的诊断错配。该错配只影响状态显示，原导出函数已经使用 prepared 结果。

150 项 Android 测试通过。生产 mapper 生成的左右转报文经当前车端离线验证，覆盖默认 18 和现有 25 km/h 策略：恢复后同 ID 可以触发转弯灯；远处中断、尚未开始制动的事件可重新准入；已经开始制动或司机取消的事件不重新激活；已取消变道不重新请求；边界否决和过期处理保持。设备测试目录 `/data/nav-integration-8amfw9hj`，本地证据 `D:/C3/.codex-tmp/nav-recovery-fix-20260922/`。

APK SHA-256：`49dadb5c069f13c6eece10dd15e431dd885c107ae7e7e90243690774b6ffc46f`。本次未修改或部署 C3 运行文件。软件验证不代表车辆实际打灯已验证。

## 安装与现场链路

按用户此前明确「司机手开、直接装」授权，在设备实时显示辅助驾驶已退出时覆盖安装并启动，手机 APK 哈希一致。用户随后恢复导航，C3 收到新 session `7caeaeef-832a-4491-bd5c-fe9bd26df764`、active=true、有效 event `8349220428080637974`。348 m 左转时未到灯光窗口，准备变道原因为 oem239NoLeftNeighbor。

13:36:05.530 记录 signalRequested=true、direction=left、turnApproach，13:36:05.676 车身 leftBlinker 从 false 变 true。已观察到请求及随后灯光反馈；没有把这条反馈扩大为自动转弯成功。13:36:12 同事件因 progressUnconfirmed 变 event=0，灯光请求撤销，车身左灯反馈随后变 false。停车附近 SDK 定位／进度继续出现长间隔，这是尚未解决的稳定性问题；未放宽过期控制资格来掩盖它。

安装状态见 installed-live.json，45 秒只读采样见 signal-live.jsonl，App 同期状态见 app-live.txt，均位于上述本地证据目录。之前“不改变同一事件恢复”的方案已被本修复替代；车端现有接管及执行中断取消判断仍有效。
