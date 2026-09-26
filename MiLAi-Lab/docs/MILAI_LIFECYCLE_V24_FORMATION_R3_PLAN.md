# Formation R3：真实工具观察后的请求提醒

R2与独立显式保存控制已发布并核对remote：`fe9bfa079ccc5c72b0af8e5b6c3fb1c04742ce93`。两轮静态cue均0/2；显式保存/后续检索通过。现在检验一个事件时机候选，不继续改F2条件、重复CRUD检查或扩大benchmark。

新臂`f_observation_retention`保留F2固定cue逐字不变。只有当前普通ReAct请求紧接一组实际返回的business-tool观察时，程序在首system消息的请求副本末尾追加以下固定文本：

> A business-tool observation has just returned. Apply the future-use rule now to this turn's information, including the actual returned observation. If the rule calls for retention, use manage_memory before answering; otherwise finish without writing. A tool returning does not by itself establish business success.

事件由现有BusinessActionJournal的complete条目和当前消息中的thread/generation/call ID绑定，最近一组ToolMessage必须实际包含匹配的业务回执。旧历史业务回执、新用户消息、纯记忆工具结果不触发；不能依赖工具名称领域、case ID或正文内容。`complete`只代表调用已返回，不代表业务成功；F观察提醒对ok:false回执也可适用，因为失败观察可能有未来用途。R后续的业务成功判定另行要求明确合同。

使用既有`request_view.project`，保留原始消息、工具正文、checkpoint与普通loop。首system副本可追加提示；本地模板不允许后置system，绝不改vLLM模板。Host仍自己判断未来用途、记忆正文和原manage_memory CRUD/no-op；程序不自动写、不读取Store、不强迫每轮保存，不加独立LLM步骤或持久semantic State。

以原四例为核心，原case内容/顺序/rubric不变，再加一个一次性业务measurement反例，检验“有工具回执”是否被误当成“应持久化”。总五例/七公开消息，只新跑F3；原四例对照为R1 B1和R2 F的固定历史结果，不称fresh matched。第五例是独立机制反例，不加入旧四例分母。必须报告实际提醒送达请求、写入/内容、后续使用、临时误存和完整费用。

最小必要验证：真实journal绑定后只改请求首system副本，回执/checkpoint不改；memory-only、旧回执和错thread/call不触发；失败业务回执触发的文字不宣称成功。只做受影响窄测/静态检查和一次必要包装。Root冻结protocol/input/rubric/source/执行身份后才串行真实调用。

连续账本起点602生成/550151tokens/5187embeddingtokens/75exact version-resolution reads。服务设置、模型、容量、原loop/scorer不变。若此单一机制仍不能形成，保留负结果并停止cue家族继续堆叠，转入独立R和P12边界；不靠更多措辞或循环试跑寻找最好轨迹。若通过，也只说明本组明确未来用途的业务情景可用，非业务隐含未来用途及总体质量仍需独立边界说明。P10/P12与master继续。
