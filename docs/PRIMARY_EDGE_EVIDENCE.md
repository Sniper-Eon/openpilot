# C3XL、Android、MacBook：当前适配与真实证据

日期：2026-10-15。不增加硬件。目标是提供可信的本车绝对编号，供高德推荐车道比较；编号未知时保留原导航逻辑，不增加阻止导航变道的条件。

## 当前实际状态

- 车端：已安装 5671670；本地及用户融合分支后续已有其他离线视觉分析、回放与投影工作。它们不是已安装的实时感知。
- 手机：aa2238a 已完成免 Key 车机广播转发入口，交付 `outputs/特会开-免Key车机转发-测试.apk`。尚无手机实机验收，本轮未安装或改写 APK。
- Mac：可用于离线日志分析和后续广角视觉处理；原 Jetlink 功能保持。尚未得到可靠实时绝对车道生产者。

## 本轮新增

`openpilot/sunnypilot/lane_topology/primary_edges.py` 从设备实际的 modelV2.roadEdges、roadEdgeStds、laneLines 和 laneLineProbs 生成几何候选，不读取并不存在的 meta.distanceToRoadEdgeLeft/Right。

使用本车左右线的实际宽度，并扣除本车车道之后计算两侧额外车道数；在前方 5、10、20 米检查一致性。低置信、非有限数、曲线缺失或乱序、不合理宽度、边界位置矛盾、非整数道路宽度均不输出候选。

候选字段明确为 candidate_index/candidate_count，absolute_confirmed 始终 false。即使数学上得到 2/3，也不能单凭道路边缘判定同方向范围、路肩或对向分隔，不会写入现有可信编号回传文件。

`tools/inspect_primary_lane_edges.py` 是离线日志导出工具，保留完整曲线、概率、不确定度、原拍摄时间、帧号及事件有效标记。真实日志中可能有 NaN，导出为 null，不能填零或写成非法 JSON。

## 实际设备核对与日志结果

通过 SSH 成功连接 comma-904f361e.local，设备 IsOffroad=1。只读设备协议与日志，未改参数、进程、系统或车辆控制。

实际 modelV2.MetaData 不含 CP搭子假设的 distanceToRoadEdgeLeft/Right，只含参与度、desire、脱离预测、制动和变道状态等字段。因此不能照抄它的手写二进制字段偏移。

取设备保存的 `0000007c--7f49fecb3a--5/rlog.zst`，1092 帧，拍摄时间跨度约 54.55 秒。在当前诊断阈值（两侧 roadEdgeStds 均 ≤0.35）下，1092 帧均为 uncertainRoadEdges，候选 0，绝对确认 0。第一帧两侧 std 约 1.94／1.15。

这只是某一段已保存日志，不能当作所有道路场景的结果；没有同步图像和人工标签，准确率未知。仅放宽阈值不能证明正确。

最近一段 qlog 没有 modelV2（服务配置不将该大消息写进 qlog），导出帧数为 0。因此后续必须保存 rlog 或专门记录模型曲线，不能再只采集状态标量。

原始日志及完整几何位于工作根目录 `work/primary-edge-evidence/`，仅本地保存，未提交私有行车日志。汇总 `outputs/C3道路边缘日志检查.json` 含日志 SHA256 便于复核。

## 验证与后续

本轮候选计算、真实 cereal 协议序列化、NaN 保留及既有主模型适配测试合计 26 项通过；没有宣称道路识别准确率或自动变道验证完成。

从工作根目录回放：

```sh
PYTHONPATH=work/port-source:work/port-source/msgq_repo:work/port-source/opendbc_repo work/test-env/bin/python work/port-source/tools/inspect_primary_lane_edges.py work/primary-edge-evidence/segment7c-5.rlog.zst --output work/primary-edge-evidence/segment7c-5-geometry.jsonl
```

接下来需用有清晰标线的同步广角画面和模型几何，判断道路边缘是否属于同方向车行道、是否含路肩及漏检；必要时由 Mac 的广角视觉补充。达到可核实的编号可靠性后，再贯通可信编号回传与推荐车道比较。未知时原逻辑不变。这一步尚未完成，不能把本轮诊断工具当成自动驾驶升级。
