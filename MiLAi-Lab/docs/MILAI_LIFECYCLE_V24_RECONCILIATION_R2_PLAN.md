# Reconciliation R2：候选附带原正文的单变量试验

R1与两个能力控制已发布`9766dcc925259d4f12ec886e0272336f147428c9`。R1候选提示实际送达但成功动作后没有更新；首显式控制真实update却虚加received，唯一任务合同澄清后严格1/1。保留全部结果，当前只检验“引用与早前正文的关联负担”这一解释，不重开F或继续换提示措辞。

新臂`r_post_action_content`，protocol `post_action_reconciliation_content_v2`。R1固定cue逐字不变；触发、真实ok:true、生成request、FULL/EXACT、namespace、去重和原返回顺序全部保持。唯一模型可见变化是候选数组从`[{id,revision}]`扩展为`[{id,revision,content}]`：content逐字复制已经实际送达的`store_item.value.content`，不摘要、不补全、不选择语义相关项，不读取Store或引入新模型步骤。回执和checkpoint原文不改；普通Host仍决定update/no-op以及正文。

旧`r_post_action`默认不附正文。源码使用最小可选参数保留旧行为，沿用薄v24入口与同一候选查询；新config/lock独立绑定B1与新臂，不能以R1锁运行R2。必要窄验证覆盖默认R1不变、原content与id准确对应、无关项也保留且顺序不变、未知/错scope不因开启正文而纳入。构建随新源锁一次完成。

输入、rubric、diagnostic/input freeze直接引用R1原字节，三个case/六公开消息，仅运行新R2一次，新namespace；B1/R1作为固定历史参考，明确不是fresh matched。成功要求原pending entry根据实际状态/标识准确更新、没有虚构后续状态、无关entry不改；失败动作/no-op两个反例继续按原rubric。严格1个正例通过也只证明此小开发情景，不能外推正式未见或产品能力。

记录实际候选正文送达、CRUD、stale-current/false update/unnecessary maintenance/action-memory consistency、新增输入tokens、本地查询/存储成本和完整账本。若仍不更新或更新错误，停止这个R提示家族，继续P12有状态应用/质量—成本边界；不追加更强措辞、循环、自动正文写入或扩大benchmark寻找通过轨迹。

连续费用起点656生成/591982tokens/5884embeddingtokens/75exact reads，原vLLM、Qwen、JSON-action、temperature0、thinking=false、4096输出与每消息12生成不变。Root负责冻结/串行真实调用/分析；Sol源码/必要检查；Luna发布。P10资源问题与P12/master继续，Product和旧M1/ODR保持。
