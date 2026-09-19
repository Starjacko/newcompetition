# CoreGeek Future War Agent

这是《未来战争》Agent 项目，包含任务书、接口文档、策略设计和可运行的 Python Agent。

## 目录

```text
docs/                  任务书、接口文档、策略和设计文档
Demo/CoreGeek/         Agent 实现
Demo/CoreGeek/src/     协议、规划、战斗、经济、任务和日志模块
Demo/CoreGeek/tests/   回放和行为测试
```

## 本地验证

```bash
cd Demo/CoreGeek
python3 -m compileall -q src tests main3.py
python3 tests/replay_request.py
```

`tests/replay_request.py` 会读取项目根目录的 `docs/request.txt`，生成响应并检查顶层字段、动作名称、目标坐标和攻击控制字段。

## 启动

```bash
cd Demo/CoreGeek
python3 main3.py <port>
```

日志默认写入 `Demo/CoreGeek/logs/agent.log`，SOP 默认写入 `Demo/CoreGeek/logs/sop.json`。这两个运行时文件不会提交到 Git。

可通过环境变量调整：

```bash
AGENT_LOG_DIR=/path/to/logs
AGENT_LOG_LEVEL=DEBUG
AGENT_SOP_FILE=/path/to/sop.json
```

## 核心策略

- 工人 1：建造火箭、轨道炮、加特林，之后按批次采石建墙，最后采矿赚钱。
- 工人 2：一个矿采完后卖矿，购买并使用升级券，再继续采矿。
- 开拓者：优先完成自进化任务，完成任务后转为升级、宝藏和防守辅助。
- 夜晚只防守 `targetTeam` 为我方阵营的机器人。
- 临近夜晚或出现我方机器人时，角色优先回到固定武器位置。
