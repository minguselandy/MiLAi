# V0222：独立意图呈现候选的完整门设计

日期：2026-09-12。版本建议：`INTENT_BOUNDARY_RUNTIME_V1`。
状态：`OFFLINE_IMPLEMENTATION_IN_PROGRESS / FULL_INSTANCE_NOT_ADMITTED`。本文件不启动生成，不解除旧批停止锁。

## 动机与前提

[残余边界诊断](../studies/active/MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md)的真实矩阵已结束，
固定选择器输出 `INTENT_BOUNDARY_SIGNAL`：原B0为4/8，独立消息B1为8/8，
前两根改善在正反两遍重复；最终独立原文审计已通过（BOUNDARY_RESULT_REVIEW_PASS），
SHA256 `99a9c0caf97743ad0aaf6769f46e62b6f6b0ed12d13132ec6f9e3d69b39d40e3`，须绑定到具体后续实例。
这是同一模型、D11、完整来源与原意图下的呈现信号，不是内部decoder根因、自然任务或Memory证据。

本设计只推广已选中的这一种机械呈现，不另试第三个提示、Schema排序或模型。
用户要求执行Goal及路线、遇到问题反思改进、委托subagent审查；具体实例仍需独立范围核对，
不能把reviewer意见或本设计当作新的用户同意，也不能消费旧批/诊断剩余位置。

## 为什么不能直接复用诊断函数

| 合同 | 原请求形态 | 必须保留的边界 |
| --- | --- | --- |
| P3 full | 原末尾user含单个put_record授权 | 已测B1；原25合法对象、完整值与资料不变 |
| P3 finish | 相同公共呈现，授权动作是finish | 旧B1函数只接put_record；新函数须支持原finish意图，验收仍为原合法finish |
| P4首轮 | 初始user含instruction和ordered_writes，最后user另有机会数/公开观察 | 不能抽出当前正确写入，不能从spec代填expected_version |
| P4后续 | 原assistant响应、tool_result、预算与公开版本回执均累积 | 保留全部轨迹，只移动原完整链授权；不得插入下一正确动作或正确回读 |
| P4第4轮 | 原Session强制finish-only Schema，初始链授权仍存在 | 链授权不要求属于该轮finish Schema，不能因此删掉它或造finish答案 |

诊断只实测了第一行；其余是明确未验证的推广，须新离线负控、完整门和实际执行建立证据。

## 唯一机械规则

对每份原Session/校准器生成的canonical请求执行纯函数，不修改Session持有的历史：

1. 定位唯一原公共presentation及其协议层authorized_intent，区别业务正文里的同名词。
2. 在deepcopy中仅从该原user JSON移除完整authorized_intent字段。
3. 使用原JSON序列化规则，将该字段及原值作为唯一最后user消息；不增加说明、答案副本或新值。
4. 其他所有消息字符与顺序、Schema及其属性/分支顺序、参数、机会数、公开观察、assistant原文、
   tool_result全部不变。新消息不写回Session.messages，下次仍从原请求作一次同样变换。
5. 保存original→presented→D11 wire及精确字符/UTF-8 splice/hash；逆变换必须恢复原请求。

纯呈现函数不能根据root/对象名/答案/已知失败挑策略，也不能使用checker生成下一轮意图。
原完整链intent不被改造成单个authorized_action；不自动填CAS、删历史、重发或修补输出。
消息边界、JSON封装、模板标记和距离共同变化，不能宣称分解了这些子因素。

## 最小接线与不可修改项

沿用原Session、ActionAdapter、World、完整Schema和独立effects检查；不原地修改任何已冻结模块。
需要新增版本化的纯呈现合同、准备/Provider/audit、批/传输、预检/worker/runner入口。
接口与源文件集合须在实施后具体冻结，不能只换旧Provider的路径而漏掉其硬编码compile逻辑。

- 准备器：原完整16 P3参考，加原24条P4参考路径的80次请求；保存三层请求与diff。
  P4参考仍以原Session和真实隔离SQLite验证提交、版本、receipt、公开回读及独立效果。
- Provider：原canonical先作纯呈现，再用相同D11编译；完整Schema→严格CAS→原意图顺序通过后才放行。
- 审计器：从原初始资料、实际原始响应和真实回执独立重建每轮请求，重新计算呈现与wire；
  不能只相信Provider自报hash或worker自报PASS。
