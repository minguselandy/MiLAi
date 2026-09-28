# v2 N2 / X3：固定bank的完整读取路径

状态：**已完成全部10条真实读取路径**。五条件最终答案均2/2，完整历史成本最低；见[结果与局限](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)。下文保留运行前协议和准备沿革。
承接[v2计划§8](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)和[N0/N1记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V2_20260928.md)。
本页逐阶段追加真实证据，不能用输入文件存在替代可执行方法。

## 首断点与竞争解释

旧C5读取草案只生成首响应，工具目录没有State READ，无法验收完整取材→回答或工具续接。
combined的原始4消息请求仅包含第二session，缺少较早handout原约定，不能叫“完整合法历史”。
两种解释必须区分：H1是固定bank选择能减少无关材料或避免错误消费；H2是完整历史/普通query已足够，
独立selector主要增加控制输入和调用。用同bank、同历史权限、同工具固定这些因素，不先分别形成bank。

原trace核实还表明combined两张“预约失败”卡来自控制模型在实际业务执行前的生成。
它们是实际存储的模型声称，不能当成实际失败回执。保留原bank和所有卡片，原始失败不删除；
评价处理计划所需事实与业务状态声称分开，不由程序纠正这些State。

## 数据沿革与共同能力

使用一个已暴露Workshop arc的两个前缀：background为当前handout问题和背景field更新，3条State；
combined为手动替换成同时询问两个计划的只读任务，5条State。后者不是原未改业务请求。
原P1 trace SHA256为`38ea180cbd0cf1e34e24f3e67b13cf2c072ba0b4a7c4056ea4e6f76942bf1a17`。
background保留实际第一session五消息前缀；combined使用该session真实六消息及第二session真实field问答两消息，
再接构造只读问题，共九消息。截止在原combined业务执行前，不包括之后任何实际业务结果/答案。
bank是原控制后已存快照，问题替换与跨session内联明确标为诊断构造，不声称历史轨迹字节重放。

每臂获得相同完整合法历史、同scope当前directory（id/title/needs/revision）和同只读工具。
普通memory统一设空，这是受控辅助前态，不声称恢复了历史ordinary memory快照；所有合法源消息已经内联，
固定读切片不运行事件维护/source展开。当前bank不重新生成、不优化正文、不过滤失败声称卡。

复用已有公开LangGraph ReAct/ToolNode与`build_agent`的`writer_tool_mode=read_only`，
工具为既有`search_memory`和`read_record`；共同关闭业务/写入/维护工具，反馈off。
自然允许零次、一次或多次READ及后续Host回答，不强制固定工具顺序。最终回答或容量/错误终态才结束路径。
只读权限是本切片的共同合同，因此不能据此评价在可用业务工具下避免错误行动的能力；该项留给N5。

## 五种条件与固定顺序

| 条件 | 预交付材料和额外选择 |
| --- | --- |
| all | 全部当前State正文，无选择生成 |
| query | 原完整问题，现有title+content向量/余弦top2 |
| query_enhanced | 与A相同目录生成entity_anchors，追加到完整原问题之后，再用相同top2；不裁掉原问题 |
| a_selector | N0共用目录A提示/载荷及实际read_ids，new_observations=[]；空集和多项合法 |
| full_history | 同完整历史、目录和State READ权限，但无预交付State正文；单独作为表示参照 |

H不是禁用State工具的消融；若主动READ取得State，按实际路径和费用报告。
A/query增强不看到完整State正文作为额外特权，embedding后端的title+content输入是共同检索计算材料。
ordinary query/增强共用top2，A返回数量另报；全读本来就是强简单参照，不把不等材料数量描述为完全相同呈现。
两种生成式选择都只有一次2048输出上限机会，选择失败保留，不隐藏补写或先看答案再挑选。

运行顺序：background-all、combined-query、background-query_enhanced、combined-a_selector、
background-full_history、combined-all、background-query、combined-query_enhanced、background-a_selector、combined-full_history。
10条读取路径是同一arc两个前缀的条件对照，不是10个独立样本，也不等于只有10次模型调用。

## 冻结输入与评分

