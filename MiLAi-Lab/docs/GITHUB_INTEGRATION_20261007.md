# GitHub 开发分支整合：2026-10-07

用户明确要求处理并合并相关PR。整合范围是[PR83](https://github.com/minguselandy/MiLAi/pull/83)、
[PR84](https://github.com/minguselandy/MiLAi/pull/84)和[PR85](https://github.com/minguselandy/MiLAi/pull/85)。
工程合并不表示原研究任务完成，也不改变Product NO_GO。

## 分支与整合方式

PR83的post-r52分支和PR84的四臂分支从`fc1c6c9`分叉；PR85原来以PR84分支为基础。
PR84已在2026-10-07 06:59 UTC合并到main，合并提交为`eb5695b`。
其实际源码`c16e109`的Fast／Full均成功。

PR83实际源码`07867c6`的Fast／Full也均成功。Root在独立整合worktree将它接入PR85，
保留两个分支的提交历史，然后接入最新main并把PR85的目标改为main。
采用普通merge保留祖先关系，GitHub上的最终合并状态和提交以PR记录为准。
PR85整合前的`7ffb96c`和整合后的源码分别接受自身CI，不借用其他提交的检查。

## 四处冲突的决定

- `AGENTS.md`：当前用户合并授权置顶，保留统一任务卡和原post-r52历史激活记录。
- `memory/functional.py`：保留普通ID、实际提交边界及当前功能，接回可选来源工作视图和提案额度。
- `runners/functional.py`：统一Host、共同维护、完整请求恢复和新读取耗尽行为保留；来源复核抽到
  PR83的方法模块，原导出仍可调用，三个post-r52选项保持可选。
- `test_v13_5_functional_integration.py`：合并两边配置参数与实际检查，旧失败断言不删除。

新增复核、额度与来源视图适配当前`proposal_id`、实际来源版本、片段范围和原操作回执。
相同输入的拒绝复用比较实际保存材料；未知旧提交先核对原操作，不能改措辞或换调用ID另写。
当前Host没有重新引入SHA／内容指纹门禁。历史封存协议、原结果及冻结源码保持原状。
当前post-r52配对驱动也适配准备接口的普通版本ID，各条件分配一次UUID并保存首次结果。
评价标签只保存原件副本并比较实际文件，既不解析也不送入模型；旧v1运行仍用其冻结驱动。

`single_verdict_v1`仍是未准入的可选候选。PR83原X1的错误接受和A2 NOT ADMITTED保留，
不会因工程整合升级为方法优势，也没有新增reviewer模型或Agent。

## 验证与边界

已先完成39项集中检查，覆盖来源工作视图、支持判定状态、提案额度、未知提交恢复和当前Host。
完整两份功能文件首轮为413通过／1失败：旧配对驱动读取已移除的`fixture_sha256`。
驱动适配后，该项定向复测通过，原48个脚本响应、标签隔离、账本和重开断言保留；
额外确认48个普通请求ID互异且准备清单没有SHA字段。39项是这414项的子集，不重复计数。
199项导入边界检查、包DAG、工具Product依赖边界、相关Ruff及六个源文件严格mypy通过；
既有源码所有权检查覆盖256个活动源和10组严格范围。整合源码自身Fast／Full另核对。

整合没有执行真实generation、embedding或Judge。连续账本和原未知请求未重置；旧dffc232
评分仍只有18/32检查点、396响应及未确认的第397请求，没有评分终态。
原04:29报告、post-r52报告、四臂失败终态和所有私有ignored产物均保留。
Product、Archive、workflow、公开Product Schema/API/权限/Canonical没有改动。

整合前PR85源码回滚参考为`7ffb96c`，当前main回滚参考为`eb5695b`；
回滚代码不撤销实际业务效果或成本账本。各冻结实验仍按自己的源码记录。
完整同版对照、长历史、保留／外部验证、完整Host及六项交付继续按原计划执行。
