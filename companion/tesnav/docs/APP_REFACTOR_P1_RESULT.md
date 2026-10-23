# P1 实施与验证记录

2026-09-19；基于本任务开始时的脏工作树，未提交。

## 本轮独立改动

| 文件 | 本轮变化 |
|---|---|
| `app/src/main/kotlin/com/garan/tesnav/data/NavigationRepository.kt` | 仅增加 normalizer imports、替换两个 showLaneInfo 的解析体；SDK 回调守卫、观察时间、store 更新、隐藏事件保持原流程 |
| `app/src/main/kotlin/com/garan/tesnav/normalization/AmapLaneNormalizer.kt` | 新增纯 Kotlin normalizer 与旧回调 primitive observation；无 Android/AMap/Gson/网络依赖，不持有任何运行状态 |
| `app/src/test/kotlin/com/garan/tesnav/normalization/AmapLaneNormalizerTest.kt` | 新增 13 个兼容测试，含规范化结果经过现有 mapper 的 canonical wire 断言 |
| `docs/APP_REFACTOR_BLUEPRINT.md` | 功能映射、脏改动审计、模块设计、阶段验收与风险 |
| `docs/NAVASSIST_SHARED_CONTRACT.md` | 当前协议事实、跨平台差异、后续对齐目标 |
| 本文件 | 范围、验证证据与回滚说明 |

保留两种回调已有优先级与差异：旧版类型字符优先于字节；背景 255 截断；新版按 laneCount 补未知值；推荐 sentinel 为 15/22/255；F 和新版 255 的路线避选行为不变；显示 U_TURN 与 wire LEFT_U_TURN 等历史映射不统一。未再增加 wire 字段。

移除了旧回调内未使用的 `recommendedActions` 局部计算。旧 SDK 若异常报告负 laneCount，诊断日志 count 现在显示实际输出的 0（原来可能显示负数）；列表、事件类型及 wire 仍为空。没有改变端口、TTL、发送频率、认证、会话/事件身份或控制输出。

## 验证

- 实施前与实施后均运行：`./gradlew.bat testDebugUnitTest assembleDebug --console=plain`。
- 实施前成功；实施后 15 个测试类、75 项测试，0 failures、0 errors、0 skipped，其中 13 项是本轮新增。XML 位于 `app/build/test-results/testDebugUnitTest/`。
- debug APK 构建成功，路径 `app/build/outputs/apk/debug/app-debug.apk`，大小 189,012,958 bytes。
- APK SHA256：`A20E65AD4D9985891D1C6D35E34B0EBC3AB44E6AAD75D2BC244C4A3080F60AC0`。
- `git diff --check` 成功；Git 有已有混合换行的 LF→CRLF 提示。构建有 3 个 SDK deprecated override 警告，位于 Repository 的既有 callback 签名；无编译错误。
- 对照改前 manifest：89 个既有源码、测试、文档文件中，88 个逐字节相同，仅 Repository 变化。与备份 `git diff --no-index` 人工检查仅出现 imports 与两个 lane 回调的预期差异。
- 协议、UDP、Service、NavigationActivity、现有 UI 与测试（包括用户未跟踪文件）、iOS 和已有车道文档均保持原内容。
- 参考仓库仍为原 HEAD，`git status --porcelain=v1` 为空。

这证明了本轮纯解析拆分的 JVM 回归与 Android 构建可用；未运行真机 UI/后台生命周期、实车 SDK 回调或 C3 端兼容回放，未运行 iOS XCTest。现有脏改动的协议扩展不因为本轮测试通过就获得线上兼容性保证。

## 回滚与继续

改前备份：`D:\C3\.codex-tmp\tesnav-refactor-20260919`，`manifest.json` 保存源文件哈希，`git-status-before.txt` 保存初始状态。备份不在 Git 仓库中。

如需撤销 P1，先确认 Repository 在本轮之后没有新修改，然后仅将它与备份对应版本逐段恢复；移除本轮新增 normalizer 和它的测试。文档可保留为审计记录。不要回滚整个 Git diff，因为其中绝大部分是用户开始前已有工作。若已有后续编辑，应反向应用本轮三个差异块而不是覆盖文件。

后续从蓝图 P2 开始，优先处理路线世代、旧车道/next icon 失效和单线程 reducer；P3 单独处理迟到 ACK 与反馈时效；P4 修正建议和许可的 UI 语义。尚未实现的风险已明确记录，不将它们混入本轮协议不变的结构拆分。

本轮没有提交、推送、安装 APK、修改或部署 C3。
