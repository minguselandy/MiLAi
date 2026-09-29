# v10 R4/R5：写入责任、对象发现与时间/输出合同审查

2026-09-29，只读与无模型接口核对。未修改旧baseline、原生工具、scorer或主表。R4比较合同已明确；R5三个首断点分别保留。新增模型费用0。此文不宣称Host或外部Mem0已修复。

## R4：形成责任与效果主张

`langmem_benchmark.form()`只接受ArchiveInput（owner、history_id、合法HistoryMessage），没有question参数。形成cache由owner/source/history/方法身份构成。MemSyco ordinary通过这条边界由Agent调用strict记忆工具，随后共同原生reader读取。R3候选必须改变独立方法身份、重做形成并计费，不能将人工修正bank当自动效果。

MERIT ordinary的`merit_adapters()`给Host strict MCP CRUD/search/exact与合法历史；完成callback只记录实际消息与Store，没有自动writer。外部Mem0/SimpleMem分支在COMPLETED公开回合后调用实际add_archive；后续Host读材料。它们是系统配置比较，不是固定形成时机的后端组件消融。

因此分开两种合同：host_direct检验Host自主保存/动作/使用；backend_boundary固定已取得轨迹、摄入时机、读取入口及预算后，比较后端表示/更新。自动边界写入不能声称Host自主识别了保存意图。费用应包括全部形成、维护、检索、Host、Judge和失败；同一事项不加一个免费或重复writer。

旧MERIT ordinary及R1 L2的0 CRUD、空bank，不自动构成写入故障。其任务仍可访问合法历史；原生通过不是持久维护成功。R2合成请求则明确要求保存真实进度并在新会话读取，可检验具体维护义务。其结果尚未产生，不能据旧0 CRUD现在新增writer。条件性边界writer目前NOT_TRIGGERED；若R2/R3提供对应写入责任断点，再按新recipe、同源输入和NO_CHANGE反控单独评价。引文、临时情境、只读和未采纳建议不能自动变成永久指令。

## R5a：原生对象发现是可用但尚未被Host采用的路径

固定MERIT `d3.get_preference(key)`在不存在key时返回实际`available`键；`set_preference`为UPSERT。原失效路径直接生成新key，原key没有改变。原模型此前未见canonical key，不能将其描述为复制一个已交付ID失败。

Root在新合成world仅调用公开工具：自然措辞key查询→实际available列表→读取实际已有key→原生更新→工具读回；确认只改已有对象，没有创造旧失败的替代key。另以明确新key执行CREATE并读回，证明不应把所有未知key拒绝掉。另一个独立world未改变。证据与源码SHA在忽略的`artifacts/repair-v10/r5/native-discovery.json`。这是工具合同可达性证据，不是Host自主发现成功，也不是重新评分旧样本。

最小使用合同：修改已有事项而canonical key尚未取得时，先通过合法查询/错误回执取得对象，再选择准确目标；明确创建新事项仍允许CREATE。没有增加list/typed-ref工具，也没有静默把模型参数改成checker答案。原接口每world内key唯一；它没有对象版本引用或跨owner ref合同。两个相似名称应保留歧义，缺失/删除对象不能假称更新成功；若以后引入typed-ref，才须共同开放并完整测试同名、owner、缺失、旧版本和CREATE反控。本轮不建设新对象平台。

## R5b：时间扩展首断点在形成，且存在真实SDK约束

Root重读Mem0 `d3-arc26-000`实际链：最初用户仅提供Friday，没有绝对日期或时区锚点；第一次ADD真实请求的Observation Date和Current Date均为运行日2026-09-28。原生系统提示要求依Observation Date转成绝对日期。模型首次提取即加入September 25, 2026，实际持久化记录ID可查；更新地点后的新记录保留同一日期，后续实际Host请求交付这些记忆，最终create_event(day=完整日期字符串)未达原生weekday checker。

此处两个机制分别可证：未有来源锚点时新增了日期精度；生成的day也偏离工具说明Monday..Friday与checker的weekday值。没有足够来源证据判断现实中的正确绝对日期，准确措辞是“不受来源支持的绝对化”，不能把它补判成另一个确定日期。检索没有漏掉错误记录，而是真实交付并使用了它。

原pin `mem0-f8082a7345da` 的`configs/prompts.py::_resolve_dates()`在observation_date缺省时使用current_date；`Memory.add(timestamp=...)`的OSS路径明确拒绝非None timestamp。不能声称传一个timestamp即可修好，也不能把处理日假造为历史事件日。保留原事件表达、实际可得来源时间/时区和独立处理时间；未知时保持相对表达及不确定性。任何未来prompt/时间处理适配必须独立命名、计入时间上下文cache identity，原pin/prompt/失败保持。

本轮没有创建Mem0-temporal-adapted效果表或改旧缓存。该变体NOT_RUN；现有证据足够定位合同缺口，不支持无锚点绝对日期“修正”。R3形成范围候选关注MiLAi来源保真，不冒称外部Mem0已改变。

## R5c：原分保留，区分内容、精确格式与政策

重新核对原失败episode哈希及实际消息：ordinary四个退款确认失败episode包含六次发送，金额数字一致但带千位逗号；三次邮件失败把用户“that says:”后的首字母改为大写。这些是原生字符串要求/文字复用问题，不是七次事实丢失。尤其明确给出发送文字时应保留原样，不能以语义近似取消原失败。没有将大小写/逗号例外规则塞进writer，也未人工补分。

Mem0另一退款轨迹实际查询到了“超过阈值需批准”的政策后没有执行全额退款；其原生目标未达，但不能为了checker去移除政策或强迫退款。保留原失败与真实政策依据，单列政策冲突。私有原消息核对在`artifacts/repair-v10/r5/format-private-audit.json`及历史trace中。

## 当前处置

R4不因CRUD为0新增writer；R5不改native工具或第三方原pin。对象发现已有合法接口，时间缺少来源锚点且SDK日期参数有约束，格式/政策不应归因于记忆丢失。接口使用、来源时间和原样输出合同分别明确，效果改善仍未验证。后续最小改动必须使用新身份并针对单一原因；本审查不触发全方法矩阵、对象平台或重新评分。
