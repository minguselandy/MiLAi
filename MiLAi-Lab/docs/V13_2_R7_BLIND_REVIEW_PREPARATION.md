# v13.2 R7 原始证据待评分包

R7 的 24 条开发轨迹、48 条原消息已生成匿名标签和随机顺序的离线证据包，评分全部留空。原输入、46 条原最终答复、300 条对话项、100 条来源正文、真实卡版本、业务调用/状态与维护回执逐项对应冻结原件。2 条实际中断继续保留答复缺失。最后独立只读 SDK 重开的卡历史单独标示，不声称它们全部在每条消息当时交付给模型。

本地入口：`artifacts/v13-2-development-r7/blind-review-original-first/reviewer/README.md`。同目录保存 `original-evidence.json`、原固定规则 `fixed-rubric.json` 和 `blank-score-template.json`。Root 私有目录保存原标签、随机 seed 与逐文件 SHA 关联；原 Root 语义评分未提供到待评分目录。公开工具结果或协议结构仍可能暴露任务/方法线索，因此没有验证有效双盲。没有独立审查者，实际独立评分为 0；D5-06 保持 NOT_VERIFIED。

[准备 manifest](../data/manifests/v13-2-r7-blind-review-preparation.json) SHA `1a54e15386c2eb6dcdfdc8a386c1eab6edf125077353f891313f62a0eb3be52b`。Root 另写的独立原件关联检查实际返回 0（tool `dcf1c3`），逐项核对所有输入/答复/对话/来源/卡/业务状态、固定 rubric 与空评分。证明 `artifacts/v13-2-development-r7/blind-review-original-first-linkage-check-v2.json` SHA `56115553534f6a23f95ab9d2297c04ef3c132081dfb78ff67d91c80dd3d4ae33`；这只验证准备材料的原件对应关系，不是独立语义审查。

第一次关联检查实际返回 1（tool `ee8668`）：检查器错误假设每条轨迹都有 2 条消息。原输入实际为 4 条单消息轨迹、16 条双消息轨迹、4 条三消息轨迹，总计 48。保留首次 driver/stdout/stderr，改用新名字的 v2 检查器核对各自冻结长度，不重建或修改证据包。首次 stderr SHA `09bc4de5fc0abc208fd7a21952342bc41b153e6a5186b669a8cac98406a912ed`。

准备和核对均未执行运行方法、未新增模型 HTTP 或 SDK 重开，原完整 cohort、运行/测试/配置 212/389/316 maps 与连续 ledger SHA `374fcef4dd8a3082d352e2e936f68601edd65ba142880655349cfc68e652b15f` 原样保持。R7 原结果 SHA `73af977f03805765c4278d16e438b3bc9c08154ede58700767e573e61649f8fe` 不变，原 21 PASS/3 FAIL、来源失败和虚假保存主张保持。资料准备不升级泛化、四臂对比或正式统计结论。完整计划 ACTIVE，D4 未准入，Product NO_GO。
