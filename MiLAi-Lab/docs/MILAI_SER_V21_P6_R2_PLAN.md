# P6 R2：存储元数据不建立来源优先级

P6 R1在`c82a89de44031e85f3987204a60fec857be59b29`封存。该冲突例中两个CURRENT正文都完整送达，模型却把Store.created_at晚0.225秒当成跨来源优先级。修复只在已有SOURCE_AUTHORITY后追加通用的存储时间/检索排名语义与冲突澄清原则；作为明确的模型可见协议干预报告，不能算纯SER或rank算法收益。

先冻结并串行运行三个控制：原current_conflict、原no_stale、新explicit_source_priority。第三例使用同样两条East/West指令，在两来源正文中明确Alpha优先，并保留Alpha先写、Beta后写；预期根据明确规则执行East。实际排名需记录，不假设优先来源必然排名更低。两个原控制fixture不改，预期不改；新控制仍不提供业务真值门、enum或输出替换。

通过要求：无优先级冲突只澄清而不执行业务；无冲突正常执行且无get/rebase/额外search；明确优先级时两来源均送达、实际写入先后相反仍选择权威来源。Root读取真实动作与终端回答，所有费用加入现有SER账本，从136生成/128447tokens/1908embeddingtokens开始。

如果三例通过，依协议变化对其余已定义类型的影响安排最终同源回归；不能把原源码11/12拼成新源码的全通过。若失败，继续比较元数据误读、历史建议锚定和排序混淆，单次选择最小可区分修复，不进入硬语义gate。

源码只改稳定协议常量，recipe仍v21但新source mapping与新lock明确身份。schema形状、当前正文、排序、rank policy、lineage、checkpoint、Store和vLLM设置不变。此类文本变更只做必要静态/协议结构/token核对，不重复pytest、decoder probe或build。新锁用于仓库checkout复现；后继P7入口的包装变化届时统一做必要构建，不假称旧包已包含新字节。

范围、rubric与gate见[协议](../data/manifests/milai-ser-v21-p6r2-protocol.json)。本次与未来同源回归仍属development，formal未见样本尚未消费；长程Goal继续。