- 新批：复用事务/事件机制，但冻结本阶段的新历史、单次launch、父子PID所有权和永久停止规则。
  保留逐实际HTTP准入、严格HTTP200和整数count、完整raw-first计费及新未知停发。
- P4使用全新隔离scope/初始World及派生hash，操作ID差异单列；不能继续使用旧可写World，
  不继承旧批或boundary模型输出。scope/hash/operation差异只作机械派生，不改原链intent。

## 完整矩阵与停止规则不缩减

P3仍是原四根×full/finish×两遍，共16次冷请求，无业务World。
原full目标依次manager_report、manager_report、placement_plan、triage；full需8/8完整保真，
finish需8/8原合同合法。首遍全通过才第二遍；首个非预期格式/Schema/意图或运行失败停止候选。
不增加B0对照、不混入诊断分母、不只测full或finish。

仅新P3全通过才触发P4：四根×单写/双写/复杂完整文本×两冷进程，共24链，每链≤4生成，最多96次。
80份参考是合法路径数量，不把96动态上界偷改成80；真实动态请求每次仍实际HTTP tokenize。
单写可在第3轮合法finish，但只有第4轮的原合同是finish-only，不为方便提前收窄Schema。
24/24需完整目标/值/顺序、版本、operation/receipt、公开回读与独立效果一致，首败停止。

P3阶段1800秒、P4阶段7200秒、每链300秒、每HTTP≤60秒、并发1、output4096、context65536。
模型及temperature0/seed213/top_p1/thinking关闭/stream=false不变；累计raw cap=null。
本设计尚未分配新实例生成次数；实际发送须新冻结、范围审查、完整容量门与前置门全部满足。

## 历史与离线必验

在boundary最终独审确认16请求全部结算后，新历史应绑定原28份独立账本＋本诊断16份＝44份，
共45请求；已知raw应为62874＋568796＝631670，旧未知预约28284单列，总实际仍未知。
以最终真实回执重新计算，不把中央镜像重复计费，不将新未知列成历史例外。

零模型验收必须覆盖：

- full/finish/P4各轮呈现完整可逆，Unicode/转义/保存读回/Schema顺序不变。
- 多份授权、漏资料或历史、额外说明、抽取下一动作、自动CAS修复均拒绝。
- 第4轮finish-only与原链授权并存；提前finish、错序、漏回读或额外副作用不能通过。
- float/bool CAS、wire/usage/tokenize/reference漂移、跨scope/version/operation错配和伪造效果负控。
- 真实新Batch＋MockHTTP＋原Session/ActionAdapter＋隔离SQLite全链及独立收口，
  并验证冷进程/父子归属、单写者、历史完整、重启/换目录/停批绕过失败。
- 离线16+80完整参考、24离线效果链及Mock接线；全部Lab工程检查。

真实HTTP身份/容量不属于零模型离线检查：须新实例完整冻结及独立范围审查通过后，
才允许调用现有vLLM HTTP，逐一检验全部完整参考及每次实际动态输入。离线设计PASS不授予HTTP许可。

后续E1/E2/M0/M1仍按[原路线](V0222_后续执行与Memory再准入规划.md)逐门执行；
不得把新的完整门准备当作恢复、自然任务或Memory实验完成。
只使用现有vLLM HTTP；不接管GPU/容器/服务、不读凭据、不改Product/A0、不打开保护池。

## 设计范围审查

`/root/v222_review`独立核对原P3 finish与P4四轮实际结构后给出
`DESIGN_SCOPE_PASS_FOR_OFFLINE_IMPLEMENTATION / LIVE_INSTANCE_NOT_ADMITTED`，
以最终boundary独立原文/费用审计确认固定B1信号为前提。
审查要求拆分离线验收与真实HTTP容量准入、明确不继承旧输出；上述要求已纳入。
这不是后续具体实例的发送准入，所有后续完整门仍须新冻结与独立范围审查。

## 2026-09-12 离线实施追加

[实施记录](../studies/active/MILA_V0222_PRESENTATION_IMPLEMENTATION_20260912.md)保存实际完整
16＋80参考、24效果链和40离线World证明及当前审计器追加重验；并记录独立审查发现的负控修订。
完整模型门尚未运行，正式实例尚未创建。单独HTTP容量预检的有限窗冻结为P3 1200秒、
P4 2400秒（包含本地源/参考复核）；这不修改1800/7200模型阶段、300秒链或60秒HTTP上限。
