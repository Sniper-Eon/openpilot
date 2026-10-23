# 导航受阻时保留打灯与变道准备

导航目标稳定后，实线/不可跨线或盲区有车不再直接撤销导航打灯请求。请求持续存在，spLaneChangeReady 保持 false，并报告 waitingCrossing / waitingBlindspot；DesireHelper 独立禁止实际变道。障碍解除后仍需真实打灯反馈和300ms稳定确认。保留60秒等待上限、路沿抑制、健康/制动/无相邻车道等原有退出条件，已开始变道的中止规则不变。

新增 phone_closing_riskd 由 manager 按原有 Tesla 导航观察条件启动，仅从 /dev/shm/phone_side_vehicles.json 读取手机观察，输出 /dev/shm/phone_closing_risk.json。没有控制调用；所有输出 control_eligible=false、clearance_authorized=false。无相关车道确认时仅记录 possible_closing_risk_lane_unknown，不能把邻路/对向车辆直接视为目标车道风险，不能发现前向相机看不到的侧后方。

接近阈值仅用于观察筛选，缺少速度和危险事件真值；不构成测速准确率或预警准确率证明。原车盲区检查保留；未采用本地高清候选或双相机融合。源码与测试在 openpilot/sunnypilot/navassist/closing_risk*.py 和 tests/test_closing_risk.py。

本地100项测试通过，包含导航等待状态、条件消失后重确认、受阻600周期保持准备且不产生变道desire，以及观察模块过期/重复/切换轨迹等故障情况。C3驻车部署与道路效果应分别记录，不能用单元测试替代路测。
