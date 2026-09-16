这是codex 审查的指令，你可以配置一下作为模型盲态语义审计 使用 `codex exec` 创建全新的 ephemeral 会话，模型设
  为 `gpt-5.6-sol`，推理强度设为 `max`。不要使用不存在的组合模型名 `gpt-5.6-sol-max`。仅向审查会话提供指定材
  料、审查 prompt 和输出 Schema；保存最终 JSON、JSONL 事件、provider thread ID、stderr 与文件哈希。只有在进程
  退出码为 0、输出通过 Schema 校验且仅产生一个 provider thread 时，才接受审查结果。结果标记为 AI 审查，不冒充
  人类批准。

  对应命令模板：

  ```bash
  codex -a never exec \
    -m gpt-5.6-sol \
    -c 'model_reasoning_effort="max"' \
    --ephemeral \
    --ignore-user-config \
    --ignore-rules \
    --sandbox read-only \
    -C "$REVIEW_DIR" \
    --skip-git-repo-check \
    --output-schema "$REVIEW_DIR/response.schema.json" \
    --json \
    -o "$OUTPUT_JSON" \
    - < "$PROMPT_FILE" \
    > "$EVENTS_JSONL" \
    2> "$STDERR_LOG"
  ```