# V02-20 Provider 加固与 V2 恢复决策

日期：2026-09-11。独立后续工程检查，不改写已关闭的 V0220 实验。

用户目标：先补齐完整 Schema 的 Provider 兼容验证、错误定位和未知用量处理，
再决定是否恢复 V2；不扩任务、不开发新 State。

结论：本轮检查与防护实现完成，**DO_NOT_RESUME_V2**。不是 Provider 全面兼容 PASS，
不是 V2 实验完成或 Memory 准入。完整 Schema 的否定检查已经足以阻止真实生成；
本轮没有追加模型请求，没有删除 uniqueItems、过滤合法目标或修改执行端语义。

## 完整 Schema 验证

使用旧 V2 manifest 中的四个原有根，构造完整、未裁剪的动作联合 Schema，
覆盖全部 25 个业务目标；另对每个根检查完整 finish-only Schema，共 8 项。
调用共享容器实际安装的 vLLM 参数校验代码，不创建引擎、不发送 completions。

| 原任务 | 全部目标数 | 完整动作 Schema | finish 对照 |
| --- | ---: | --- | --- |
| real_estate_task6 | 5 | REJECTED：uniqueItems | CPU PASS |
| investment_analyst_task4 | 6 | REJECTED：uniqueItems | CPU PASS |
| hr_task4 | 7 | REJECTED：uniqueItems | CPU PASS |
| hr_task3 | 7 | CPU PASS | CPU PASS |

CPU PASS 只表示通过参数验证；不证明 GPU 解码、模型正确输出或实际 usage 可结算。
没有挑选唯一通过的根恢复运行，也没有把先前两个小型兼容样例当成完整覆盖。

## 错误定位

以原失败请求的精确 Schema 重放实际安装代码，得到：
`uniqueItems → XGrammar 校验拒绝 → Guidance ValueError → AsyncLLM.generate`
`包装为空消息 EngineGenerateError → 公共 HTTP 500`。
公共错误 JSON 与历史 HTTP 回执完全一致。重放进入校验一次、未通过参数校验、
引擎提交为零。模型配置采用明确披露的 CPU stub，未声称重放了 GPU 推理。

第一次新探针因 stub 缺少 logits_processors 字段先抛 AttributeError，断言失败；
原失败证据保留。第二版补齐该字段后才得到上述 uniqueItems 异常链。
历史请求没有可恢复的调用栈/逐请求用量凭据：这条确定性匹配路径是强定位证据，
不是对历史运行的追溯性零 token 结算，也不能排除当时的独立基础设施问题。

## 新防护与未知用量

新增前瞻 Provider 和完整 Schema 准入器，旧 Provider、Host、V2 runner 与 sealed
证据不变，未暗中把新实现接入旧候选。

- 发送前必须提供完整 Schema 预检和历史账本范围；任一完整根失败即禁止发送。
- 保存精确请求字节/hash、客户端请求 ID、允许列表内响应头、原始响应体和耗时。
- 追加式记录 RESERVED、DISPATCH_STARTED、RESPONSE_RECEIVED、USAGE_UNKNOWN/KNOWN。
  崩溃留下的中间状态也算未结算，HTTP 400/500、超时、缺失/非法 usage 不推断为零。
- 新目录不能豁免传入的历史未结算账本；未知用量阻止下一次生成，无自动重试。
  存在合法 usage 但超过预约时保留实际值并标记违规，而不是把估计当实际值。
- 保留模型上下文/单次输出/请求次数和超时边界，累计 token cap 仍为 null。
  这些是运行有效性与故障边界，不是 token 优化目标。

历史总数仍是 3 个请求：2 个已结算，已知 raw=2,221；1 个未知，预约 raw=28,284。
实际总 raw=null。新零 HTTP 审计验证了 Schema 拒绝和历史债务拒绝两个独立门禁，
并核对旧账本字节未变。业务提交未知与 Provider usage 未知仍严格区分。

## 证据与后续边界

外部证据根：`/cra/memory/mx_memory/evidence/v0220-provider-hardening/`。

| 结果文件 | SHA256 |
| --- | --- |
| error-localization-v2/result.json | 8a9474fc647db6e6f289beb99ee250cea65023e31785ae710f0a2ad7213d901c |
| full-schema-v1/result.json | 49c034da6fd82a68382e3f6f4645048a60554736b3283b46142ff925e083e12c |
| decision-v1/result.json | 38e3582363bf227c280957df520bc53d14d09ba2e013e5732d331f9a5f019631 |

代码：`tools/v0220_provider_hardened.py`、`tools/v0220_schema_admission.py`；
验证：`tests/unit/test_v0220_provider_hardened.py`，32 项离线测试通过。
完整仓库检查另见紧邻的机器可读结果文件。

若继续推进，需要另行选择并冻结兼容后端或经审阅的 wire-grammar 方案，
不能悄悄放宽完整公共契约。四个完整 Schema 全部通过后，才能安排有明确授权的
有界真实生成兼容检查；还需要真实历史 usage 凭据，或明确授权在保留历史未知的
条件下开展独立诊断。CPU 报告本身不是新请求额度，亦不是共享服务重启许可。

本轮未改 Product/A0/业务 Schema/权限，未打开 candidate 57 或保护池，未重启共享
vLLM，未开发 State。V2 的 23 条未运行链和 V3–V5 未触发状态保持不变。
