# 变道前语音确认（2026-09-22，配套部署）

## 道路启动发现的问题（优先于下方部署检查结论）

2026-09-22 用户上路后 C3 报“进程未运行”。实时读取确认 `started=true`，`nav_lane_intentd` PID 58437 退出码 1；模型 `modeld_tinygrad` 和 `controlsd` 正在运行。崩溃日志 `/data/community/crashes/2026-09-22--14-37-22.log` 指向 `efficiency_lane.py:24`：真实 Cap’n Proto 模型数组不支持 `line.x[1:]`，抛出 `TypeError: an integer is required`。此前以普通 Python 列表构造的选道测试未覆盖此接口差异；offroad 服务验证不能证明行驶进程正常。

最小修复将相邻点检查改为整数索引，并将末点访问改为显式非负索引。新增 5 个真实 `modelV2`／`radarTracks` reader 用例；旧安装版复现 3 失败、2 通过，修复候选选道测试 **51 passed in 0.40s**，隔离目录 `/data/lane-reader-fix-hmiohnyv`。

用户确认停车后，再次读取确认 `started=false` 且模型／控制／变道进程已停止，仅替换 `efficiency_lane.py`。候选 **1034 passed in 8.57s**，实际安装路径 **1034 passed in 8.86s**。原文件备份 `/data/lane-reader-fix-hmiohnyv/efficiency_lane.py.before`，安装收据同目录 `receipt.json`；修复文件 SHA256 为 `67b1f555a03b65c0eb2216787f58d9bb910dc7e00c00f16d20e56e5662d71479`，取代上次语音部署收据中的该文件哈希。

用户随后要求重启，核对 offroad 后通过 `DoReboot` 执行。恢复连接后，`started=true`，`nav_lane_intentd` PID 51422 连续采样运行、消息存活，真实模型／雷达 reader 进行 103 次纯函数评估无异常；文件哈希一致。后续读取 `shouldBeRunning && !running` 列表为空，“进程未运行”事件已消失，同一 PID 持续运行。最后观测到 `laneChange` 告警，该观测不能区分手动／自动来源，不能据此宣称语音门槛或自动变道道路验收通过。运行证据为 `.codex-tmp/lane-reader-runtime-20260922.txt` 和 `.codex-tmp/lane-reader-final-alerts-20260922.txt`。启动阶段存在调度延迟日志，后续日志延迟缩小，长期负载与路测效果仍待记录。

## 语音配套部署基线

用户明确选择：提示后再开始；静音、断连或无法播报时，不发起该次自动变道。Android App 播报“准备向左变道”或“准备向右变道”。导航优先、ARS408 收益判断、BSM／0x399、边界和实体灯光条件仍由 C3 持有。

## 实现与工程约束

1. 既有协调器先满足邻道、边界、盲区与实体灯光条件，稳定后生成随机的 32 位十六进制提示编号。等待语音期间 `spLaneChangeReady=false`，使用同一个灯光请求。
2. `navLaneIntentSP.announcementId` 经 navassistd 的时效与状态检查，加入现有 UDP ACK 的 `laneAnnouncement={id,sessionId,direction}`。仅回传同一导航 session，原 ACK 继续发送。
3. Android Service 使用系统 TTS，以编号作为 utterance ID；非静音、媒体音量非零、中文语言可用并取得音频焦点后开始。只有对应 `onStart` 后的 `onDone` 才回传完成，排队成功、错误、停止和迟到回调不算完成。陈旧反馈或导航停止会撤销播报关联。
4. 导航快照增加可选 `laneChangeSpeechCompletedId`，通过同名 cereal 字段送至协调器。原 session、sequence、TTL 检查保持；缺少字段视为未播报。C3 只接受当前编号，最多等待 8 秒；期间条件丢失、司机介入、路线／输入失效或超时均取消。
5. 播报完成只是新增前置条件，之后仍经过原有 SP／模型及车辆资格。手动变道不增加这道门槛；不改纵向、轨迹、方向盘或原车许可判定。

