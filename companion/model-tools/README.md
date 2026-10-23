# 原车辆模型训练入口

保留原数据生成与 YOLOv8n 训练入口，个人绝对路径改为环境变量。当前 APP 运行的是发布的 320×320 ONNX，而不是上次清洗后的未采用候选。模型元数据记录 Ultralytics 8.4.182 / AGPL-3.0。依赖和权重沿用相应组件许可；这里没有把它重新声明为整个 openpilot 的许可证。

`build_side_dataset.py` 从 `C3_DATA_ROOT` 下原采集目录 `highway-capture-20261017-0c9ef729/frames` 和 `road-review-20261017-afternoon/frames` 读取 NV12 JSONL。车辆框由 YOLOv8m 自动生成。`C3_TRAINING_OUTPUT` 指定派生图片 / 标签目录，随后运行 `train_side.py`；`C3_TRAINING_RUNS` 指定训练产物目录。脚本会读取本地权重或按 Ultralytics 默认机制获取所需权重，不会自动接入车辆。

原始图片、驾驶日志和设备私人数据不公开发布。没有这些数据，不能仅凭本目录宣称复现原训练质量。旧数据是自动标签，含误标；旧验证集也不是独立人工真值。新 2,488 帧及其中 24 帧 AI 草稿仍未用于训练。没有目标车辆独立真实速度，不能把检测框训练当作测速精度训练或验收。
