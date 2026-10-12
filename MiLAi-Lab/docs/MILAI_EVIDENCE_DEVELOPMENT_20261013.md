# 2026-10-13 evidence 开发与实验

执行用户指定 `MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20261012.md`。基线为包含 PR121 的
f964292a，开发分支 `feat/lab-evidence-development-20261013`。原 main 与集成树已有未提交文档保持。
本轮无 SHA 校验，无新服务／模型部署，不改 Product／Archive。旧结论与冻结结果不覆盖。

## 已实现

- S0／S1／S2 配置实际进入材料组装；未指定仍为原 S2。正常 S0 捕获原文后跳过语义形成和召回。
- 复用原逐题到达前缀的原文与真实语义召回；复制旧银行仅用于按原身份重开来源和版本，
  不从最终银行重新搜索、不进行维护、不写 ActivationIndex。共同形成／召回费用单列。
- 排序保持原池 canonical 索引，独立顺序作用于 direct 分页及最终来源重开。
  当前未部署 MemSifter；四个开发配置明确使用 native 或 llm_probe，不报告 checkpoint 成绩。
  完整 Reader 包能装下时跳过排序；超限原件按完整排序包装预算分批，每批一次，
  单条批次不调用模型，各批提名交错交付。该过渡策略没有全池相关性评分；所有排序调用
  占用原 12 次读取／回答总额度，预留至少一页与最终回答。不增加模型额度或自动重试。
- patch_text 默认关闭：从实际目标全文唯一匹配、编译为 replace、当前断言与实际旧 h 支持并存；
  拒绝重复／重叠匹配和同目标重复编辑。保留来源单独作为 retained_support 重开，
  不将旧支持改记为本次 revision witness。仍为单元级归因。
- 官方 QA 评分复用原模板和解析；保留 invalid、missing，NOT_RUN 单列，不重复评分。

## 已核对的真实基线

b558 原预测已于 2026-10-12 06:59:52 UTC 闭合：32 会话、73 QA 机会，71 份答案、2 次已知读取失败。
实际进程已退出，连续账本与预测终态一致，原 HTTP 锁空闲。原运行仍未评分，不在本轮补写成绩。

原73题每题都保存了当时真实 native 召回。零 HTTP 离线重开1201段关联支持，均属于对应已到达前缀。
两条 direct／paged 题的重组材料逐字段等于原件。原73题 linked 新增数均为0；37题有语义候选却未装入语义材料。
因此短前缀 S0/S1 差异不能证明关联来源收益；独立机制例子验证 S1 确实可交付额外来源。

六题固定为 U1/S0/Q0,Q1,Q2、U2/S0/Q0、U3/S2/Q0、U4/S7/Q3；前五 direct，最后一题需分页。
同原模型窗口、采样、材料池与输出预留。实际 llm_probe 长题输入97,956＞32,256，
分批为[0,1]／[2]／[3,4]／[5,6,7]，单批最高27,950；单条批次免调用。
这只是接通观察。冻结源码f9f01661的S0六题已完成，6份答案、0缺答；
168,443预测生成tokens，0新维护／检索／embedding。S1与S2串行执行中，尚未评分或形成效果结论。

## 验证和剩余工作

已运行140项读取、重放、排序、局部修改相关检查；四个集成源文件 strict mypy、Ruff、
Lab包与工具依赖边界通过。模型代码审核发现的 canonical 索引误用、排序前可见性、旧配置缓存
兼容及排序额度问题已修复。验证只支持实现行为，不证明任务质量或 Product 可用性。

待执行：六题三条件实际回答／首次评分、有限排序对照、真实 patch／replace 更新观察；
固定24题筛选、按材料记录决定J1；仅收益候选进入73题／长历史／未参与调参历史。
学习训练取决于发布 checkpoint 的实际价值；未部署权重时继续明确的 llm_probe，不伪造训练结果。
完整计划仍 active，不以本次编码和局部检查替代最终实验交付。

## 入口

在本开发工作树的 MiLAi-Lab 执行（实际冻结副本和运行配置另存 ignored artifacts）：

```bash
PYTHONPATH=src /cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python \
  tools/run_baseline_alignment.py configs/milai-evidence-s0-dev-v1.json \
  artifacts/evidence-development/s0-six-v1 --phase predict --backend MiLAi-memory-only
```

S1／S2／ranked 使用各自配置与独立结果根。预测终态与资源闭合后，同配置同根显式 `--phase score`。
运行结果的 evidence-results.json 保存逐题答案路径、交付材料、各模型输入输出与耗时；
ranking.json 记录排序模型、各批实际索引及最终顺序。Judge费用与预测费用分开。