| 文件 | SHA256 |
| --- | --- |
| [inputs](../data/diagnostics/next-development-v2-n2-fixed-read-r1/inputs.json) | `50b334aee2e234952940bcce286cdbb677ef9cdc403c28442b9c42b58120f8fb` |
| [config](../data/diagnostics/next-development-v2-n2-fixed-read-r1/config.json) | `c5fb7130f801d738a37189bc71474a34216e062f4017116b633a3e25eff7e41f` |
| [rubric](../data/diagnostics/next-development-v2-n2-fixed-read-r1/rubric.json) | `33e016291601d2cc4d62f6fe30b30d80777b714af72924f7734fa09b6f8eb37e` |

Root在实际输出后按固定rubric评分，runtime不读取rubric/gold，不按样本ID/预期答案分支；外部Judge为0。
background要求handout的数量/地点/包装正确；combined要求两计划事实与对象关联正确。
自然语言总结允许不改变关联的正常改写/标点，不把非业务回答当精确工具key测试。
任何不受原观察/真实工具支持的已执行或失败业务声称仍失败；候选不能把模型State文字升格为执行事实。
分别报告选材事实覆盖、实际HTTP交付、真实READ返回、最终答案、Store不变与成本。
含答案的非预期State同样可能提供信息，不能仅因ID不同判失败；空选择后依靠历史或实际READ完成也可通过。

## 执行、费用与限度

真实调用前须冻结已发布源码、实际模板/schema、scorer字节、依赖、顺序、每job新namespace/Store/checkpoint路径。
Root串行真实HTTP，既有Qwen3.6 Host temperature0/max_tokens4096/thinkingfalse，每任务Host上限12；
控制输出2048/每公开消息上限13，bge-m3/1024维，65536容量及原账本不变，不改共享部署。
所有selection/Host/embedding/读取/初始化/observer费用记录；request ID去重、角色互斥，失败/空结果收费保留。
同样的seed或日志子指标不能重复加到已付账本，未知CPU/物理I/O不写0。

当前v2成本仍2799生成/3486504 generation tokens/19273 embedding tokens，N0及本输入准备新增0。
新增真实运行以正式freeze前账本为起点，若之前另有授权实验则使用实际连续数值，不使用过期常量清零。
只接受对应窄检查与必要入口build；公开结果在全部固定job终态后汇总，不替换失败或挑最好轨迹。
小bank完整历史足够时Pivot独立选择收益主张，不扩充干扰材料硬造优势，也不外推所有任务规模。
N3固定更新、N5连续任务与WP7生命周期费用继续独立验收；N2不能代替它们。

## 恢复后的实现与准入检查

实际 Goal 已恢复 active，原11项N2 WIP按暂停清单移入 next-development-v2-resume；源码、配置、CI、测试7工程文件未再修改。
新 runner 复用既有 build_agent/ToolNode、严格 read_record/search_memory 与持久 Store/checkpoint，完成实际多轮读取路径，维护关闭。
原12项窄测、目标Ruff/Mypy与归属矩阵沿用已通过记录；恢复后只补必要边界与新入口包装检查，没有重复全suite。
一次离线构建通过，wheel/sdist关键源码/入口与源文件字节相同，不包含私密/运行制品。

零模型 /tmp prepare 成功，10 jobs，绑定153项源码/入口/包装文件、依赖锁、实际只读catalog与派生Host schema、参数、顺序和隔离路径。
该prepare使用发布前HEAD，不能作为发布后的正式执行身份。Root在源码发布后另建正式runtime_root及prepare，
再独立绑定本页rubric、共同输入与实际账本起点；只有该正式冻结完成才串行调用模型。
[精简检查回执](../data/manifests/next-development-v2-n2-checks-20260928.json)保留命令、旧检查、初始失败、包身份和未运行项。
检查只支持实现准入，真实decoder、数据库持久化与最终回答仍由10条完整路径核实；不以CI替代语义结果。

## 本轮执行已完成

正式方法 575360295946a77847702a527271f66102375365，十条路径全部终态。
生成19次/17901tokens，embedding4次/820tokens；五条件答案各2/2，保留A背景错误memory读取而最终回答正确的轨迹。
连续账本为2818/3504405/20093，全部收费与实际trace对齐。
结论Pivot本切片独立A/查询增强必需性，不扩充干扰造收益；N3/N5与WP7继续独立验收。
[结果报告](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)及[清单](../data/manifests/next-development-v2-n2-results-20260928.json)保存完整证据与边界。
