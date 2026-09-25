# v10 本地准备与运行

v10 复用既有准备入口；`--template` 选择[强工作笔记](../configs/contextual-memory-v10-notes-template.json)或[单决策依据](../configs/contextual-memory-v10-basis-template.json)。模板中的空模型身份由准备阶段填充，不能直接用于实验。两臂使用相同 Host、embedding、容量、原始数据和连续账本，区别仅为 decision policy 及相应反馈／缺口开关。ordinary 默认不变。

在 Lab 根目录，固定 MERIT checkout 为 `293933d96b1d1849e1f20d1bb324def5de9ed33f`：

```bash
uv run python tools/prepare_contextual_v9.py \
  --template configs/contextual-memory-v10-basis-template.json \
  --merit-root /path/to/MERIT \
  --host-dir /path/to/host-model \
  --embedding-dir /path/to/embedding-model \
  --host-url http://127.0.0.1:7860/v1/ \
  --embedding-url http://127.0.0.1:7861/v1/ \
  --output-dir artifacts/contextual-user-memory/v10-my-basis \
  --budget-path artifacts/contextual-user-memory/v10-budget.json
```

准备阶段只有本地哈希、原始 arc 生成和身份检查，没有模型调用。输出目录必须为空。两份模板均进入同一源码映射；各臂配置另有独立 SHA。对 notes 臂替换模板和输出目录，保留相同模型、账本与其他参数。不得覆盖旧 v9 账本，或以新运行目录清零已发生的 v10 用量。

准备成功后，真实运行命令为：

```bash
uv run python tools/run_contextual_merit.py \
  --selection artifacts/contextual-user-memory/v10-my-basis/selection.json \
  --config artifacts/contextual-user-memory/v10-my-basis/config.json \
  --freeze artifacts/contextual-user-memory/v10-my-basis/freeze.json \
  --output artifacts/contextual-user-memory/v10-my-basis/run
```

加 `--prepare-only` 只检查身份，不请求模型。比较时串行运行两臂，每臂从原始空记忆和原始业务世界开始；保留一个完整 arc 的 5 个 episode、7 条原始消息及原 session 边界。原生任务分数、Host／维护完成、决策机制实际使用和全部费用分别报告。该 arc 已用于开发，不是未暴露确认集；跨 episode 的持久记忆复用也不等于跨任务复用当前决策。

StateMemBench 尚未取得可核验的官方数据、许可和 scorer，相关实验不在这些命令中，也没有用 MERIT 替代其名称。实际执行与未运行项以[开发记录](CONTEXTUAL_USER_MEMORY_V10_DEVELOPMENT_20260925.md)为准。原始模型请求、权重、语料、运行日志和 checkpoint 保持 ignored。
