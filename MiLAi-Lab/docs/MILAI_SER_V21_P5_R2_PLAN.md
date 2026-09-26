# P5 R2：只检验完整对象引用合同

P5 R1已在`2c90dd376c3ec486ed154853a6d980eea8094610`发布，严格2/6和四次失败不变。按[失败分析](MILAI_SER_V21_P5_R1_RESULTS_20260927.md)，本轮仅对numeric_amount与retained_metadata的item参数加同一句公开description，要求完整复制用户给出的类型词与编号。全部公开消息、初始记忆、更新、数值类型和期望动作保持原样，不改SER、模型参数或旧评分，不添加enum/const/业务gate。

运行2例×A4/A5共4条新轨迹，沿用冻结64文件源码、v21 config、P5方法锁和连续账本。P5锁中的逐fixture合同是R1参考，本轮实际v2 schema与A4/A5相同性另存阶段freeze，prepare绑定新fixture哈希。该变更增加工具描述tokens，不能说是纯算法改进。

四例均需满足原严格完整动作参数和当前版本取得要求。成功后才为P6尚未运行九例加入同一description并冻结。原irrelevant v1对照无需为了改名重跑，引用时明确它的工具合同较弱；P6最终为两条R2 A5 v2、九条新A5 v2和一条原irrelevant A5 v1的同源码开发覆盖，不冒充统一新合同的独立12例试验。

假设H1是一般目标复制失败，H2是此前工具合同不够明确。显式description若有效支持H2但不排除简单提示遵循解释；若仍失败，保留轨迹后选择一个新通用诊断，不自动加输出替换或强制参数。

起点71生成/65327tokens/1035embeddingtokens，旧失败永久计费。fixture与文档变更不重复单测/build；源码、authority、vLLM不变。实际完整范围与评分见[冻结协议](../data/manifests/milai-ser-v21-p5r2-protocol.json)，总体Goal继续。