沿用异常锁止策略：导航同事件不因恢复或旧回执重试；收益选道播报失败后锁住本导航 session，避免新合成事件重复请求。重新打开声音不会自动复活已经取消的请求。

高德 SDK `TTSPlayListener` 只有按文本的开始／结束回调，无法可靠关联同方向的连续请求及取消结果；因此增加局部 Android 系统 TTS 适配器和回调关联类，不替换原高德导航播报。TTS 完整播放回调表示软件播放完成，不能证明驾驶员实际听见或蓝牙扬声器实际出声。

复用 UDP 4213 和导航快照，不新增端口、进程或控制器。协议保留 v3，增加可选字段，两份 JSON schema 同步。旧 C3 不发送提示，新 App 不发送回执字段；新 C3 配旧 App 则无法满足语音门槛。本轮仅针对当前 Android／UDP 链路，iOS 和 HTTP-only 客户端未增加回执，不能宣称功能已实现。没有改变现有 UDP 无认证属性，App 回执不代表执行授权。

## 验证与状态

- Android：156 项测试通过，`:app:testDebugUnitTest :app:assembleDebug` 成功。覆盖方向、开始／完成关联、去重、静音／取消／陈旧／session 切换、回执发送和停止清理。
- C3：独立目录加载新 cereal schema，**1029 passed in 13.80s**，目录 `/data/lane-speech-test-be32be5c`。覆盖协议、typed message、UDP 新旧 ACK、左右等待门槛、超时／条件丢失／已有模型活动，以及原 CP 周期和灯光回归。未发布车辆控制动作。
- 已在 Android 设备 `3VU6R21914002522` 保留数据安装新 APK。系统中文 TTS 实机测试通过：左右播报均收到开始及完成回调；重复反馈只确认一次；静音和取消没有完成回执。仪器测试 `LaneSpeechDeviceTest` 通过（8.908 秒），测试包已卸载，主 App 保留。完整回调不能证明扬声器实际出声或驾驶员听见。
- APK、哈希、测试载荷和复跑记录：`D:/C3/.codex-tmp/lane-speech-20260922-g7jmnnp1/`。

用户随后明确要求“部署吧，然后验证”，已安装 Android 与 C3 配套语音版本。C3 仅更新 9 个必要文件；设备 cereal schema 只补两个语音字段，没有带入本地无关的转弯诊断扩展。缩小后的候选与实际安装路径分别回归 **1029 passed（13.70 秒／13.54 秒）**。备份 `/data/lane-speech-install-pf_ngo9k/backup`，部署收据 `/data/lane-speech-install-pf_ngo9k/receipt.json`。

部署与手机实测记录：`D:/C3/.codex-tmp/lane-speech-deploy-20260922-3j_p0chk/`；其中 `previous-app.apk` 为原手机 APK，可供回滚。安装 APK SHA256：`30b9bb48e42b11b38a44f6fc8a6e6289256269e2cbd345a13a51b2b57a9e5ea5`。

运行验证：单独终止接收进程后，现有 `PythonProcess` 管理器没有自动重启它，因此在再次确认 offroad 后通过 `DoReboot` 正常重启车机。启动编译完成，管理器启动的新 `navassistd` PID 为 50807；新字段可读，typed message 存活有效。重启后 9 个文件哈希全部一致，手机空闲会话 sequence 从 811 增至 826，UDP 累计收到并接受 192 包、拒绝 0 包。空闲状态 `routeActive=false`、导航内容 `valid=false`、语音回执为空，符合无路线时的限制。未强行启动 offroad 下应停止的模型／控制／变道协调进程，其行驶加载及完整联调待道路记录验证。

本次验证在 offroad 完成，未发送实际灯光或车辆控制动作，未验证高速／高架实际跨线、蓝牙出声或行驶中的高德播报竞争。独立手机 TTS 实测与 C3 回归不能当作完整道路联调通过。
