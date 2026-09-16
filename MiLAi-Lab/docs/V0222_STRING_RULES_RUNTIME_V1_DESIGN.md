# V0222：单一字符串兼容候选及验收边界

本候选由 P1 事前冻结的选择器选出 D11：三种合成字符串、两遍均精确保真（6/6）；
D00 为 0/6，D10 为 2/6，D01 为 0/6。详见
[P1 诊断报告](../studies/active/MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md)。
这支持当前 HTTP 条件下的字符串约束相关差异，不识别服务内部 decoder 根因。

## 变更及不变项

新增可选 `STRING_RULES_RUNTIME_V1`，不修改旧 `UNIQUE_ITEMS_RUNTIME_V1`。
先执行旧 uniqueItems 变换，再仅在已审阅正向、显式 `type=string` 节点延后精确
`pattern="\\S"` 和整数 `minLength=1`。manifest 保存每个 JSON pointer、原值及规则类型。
其他正则、长度、格式、枚举、数值和对象规则不移除；引用、负向或未知运算符继续拒绝。
业务属性、default/example/enum 中的同名键不是变换目标。

完整权威 Schema 仍呈现并用于每份原始输出的最终校验。禁止修补、trim、去重、排序、代填，
不根据字段名、root 或目标答案选择规则。旧校验器对缺少可选检查器的 date-time 格式存在既有
限制，本次不安装依赖或改变其接受行为；格式规则保留与全部格式均被强制验证不能混为一谈。
原完整值比较、身份、scope、CAS 和独立环境效果仍分别验收；浮点 `0.0` 版本在派发前拒绝。

共用兼容说明同步更新，仍附完整权威 Schema。相对旧说明的逐字 diff、UTF-8 增量和每请求
messages hash 随候选封存，实际容量另用 HTTP tokenize 测量。因此完整任务复验不是只改
decoder 的单变量因果实验，不能把效果全部归因于某个内部 grammar 实现。

## 分层接线

P3：完整参考 canonical → 新 wire → HTTP/raw/usage → 完整 Schema → 精确意图比较；
无业务 World 或 dispatcher。16 个位置按原四根 full/finish 两遍运行，首个异常停批。

P4：原 Session → 相同 Provider → 完整 Schema/意图通过 → 原 ActionAdapter → 隔离 SQLite
→ 公开回读与 finish。24 条链独立 scope/进程，最多每链四次；不自动重发或重置 CAS。
独立审计从实际 HTTP 原文重新解码动作、核验原意图、重建动态请求，并复算 SQLite/receipt。
仅比较 Host 已解码的 action 或保存的效果报告不足以通过。

新 P4 scope 已在原批 manifest 冻结，但其准备期初始 hash 继承旧 scope。单独的
`P4_resolved_specs` 仅用已冻结新 scope 和未变公共数据重算这一派生 hash；保存旧新值与原因，
原 manifest、scope、动作、意图不改。运行时再次核验仅这一派生字段发生变化。

## 证据与准入

新源码、测试、传递依赖、P1 选择及独立审查、96 份完整参考、24 份独立效果和工程检查
须封存在当前批 P2 制品中，供 subagent 对实际实例签发审查；原 P1 manifest 不重写。
P2 离线通过并不等于 P3/P4 已通过。服务身份与完整容量只经 vLLM HTTP 验证，
没有 GPU/设备/容器准入检查，也不改服务。后续恢复、自然任务、Memory 仍依次等待各自门。
