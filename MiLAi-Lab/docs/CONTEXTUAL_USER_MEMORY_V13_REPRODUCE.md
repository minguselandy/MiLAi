# 当前 ordinary 连续运行入口

本入口使用已提交的原生 MERIT 选择和当前 v12 notes 模板，适用于 v13 后续工程。运行工具名称保留 prepare_contextual_v9.py；版本由 template 与冻结配置决定。它不会改动 benchmark，也不会用旧前缀冒充当前完整运行。

## 环境和原生输入

在 MiLAi-Lab 目录中执行，按现有锁文件建立 Python 环境。需要已准备的 Qwen3.6-35B-A3B-FP8、bge-m3、本地 tokenizer 及兼容 vLLM 服务。

MERIT 使用官方提交 293933d96b1d1849e1f20d1bb324def5de9ed33f。现有冻结选择为 data/manifests/contextual-memory-v7-e0-selection-final.json，固定 arc0-000 的原消息、工具、初始世界和 scorer；这是已暴露开发场景，不是新样本。

按本机填写以下路径。变量只指定位置，不改变模型和数据身份：

    export MILAI_MERIT_ROOT=/path/to/pinned/MERIT
    export MILAI_HOST_DIR=/path/to/Qwen3.6-35B-A3B-FP8
    export MILAI_EMBED_DIR=/path/to/bge-m3

## 零模型准备

选择新的输出目录，原运行目录不会被覆盖：

    .venv/bin/python tools/prepare_contextual_v9.py \
      --template configs/contextual-memory-v12-notes-template.json \
      --output-dir artifacts/contextual-user-memory/current-ordinary \
      --merit-root "$MILAI_MERIT_ROOT" \
      --host-dir "$MILAI_HOST_DIR" \
      --embedding-dir "$MILAI_EMBED_DIR" \
      --embedding-tokenizer "$MILAI_EMBED_DIR/tokenizer.json" \
      --host-url http://127.0.0.1:7860/v1/ \
      --embedding-url http://127.0.0.1:7861/v1/ \
      --budget-path artifacts/contextual-user-memory/current-ordinary-budget.json

准备器重新散列模型、tokenizer、Lab 运行源码及模板；重建并核对同一原生 arc/world，生成 config.json、selection.json、freeze.json 和模型身份清单。返回 PREPARED_ZERO_MODEL 不表示已经生成答案或通过任务。

Host 与容量 tokenizer 都使用 thinking=false。若要改变模型、推理模式或方法，建立明确的新配置与运行身份，不在已冻结产物中直接改字段。

## 运行与结果

    .venv/bin/python tools/run_contextual_merit.py \
      --selection artifacts/contextual-user-memory/current-ordinary/selection.json \
      --config artifacts/contextual-user-memory/current-ordinary/config.json \
      --freeze artifacts/contextual-user-memory/current-ordinary/freeze.json \
      --output artifacts/contextual-user-memory/current-ordinary/run

加 --prepare-only 可仅核对运行身份与原生输入，不调用模型。正式运行使用原始世界和空记忆，输出逐集结果、真实 trace、连续费用及最终结果；出现中断则保留 interruption.json 和实际业务状态，不能把已经发生的业务直接重跑到同一世界。

当前完整 arc 命令只负责新运行，不能拿它当同轮维护恢复命令。运行库的维护恢复能力由 TaskRuntime / RuntimeStore 提供；需要恢复时使用实际 session/turn 和已保存业务结果，先核对同一身份，不绕过 manifest，也不另造一次退款。v12 已有该能力的有限恢复证据。

没有 result.json 或存在中止不能按完整 arc 评分。即使原生通过，也需另外核对当前卡片是否记录更正和实际完成状态。全部模型失败计入 budget；MERIT 原生 checker 不调用 Judge。

本轮实际运行、源码身份与费用由 v13 结果报告记录；以上命令不承诺泛化可靠性或 Attention 收益。原始 transcript、世界、数据库及模型保持 ignored。
