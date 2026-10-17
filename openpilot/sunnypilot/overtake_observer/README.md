# Mac 超车观察与高频采集测试模块

本分支新增一个默认不启动的离线模块。未注册manager进程，不修改原导航/自动变道/转向控制，不发布CAN或控制消息。硬件保持C3XL + MacBook + 安卓手机；无需新增设备或更换Jetlink驾驶模型。

## 当前能力与边界

- motion.py：候选目标关联与实验轴向相对速度拟合。身份丢失/歧义/断档会重置，不把旧速度冒充当前速度。
- projection.py：显式健康标定下的实验地面投影，返回candidate值；接地点、畸变、道路平面未验证，valid_for_control始终false。
- overtake.py：离线超车意图状态流程（跟随、准备超越、超越、准备返回、等待、取消）。输入为明确的局部相邻车道/可跨边界、前后空隙、BSM和完成事件；不依赖绝对车道编号。缺证据等待，取消保持，无执行器指令。
- replay.py：只读JSONL回放，输出新文件，已有输出不覆盖。
- capture.py：C3端显式启动的限时记录，不推理、不控制，不删除旧文件。

这不是已完成的道路自动超车功能。人工体感反馈可以补充，但不能替代侧后空隙、跟踪身份和速度尺度验证。本分支不能用实验估速自动触发转向；原车既有驾驶员确认/保护流程原样保留。手机端暂未新增界面。

## 采集方式（代码尚需单独核对设备版本，不能直接覆盖旧分支）

在已核对的测试代码环境、停车准备时显式启动：

```
cd /data/openpilot
PYTHONPATH=/data/openpilot /usr/local/venv/bin/python -m openpilot.sunnypilot.overtake_observer.capture --hz 10 --seconds 900 --wait-seconds 1800 --max-mib 4096 --segment-seconds 60
```

两分钟是之前的试录配置，不是相机或硬件限制。默认等新鲜车速持续超过1m/s达0.5秒后才开始15分钟计时，同时保留最多2秒内存预录；停车等待不会用掉行驶窗口。需要专门停车画面时可显式传--start camera。随后正常行驶即可，不需要操作安卓或Mac界面，也不需要开外接大模型推理。Mac可放车内但本工具先在C3本地记录，断外网不影响已启动采集；采集后再通过本地网络下载到Mac计算。

- 最多等30分钟实际起步；起步触发后目标记录15分钟（另含最多2秒预录），每60秒封存一个独立文件，最多使用4GiB，达到容量或2GiB剩余空间保护时先停。停车、异常、空间不足也结束。目标10Hz不是已测得10Hz。不会插帧或删旧日志。
- 原生相机维度和640×400左右的导出载荷尺寸分别保存；传感器EOF时间、frame_id、各服务消息时间、实测帧率和跳过计数落盘。
- 同时记录vEgo/aEgo/yawRate、方向盘/踏板/灯光/BSM、calibration、cameraState、deviceState及model时效/负载。异步消息保留时间差，不伪装同帧。
- 模型未健康、模型执行时间超过45ms/掉帧超过5%、温度到red或danger时跳过附加采集；最低保留2GiB空间。这些是录制保护参数，仍需实际负载测试，不能声称不会影响驾驶推理。
- 记录位于/data/media/0/motion-evidence/<time-session>/，结束后frames-00000.jsonl等分段文件 + summary.json。Ctrl-C可提前结束；进程/断电中断留下.partial也应完整保留。
- carState的BSM布尔量不能识别底层SNA，必须同时保留对应原始rlog回到Mac核查；不把无报警当作后方间隙安全。
- 首次只做普通驾驶记录和停车检查，不要求专门超车。不要为采集制造近距离切入场景。

## Mac回放与测试

已提取检测/候选地面位置的输入每行包含route、capture_mono_ns、frame_id、detections。每个检测需bbox_xyxy、class_id_raw，可有ground_candidate=[forward_m,right_m]；候选值不是真实确认位置。可选shadow_evidence只用于显式合成/离线观察，不接车辆消息输出。

```
PYTHONPATH=. python -m openpilot.sunnypilot.overtake_observer.replay input.jsonl output-new.jsonl
PYTHONPATH=. python -m pytest -q openpilot/sunnypilot/overtake_observer/tests
```

完整图像检测头回放已在Mac项目保存；本分支只包含可复用核心和采集，不上传用户路测原图、BSM日志或账号配置。后续仍需高帧率实测、像素到距离标定、本车旋转补偿、目标身份验证及局部车道/前后空隙验证。不要把回放模拟通过写成已能道路自动超车。
