# V0222 P1 字符串诊断：D11获得唯一候选信号

日期：2026-09-11。批次：`20260911-http-r1`。独立审查：`/root/v222_review`。

结论为 `STRING_RULE_SIGNAL / SELECTED_D11`，不是完整业务、动作执行或Memory通过。依照发送前冻结的选择器，只允许进入一个D11派生兼容候选的P2离线实现与回归。

## 实际结果

完成三类合成夹具、四条件、两遍共24次真实HTTP生成。首遍出现同夹具D00失败而移出条件保真的差异，按预定规则执行第二遍全部12位置、反向条件顺序；没有挑选有利单元重试。

| 条件 | wire移出规则 | 精确保真 | 严格JSON／完整Schema通过 | raw tokens |
| --- | --- | ---: | ---: | ---: |
| D00 | 无 | 0/6 | 6/6 | 1,090 |
| D10 | 仅精确pattern | 2/6 | 5/6 | 1,124 |
| D01 | 仅minLength=1 | 0/6 | 6/6 | 1,080 |
| D11 | 二者 | 6/6 | 6/6 | 1,157 |

每个夹具的messages、完整权威Schema、目标及参数在四条件间相同；实际wire仅改变两个预定关键字。T2含真实Unicode、引号、反斜线、换行和制表符；T3含边界空白。按JSON解码后的字符串精确比较，没有trim、归一化或输出修补。

D00、D01两遍均只返回单字符，合法但不保真。D10仅ASCII夹具T1两遍成功；T2两遍均为合法JSON，但字符串在引号前截断。D10/T3首遍为合法JSON但丢失tab/newline，第二遍`p1-23`含未转义的真实tab，因此是本批唯一非法JSON。它们均在HTTP成功、usage可信并结算后作为预定内容观测继续，不是业务验收放行。

D11三夹具两遍6/6，且三个夹具都在两遍相对D00一致改善。更简单的D10、D01均不合格，因此固定最小选择器唯一选中D11；未改规则、补跑或查看结果后换目标。

## 独立核查与成本

独立审查逐一读取24份实际请求、原始HTTP正文、可见输出、tokenize回执和episode账本；对照冻结条件并重新执行严格JSON、原完整Schema及精确比较。中央账与24个episode账完全一致，选择器复算与冻结结果一致。24个客户端PID不同，模型请求无重叠；未连接业务Session、World、dispatcher或Note。

全部HTTP身份回执匹配固定模型、65536上下文与0.27.1可见版本。48次预检tokenize及24次生成前tokenize均记录，身份GET共52次。单次生成HTTP最长约0.681秒，阶段启动至最终usage约59.606秒；不存在超时、未知usage或批停止。

本批模型输入4,072、输出379，合计 **4,451 raw tokens**，24次全部结算。历史已知30,085 raw加本批后，已知合计34,536；旧未知预约28,284仍未结算，因此跨历史总实际仍未知，预约不计作实际费用。Judge和云端回退均为0；Agent工作用量独立按线程计，不混入模型benchmark成本。

## 解释边界与下一步

证据支持“当前HTTP条件下，与这两个字符串wire约束相关的行为差异”。不能据此确定当前内部解码后端，更不能宣布线上XGrammar根因、完整字符串语言等价、统计效果量或业务能力改善。三种合成夹具与两遍固定seed不等于六个独立业务任务。

下一步仅为一个可选`STRING_RULES_RUNTIME_V1`：按预先规则延后已审阅正向显式string节点中的精确`pattern="\\S"`和`minLength=1`，保留完整权威Schema及原uniqueItems后验；具体变换清单、边界负控和完整接线须通过P2独立审查。P3、P4及后续E1/E2/M0/M1均未在本报告取得准入或成绩。

## 证据定位

原始制品保留在 `/cra/memory/mx_memory/evidence/v0222/20260911-http-r1/`，未写入Git。独立结果为 `P1-independent-review.json`，绑定499份原始／冻结制品hash，状态 `P1_OBSERVATION_AND_STRING_SIGNAL_REVIEW_PASS`；它是受用户委托的审查结论，不是新的用户授权。

批binding SHA256：`f6abde2c7258eba7288aa0cb7c74e03aafb97a486127f9b7a5827525c30c70d9`。配套原始结果：`P1-result.json`、`P1-firstpass-decision.json`、`P1-final-selection.json`及24个episode。
