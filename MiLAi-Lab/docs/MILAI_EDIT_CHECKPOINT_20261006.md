# MiLAi-Edit 当前实验检查点

快照：2026-10-06 12:34:28 Asia/Shanghai。**共同原生配置的两分支80次已经完成并经
Root复核。M首次在共同条件分支完整执行例外增加、共享条件更正及撤销；原分支仍
失败，最终Reader仍未完整使用保存的规则。没有最终候选或方法优势结论，Product NO_GO。**

保留I2、B0/B1/B2/M和现有Qwen3.6家族。实验源码固定
`497b8d89f37ebe795e1e79f8791fe5ddd9289ed9`；普通SDK修复另提交为
`651a7b558b862809d07150bb83bcb6a2dd623407`，未进入这80次模型实验。
本次只更新七个Lab报告/状态文件，发布新增模型调用0；开发中的旧正文补交源码排除。
PR85仍open、draft、未合并，基础是PR84开发分支。

## 最新真实结果

| 冻结源码及配置 | 完成量 | 已获得的证据与限制 |
| --- | --- | --- |
| 497b8d8，非思考、temperature0、output8192 | 80次，162,068 known token，80 stop | 条件实际形成、普通更正保留未重述限定；范围、共同条件更新和撤销仍失败 |
| 同497b8d8，原生思考、temperature1、output32768 | 原44次197,788 token；共同36次186,607 token；合计80次384,395 token、80 stop | M共同条件Writer生命周期通过有限复核；原分支与最终Reader失败，不能宣布稳定优势 |
| 2335ea9，思考、output8192 | 80次348,003 token，71 stop/9 length | M选择过增加/撤销例外，两次形成截断，未入库限定不能算保持成功 |
| 8ed7826，非思考及来源控制 | 132次236,165 token，全部stop | 普通更正改善；范围、撤销和助手无依据强化的归属仍失败 |
| 旧4357d46完整历史 | B0 277/277；B1 115/277；B2/M各0/277 | 剩余162个B1会话及B2/M延后，未取消或补零，尚无四组完整比较 |

原生80次包含44 Writer、36 Reader、零Judge。33 committed、4 rejected、1 no_change，
另六个空envelope；这些是操作计数，不是语义成功率。四组原分支的无新事实查询
保持实际状态、版本和支持不变。两个分支来自同一个已曝光开发来源，各组各分支
从自己的空库形成，没有注入理想旧卡或读取保留用户。

## 条件机制已有一个完整Writer正例，读取仍失败

共同条件分支的M实际形成两个条件和两条关系；普通更正保留未重述限定。随后：

1. `add_exception`形成独立夜班四次及覆盖关系，保留一般三次和两个共享限定。
2. 两次`change_condition`更新实际共享条件节点，两个频率和各自适用关系保持。
3. `remove_exception`删除已形成例外及专属范围条件，一般三次、新开始时间及新
   节假日安排连同支持继续存在。

Root核对实际节点、边、支持及前后状态，而非只统计算子名称。共同条件更新后的
Reader完整回答了班次和限定；最终撤销后的Reader仍拒绝将一般规则应用到班次，
并把报告日期误作需要再次确认的理由。**Writer正确保存与Reader正确使用必须分开。**

原分支的M仍用`change_value`覆盖一般规则，撤销时误删节假日条件；后续重申中的
`add_exception`只是修复节假日，未完成夜班例外生命周期。B1在原分支插入/删除
独立例外保留旧规则，但共同分支改为替换复合正文并损坏一般频率；这显示结果尚不稳定。
两分支四组最终完整安排回答都未通过本次Root复核。

共同分支B0丢一般频率；B1还把矛盾旧限定归到更晚的撤销消息，最终Reader因此答错。
B2正确更新两个共同条件，但例外从未成功形成；撤销提案还复制无关的通用提醒示例，
仅用项目旧支持，被拒不是“完整正确更新遭误拒”。另一个合法改写问题仍保留：
原分支B0把旧复合限定拆成h-only新clause而被字面支持规则拒绝，必要旧正文补交待复核。

## 工程与版本边界

SDK的嵌套`keep_support`收集遗漏已在真实SQLite重开用例独立复现；651a7b5最小修复
通过341项SDK/普通Host回归（77+264）、Ruff、strict mypy及package/tools/root边界。
不改变来源身份、当前事件边界、h字面保持、origin、权限或CAS；没有模型队列使用它。
其自身Fast已success、Full仍in_progress（本次查询），不能借冻结497的成功CI代替。

旧正文补交已由owner稳定交付，报告148项离线检查通过；Root复核、runner预算接线、
提交及模型实验准入仍未完成。要求四组共同预算、
只交付选中旧记录实际支持范围、明确区分本次事件与重新交付正文；不放宽支持检查。
Reader改进尚未实施，不热修改已完成80次结果，不追加Writer警告、审核平台或新部署。

冻结497自身440项受影响检查、Ruff、strict mypy、24份默认关闭合同及依赖边界通过；
[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37408624077)与
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37408624028)均成功，Full21/21。
SDK修复自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37413376702) /
[Full](https://github.com/minguselandy/MiLAi/actions/runs/37413376862)及本次报告CI单独核对。
工程检查通过不能替代语义结果。本次报告JSON/计数/成本/账本、65个本地链接、
6,440 tracked paths依赖边界（零findings）与diff检查通过；未重复源码测试。

## 复核、成本和剩余范围

Root阅读44事件的实际输入、提案、回执及前后状态和36回答，核对80对HTTP及全部
prompt投影/usage。158,144 input + 226,251 completion =384,395 known token；80响应
均有原生reasoning，已包含在completion内，只计一次。四组共同配置同时调整原生模式、
温度和输出额度，其余采样保留现服务默认，不称完整厂商最优设置或M贡献。

连续账本36,286→36,366请求、139,019,217→139,403,612 known，charged139,455,314；
历史generation unknown2/embed unknown0不变，无新增unknown或embedding。两进程退出、
账本稳定、串行锁释放，无模型队列。Post-B0各版本完成成本合计516次/1,339,873 known，
只用于成本累计，不合并为同版方法分数。首次失败、原配置、运行终态和预声明actual0保留。

下一步在新版本复核共同旧正文交付和Reader使用仍有效规则的行为，再验证关键生命周期
与来源归属；符合准入后进入四开发用户前八会话和事前固定第一用户长历史，随后同版
四组完整比较。同M低层/语义入口消融与一次较紧预算、原生机制/漂移、16保留用户、
LongMemEval及现有基线、Host功能与恢复仍未完成。完整R0–R5/E0–E5和六项交付继续。

Root复核不是独立Judge或独立完整数据库审计，仅用一个模型家族。raw/gold/HTTP/
reasoning/数据库/日志继续ignored；本次不改Product Schema/API/权限/Canonical。
回滚参考651a7b5，不回滚实验原件，未合并。

[原生80次结果](../data/manifests/milai-edit-post-b0-native-capacity-results-20261006.json) ·
[当前状态](../data/manifests/milai-edit-v2-current-status-20261006.json) ·
[预声明](../data/manifests/milai-edit-post-b0-native-capacity-development-20261006.json) ·
[非思考80次](../data/manifests/milai-edit-post-b0-bound-clauses-results-20261006.json) ·
[完整进度](MILAI_EDIT_V2_PROGRESS_20261005.md) · [复现](MILAI_EDIT_REPRODUCTION.md)。
