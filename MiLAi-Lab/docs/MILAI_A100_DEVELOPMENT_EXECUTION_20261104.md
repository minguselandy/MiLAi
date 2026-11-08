# MiLAi 双单卡开发执行记录：2026-11-04

完整目标仍在执行。依据用户指定的
[实验计划](/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/docs/MILAI_DEVELOPMENT_EXPERIMENT_PLAN_2XA100_40GB_20261104.md)，
从其指定的 `6c49bf05` 创建 `feat/a100-development-20261104`。
历史 worktree、原始失败与用户文档保持原状。没有使用子代理、SHA/内容指纹校验、新服务、第二账本或远端写入。

本轮机器可读入口为
[progress](../data/manifests/a100-development-progress-20261109-v156.json)。
原始数据、冻结运行时、权重、命令、计时和实际输出位于本 worktree 的 ignored
`artifacts/a100-development-20261104/`。本记录是现有报告体系的执行摘要。

## v156 当前状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第365/99b6e22f原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6271/total14463/
reserved14975<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭366整首结果逐项等于36段最早祖先；本段
40NN/input269588、5ReaderHTTP/
37629known、40真实before归档、
5案例/35control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子300.975499＋父0.160132434CPU，
NN/load已含其中；GPU2job区间0.12127611253953849h包含IO/Reader等待，非kernel忙碌时间。
idle119真实空闲支付4新增关闭计时6.029999999999999CPU，存储
29.717882864CPU另计，原89native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-036，仅85原生NOT_RUN，前序首结果整dict保持。
模型父3314086/子3314087与CPU存储父3314231/子3314232实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active366、{'FAILED_RETRIEVING': 2, 'COMPLETED': 330, 'FAILED_READING': 34, 'PREPARING_INPUT': 1, 'NOT_RUN': 84}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v155 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第360/97d5309a原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4976/total13168/
reserved13680<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭361整首结果逐项等于35段最早祖先；本段
160NN/input1112570、20ReaderHTTP/
138959known、160真实before归档、
20案例/140control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子1163.814167＋父0.167954752CPU，
NN/load已含其中；GPU2job区间0.43727046963008537h包含IO/Reader等待，非kernel忙碌时间。
idle118真实空闲支付4新增关闭计时21.770000000000003CPU，存储
114.997892832CPU另计，原88native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-035，仅90原生NOT_RUN，前序首结果整dict保持。
模型父3281566/子3281567与CPU存储父3281693/子3281694实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active361、{'FAILED_RETRIEVING': 2, 'COMPLETED': 326, 'FAILED_READING': 33, 'PREPARING_INPUT': 1, 'NOT_RUN': 89}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v154 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第340/84238c8f原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6183/total14375/
reserved14887<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭341整首结果逐项等于34段最早祖先；本段
16NN/input109128、2ReaderHTTP/
25248known、16真实before归档、
2案例/14control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子141.425455＋父0.143226521CPU，
NN/load已含其中；GPU2job区间0.0646730918610572h包含IO/Reader等待，非kernel忙碌时间。
idle117真实空闲支付4新增关闭计时2.89CPU，存储
12.657494855000001CPU另计，原87native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-034，仅110原生NOT_RUN，前序首结果整dict保持。
模型父3177331/子3177337与CPU存储父3177470/子3177471实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active341、{'FAILED_RETRIEVING': 2, 'COMPLETED': 307, 'FAILED_READING': 32, 'PREPARING_INPUT': 1, 'NOT_RUN': 109}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v153 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第338/820d56e2原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5918/total14110/
reserved14622<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭339整首结果逐项等于33段最早祖先；本段
16NN/input108814、2ReaderHTTP/
21618known、16真实before归档、
2案例/14control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子144.656778＋父0.146852258CPU，
NN/load已含其中；GPU2job区间0.058400259169801655h包含IO/Reader等待，非kernel忙碌时间。
idle116真实空闲支付4新增关闭计时2.94CPU，存储
13.17299522CPU另计，原86native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-033，仅112原生NOT_RUN，前序首结果整dict保持。
模型父3157414/子3157416与CPU存储父3157549/子3157550实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active339、{'FAILED_RETRIEVING': 2, 'COMPLETED': 306, 'FAILED_READING': 31, 'PREPARING_INPUT': 1, 'NOT_RUN': 111}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v152 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第336/7ebb0b95原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5884/total14076/
reserved14588<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭337整首结果逐项等于32段最早祖先；本段
56NN/input380873、7ReaderHTTP/
58901known、56真实before归档、
7案例/49control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子416.99894400000005＋父0.153027836CPU，
NN/load已含其中；GPU2job区间0.16506363685993064h包含IO/Reader等待，非kernel忙碌时间。
idle115真实空闲支付4新增关闭计时9.0CPU，存储
41.144453039CPU另计，原85native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-032，仅114原生NOT_RUN，前序首结果整dict保持。
模型父3137590/子3137591与CPU存储父3137813/子3137814实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active337、{'FAILED_RETRIEVING': 2, 'COMPLETED': 305, 'FAILED_READING': 30, 'PREPARING_INPUT': 1, 'NOT_RUN': 113}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v151 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第329/7376c10d原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt2996/total11188/
reserved11700<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭330整首结果逐项等于31段最早祖先；本段
16NN/input108831、2ReaderHTTP/
15147known、16真实before归档、
2案例/14control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子151.773037＋父0.145030887CPU，
NN/load已含其中；GPU2job区间0.060508952825847596h包含IO/Reader等待，非kernel忙碌时间。
idle114真实空闲支付4新增关闭计时3.28CPU，存储
12.790226417CPU另计，原84native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-031，仅121原生NOT_RUN，前序首结果整dict保持。
模型父3093336/子3093407与CPU存储父3093466/子3093467实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active330、{'FAILED_RETRIEVING': 2, 'COMPLETED': 299, 'FAILED_READING': 29, 'PREPARING_INPUT': 1, 'NOT_RUN': 120}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v150 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第327/73297783原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5276/total13468/
reserved13980<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭328整首结果逐项等于30段最早祖先；本段
16NN/input109901、2ReaderHTTP/
19568known、16真实before归档、
2案例/14control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子152.56401＋父0.153372903CPU，
NN/load已含其中；GPU2job区间0.06107743448474341h包含IO/Reader等待，非kernel忙碌时间。
idle113真实空闲支付4新增关闭计时3.13CPU，存储
13.17354795CPU另计，原83native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-030，仅123原生NOT_RUN，前序首结果整dict保持。
模型父3073417/子3073418与CPU存储父3073568/子3073569实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active328、{'FAILED_RETRIEVING': 2, 'COMPLETED': 298, 'FAILED_READING': 28, 'PREPARING_INPUT': 1, 'NOT_RUN': 122}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v149 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第325/70e79657原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4896/total13088/
reserved13600<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭326整首结果逐项等于29段最早祖先；本段
144NN/input991777、18ReaderHTTP/
115491known、144真实before归档、
18案例/126control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子1027.977969＋父0.149052754CPU，
NN/load已含其中；GPU2job区间0.3836673587677069h包含IO/Reader等待，非kernel忙碌时间。
idle112真实空闲支付4新增关闭计时19.810000000000002CPU，存储
103.022875007CPU另计，原82native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-029，仅125原生NOT_RUN，前序首结果整dict保持。
模型父3053292/子3053300与CPU存储父3053421/子3053422实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active326、{'FAILED_RETRIEVING': 2, 'COMPLETED': 297, 'FAILED_READING': 27, 'PREPARING_INPUT': 1, 'NOT_RUN': 124}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v148 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第307/631667c9原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4932/total13124/
reserved13636<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭308整首结果逐项等于28段最早祖先；本段
32NN/input232890、4ReaderHTTP/
32434known、32真实before归档、
4案例/28control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子250.618204＋父0.16691508CPU，
NN/load已含其中；GPU2job区间0.09432073743341284h包含IO/Reader等待，非kernel忙碌时间。
idle111真实空闲支付4新增关闭计时5.28CPU，存储
23.842733712CPU另计，原81native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-028，仅143原生NOT_RUN，前序首结果整dict保持。
模型父2962311/子2962312与CPU存储父2962442/子2962443实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active308、{'FAILED_RETRIEVING': 2, 'COMPLETED': 280, 'FAILED_READING': 26, 'PREPARING_INPUT': 1, 'NOT_RUN': 142}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v147 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第303/609acb91原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6282/total14474/
reserved14986<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭304整首结果逐项等于27段最早祖先；本段
72NN/input498247、9ReaderHTTP/
63790known、72真实before归档、
9案例/63control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子518.415579＋父0.146488867CPU，
NN/load已含其中；GPU2job区间0.19235109539392095h包含IO/Reader等待，非kernel忙碌时间。
idle110真实空闲支付4新增关闭计时10.299999999999999CPU，存储
52.671696250000004CPU另计，原80native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-027，仅147原生NOT_RUN，前序首结果整dict保持。
模型父2933729/子2933732与CPU存储父2933864/子2933865实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active304、{'FAILED_RETRIEVING': 2, 'COMPLETED': 277, 'FAILED_READING': 25, 'PREPARING_INPUT': 1, 'NOT_RUN': 146}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v146 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第294/57817b87原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4918/total13110/
reserved13622<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭295整首结果逐项等于26段最早祖先；本段
88NN/input605308、11ReaderHTTP/
108373known、88真实before归档、
11案例/77control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子603.121541＋父0.171184413CPU，
NN/load已含其中；GPU2job区间0.26745660735915106h包含IO/Reader等待，非kernel忙碌时间。
idle109真实空闲支付4新增关闭计时12.15CPU，存储
64.510464319CPU另计，原79native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-026，仅156原生NOT_RUN，前序首结果整dict保持。
模型父2884986/子2884987与CPU存储父2885110/子2885111实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active295、{'FAILED_RETRIEVING': 2, 'COMPLETED': 269, 'FAILED_READING': 24, 'PREPARING_INPUT': 1, 'NOT_RUN': 155}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v145 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第283/4a4aad22原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6340/total14532/
reserved15044<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭284整首结果逐项等于25段最早祖先；本段
16NN/input112638、2ReaderHTTP/
26699known、16真实before归档、
2案例/14control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子147.04513400000002＋父0.143931757CPU，
NN/load已含其中；GPU2job区间0.06848990107653663h包含IO/Reader等待，非kernel忙碌时间。
idle108真实空闲支付4新增关闭计时2.95CPU，存储
12.750315883999999CPU另计，原78native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-025，仅167原生NOT_RUN，前序首结果整dict保持。
模型父2820193/子2820194与CPU存储父2820320/子2820321实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active284、{'FAILED_RETRIEVING': 2, 'COMPLETED': 259, 'FAILED_READING': 23, 'PREPARING_INPUT': 1, 'NOT_RUN': 166}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v144 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第281/48ab5c3d原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6193/total14385/
reserved14897<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭282整首结果逐项等于24段最早祖先；本段
40NN/input272302、5ReaderHTTP/
36206known、40真实before归档、
5案例/35control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子309.54395＋父0.148258711CPU，
NN/load已含其中；GPU2job区间0.11514775943942368h包含IO/Reader等待，非kernel忙碌时间。
idle107真实空闲支付4新增关闭计时6.1CPU，存储
29.736828831CPU另计，原77native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-024，仅169原生NOT_RUN，前序首结果整dict保持。
模型父2797465/子2797466与CPU存储父2797594/子2797595实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active282、{'FAILED_RETRIEVING': 2, 'COMPLETED': 258, 'FAILED_READING': 22, 'PREPARING_INPUT': 1, 'NOT_RUN': 168}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v143 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第276/4266cb67原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4967/total13159/
reserved13671<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭277整首结果逐项等于23段最早祖先；本段
88NN/input602614、11ReaderHTTP/
91150known、88真实before归档、
11案例/77control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子602.8026259999999＋父0.168176012CPU，
NN/load已含其中；GPU2job区间0.2538620770673474h包含IO/Reader等待，非kernel忙碌时间。
idle106真实空闲支付4新增关闭计时12.25CPU，存储
63.612178934999996CPU另计，原76native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-023，仅174原生NOT_RUN，前序首结果整dict保持。
模型父2765718/子2765719与CPU存储父2765850/子2765851实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active277、{'FAILED_RETRIEVING': 2, 'COMPLETED': 254, 'FAILED_READING': 21, 'PREPARING_INPUT': 1, 'NOT_RUN': 173}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v142 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第265/3269a3c5原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4308/total12500/
reserved13012<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭266整首结果逐项等于22段最早祖先；本段
48NN/input333921、6ReaderHTTP/
45069known、48真实before归档、
6案例/42control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子347.809752＋父0.149456409CPU，
NN/load已含其中；GPU2job区间0.13106282028524827h包含IO/Reader等待，非kernel忙碌时间。
idle105真实空闲支付4新增关闭计时7.029999999999999CPU，存储
35.48293945299999CPU另计，原75native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-022，仅185原生NOT_RUN，前序首结果整dict保持。
模型父2702122/子2702123与CPU存储父2702251/子2702252实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active266、{'FAILED_RETRIEVING': 2, 'COMPLETED': 244, 'FAILED_READING': 20, 'PREPARING_INPUT': 1, 'NOT_RUN': 184}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v141 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第259/2ca2d443原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6266/total14458/
reserved14970<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭260整首结果逐项等于21段最早祖先；本段
8NN/input55873、1ReaderHTTP/
14458known、8真实before归档、
1案例/7control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子96.981723＋父0.146255547CPU，
NN/load已含其中；GPU2job区间0.040947315184037304h包含IO/Reader等待，非kernel忙碌时间。
idle104真实空闲支付4新增关闭计时1.7900000000000003CPU，存储
7.310121468CPU另计，原74native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-021，仅191原生NOT_RUN，前序首结果整dict保持。
模型父2667922/子2667925与CPU存储父2668051/子2668052实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active260、{'FAILED_RETRIEVING': 2, 'COMPLETED': 239, 'FAILED_READING': 19, 'PREPARING_INPUT': 1, 'NOT_RUN': 190}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v140 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第258/2c45ecbb原生Reader单次HTTP以length结束，输出8192
tokens、final=present_truncated_final；prompt4892/total13084/
reserved13596<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭259整首结果逐项等于20段最早祖先；本段
40NN/input270581、5ReaderHTTP/
38253known、40真实before归档、
5案例/35control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子300.90320099999997＋父0.149107771CPU，
NN/load已含其中；GPU2job区间0.1162067671945422h包含IO/Reader等待，非kernel忙碌时间。
idle103真实空闲支付4新增关闭计时7.3CPU，存储
29.227440962CPU另计，原73native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-020，仅192原生NOT_RUN，前序首结果整dict保持。
模型父2651781/子2651782与CPU存储父2651895/子2651897实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active259、{'FAILED_RETRIEVING': 2, 'COMPLETED': 239, 'FAILED_READING': 18, 'PREPARING_INPUT': 1, 'NOT_RUN': 191}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v139 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第253/25853d7f原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6190/total14382/
reserved14894<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭254整首结果逐项等于19段最早祖先；本段
48NN/input326097、6ReaderHTTP/
55880known、48真实before归档、
6案例/42control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子366.20469099999997＋父0.151506713CPU，
NN/load已含其中；GPU2job区间0.15767386154996024h包含IO/Reader等待，非kernel忙碌时间。
idle102真实空闲支付4新增关闭计时7.16CPU，存储
37.745863896CPU另计，原72native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-019，仅197原生NOT_RUN，前序首结果整dict保持。
模型父2619639/子2619642与CPU存储父2619775/子2619776实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active254、{'FAILED_RETRIEVING': 2, 'COMPLETED': 235, 'FAILED_READING': 17, 'PREPARING_INPUT': 1, 'NOT_RUN': 196}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v138 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第247/1fec75e5原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt7315/total15507/
reserved16019<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭248整首结果逐项等于18段最早祖先；本段
48NN/input330646、6ReaderHTTP/
46662known、48真实before归档、
6案例/42control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子371.513242＋父0.149367458CPU，
NN/load已含其中；GPU2job区间0.13707738682886378h包含IO/Reader等待，非kernel忙碌时间。
idle101真实空闲支付4新增关闭计时7.029999999999999CPU，存储
35.979949173CPU另计，原71native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-018，仅203原生NOT_RUN，前序首结果整dict保持。
模型父2579495/子2579496与CPU存储父2579634/子2579635实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active248、{'FAILED_RETRIEVING': 2, 'COMPLETED': 230, 'FAILED_READING': 16, 'PREPARING_INPUT': 1, 'NOT_RUN': 202}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v137 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第241/1a89c3ac原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4964/total13156/
reserved13668<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭242整首结果逐项等于17段最早祖先；本段
8NN/input55895、1ReaderHTTP/
13156known、8真实before归档、
1案例/7control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子93.93956499999999＋父0.147160553CPU，
NN/load已含其中；GPU2job区间0.04011289593686039h包含IO/Reader等待，非kernel忙碌时间。
idle100真实空闲支付4新增关闭计时1.7900000000000003CPU，存储
6.910657677CPU另计，原70native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-017，仅209原生NOT_RUN，前序首结果整dict保持。
模型父2541846/子2541848与CPU存储父2541956/子2541957实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active242、{'FAILED_RETRIEVING': 2, 'COMPLETED': 225, 'FAILED_READING': 15, 'PREPARING_INPUT': 1, 'NOT_RUN': 208}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v136 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第240/19c641bd原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt7356/total15548/
reserved16060<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭241整首结果逐项等于16段最早祖先；本段
96NN/input652222、12ReaderHTTP/
73689known、96真实before归档、
12案例/84control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子659.195864＋父0.164816437CPU，
NN/load已含其中；GPU2job区间0.24429033434147843h包含IO/Reader等待，非kernel忙碌时间。
idle99真实空闲支付4新增关闭计时13.55CPU，存储
70.426170188CPU另计，原69native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-016，仅210原生NOT_RUN，前序首结果整dict保持。
模型父2526642/子2526643与CPU存储父2526768/子2526769实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active241、{'FAILED_RETRIEVING': 2, 'COMPLETED': 225, 'FAILED_READING': 14, 'PREPARING_INPUT': 1, 'NOT_RUN': 209}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v135 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第228/0af83ccc原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5201/total13393/
reserved13905<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭229整首结果逐项等于15段最早祖先；本段
8NN/input54562、1ReaderHTTP/
13393known、8真实before归档、
1案例/7control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子98.177543＋父0.149874181CPU，
NN/load已含其中；GPU2job区间0.0409428264055815h包含IO/Reader等待，非kernel忙碌时间。
idle98真实空闲支付4新增关闭计时1.7500000000000002CPU，存储
7.054733695CPU另计，原68native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-015，仅222原生NOT_RUN，前序首结果整dict保持。
模型父2466182/子2466188与CPU存储父2466321/子2466323实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active229、{'FAILED_RETRIEVING': 2, 'COMPLETED': 214, 'FAILED_READING': 13, 'PREPARING_INPUT': 1, 'NOT_RUN': 221}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v134 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第227/0ace674b原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt6164/total14356/
reserved14868<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭228整首结果逐项等于14段最早祖先；本段
24NN/input163281、3ReaderHTTP/
28182known、24真实before归档、
3案例/21control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子196.653711＋父0.160147384CPU，
NN/load已含其中；GPU2job区间0.0801794600326361h包含IO/Reader等待，非kernel忙碌时间。
idle97真实空闲支付4新增关闭计时3.9399999999999995CPU，存储
18.484957229CPU另计，原67native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-014，仅223原生NOT_RUN，前序首结果整dict保持。
模型父2449425/子2449427与CPU存储父2449554/子2449555实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active228、{'FAILED_RETRIEVING': 2, 'COMPLETED': 214, 'FAILED_READING': 12, 'PREPARING_INPUT': 1, 'NOT_RUN': 222}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v133 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第224/07fff330原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt7265/total15457/
reserved15969<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭225整首结果逐项等于13段最早祖先；本段
64NN/input444503、8ReaderHTTP/
56225known、64真实before归档、
8案例/56control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子488.630316＋父0.148577537CPU，
NN/load已含其中；GPU2job区间0.1837886735996128h包含IO/Reader等待，非kernel忙碌时间。
idle96真实空闲支付4新增关闭计时9.19CPU，存储
46.687313189CPU另计，原66native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-013，仅226原生NOT_RUN，前序首结果整dict保持。
模型父2424146/子2424156与CPU存储父2424366/子2424367实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active225、{'FAILED_RETRIEVING': 2, 'COMPLETED': 212, 'FAILED_READING': 11, 'PREPARING_INPUT': 1, 'NOT_RUN': 225}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v132 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第216/05cce9b3原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5216/total13408/
reserved13920<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭217整首结果逐项等于12段最早祖先；本段
72NN/input484522、9ReaderHTTP/
73008known、72真实before归档、
9案例/63control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子604.505711＋父0.160704083CPU，
NN/load已含其中；GPU2job区间0.22776995009147666h包含IO/Reader等待，非kernel忙碌时间。
idle95真实空闲支付4新增关闭计时10.53CPU，存储
62.49400030699999CPU另计，原65native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-012，仅234原生NOT_RUN，前序首结果整dict保持。
模型父2376460/子2376461与CPU存储父2376602/子2376603实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active217、{'FAILED_RETRIEVING': 2, 'COMPLETED': 205, 'FAILED_READING': 10, 'PREPARING_INPUT': 1, 'NOT_RUN': 233}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v131 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第207/fa504f5e原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5187/total13379/
reserved13891<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭208整首结果逐项等于11段最早祖先；本段
32NN/input236737、4ReaderHTTP/
33072known、32真实before归档、
4案例/28control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子484.68512＋父0.143627567CPU，
NN/load已含其中；GPU2job区间0.16744419667455884h包含IO/Reader等待，非kernel忙碌时间。
idle94真实空闲支付4新增关闭计时4.23CPU，存储
31.970983447000002CPU另计，原64native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-011，仅243原生NOT_RUN，前序首结果整dict保持。
模型父2320861/子2320869与CPU存储父2320995/子2320996实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active208、{'FAILED_RETRIEVING': 2, 'COMPLETED': 197, 'FAILED_READING': 9, 'PREPARING_INPUT': 1, 'NOT_RUN': 242}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v130 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第203/f3496ca5原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt3204/total11396/
reserved11908<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭204整首结果逐项等于10段最早祖先；本段
238NN/input1668601、30ReaderHTTP/
152579known、238真实before归档、
30案例/208control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子2438.784359＋父0.165338603CPU，
NN/load已含其中；GPU2job区间0.829361308052515h包含IO/Reader等待，非kernel忙碌时间。
idle93真实空闲支付4新增关闭计时27.250000000000004CPU，存储
229.36778992700002CPU另计，原63native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-010，仅247原生NOT_RUN，前序首结果整dict保持。
模型父2276749/子2276763与CPU存储父2276872/子2276873实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active204、{'FAILED_RETRIEVING': 2, 'COMPLETED': 194, 'FAILED_READING': 8, 'PREPARING_INPUT': 1, 'NOT_RUN': 246}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v129 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第173/ccf29914原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5278/total13470/
reserved13982<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭174整首结果逐项等于9段最早祖先；本段
352NN/input2502137、44ReaderHTTP/
198435known、352真实before归档、
44案例/308control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子3622.3989＋父0.167392035CPU，
NN/load已含其中；GPU2job区间1.1842579724740547h包含IO/Reader等待，非kernel忙碌时间。
idle92真实空闲支付4新增关闭计时39.67999999999999CPU，存储
344.674700249CPU另计，原62native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-009，仅277原生NOT_RUN，前序首结果整dict保持。
模型父2084662/子2084734与CPU存储父2084800/子2084801实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active174、{'FAILED_RETRIEVING': 2, 'COMPLETED': 165, 'FAILED_READING': 7, 'PREPARING_INPUT': 1, 'NOT_RUN': 276}，
新存储0案例/0control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v128 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第129/9b34f55b原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt4286/total12478/
reserved12990<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭130整首结果逐项等于8段最早祖先；本段
40NN/input284884、5ReaderHTTP/
28006known、40真实before归档、
5案例/35control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子443.214697＋父0.145280462CPU，
NN/load已含其中；GPU2job区间0.1540824697425382h包含IO/Reader等待，非kernel忙碌时间。
idle91真实空闲支付4新增关闭计时5.59CPU，存储
41.481622103999996CPU另计，原61native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-008，仅321原生NOT_RUN，前序首结果整dict保持。
模型父1813508/子1813509与CPU存储父1813639/子1813640实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active131、{'FAILED_RETRIEVING': 2, 'COMPLETED': 123, 'FAILED_READING': 6, 'PREPARING_INPUT': 1, 'NOT_RUN': 319}，
新存储1案例/7control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v127 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第124/93d0613b原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt3256/total11448/
reserved11960<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭125整首结果逐项等于7段最早祖先；本段
48NN/input331079、6ReaderHTTP/
29396known、48真实before归档、
6案例/42control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子513.8212639999999＋父0.157231317CPU，
NN/load已含其中；GPU2job区间0.1770128337117947h包含IO/Reader等待，非kernel忙碌时间。
idle90真实空闲支付4新增关闭计时6.359999999999999CPU，存储
50.353559912CPU另计，原60native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-007，仅326原生NOT_RUN，前序首结果整dict保持。
模型父1763756/子1763768与CPU存储父1763875/子1763876实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active127、{'FAILED_RETRIEVING': 2, 'COMPLETED': 120, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 323}，
新存储2案例/14control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v126 历史状态（2026-11-09，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第118/8e21c6e5原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5162/total13354/
reserved13866<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭119整首结果逐项等于6段最早祖先；本段
120NN/input853076、15ReaderHTTP/
71166known、120真实before归档、
15案例/105control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子1368.516423＋父0.166567072CPU，
NN/load已含其中；GPU2job区间0.44922879124241366h包含IO/Reader等待，非kernel忙碌时间。
idle89真实空闲支付4新增关闭计时14.14CPU，存储
120.654066123CPU另计，原59native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-006，仅332原生NOT_RUN，前序首结果整dict保持。
模型父1701011/子1701013与CPU存储父1701130/子1701131实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active120、{'FAILED_RETRIEVING': 2, 'COMPLETED': 114, 'FAILED_READING': 4, 'PREPARING_INPUT': 1, 'NOT_RUN': 330}，
新存储1案例/7control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v125 历史状态（2026-11-08，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第103/7e32e4a2原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt1947/total10139/
reserved10651<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭104整首结果逐项等于5段最早祖先；本段
280NN/input2036946、35ReaderHTTP/
158211known、280真实before归档、
35案例/245control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子3275.310959＋父0.174426316CPU，
NN/load已含其中；GPU2job区间1.0478285318183609h包含IO/Reader等待，非kernel忙碌时间。
idle88真实空闲支付4新增关闭计时31.200000000000003CPU，存储
276.496264056CPU另计，原58native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-005，仅347原生NOT_RUN，前序首结果整dict保持。
模型父1575449/子1575450与CPU存储父1575568/子1575569实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active106、{'FAILED_RETRIEVING': 2, 'COMPLETED': 101, 'FAILED_READING': 3, 'PREPARING_INPUT': 1, 'NOT_RUN': 344}，
新存储2案例/14control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v124 历史状态（2026-11-08，Asia/Shanghai）：Reader首失败保留与完整计量关闭，仅未尝试尾部运行

第68/50d92f55原生Reader单次HTTP以length结束，输出8192
tokens、final=absent_final；prompt5155/total13347/
reserved13859<65536，无输入溢出/新unknown。
全部首失败保留FAILED/scoreNone，没有修改thinking/cap/Source或补成UNKNOWN/负gold。
已关闭69整首结果逐项等于4段最早祖先；本段
160NN/input1144445、20ReaderHTTP/
104060known、160真实before归档、
20案例/140control原字节比对全部对齐。
模型父子实际退出/消失/原生CPU已记，完整子1773.8029569999999＋父0.160637573CPU，
NN/load已含其中；GPU2job区间0.5893138563348395h包含IO/Reader等待，非kernel忙碌时间。
idle87真实空闲支付4新增关闭计时18.59CPU，存储
161.915407198CPU另计，原57native client phases已核对且不重计。

显式登记/check-only并启动primary-seed0-u32-prediction451-v1-continuation-004，仅382原生NOT_RUN，前序首结果整dict保持。
模型父1321667/子1321669与CPU存储父1326926/子1326927实际存活；
cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过。当前active73、{'FAILED_RETRIEVING': 2, 'COMPLETED': 69, 'FAILED_READING': 2, 'PREPARING_INPUT': 1, 'NOT_RUN': 377}，
新存储3案例/21control检查点。原1141绑定/科学配置/
checkpoint/seed/预算/Source与输出首结果均未变。运行时不读写离线账本，本进度计时等待实际下一idle。
全451覆盖及Source/NN/SDK/Reader/评分审计、归档、Mem2Act400×2、最终全成本/论文/图表/763完成审计仍未完成；
原1..9逐步物理快照缺口按真实Source/Store/trace/SDK/Reader证据披露，不伪造或重跑。

## v123 历史状态（2026-11-08，Asia/Shanghai）：002首Reader失败保留与成本关闭，003仅402未尝试任务运行

连续实际进程核验后，第48/3a2e9368原生Reader单次HTTP输出8192到顶、length且final正文None，
prompt3335/total11527/reserved12039<65536，估算误差0、新unknown0/0；没有改cap/thinking/Source或救回正文。
002父874577/子874598实际退出1/消失/原生CPU关闭；首49项46COMP/2FAILED_RETRIEVING/1FAILED_READING，
全部整dict等于3段最早祖先，0/9/48失败及其分母保留，余下49..450共402项原生NOT_RUN。

本段39实际ReaderHTTP/183109known tokens，312NN/input2176872完整before/菜单/payload/head/有限argmax/
无截断与原生账本计数对齐。39案例312真实完整before归档、273control检查点完整原字节核对通过，
存储父878698/子878704退出0/消失。模型完整子3200.977528＋父0.180046645CPU已原生一次计量，
含NN375.57629894989077/load8.291268228999797；GPU2job区间1.0427041608082235h包含IO/HTTP等待，
不是kernel忙碌小时。idle86实际空闲支付7新增关闭计时58.23CPU，存储312.603644906CPU另计，旧费用不重加。

冻结同一1141绑定观察v3已显式register/check-only并启动003仅402未尝试项；父1153163/子1153165
实际存活，cuda0/GPU2FP32/16384/2048/threads4/MHAFalse/refcompileFalse加载通过，首49整记录与002相同。
当前active52、{'FAILED_RETRIEVING': 2, 'COMPLETED': 49, 'FAILED_READING': 1, 'PREPARING_INPUT': 1, 'NOT_RUN': 398}；CPU跟随器父1159147/子1159148存活，
已存储3新案例/21control检查点，保留所有已创建不可变base。
运行时不读写离线账本，本进度writer等待实际idle87。固定451三阶段及内部结果均未改变。
主方法全451覆盖/Source输入审计/原生评分与评分审计/归档、Mem2Act400×2、最终全成本/论文/图表/
原763行完成审计仍未完成；原1..9物理快照缺口继续按真实证据披露，不伪造或重跑。

## v122 历史状态（2026-11-08，Asia/Shanghai）：观察回调组合已实际恢复快照与字节存储，主方法441未尝试尾部运行

无模型探针直接执行原functional的observer赋值AST、原verify_replay与原RetrievalRecorder：旧覆盖问题复现，
组合后先验证再记录，初始/逐步文件实际写出，验证失败阻止记录，作用域结束恢复类行为。未改1138旧绑定。
执行v3新增3绑定至1141；仅观察接线/精确serial2协议桥接/明确缺口的审计修订，模型、数据、Source、
checkpoint/seed、完整配置/预算、thinking、cap、评分和原451分母均未变。

已保留1..9的补审计实际通过：每条全部13837个原有Store值逐项等于恢复的完整baseline-before，
Source/角色/时钟/身份/权限/lifecycle/应用不变，只新增声明的检索/准入/exposure派生键。
68实际NN/input459461的完整状态/菜单/payload/head/有限argmax/未截断与原生计数一致，
8实际原生SDK交付上下文、8完整Reader请求及答案原文相符。第9条末READ无操作结果/无Reader保持失败。
这些9条的实际逐步物理Store/Saver字节快照仍不可用，没有伪造；审计资格明确按真实Source/Store/trace/SDK/
Reader证据列示，10..450仍要求原完整实际capture/snapshot审计。首0的严格加载失败Source核验继续保留。

idle85真实空闲一次支付9条关闭计时47.34CPU（含失败反思v1），失败存储001整CPU0.133648045另计。
旧模型426.852512653及其NN/load、归档与旧存储不再加。显式启动002仅未尝试10..450共441条，
父874577/子874598实际存活、cuda:0/GPU2 FP32/16384/2048/4线程加载通过。
当前active19、{'FAILED_RETRIEVING': 2, 'COMPLETED': 17, 'PREPARING_INPUT': 1, 'NOT_RUN': 431}；首0..9整记录保持。
第一对实际完成调用10/11已有16完整before归档/14control检查点全原字节比较及16NN完整输入核验通过，
原回放请求/额度/首观测/完整菜单相等标记保持；实际CPU跟随器父878698/子878704存活，
已处理9案例/63检查点，保留primary不可变base。
本轮首对核验及进度writer等待实际idle86，运行时不读写离线账本。原生model/HTTP/CPU/GPU区间均等实际退出。

Mem2Act只读静态路径核查：既有frozen_host_message已将policy/checkpoint合并完整memory_control，
primary进入host replay而不是retrieval replay覆盖分支，1147原绑定完整；这两处LME故障不要求修改其原接线。
没有实际400任务/模型输入证明，仍须all6LME闭合后执行原门槛。完整主方法451审计/评分/归档、
Mem2Act400×2、全项目成本/论文/图表/763行完成审计仍未完成，目标保持ACTIVE。

补充完整路径核验：冻结审计器的完整案例循环AST原文未变，仅将迭代输入限定为已关闭的真实第10条。
31,122次Source比对、8实际完整before恢复、8次NN、1原生SDK上下文及1完整Reader请求均通过。
没有重跑任务、修改Source/原绑定代码、调用模型/tokenizer/HTTP或读取账本，未生成全451启动门槛。
[单案例路径紧凑结果](../data/manifests/a100-primary-case10-full-source-path-20261108-v1.json)记录明确范围；
全451Source/评分/归档及完整计划仍待验证，核验与出版CPU等待实际idle86。

## v121 历史状态（2026-11-08，Asia/Shanghai）：主方法实际68次NN通过输入核验，快照观察缺口保留并停止扩展

执行v2已冻结1138字节相同比对绑定，原1135未改；完整配置修正、严格v1→v2未尝试尾部桥接、
首失败0的3458完整Source/baseline-before/应用/trace审计均已通过。idle84在实际无worker窗口
一次支付7条关闭计时13.29CPU，另支付原零案例存储0.064661018CPU，旧模型/归档未重计。

显式continuation001实际载入cuda:0/GPU2、FP32、16384/2048、4线程、MHAFalse/refcompileFalse；
1..8条首次完成。完整68次实际NN/input459461与原生计数逐项相符，完整before/菜单/payload/
head ID顺序、有限logits与概率/argmax/无截断核验通过。8实际ReaderHTTP/35372known tokens、
0Judge、newunknown0/0；不由此宣称正确答案或超过8192的有效语义能力。

CPU跟随器对缺少control快照正确退出1，发现functional.message先安装RetrievalRecorder后以
verify_replay覆盖observer；原回放验证仍执行，但1..9的实际capture/逐步快照未生成。
这不是可重跑首结果的理由。为了停止扩大缺口，在第9条检索且Reader未开始时显式SIGINT；
父673576/子673577实际退出-2/消失/原生CPU关闭，8COMP/2FAILED_RETRIEVING/441NOT_RUN。
首0保持原加载失败，首1..8完整结果及中断9保持原样；68个NN全部已有完整trace，无缺失forward。
子426.59694＋父0.255572653CPU已付，包含NN74.80637742194813与load7.513192891000017，不能重复加。
存储父676747/子676748退出1/消失/处理0条，整CPU0.13364804499999998等待实际idle85。

反思工具v1因中断9缺少成功路径query字段退出1，发生在账本访问前；其原计时保留。
v2改为直接逐完整dict比较真实trace首before/actions与基线call，已通过，没有新模型或HTTP。
ROOT/reflect-primary001-observer-overwrite-v2.json保留首10整记录、68输入核验及全部费用边界。
不能把未存在的实际逐步物理快照补成“已捕获”。Source/SDK/Reader全量追溯仍需补齐，并明确
这些9条的逐步原始Store/Saver字节快照证明不可用；其余441应在观察回调组合修正后按原完整协议捕获。
下一步ROOT/primary-observation-execution-v3-next-actions.json：保持1138旧绑定，冻结观察修订/
真实回调安装无模型探针与完整审计补充，idle85计量后只执行未尝试10..450，不重跑0..9。
当前无实际worker、无真实阻塞。主方法全451、Mem2Act400×2及最终全成本/论文/图表/763完成审计仍未完成。

## v120 历史状态（2026-11-08，Asia/Shanghai）：固定451三阶段关闭，主方法首条接线失败保留，配置探针通过

固定归档实际退出0/父子进程消失/451全部ARCHIVED，冻结finalizer及关闭核验通过。
案例逻辑原字节138,163,243,297，归档4,359,462,529字节，完整模板及两pool不可变base另行保留。
所有451首结果整dict仍等于51段最早祖先；原生指标/50Reader失败、451存储收据/2706控制检查点及
1135旧代码绑定保持。归档完整子1965.312778＋父0.192329002CPU已原生支付一次，嵌套index CPU不再加。
idle83在真实无模型窗口支付9条新增关闭计时6.91CPU，并核对53个native owner原账本记录。

主方法通过冻结check-only并显式启动后，首row0/01307e07在构造校验失败：原适配器只传policy/checkpoint，
而functional.message将override当完整memory_policy配置，导致cpu/8192/默认full投影，偏离声明的
cuda:0/16384/shared_actions。首观测与完整菜单仍逐dict相同，零实际NN/Reader/Judge/HTTP，
row0保留FAILED_RETRIEVING/unscored，450条仍NOT_RUN；父571114/子571116实际退出1/消失，
完整子28.212299＋父0.144564571CPU已付，其中7.042261228999905 load CPU已包含，不重复相加。
原生result中的generation_calls1为本地控制准入，不是HTTP；owner实际shared admission0。
CPU存储父573235/子573238退出0/消失/处理0案例，整CPU0.064661018等待实际idle84。

[修订适配器源码](../tools/run_a100_lme_with_actual_policy_capture_v2.py)仅改为传入原先冻结的完整memory_control，
没有编辑原1135绑定文件。实际memory_policy工厂的配置探针复现旧默认值并验证完整配置构造参数，
不加载模型/forward/tokenizer/HTTP/业务或账本写入；这不冒充修正后实际NN已运行。
下一步需冻结明确execution-v2协议/owner桥接及完整Source审计补充：保留row0捕获前失败的真实缺项，
不能伪造call.json/输入/评分；其余450按原完整审计。实际idle84成本关闭后只续行原生未尝试1..450，
不重跑row0。具体入口ROOT/primary-execution-wiring-v2-next-actions.json。当前无实际实验worker，无真实阻塞。
主方法全451、Mem2Act400×2、最终全成本/论文/图表/原763行完成审计仍未完成。

## v119 历史状态（2026-11-08，Asia/Shanghai）：固定451原生操作/用量成本报告关闭，CPU归档运行

[固定前缀结果报告](MILAI_A100_LME_FIXED_NATIVE_RESULTS_20261108.md)与紧凑manifest/分析代码已形成，
研究草案已纳入401已评分中75正确、50Reader失败未评分、250有效UNKNOWN及全451缺失边界。
全451Reader/130Judge原始usage独立复算、52个关闭owner完整CPU核对和报告链接检查通过，
没有新模型/HTTP、Source/首结果改写或账本读取/写入。

实际Reader451HTTP/2,866,515known tokens，Judge130HTTP/174,230known tokens；50Reader失败的
657,582tokens属于Reader子集。51段预测完整子CPU＋已测父CPU38,088.242489秒，评分35.873309秒，
都已原生支付一次。完整CPU包含复制/捕获等，不是纯推理；本地NN/加载0，HostGPU时间未知。
902SEARCH/1804READ/451HANDOFF、3157决策/2706操作返回逐完整绑定核对；嵌套计时不重复叠加。

仅CPU原生归档父424962/子424964实际存活，索引{'ARCHIVED': 243, 'ARCHIVING': 1, 'PENDING': 207}；没有模型/HTTPworker。
保持两pool不可变base；归档退出/全451索引/完整CPU关闭后finalize，再显式启动预选主seed0-u32。
post82已关闭分析/文档计时等待实际idle83，归档运行时不动账本以免污染其compute-delta归属。
主方法451全预测/Source与评分审计/归档、Mem2Act400×2、最终全成本/论文/图表/763行完成审计仍未完成。

## v118 历史状态（2026-11-08，Asia/Shanghai）：固定前缀全451评分审计关闭，CPU归档运行

原生评分实际退出0/父子进程消失/原生完整CPU已计量，401项COMPLETED、50项UNSCORED_FAILED_READING。
无Judge失败，Reader未重新生成。130实际JudgeHTTP/174230known tokens，子35.715858＋父0.157451301CPU
已原生一次计量，新unknown0/0。冻结全451评分审计实际退出0，401原生分数、130完整Judge请求、
Reader原文、原生规则/汇总及缺失分母逐项核对通过，没有新模型/tokenizer/HTTP调用；评分别名已finalize。

401已评分项中原生规则判定正确75项，有效模型UNKNOWN回答250项。条件子集原生overall=75/401
（18.7032%）；50Reader失败未变成UNKNOWN或负gold，全451缺失边界为[75/451,125/451]
（16.6297%至27.7162%），native_complete_cohort_metrics仍None，不能当作完整组精确分数。
这是本地声明Reader/Judge下的benchmark原生口径，不是自主Host或原论文模型复现，也不是独立用户证据。

评分审计/finalizer/核验/v117进度4条关闭计时5.17CPU秒在真实idle82一次支付。
冻结CPU归档已显式启动，父424962/子424964实际存活，索引{'ARCHIVED': 42, 'ARCHIVING': 1, 'PENDING': 408}。
保留完整模板及固定偏移字节块，原始预测/评分首结果保持；两pool不可变controlbase仍在案例树外。
归档全451与完整成本关闭后才finalize并进入主方法451相同流程；Mem2Act400×2、最终全成本/
论文/整体图表及763行完成审计仍未完成。

## v117 历史状态（2026-11-08，Asia/Shanghai）：全451机械审计通过，原生评分运行

冻结审计已实际退出0/进程消失：451问题ID及原生状态逐项相同，9,364,144次Source比对、3157完整
归档快照、451原生SDK上下文、451完整Reader请求核对通过；固定前缀NN0/输入token0，未产生新模型、
tokenizer或HTTP调用。这个门槛证明Source/状态/输入与原生路径一致，不证明回答真值或语义评分。
401COMPLETED/50FAILED_READING及49空正文/1截断正文保持；全451整记录均等于最早祖先首结果。
冻结finalizer已建立预测别名，未重写失败状态或选择更好结果。审计完整CPU3827.69秒/墙钟5111.32秒，
连同finalizer、核验与上一进度共4条关闭计时3827.9900000000002CPU秒在真实idle81一次结算。
既有模型/存储/祖先费用不重计，作者未计量部分仍为unknown_not_zero。

固定前缀原生评分已显式启动：父341568/子341673实际存活，active133、{'COMPLETED': 128, 'UNSCORED_FAILED_READING': 50, 'UNSCORED_COMPLETED': 273}。
不重新生成Reader，50项失败原样保留UNSCORED_FAILED_READING/scoreNone；全451分母与缺失边界保持。
评分未全闭合，暂不声明最终分数。完整评分审计/finalize/archive之后才进入主方法451相同流程；
Mem2Act400×2、最终全成本/论文/整体图表及763行完成审计仍未完成。

## v116 历史状态（2026-11-08，Asia/Shanghai）：固定前缀全451首结果关闭，CPU机械审计运行

050实际退出0、原生CPU已计量、父子进程消失，原生完整覆盖门槛通过。全451项为401COMPLETED/
50FAILED_READING；50项失败保留49空正文及1截断正文，不是UNKNOWN或负gold。最后438..450共13项
均首次完成，13HTTP/78151known tokens；子704.727325＋父0.206916022CPU已原生支付。
完整451整dict逐项等于51个祖先集合中的最早尝试；问题ID顺序一致，1135代码绑定整字节相同。
451案例/2706控制检查点保留完整字节，两pool不可变base仍在案例树外。

存储050整CPU65.305282144及3条关闭计时5.67CPU秒已在真实idle80一次支付。
结算工具首次路径类型错误在账本访问前退出，仅改Path转换；未改模型结果或冻结配方，未计量作者CPU为unknown_not_zero。
冻结全451机械审计已显式启动：GNU time父4318/CPU审计子4319真实存活。
其计时文件尚未关闭，审计门槛尚未生成，不能提前声明Source/输入审计或语义评分完成。
审计通过后才finalize预测别名并执行原生评分/评分审计/归档；当前无实验模型/HTTPworker。
完整主方法451、Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v115 历史状态（2026-11-08，Asia/Shanghai）：049关闭，050续行未尝试尾部

049实际退出1/原生已计量/父子进程消失，首438=388COMP/50ReaderF。
437/f43926d9单次输出8192到顶、正文为空，prompt5887/总14079/reserved14591<65536，无输入溢出/新增未知。
本段2HTTP/24140known tokens，子126.288211＋父0.296587244CPU已原生计量。
存储2案例整CPU11.782763016与4个实际关闭计时0.33000000000000007CPU秒在真实idle79一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 49, 'present_truncated_final': 1}。

显式启动050仅未尝试438至450共13项，父4097652/子4097729实际存活，active438、{'COMPLETED': 388, 'FAILED_READING': 50, 'PREPARING_INPUT': 1, 'NOT_RUN': 12}；首438整dict相同。
CPU存储只跟随050，累计438案例/2628检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v114 历史状态（2026-11-08，Asia/Shanghai）：048关闭，049续行未尝试尾部

048实际退出1/原生已计量/父子进程消失，首436=387COMP/49ReaderF。
435/f23807ed单次输出8192到顶、正文为空，prompt5951/总14143/reserved14655<65536，无输入溢出/新增未知。
本段2HTTP/21749known tokens，子148.094167＋父0.147586615CPU已原生计量。
存储2案例整CPU11.488903880999999与4个实际关闭计时0.31CPU秒在真实idle78一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 48, 'present_truncated_final': 1}。

显式启动049仅未尝试436至450共15项，父4072345/子4072385实际存活，active436、{'COMPLETED': 387, 'FAILED_READING': 49, 'PREPARING_INPUT': 1, 'NOT_RUN': 14}；首436整dict相同。
CPU存储只跟随049，累计436案例/2616检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v113 历史状态（2026-11-08，Asia/Shanghai）：047关闭，048续行未尝试尾部

047实际退出1/原生已计量/父子进程消失，首434=386COMP/48ReaderF。
433/f078f429单次输出8192到顶、正文为空，prompt3066/总11258/reserved11770<65536，无输入溢出/新增未知。
本段1HTTP/11258known tokens，子73.05035＋父0.14683057CPU已原生计量。
存储1案例整CPU6.442931458与4个实际关闭计时0.3CPU秒在真实idle77一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 47, 'present_truncated_final': 1}。

显式启动048仅未尝试434至450共17项，父4048890/子4048981实际存活，active434、{'COMPLETED': 386, 'FAILED_READING': 48, 'PREPARING_INPUT': 1, 'NOT_RUN': 16}；首434整dict相同。
CPU存储只跟随048，累计434案例/2604检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v112 历史状态（2026-11-08，Asia/Shanghai）：046关闭，047续行未尝试尾部

046实际退出1/原生已计量/父子进程消失，首433=386COMP/47ReaderF。
432/eff00409单次输出8192到顶、正文为空，prompt4875/总13067/reserved13579<65536，无输入溢出/新增未知。
本段3HTTP/26725known tokens，子189.78718800000001＋父0.188317397CPU已原生计量。
存储3案例整CPU17.00234493与4个实际关闭计时0.3CPU秒在真实idle76一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 46, 'present_truncated_final': 1}。

显式启动047仅未尝试433至450共18项，父4027443/子4027444实际存活，active433、{'COMPLETED': 386, 'FAILED_READING': 47, 'PREPARING_INPUT': 1, 'NOT_RUN': 17}；首433整dict相同。
CPU存储只跟随047，累计433案例/2598检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v111 历史状态（2026-11-08，Asia/Shanghai）：045关闭，046续行未尝试尾部

045实际退出1/原生已计量/父子进程消失，首430=384COMP/46ReaderF。
429/ee75b921单次输出8192到顶、正文为空，prompt4883/总13075/reserved13587<65536，无输入溢出/新增未知。
本段12HTTP/88936known tokens，子719.259853＋父0.158619168CPU已原生计量。
存储12案例整CPU62.844269586与4个实际关闭计时0.31CPU秒在真实idle75一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 45, 'present_truncated_final': 1}。

显式启动046仅未尝试430至450共21项，父3994707/子3994708实际存活，active430、{'COMPLETED': 384, 'FAILED_READING': 46, 'PREPARING_INPUT': 1, 'NOT_RUN': 20}；首430整dict相同。
CPU存储只跟随046，累计430案例/2580检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v110 历史状态（2026-11-08，Asia/Shanghai）：044关闭，045续行未尝试尾部

044实际退出1/原生已计量/父子进程消失，首418=373COMP/45ReaderF。
417/e77d1287单次输出8192到顶、正文为空，prompt2934/总11126/reserved11638<65536，无输入溢出/新增未知。
本段7HTTP/50810known tokens，子394.90153799999996＋父0.192079163CPU已原生计量。
存储7案例整CPU36.824453240000004与5个实际关闭计时0.38CPU秒在真实idle74一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 44, 'present_truncated_final': 1}。

显式启动045仅未尝试418至450共33项，父3914671/子3914672实际存活，active418、{'COMPLETED': 373, 'FAILED_READING': 45, 'PREPARING_INPUT': 1, 'NOT_RUN': 32}；首418整dict相同。
CPU存储只跟随045，累计418案例/2508检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v109 历史状态（2026-11-08，Asia/Shanghai）：043关闭，044续行未尝试尾部

043实际退出1/原生已计量/父子进程消失，首411=367COMP/44ReaderF。
410/dae9f7e9单次输出8192到顶、包含截断正文（501字符），prompt3105/总11297/reserved11809<65536，无输入溢出/新增未知。
本段1HTTP/11297known tokens，子118.244413＋父0.146243822CPU已原生计量。
存储1案例整CPU6.462519707与5个实际关闭计时0.41CPU秒在真实idle73一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。
length响应即便含部分正文仍保留原生失败；未提取片段评分。累计失败正文状态：{'absent_final': 43, 'present_truncated_final': 1}。

显式启动044仅未尝试411至450共40项，父3861230/子3861231实际存活，active411、{'COMPLETED': 367, 'FAILED_READING': 44, 'PREPARING_INPUT': 1, 'NOT_RUN': 39}；首411整dict相同。
CPU存储只跟随044，累计411案例/2466检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v108 历史状态（2026-11-08，Asia/Shanghai）：042关闭，043续行未尝试尾部

042实际退出1/原生已计量/父子进程消失，首410=367COMP/43ReaderF。
409/d886b018单次输出8192到顶、正文为空，prompt4053/总12245/reserved12757<65536，无输入溢出/新增未知。
本段5HTTP/28286known tokens，子306.908389＋父0.151728595CPU已原生计量。
存储5案例整CPU27.662033040999997与4个实际关闭计时0.32CPU秒在真实idle72一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动043仅未尝试410至450共41项，父3792792/子3792836实际存活，active410、{'COMPLETED': 367, 'FAILED_READING': 43, 'PREPARING_INPUT': 1, 'NOT_RUN': 40}；首410整dict相同。
CPU存储只跟随043，累计410案例/2460检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v107 历史状态（2026-11-08，Asia/Shanghai）：041关闭，042续行未尝试尾部

041实际退出1/原生已计量/父子进程消失，首405=363COMP/42ReaderF。
404/d3300354单次输出8192到顶、正文为空，prompt3951/总12143/reserved12655<65536，无输入溢出/新增未知。
本段8HTTP/59991known tokens，子451.57463500000006＋父0.143346303CPU已原生计量。
存储8案例整CPU42.24621410899999与4个实际关闭计时0.31CPU秒在真实idle71一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动042仅未尝试405至450共46项，父3755037/子3755038实际存活，active405、{'COMPLETED': 363, 'FAILED_READING': 42, 'PREPARING_INPUT': 1, 'NOT_RUN': 45}；首405整dict相同。
CPU存储只跟随042，累计405案例/2430检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v106 历史状态（2026-11-08，Asia/Shanghai）：040关闭，041续行未尝试尾部

040实际退出1/原生已计量/父子进程消失，首397=356COMP/41ReaderF。
396/c6124506单次输出8192到顶、正文为空，prompt2964/总11156/reserved11668<65536，无输入溢出/新增未知。
本段1HTTP/11156known tokens，子77.932863＋父0.144407334CPU已原生计量。
存储1案例整CPU6.454063151000001与4个实际关闭计时0.26CPU秒在真实idle70一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动041仅未尝试397至450共54项，父3702811/子3702818实际存活，active397、{'COMPLETED': 356, 'FAILED_READING': 41, 'PREPARING_INPUT': 1, 'NOT_RUN': 53}；首397整dict相同。
CPU存储只跟随041，累计397案例/2382检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v105 历史状态（2026-11-08，Asia/Shanghai）：039关闭，040续行未尝试尾部

039实际退出1/原生已计量/父子进程消失，首396=356COMP/40ReaderF。
395/c5dfa558单次输出8192到顶、正文为空，prompt4055/总12247/reserved12759<65536，无输入溢出/新增未知。
本段15HTTP/116280known tokens，子851.4833629999999＋父0.172464369CPU已原生计量。
存储15案例整CPU75.15284198500001与4个实际关闭计时0.27CPU秒在真实idle69一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动040仅未尝试396至450共55项，父3683794/子3683796实际存活，active396、{'COMPLETED': 356, 'FAILED_READING': 40, 'PREPARING_INPUT': 1, 'NOT_RUN': 54}；首396整dict相同。
CPU存储只跟随040，累计396案例/2376检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v104 历史状态（2026-11-08，Asia/Shanghai）：038关闭，039续行未尝试尾部

038实际退出1/原生已计量/父子进程消失，首381=342COMP/39ReaderF。
380/b05cf470单次输出8192到顶、正文为空，prompt4880/总13072/reserved13584<65536，无输入溢出/新增未知。
本段8HTTP/58522known tokens，子455.286456＋父0.155423704CPU已原生计量。
存储8案例整CPU42.581879702与4个实际关闭计时0.26CPU秒在真实idle68一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动039仅未尝试381至450共70项，父3592982/子3593034实际存活，active381、{'COMPLETED': 342, 'FAILED_READING': 39, 'PREPARING_INPUT': 1, 'NOT_RUN': 69}；首381整dict相同。
CPU存储只跟随039，累计381案例/2286检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v103 历史状态（2026-11-08，Asia/Shanghai）：037关闭，038续行未尝试尾部

037实际退出1/原生已计量/父子进程消失，首373=335COMP/38ReaderF。
372/a363341d单次输出8192到顶、正文为空，prompt4059/总12251/reserved12763<65536，无输入溢出/新增未知。
本段1HTTP/12251known tokens，子74.179898＋父0.145920819CPU已原生计量。
存储1案例整CPU6.78134198与4个实际关闭计时0.38CPU秒在真实idle67一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动038仅未尝试373至450共78项，父3544934/子3544936实际存活，active373、{'COMPLETED': 335, 'FAILED_READING': 38, 'PREPARING_INPUT': 1, 'NOT_RUN': 77}；首373整dict相同。
CPU存储只跟随038，累计373案例/2238检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v102 历史状态（2026-11-08，Asia/Shanghai）：036关闭，037续行未尝试尾部

036实际退出1/原生已计量/父子进程消失，首372=335COMP/37ReaderF。
371/a2a71197单次输出8192到顶、正文为空，prompt4055/总12247/reserved12759<65536，无输入溢出/新增未知。
本段5HTTP/34950known tokens，子278.98804＋父0.17637459CPU已原生计量。
存储5案例整CPU28.000474903与4个实际关闭计时0.26CPU秒在真实idle66一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动037仅未尝试372至450共79项，父3527645/子3527651实际存活，active372、{'COMPLETED': 335, 'FAILED_READING': 37, 'PREPARING_INPUT': 1, 'NOT_RUN': 78}；首372整dict相同。
CPU存储只跟随037，累计372案例/2232检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v101 历史状态（2026-11-08，Asia/Shanghai）：035关闭，036续行未尝试尾部

035实际退出1/原生已计量/父子进程消失，首367=331COMP/36ReaderF。
366/99fa7c96单次输出8192到顶、正文为空，prompt5958/总14150/reserved14662<65536，无输入溢出/新增未知。
本段1HTTP/14150known tokens，子95.01962900000001＋父0.144914314CPU已原生计量。
存储1案例整CPU6.586127608与4个实际关闭计时0.26CPU秒在真实idle65一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动036仅未尝试367至450共84项，父3492661/子3492663实际存活，active367、{'COMPLETED': 331, 'FAILED_READING': 36, 'PREPARING_INPUT': 1, 'NOT_RUN': 83}；首367整dict相同。
CPU存储只跟随036，累计367案例/2202检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v100 历史状态（2026-11-08，Asia/Shanghai）：034关闭，035续行未尝试尾部

034实际退出1/原生已计量/父子进程消失，首366=331COMP/35ReaderF。
365/99b6e22f单次输出8192到顶、正文为空，prompt5916/总14108/reserved14620<65536，无输入溢出/新增未知。
本段9HTTP/55303known tokens，子492.109741＋父0.163629828CPU已原生计量。
存储9案例整CPU45.365677603与4个实际关闭计时0.30000000000000004CPU秒在真实idle64一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动035仅未尝试366至450共85项，父3474422/子3474450实际存活，active366、{'COMPLETED': 331, 'FAILED_READING': 35, 'PREPARING_INPUT': 1, 'NOT_RUN': 84}；首366整dict相同。
CPU存储只跟随035，累计366案例/2196检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v99 历史状态（2026-11-08，Asia/Shanghai）：033关闭，034续行未尝试尾部

033实际退出1/原生已计量/父子进程消失，首357=323COMP/34ReaderF。
356/91d0775e单次输出8192到顶、正文为空，prompt3102/总11294/reserved11806<65536，无输入溢出/新增未知。
本段1HTTP/11294known tokens，子142.473095＋父0.16491117CPU已原生计量。
存储1案例整CPU6.177318318与4个实际关闭计时0.27CPU秒在真实idle63一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动034仅未尝试357至450共94项，父3424048/子3424087实际存活，active357、{'COMPLETED': 323, 'FAILED_READING': 34, 'PREPARING_INPUT': 1, 'NOT_RUN': 93}；首357整dict相同。
CPU存储只跟随034，累计357案例/2142检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v98 历史状态（2026-11-08，Asia/Shanghai）：032关闭，033续行未尝试尾部

032实际退出1/原生已计量/父子进程消失，首356=323COMP/33ReaderF。
355/914ab1d4单次输出8192到顶、正文为空，prompt6836/总15028/reserved15540<65536，无输入溢出/新增未知。
本段4HTTP/29807known tokens，子256.267617＋父0.141085007CPU已原生计量。
存储4案例整CPU20.856521255与4个实际关闭计时0.25CPU秒在真实idle62一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动033仅未尝试356至450共95项，父3403426/子3403428实际存活，active356、{'COMPLETED': 323, 'FAILED_READING': 33, 'PREPARING_INPUT': 1, 'NOT_RUN': 94}；首356整dict相同。
CPU存储只跟随033，累计356案例/2136检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v97 历史状态（2026-11-08，Asia/Shanghai）：031关闭，032续行未尝试尾部

031实际退出1/原生已计量/父子进程消失，首352=320COMP/32ReaderF。
351/8da5c407单次输出8192到顶、正文为空，prompt5889/总14081/reserved14593<65536，无输入溢出/新增未知。
本段4HTTP/25847known tokens，子253.567257＋父0.136523741CPU已原生计量。
存储4案例整CPU21.536028843999997与6个实际关闭计时0.41000000000000003CPU秒在真实idle61一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动032仅未尝试352至450共99项，父3372988/子3372989实际存活，active352、{'COMPLETED': 320, 'FAILED_READING': 32, 'PREPARING_INPUT': 1, 'NOT_RUN': 98}；首352整dict相同。
CPU存储只跟随032，累计352案例/2112检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v96 历史状态（2026-11-08，Asia/Shanghai）：030关闭，031续行未尝试尾部

030实际退出1/原生已计量/父子进程消失，首348=317COMP/31ReaderF。
347/89a20f48单次输出8192到顶、正文为空，prompt4918/总13110/reserved13622<65536，无输入溢出/新增未知。
本段2HTTP/20510known tokens，子145.766388＋父0.168883782CPU已原生计量。
存储2案例整CPU13.800693170999999与5个实际关闭计时0.46CPU秒在真实idle60一次支付，native/旧费用不重计。
首失败保持，未改cap、thinking、模型或完整输入。全部数值从原生记录与回执读取。

显式启动031仅未尝试348至450共103项，父3342656/子3342657实际存活，active348、{'COMPLETED': 317, 'FAILED_READING': 31, 'PREPARING_INPUT': 1, 'NOT_RUN': 102}；首348整dict相同。
CPU存储只跟随031，累计348案例/2088检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v95 历史状态（2026-11-08，Asia/Shanghai）：029关闭，030续行未尝试尾部

029实际退出1/原生已计量/父子进程消失，首346=316COMP/30ReaderF。345/8957a127单次
输出8192到顶、正文为空，prompt4893/总13085/reserved13597<65536，无输入溢出/新增未知。
6HTTP55178known tokens，子349.057788＋父0.167414807CPU已原生计量；存储6案例整CPU
31.921026096与4个实际关闭计时0.27CPU秒在真实idle59一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动030仅未尝试346至450共105项，父3314136/子3314156实际存活，
active346、{'COMPLETED': 316, 'FAILED_READING': 30, 'PREPARING_INPUT': 1, 'NOT_RUN': 104}；首346整dict相同。CPU存储只跟随030，累计346案例/
2076检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v94 历史状态（2026-11-08，Asia/Shanghai）：028关闭，029续行未尝试尾部

028实际退出1/原生已计量/父子进程消失，首340=311COMP/29ReaderF。339/83a77f9d单次
输出8192到顶、正文为空，prompt4883/总13075/reserved13587<65536，无输入溢出/新增未知。
13HTTP106042known tokens，子792.622476＋父0.160753063CPU已原生计量；存储13案例整CPU
66.52775610200001与4个实际关闭计时0.28CPU秒在真实idle58一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动029仅未尝试340至450共111项，父3251470/子3251471实际存活，
active340、{'COMPLETED': 311, 'FAILED_READING': 29, 'PREPARING_INPUT': 1, 'NOT_RUN': 110}；首340整dict相同。CPU存储只跟随029，累计340案例/
2040检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v93 历史状态（2026-11-08，Asia/Shanghai）：027关闭，028续行未尝试尾部

027实际退出1/原生已计量/父子进程消失，首327=299COMP/28ReaderF。326/7195f494单次
输出8192到顶、正文为空，prompt4900/总13092/reserved13604<65536，无输入溢出/新增未知。
23HTTP151369known tokens，子1301.770189＋父0.154831311CPU已原生计量；存储23案例整CPU
120.01770023799999与4个实际关闭计时0.27CPU秒在真实idle57一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动028仅未尝试327至450共124项，父3172044/子3172045实际存活，
active327、{'COMPLETED': 299, 'FAILED_READING': 28, 'PREPARING_INPUT': 1, 'NOT_RUN': 123}；首327整dict相同。CPU存储只跟随028，累计327案例/
1962检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v92 历史状态（2026-11-08，Asia/Shanghai）：026关闭，027续行未尝试尾部

026实际退出1/原生已计量/父子进程消失，首304=277COMP/27ReaderF。303/609acb91单次
输出8192到顶、正文为空，prompt4892/总13084/reserved13596<65536，无输入溢出/新增未知。
1HTTP13084known tokens，子86.80480700000001＋父0.153200981CPU已原生计量；存储1案例整CPU
6.7550797110000005与4个实际关闭计时0.26CPU秒在真实idle56一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动027仅未尝试304至450共147项，父3050522/子3050523实际存活，
active305、{'COMPLETED': 278, 'FAILED_READING': 27, 'PREPARING_INPUT': 1, 'NOT_RUN': 145}；首304整dict相同。CPU存储只跟随027，累计305案例/
1830检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v91 历史状态（2026-11-08，Asia/Shanghai）：025关闭，026续行未尝试尾部

025实际退出1/原生已计量/父子进程消失，首303=277COMP/26ReaderF。302/5db4899c单次
输出8192到顶、正文为空，prompt5896/总14088/reserved14600<65536，无输入溢出/新增未知。
5HTTP28692known tokens，子287.208963＋父0.138925119CPU已原生计量；存储5案例整CPU
26.764608687与4个实际关闭计时0.27CPU秒在真实idle55一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动026仅未尝试303至450共148项，父3030367/子3030368实际存活，
active303、{'COMPLETED': 277, 'FAILED_READING': 26, 'READING': 1, 'NOT_RUN': 147}；首303整dict相同。CPU存储只跟随026，累计303案例/
1818检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v90 历史状态（2026-11-08，Asia/Shanghai）：024关闭，025续行未尝试尾部

024实际退出1/原生已计量/父子进程消失，首298=273COMP/25ReaderF。297/5a85ca0f单次
输出8192到顶、正文为空，prompt6100/总14292/reserved14804<65536，无输入溢出/新增未知。
8HTTP70899known tokens，子455.937808＋父0.158311469CPU已原生计量；存储8案例整CPU
40.406119905000004与4个实际关闭计时0.25CPU秒在真实idle54一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动025仅未尝试298至450共153项，父2994949/子2994950实际存活，
active299、{'COMPLETED': 274, 'FAILED_READING': 25, 'PREPARING_INPUT': 1, 'NOT_RUN': 151}；首298整dict相同。CPU存储只跟随025，累计298案例/
1788检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v89 历史状态（2026-11-08，Asia/Shanghai）：023关闭，024续行未尝试尾部

023实际退出1/原生已计量/父子进程消失，首290=266COMP/24ReaderF。289/51764e11单次
输出8192到顶、正文为空，prompt4868/总13060/reserved13572<65536，无输入溢出/新增未知。
18HTTP128873known tokens，子1036.191374＋父0.144365319CPU已原生计量；存储18案例整CPU
91.080253967与4个实际关闭计时0.23CPU秒在真实idle53一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动024仅未尝试290至450共161项，父2942811/子2942813实际存活，
active290、{'COMPLETED': 266, 'FAILED_READING': 24, 'READING': 1, 'NOT_RUN': 160}；首290整dict相同。CPU存储只跟随024，累计290案例/
1740检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v88 历史状态（2026-11-08，Asia/Shanghai）：022关闭，023续行未尝试尾部

022实际退出1/原生已计量/父子进程消失，首272=249COMP/23ReaderF。271/401566e6单次
输出8192到顶、正文为空，prompt5938/总14130/reserved14642<65536，无输入溢出/新增未知。
2HTTP16632known tokens，子144.339933＋父0.160454372CPU已原生计量；存储2案例整CPU
11.720660276与4个实际关闭计时0.29CPU秒在真实idle52一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动023仅未尝试272至450共179项，父2843537/子2843538实际存活，
active272、{'COMPLETED': 249, 'FAILED_READING': 23, 'READING': 1, 'NOT_RUN': 178}；首272整dict相同。CPU存储只跟随023，累计272案例/
1632检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v87 历史状态（2026-11-08，Asia/Shanghai）：021关闭，022续行未尝试尾部

021实际退出1/原生已计量/父子进程消失，首270=248COMP/22ReaderF。269/3c0c1b19单次
输出8192到顶、正文为空，prompt5947/总14139/reserved14651<65536，无输入溢出/新增未知。
4HTTP33920known tokens，子237.293114＋父0.156536366CPU已原生计量；存储4案例整CPU
21.870740091与4个实际关闭计时0.31CPU秒在真实idle51一次支付。native/旧费用不重计，
首失败保持，未改cap、thinking、模型或完整输入。

显式启动022仅未尝试270至450共181项，父2820151/子2820159实际存活，
active271、{'COMPLETED': 249, 'FAILED_READING': 22, 'PREPARING_INPUT': 1, 'NOT_RUN': 179}；首270整dict相同。CPU存储只跟随022，累计271案例/
1626检查点保留完整字节，两pool不可变base保持在案例树外。
冻结批次标识20261107保留，执行时间记录当前UTC与Asia/Shanghai。
全451预测/评分/审计未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v86 历史状态（2026-11-08，Asia/Shanghai）：019/020关闭，021续行未尝试尾部

实际执行时间按Asia/Shanghai与UTC同时记录；冻结协议、source-version及计量phase沿用原
20261107批次标识。原020运行状态草稿未执行或发布；新日期下重新核验发现该段已经终止，
本检查点汇总两段实际关闭，不补造运行状态、计时器或费用。

019实际退出1/原生已计量/进程消失，首265=245COMP/20ReaderF。264/31f146ba一次输出
8192到顶、正文为空，prompt5963/总14155/reserved14667<65536；14HTTP121426known tokens，
子800.6938250000001＋父0.162063215CPU已原生计量。存储14案例整CPU75.19489691899999与
4个关闭计时0.24CPU秒在真实idle49一次支付。

020实际退出1/原生已计量/进程消失，首266=245COMP/21ReaderF。265/3269a3c5一次输出
8192到顶、正文为空，prompt3947/总12139/reserved12651<65536；1HTTP12139known tokens，
子76.139291＋父0.143302152CPU已原生计量。存储1案例整CPU6.590526134999999与3个实际
关闭计时0.27CPU秒在真实idle50一次支付。两段均无输入溢出/新增未知，首失败全部保持，
native/旧费用不重计，未提高cap或关闭thinking。

显式启动021仅未尝试266至450共185项，父2786990/子2786997实际存活，
active267、{'COMPLETED': 246, 'FAILED_READING': 21, 'PREPARING_INPUT': 1, 'NOT_RUN': 183}；首266整dict相同。CPU存储只跟随021，累计267案例/
1602检查点保留完整字节，两pool不可变base保持在案例树外。
全451预测/评分/审计仍未关闭；内部总体图、训练工作表、1024确认及Q64指标保持。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未完成。

## v85 历史状态（2026-11-07）：018首251项关闭，019续行未尝试尾部

018实际退出1/原生已计量/父子进程消失，首251=232COMP/19ReaderF。250/238c3621
单次Reader输出8192到顶、content为空，prompt3920/总12112/reserved12624<65536，
无输入溢出/新增未知。2HTTP14873known tokens，子125.07128399999999＋父0.153897246CPU
已原生计量。存储2案例关闭，整CPU11.109936775与4个关闭计时0.25CPU秒在真实idle48
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动019仅未尝试251至450共200项，父4154870/子4154871实际存活，
active251、{'COMPLETED': 232, 'FAILED_READING': 19, 'PREPARING_INPUT': 1, 'NOT_RUN': 199}；首251整dict相同。CPU存储仅跟随019，累计251案例/
1506控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v84 历史状态（2026-11-07）：017首249项关闭，018续行未尝试尾部

017实际退出1/原生已计量/父子进程消失，首249=231COMP/18ReaderF。248/21df0107
单次Reader输出8192到顶、content为空，prompt4907/总13099/reserved13611<65536，
无输入溢出/新增未知。7HTTP67308known tokens，子431.930477＋父0.16031058CPU
已原生计量。存储7案例关闭，整CPU36.871982855999995与4个关闭计时0.24CPU秒在真实idle47
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动018仅未尝试249至450共202项，父4133743/子4133744实际存活，
active249、{'COMPLETED': 231, 'FAILED_READING': 18, 'PREPARING_INPUT': 1, 'NOT_RUN': 201}；首249整dict相同。CPU存储仅跟随018，累计249案例/
1494控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v83 历史状态（2026-11-07）：016首242项关闭，017续行未尝试尾部

016实际退出1/原生已计量/父子进程消失，首242=225COMP/17ReaderF。241/1a89c3ac
单次Reader输出8192到顶、content为空，prompt4975/总13167/reserved13679<65536，
无输入溢出/新增未知。4HTTP35523known tokens，子259.278945＋父0.153476215CPU
已原生计量。存储4案例关闭，整CPU23.369629064999998与4个关闭计时0.27CPU秒在真实idle46
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动017仅未尝试242至450共209项，父4083027/子4083028实际存活，
active242、{'COMPLETED': 225, 'FAILED_READING': 17, 'PREPARING_INPUT': 1, 'NOT_RUN': 208}；首242整dict相同。CPU存储仅跟随017，累计242案例/
1452控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v82 历史状态（2026-11-07）：015首238项关闭，016续行未尝试尾部

015实际退出1/原生已计量/父子进程消失，首238=222COMP/16ReaderF。237/17d63ad8
单次Reader输出8192到顶、content为空，prompt4866/总13058/reserved13570<65536，
无输入溢出/新增未知。1HTTP13058known tokens，子88.011709＋父0.223376255CPU
已原生计量。存储1案例关闭，整CPU6.575861649999999与4个关闭计时0.24CPU秒在真实idle45
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动016仅未尝试238至450共213项，父4048777/子4048796实际存活，
active238、{'COMPLETED': 222, 'FAILED_READING': 16, 'PREPARING_INPUT': 1, 'NOT_RUN': 212}；首238整dict相同。CPU存储仅跟随016，累计238案例/
1428控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v81 历史状态（2026-11-07）：014首237项关闭，015续行未尝试尾部

014实际退出1/原生已计量/父子进程消失，首237=222COMP/15ReaderF。236/15e5efa6
单次Reader输出8192到顶、content为空，prompt4873/总13065/reserved13577<65536，
无输入溢出/新增未知。9HTTP68545known tokens，子508.193812＋父0.173297767CPU
已原生计量。存储9案例关闭，整CPU47.125815543与4个关闭计时0.24CPU秒在真实idle44
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动015仅未尝试237至450共214项，父4030663/子4030664实际存活，
active237、{'COMPLETED': 222, 'FAILED_READING': 15, 'PREPARING_INPUT': 1, 'NOT_RUN': 213}；首237整dict相同。CPU存储仅跟随015，累计237案例/
1422控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v80 历史状态（2026-11-07）：013首228项关闭，014续行未尝试尾部

013实际退出1/原生已计量/父子进程消失，首228=214COMP/14ReaderF。227/0ace674b
单次Reader输出8192到顶、content为空，prompt5841/总14033/reserved14545<65536，
无输入溢出/新增未知。3HTTP22307known tokens，子176.583044＋父0.148766484CPU
已原生计量。存储3案例关闭，整CPU15.920724215与4个关闭计时0.22CPU秒在真实idle43
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动014仅未尝试228至450共223项，父3972968/子3973046实际存活，
active228、{'COMPLETED': 214, 'FAILED_READING': 14, 'READING': 1, 'NOT_RUN': 222}；首228整dict相同。CPU存储仅跟随014，累计228案例/
1368控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v79 历史状态（2026-11-07）：012首225项关闭，013续行未尝试尾部

012实际退出1/原生已计量/父子进程消失，首225=212COMP/13ReaderF。224/07fff330
单次Reader输出8192到顶、content为空，prompt5878/总14070/reserved14582<65536，
无输入溢出/新增未知。12HTTP85643known tokens，子713.485593＋父0.143678989CPU
已原生计量。存储12案例关闭，整CPU63.645677356与4个关闭计时0.23CPU秒在真实idle42
一次支付，native/旧费用不重计；全部首失败保持，未提高cap或关闭thinking。

显式启动013仅未尝试225至450共226项，父3945775/子3945776实际存活，
active226、{'COMPLETED': 213, 'FAILED_READING': 13, 'PREPARING_INPUT': 1, 'NOT_RUN': 224}；首225整dict相同。CPU存储仅跟随013，累计226案例/
1356控制检查点保持完整字节；两pool不可变base保留在案例树外。
全451预测/原生评分/审计未关闭；给定检索协议不冒充自主Host或未见Small确认。

内部总体图、训练计算工作表、1024确认及Q64原生指标保持。静态成本截止仍在007启动前；
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表及763行完成审计仍未完成。

## v78 历史状态（2026-11-07）：011首213项关闭，012续行未尝试尾部

011完成web首pool完整输入准备，期间实际CPU/读写持续增长，随后进入Reader，未以时长
重启或缩短Source。原生实际退出1/已计量/父子进程消失；首213=201COMP/12ReaderF。
212/01f6e679单次响应输出8192到顶、content为空，prompt5851/总14043、reserved14555<65536，
无输入溢出/新增未知。5HTTP30400known tokens，子847.1021000000001＋父0.151164293CPU
已经原生计量，首失败保持。存储5案例关闭/全字节比较，整CPU38.566542551与8个关闭计时
1.2CPU秒在真实idle41一次支付，包含发布表格校验首失败，native/旧费用不重计。

显式启动012仅原生未尝试213至450共238项，父3875079/子3875081实际存活，
active214、{'COMPLETED': 202, 'FAILED_READING': 12, 'PREPARING_INPUT': 1, 'NOT_RUN': 236}；首213整dict相同。CPU存储仅跟随012，累计213案例/
1278控制检查点保持完整字节，pool0000与新增pool0001共享base均保留在案例树外。
冻结输入/模型/thinking/预算/图像/首结果不改；全451预测/原生评分/审计仍未关闭。

内部总体图与八训练作业工作表保持；静态已付成本截止仍为007启动前。完整LME451×2/
Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计继续执行，目标未完成。

## v77 历史状态（2026-11-07）：八训练作业实测工作表，011续行

[训练计算工作表](MILAI_A100_CLOSED_TRAINING_COMPUTE_20261107.md)从原生调度/lengths逐draw
复算八个新目标训练/短测：6062更新、96968draws、108769579训练tokens，另134189058
已记录评测tokens。原生CPU41674.642654265秒、GPU作业区间9.841170150880545小时，
属于原有已付训练分项，不再次加入截止成本。A1未padding tokens比A0少184309、padding
后多1556044；B两臂同tokens不等于FLOPs。P0固定4热身/28稳态比2.344645保持；六入口
和原E3的显存/TF32/padding/阶段计时边界分列，未知不填零。没有新拟合或模型调用。

010实际退出1/原生费用关闭/父子进程消失，首208=197COMP/11ReaderF。207/fa504f5e
一次Reader输出8192到顶、正文为空，prompt4769/总12961/reserved13473<65536，新增
未知0；3HTTP18907known tokens，子341.444182＋父0.180090851CPU已计量。存储三案例
全字节关闭，整CPU22.307924042与6个关闭计时4.81CPU秒在真实idle40一次支付。
随后显式启动011，仅未尝试208至450共243项，父3799450/子3799452确认存活，
active211、{'COMPLETED': 200, 'FAILED_READING': 11, 'PREPARING_INPUT': 1, 'NOT_RUN': 239}；首208整dict相同，CPU存储只跟随011。

已完成的内部1024、Q64全12999、D综合和总体图保持；静态成本截止仍为007启动前。
完整LME451×2/Mem2Act400×2、全成本、最终论文/整体图表与763行完成审计仍未关闭。

## v76 历史状态（2026-11-07）：内部总体图发布，009关闭后010续行

[内部总体图](MILAI_A100_CLOSED_INTERNAL_OVERVIEW_20261107.md)的PNG/PDF、数值来源与绘图代码
已发布。四面板保留开发64全部七方法、确认256全部四方法、更新32×10三方法与原生条件
64三固定模型/两constant参考；C从原逐项审阅重新统计，布局修正前后数值摘要完整相同。
任务C由本次实施助手按Source审阅；原生条件指标另列，分母/暴露不合并，不作跨面板
因果检验或重选。实际检查PNG；PDF同图导出，未另行渲染复查。图表不代替全计划交付。

LME009实际退出1/原生费用关闭/进程消失，首205=195COMP/10ReaderF。204/f35bac4a
单次响应达到8192输出上限且最终content为空，prompt4751/总12943/reserved13455<65536，
无输入溢出/新增未知。28HTTP共148299known tokens、子3005.792088＋父0.172908675CPU
已计量；所有首结果保持。存储28案例关闭，整CPU189.374388963与6个关闭计时4.89CPU秒
在真实idle39一次支付，native/owner/旧费用不重计。随后显式启动010仅原生未尝试205至450
共246项，父3762632/子3762633确认存活，active206、{'COMPLETED': 196, 'FAILED_READING': 10, 'PREPARING_INPUT': 1, 'NOT_RUN': 244}。
首205整dict相同；CPU存储只跟随010。原文/完整输入/固定模型/预算/thinking/图像不变。

静态已付成本截止仍为LME007启动前，不冒充当前全项目总成本。完整LME451×2/
Mem2Act400×2、全成本、最终论文/图表及763行完成审计继续执行，目标未完成。

## v75 历史状态（2026-11-07）：LME008首177项关闭，009续行未尝试尾部

008实际退出1/原生计量/父子进程消失，首177=168COMP/9ReaderF。176单次响应达到
8192输出上限且content为空，prompt6748、总14940，无输入溢出/新增未知；失败首结果
保持。存储008三案例关闭并全字节核对，整CPU21.984731559秒和六个post37计时
0.24CPU秒在真实idle38一次支付，旧native/owner费用不重计。随后显式启动009，
仅原生未尝试177至450共274项，父3528533/子3528534确认存活，
active178、{'COMPLETED': 169, 'FAILED_READING': 9, 'PREPARING_INPUT': 1, 'NOT_RUN': 272}；首177完整dict相同。CPU存储只跟随009，累计
178案例/1068检查点逐字节一致。全451预测关闭后才能进入原生Judge/评分，
不能以局部结果或FAILED状态改写成功；实际失败保持未评分并保留全451界限。

已发布的静态成本截止仍是LME007启动前，不混入后来费用。内部1024确认、旧64
全12999评测及Source/View控制综合保持关闭；完整LME451×2/Mem2Act400×2、最终全
成本、论文/图表与完成审计继续执行，目标未完成。

## v74 历史状态（2026-11-07）：静态已付成本精确核对，LME008运行

[已付可观测成本截止报告](MILAI_A100_KNOWN_COST_CUTOFF_20261107.md)以LME007启动前
静态副本为终点，123具名phase＋20实际native归属边的10313.136976秒通用增量完全
相等；排除旧v79债务后新目标已付CPU87091.840961秒。Host known差25368797tokens，
reserve计数差5767不冒充成功HTTP数；旧未知与embedding状态保持。完整child/native
不重复相加，尚运行/后续/未测费用不算零。源码实际复现除时间戳外逐字段相同，无
live账本读写、新charge或SHA；这仍不是完整项目最终总成本。

LME007实际退出1/原生计量/进程消失，首174为166COMP/8ReaderF。173单次响应输出
8192到顶、content为空，prompt4863、无输入溢出/新增未知；所有首失败保留。存储
九案例关闭、整CPU62.620116737秒和22个post36计时2.98CPU秒在真实idle37一次支付。
随后显式启动008，仅原生未尝试174至450共277项，父3487195/子3487220确认
存活，active174、{'COMPLETED': 166, 'FAILED_READING': 8, 'PREPARING_INPUT': 1, 'NOT_RUN': 276}；首174整dict相同。CPU存储仅跟随008，
累计174案例/1044检查点逐字节一致。Q64全12999指标/审计闭合保持；完整
外部两方法、全项目最终成本与论文/图表/完成审计等尚未完成，目标继续执行。

## v73 历史状态（2026-11-07）：旧64三模型全指标闭合，LME007恢复

[旧64原生条件结果](MILAI_A100_RESERVED64_NATIVE_RESULTS_20261107.md)已完成3×4333首输出、
完整输入/head/有限argmax/无截断全量审计、原生评分与逐格独立复算。balanced族宏
初始66.51%、A0 85.31%、A1 79.94%；预定A1−A0差−5.37pp，95%区间[−7.76，−3.16]，
提高14族/降低45/相同5。全部4066known/267unknown掩码不改，无judged change所以
变化准确率不可用。两者均优于初始，不支持覆盖组成优于legacy，不触发新拟合。
三模型实际退出0、整CPU共1626.91118004秒一次付费/进程消失，3156354实际tokens；
每格token序列相同。PNG/PDF、机器汇总及所有文档路径和图像检查通过。

idle36一次支付6个关闭离线计时8.51CPU秒后，显式恢复LME007仅原生未尝试尾部，
父3389690/子3389708存活，active167、{'COMPLETED': 160, 'FAILED_READING': 7, 'PREPARING_INPUT': 1, 'NOT_RUN': 283}；
首165完整dict与006相同，旧七个Reader首失败保持。存储007仅跟随该段，累计
167案例/1002检查点逐字节一致。活动模型期间不离线读写账本。
旧64是共享语料次级条件指标，不是HostC或独立Source泛化；原生TEST语义未打开。
完整LME451×2/Mem2Act400×2、全项目成本与最终论文/图表/完成审计等仍执行，目标未完成。

## v72 历史状态（2026-11-07）：旧64初始与A0全审计关闭，A1实际运行

初始/A0各4333原生完成、完整输入/head/有限logits/argmax无截断全审计通过，真实
退出0/CPU付费/进程消失。两者逐格input_tokens相同、各1052118tokens；A0完整
child＋parent为543.30228464CPU秒，未重复计量。idle35一次支付5个关闭计时4.69秒后，
显式启动唯一A1父3341898/子3341903，{'COMPLETED': 2226, 'RETURNED_PENDING_VALIDATION': 1, 'NOT_RUN': 2106}，条件VERIFIED。
效果统计仍待A1真实关闭与审计之后，三模型统一离线评分；LME007尚未启动。

[已知View与旧输出控制综合](MILAI_A100_D_KNOWN_VIEW_OLD_OUTPUT_CONTROLS_20261107.md)
保留9＋42首格、预检失败、Host随机生成未匹配、旧输出父监测缺失及199.51CPU已知
下界，不臆造退出码/零清理开销，不把小TRAIN诊断外推一般性因果结论。新32的960项
Source/View/操作综合保持v71，无新调用或改标签。LME007及仅跟随该段存储计划准备
未启动；完整外部、旧64剩余实际评测与全项目交付仍继续，目标尚未完成。

## v71 历史状态（2026-11-07）：旧64初始模型全4333审计通过，A0实际运行

初始模型4333格全部原生完成、实际退出0/整段CPU547.671640077秒一次支付、父子
进程消失；完整4333输入、head、有限logits/argmax/无截断审计通过。真实idle34支付
10个关闭离线计时3.89CPU秒后，显式启动A0父3300729/子3300733，
{'COMPLETED': 1546, 'FORWARD_STARTED': 1, 'NOT_RUN': 2786}，加载条件VERIFIED。A1未启动，效果指标尚未计算；须A0/A1
各自全量预测审计后，三模型才一起离线计分。LME007未尝试尾部仍登记未运行。

[D的Source/View/操作综合](MILAI_A100_D_SOURCE_VIEW_OPERATIONS_20261107.md)保留三方法
全960项已有审阅与实际审计：收到View引用42/25/0、含K出现163/117/0，USE_VIEW
0/3/0、REFRESH59/54/0。忠实旧View可能过时；E3这组开发收益不能当作View复用
学习证据，Source role/身份也不等同事实权威。既有标签与首结果不改，无新模型/工具
执行。完整外部、其余SourceView/成本综合及最终论文/图表/审计仍继续，目标未完成。

## v70 历史状态（2026-11-07）：LME006关闭、idle33已付，旧64初始模型实际运行

LME006实际退出1、原生CPU/HTTP付费且进程消失；首165项158COMP/7ReaderF，164单次
输出8192到顶、content为空，prompt6677，无输入溢出/新增未知用量，所有失败保留。
明确登记007仅165至450共286个原生NOT_RUN位置，尚未启动。存储006退出0、46案例
关闭，累计165案例/990检查点逐字节一致；41个post32计时46.81CPU秒和存储整段
325.6683CPU秒在真实idle33一次支付，旧native/owner/历史成本不重计。

旧64初始模型准入通过后已显式启动，父3257111/子3257116存活，
{'COMPLETED': 2673, 'RETURNED_PENDING_VALIDATION': 1, 'NOT_RUN': 1659}，实际GPU2/FP32/完整输入条件VERIFIED，HTTP0/无gold读取。
下一步须真实退出/成本关闭、全4333审计，再显式启动A0/A1；三者都审计后才离线
评分，不与LME并行、不重跑失败或选择最好模型。

[已关闭离线成本证据](MILAI_A100_CLOSED_COST_EVIDENCE_20261107.md)逐项核对1309计时/
40phase，区分旧v79债务、C嵌套native、Source准备与存储整进程；仍非全项目总成本。
当前报告将“人工”澄清为本次实施助手的Source作者审阅，非独立人类/盲审或原论文
作者背书；所有C/材料/首结果不改。原生F1、数据集标签与外部原生Judge分别报告。
完整外部、实际旧64全评测、全项目综合和最终论文/图表/审计尚未完成，目标继续。

## v69 历史状态（2026-11-07）：旧64原生条件合同冻结，4333格全输入准备完成

先冻结初始E1/u16、A0/u2104、A1/u2104既定权重、7新＋1135既有代码绑定及评分，
再投影64保留query语义。18个权重文件2034760045字节复制后逐字节相同，无SHA。
127原始行→4333条件×候选格（4066 known、267 unjudged），全部公开预测输入与
原生完整state/questions相同；原始127行字节、native矩阵/掩码和所有输入全量复算通过。
1884 stable/267 unknown/0 change，变化准确率不可用。NativeTEST语义仍未打开。

[合同与范围](MILAI_A100_RESERVED64_QUERY_SCOPE_20261107.md)、
[准备摘要](../data/manifests/a100-reserved64-native-protocol-preparation-20261107-v1.json)及
[六个入口](../tools/reserved64/README.md)已保存。已有8744预测契约与原生评分字段相同；
CUDA/HTTP包路径导入失败已保留并按既有先固定SDK、后追加HTTP依赖的方式修正。
三模型计划已登记，实际预测0；准入因LME006存活被拒，不并行启动第二model worker。
所有4333格含unknown均保留，每模型全量审计后进入下一个，三者完成后离线评分；
这是共享语料次级条件指标，不是HostC/FollowIR或独立Source确认，不触发新拟合。

LME006父2889923/子2889928确认存活，active161、{'COMPLETED': 155, 'FAILED_READING': 6, 'PREPARING_INPUT': 1, 'NOT_RUN': 289}；
首119完整dict相同、原六Reader失败保留。CPU存储累计161案例/
966检查点逐字节一致，post32全部离线计时待真实空闲窗口，活动模型期间不读写账本。
内部四方法全量质量/统计/操作成本与计划初审保持；完整外部、实际旧64评测、全项目
综合及最终论文/图表/审计仍执行，完整763行目标未完成。

## v68 历史状态（2026-11-07）：旧64元数据核验与内部研究草案完成

[旧64保留query范围](MILAI_A100_RESERVED64_QUERY_SCOPE_20261107.md)核实64组完整元数据
与原分配相同，均原生dev/new_query_family，127条新行，无prior rows/anchor，
与新增128DEV家族无交集。它们是共享语料条件相关性家族，不增加独立Source来源数。
保留query/标签和nativeTEST语义仍未打开，合适的固定模型/原生输入及unknown mask/
评分合同与任何符合范围的实际评测仍未准入，不能由元数据通过替代。

[内部阶段研究结果草案](MILAI_A100_DEVELOPMENT_RESULTS_DRAFT_20261107.md)整合已闭合
P0/A/B/C/D、256确认、操作与推理成本，明确开发信号、确认未复现、Source/评分曝光
边界与外部未完成。它不是最终论文或整体目标完成凭证；主seed选择时序和原失败保留。
原763行初审与四方法1024项全质量/统计/图表/复现保持v67。

LME006父2889923/子2889928确认存活，active135、{'COMPLETED': 129, 'FAILED_READING': 6, 'PREPARING_INPUT': 1, 'NOT_RUN': 315}；
首119整dict保持，六个Reader首失败保留。CPU存储累计135案例/
810检查点逐字节一致，post32全部新计时待真实空闲窗口，活动模型期间不离线结算。
Mem2Act实际400×2仍0；完整外部实验、全项目综合及最终论文/审计等继续执行，目标未完成。

## v67 历史状态（2026-11-07）：原计划763行证据审计初版，LME006继续

[原计划逐项审计](MILAI_A100_PLAN_REQUIREMENT_AUDIT_20261107.md)将全部763行归入73个
标题/要求单元，并绑定原文及实际证据。完整UTF-8/逐单元行范围/不重不漏、紧凑版
与完整记录及全部证据路径检查通过；不按行覆盖率宣布科研成功或整体目标完成。
A20k/B192/J按原计划有信号门槛未触发；两个metadata只读schema假设失败的原计时
与反思均保留，不以默认空值掩盖证据缺失或改变实验状态。

内部四方法256×4质量、家族区间、操作/Source交付/推理成本、复现与图表保持v66。
完整目标仍需LME451×2、Mem2Act400×2、旧64保留query资格、其余Source/View与全项目
成本、最终论文/整体图表及最终完成审计五组工作。保留query/nativeTEST语义仍未打开。
LME006父2889923/子2889928存活，active127、{'COMPLETED': 121, 'FAILED_READING': 6, 'PREPARING_INPUT': 1, 'NOT_RUN': 323}；
首119整dict与005相同，六个Reader失败保留。纯CPU存储累计127案例/
762检查点逐字节一致；全部post32新计时等待真实空闲窗口，活动模型期间不离线结算。
完整763行目标持续执行，尚未完成。

## v66 历史状态（2026-11-07）：原生操作/交付/推理成本报告完成，LME006运行

原生1024个首结果的Source、完整操作绑定、实际wire材料、用量和完整推理CPU普查
已形成[详细报告](MILAI_A100_CONFIRMATION256_OPERATIONS_COST_20261107.md)与
[紧凑汇总](../data/manifests/a100-confirmation256-operations-cost-20261107-v1.json)。
tracked代码实际复算全1024项，除时间戳外逐字段相同。没有检索结果事件的15条wire
Tool消息均逐条核实：5枚举拒绝、10原生读取准入拒绝，未删错误或补造READ。
主seedHost tokens2214052，基线1985393；完整子进程加已测父CPU为2635.303秒、
816.987秒。NN/load嵌套不重复叠加，准备/训练/筛选及全项目成本仍单列。

实际idle32已一次支付307个关闭计时72.49CPU秒及存储005完整348.15CPU秒，
未变动generation/limits或任何旧compute。随后显式启动006，仅原生未尝试尾部，
父2889923/子2889928存活，active122、{'COMPLETED': 116, 'FAILED_READING': 6, 'PREPARING_INPUT': 1, 'NOT_RUN': 328}；
首119完整dict与005相同、六个Reader首失败保留。仅CPU存储006跟随该段，累计
121关闭案例/726检查点逐字节重建一致。新增post32计时待下次真实空闲窗口，
活动模型期间不离线结算。Mem2Act实际400×2仍0，完整LME两方法闭合门槛保持。
质量结果及暴露限制同v64；全外部实验、其余Source-View/操作/全项目成本和最终论文
等持续执行，完整763行目标未完成。

## v65 历史状态（2026-11-07）：LME005第119项首失败保留，006未尝试尾部已登记

005实际退出1且原生CPU/HTTP已一次计量，模型与存储进程均消失。首119项为113COMP/
6ReaderF，新增118单次响应达到8192输出上限、最终内容为空；输入4745、总12937tokens，
无输入溢出或新增未知用量。所有首结果保持，明确登记006仅续行119至450共332个
原生NOT_RUN位置；冻结协议check-only准入通过，尚未启动。CPU存储005实际退出0，
50个本段案例关闭；累计119例/714检查点逐字节重建一致，完整CPU348.149929054秒
等待idle32与所有post31已关闭计时一起一次结算，随后显式启动006。

四方法质量/家族统计与图表保持v64。新增1024个原生结果、操作轨迹、Source正文/角色/
来源、返回与响应过的Provider输入packet完整相等性及推理成本普查闭合。HTTP次数
590/591/565/616、已知tokens1985393/2214052/2136058/2187880；NN0/2036/1959/1971。
READ选择、成功打开、预算拒绝、交付与收到材料分别保留；完整推理子进程加已测父CPU
不再叠加NN/load。初次schema预读误将路径当字典的只读失败已保留并按原生路径修正。
Source/操作/成本细报告仍待整理，完整项目成本与外部实验、最终论文等尚未完成。

## v64 历史状态（2026-11-07）：四方法全256质量与家族统计闭合

全部1024首结果已逐项审阅并绑定；主C为149/148/131/115，共同固定122敏感性C为
71/79/62/57，材料S为150/149/139/103，原生首失败40/52/51/61均保留。
主seed相对基线−0.39pp，20,000次家族配对bootstrap95%区间[−7.42，6.64]；
三seed族内均值主C差−6.90pp，区间[−12.50，−1.17]；共同敏感性差−1.95pp，
区间[−5.34，1.43]。来源族仍为256，不以三个seed扩N，不选最佳seed/分层/掩码。
材料、质量转移与原生DEV185/TRAIN71分列；原生F1保持独立不改。

[详细结果与限制](MILAI_A100_CONFIRMATION256_RESULTS_20261107.md)、
[机器可读汇总](../data/manifests/a100-confirmation256-quality-results-20261107-v1.json)、
[复现代码](../tools/analyze_a100_confirmation256_quality.py)与PNG/PDF图表均已保存。
实际运行tracked代码的全量输出除时间戳外与原结果相同；精确分数复算、摘要全部
统计、文档路径与图表目视检查通过。作者非盲审/独立、指南与掩码时序限制仍在。

唯一LME005父2465168/子2465173存活，active117，
{'COMPLETED': 112, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 333}；首69整dict保持，旧Reader五失败保留。
纯CPU存储累计117关闭案例/702检查点逐字节一致。
所有post31新CPU计时待真实空闲窗口一次结算，活动模型期间不打开/写入账本。
Mem2Act最终协议保持，实际400×2仍0；须等LME两方法完整预测/评分/归档闭合。
完整763行目标仍需外部结果、Source-View/操作/全成本及最终论文等工作，未完成。

## v63 历史状态（2026-11-07）：seed2前160绑定，唯一LME005推进

seed2前160整答/全部实际非system文本及失败绑定逐条复核：C77/I38/W6/F33/U6，
材料S69/P77/I14，nativeDEV160。旧8至152所有前缀整记录相同；余160至255共96项。
四方法主C/材料/共同固定122敏感性/家族配对区间及三seed家族内均值仍待全量闭合，
不外推前缀或按结果选优。旧seed1全256主C131、敏感性62/256，基线149/71、
主seed148/79及四方法原生F1保持。指南曝光时序、作者非盲审/独立均保持。

新增完整原始Source核对：100全部69条未建立MAS缩写展开；103全部43条未建立
“引言阶段放弃论点数量”这一额外特征；105全部44条只将POS标注列为可能方法，
而共指图/Louvain聚类有明确已完成措辞。相应额外主张为U，不断言相反事实；
原始答案/指南不改。101明确联合训练NER与支持性RE、未发布RE结果，按该范围接受。

LME005父2465168/子2465173确认仍存活，active100、
{'COMPLETED': 95, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 350}；首69完整dict与004相同，五个既有Reader失败保留。
CPU存储仅跟随该段，累计100关闭案例/600检查点逐字节重建一致。
活动模型期间不离线结算，post31所有新复核/Source检查/progress计时保留待付。
Mem2Act最终1147绑定协议/全Source/公有400投影保持，实际400×2仍0，须等LME
两方法全预测/评分/归档真实闭合。完整763行目标持续执行，尚未完成。

## v62 历史状态（2026-11-07）：seed2前96绑定，seed1全256保持，LME005唯一运行

seed2前96整答、全部实际非system文本及失败绑定已逐条复核：C46/I24/W5/F18/U3，
材料S38/P51/I7，nativeDEV96；所有先前8至88前缀整记录一致。旧seed1全256主C131、
共同敏感性62/256，基线149/71、主seed148/79及四方法原生F1保持。余seed2的160项，
全四方法家族配对统计仍待，不从局部前缀或三方法选择模型/种子。共同122集合、
全256分母、作者非盲审/独立和指南曝光时序均保持。

41查全部84条原始Source，ARC明确为Aristo Reasoning Challenge；错误展开为另一
数据集且遗漏其他评测集，整答W/P。56明确区分327对话角色和45821属性库角色，
按原文支持的命名子集回答接受；81把工业研究/条件访问提升为商业许可，未被Source
建立，U/S而非断言相反禁止。所有实际首答及指南不改，无外部数据补齐。

LME005父2465168/子2465173确认仍存活，active94、
{'COMPLETED': 89, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 356}；首69完整dict与004相同。纯CPU存储只跟随该段，累计
94关闭案例/564检查点逐字节重建一致。原有Reader失败保留，无第二
模型worker或自动后续队列。post31全部新计时继续待付，活动模型期不离线结算。
Mem2Act最终协议/全Source/公有400投影保持，实际400×2仍0，等待LME两方法全量
预测、评分及归档真实闭合。完整763行目标持续执行，未完成。

## v61 历史状态（2026-11-07）：seed1全256保持，seed2前32；LME005唯一运行

seed1全256闭合结果不改：主C131/256、共同固定122敏感性62/256；基线149/71、
主seed148/79和四方法原生F1均保持。seed2在首次语义答案暴露前登记起点，
现前32首答/全部实际文本及失败绑定完成：C15/I10/W1/F5/U1，材料S15/P14/I3，
nativeDEV32。旧8/16/24整记录相同，未继承其他方法标签或外推。共同指南及
82/101/231补充早于该方法语义复核，未早于所有模型执行或其他方法答案；作者
仍非盲审/独立。余224项及全四方法主C/材料/家族配对统计，禁止按局部结果选优。

27完整37条原始Source未出现Google，BIBREF11未解析；附加Google Translate归属
未被建立，整答U/S而非将其余正确LID综述抹除；不以外部引文解析补齐数据。
24人类评估比较和22注释伪迹控制均按原文允许的受限路径评价，不要求唯一gold串。

LME005父2465168/子2465173实际仍运行，active88、
{'COMPLETED': 83, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 362}；首69完整dict与004相同。纯CPU存储只跟随该段，
累计88关闭案例/528检查点逐字节重建一致；无第二模型worker、
新服务、活动期离线结算或自动后续队列。Mem2Act最终协议/全Source投影保持，
实际400×2仍0，等待LME全量真实闭合。完整763行目标继续执行，未完成。

## v60 历史状态（2026-11-07）：seed1全256语义闭合，唯一LME005仍运行

seed1全部256首答/全部实际材料逐条复核并与原始审计、失败绑定、指南和家族核对：
C131/I53/Q0/W9/F51/U12，材料S139/P105/I12/U0。主C131/256；共同固定122
范围敏感性扣除69个C，仍以256为分母得62/256。DEV185为C97/I34/W6/F37/U11、
材料S102/P73/I10，敏感性43/185；TRAIN71为C34/I19/W3/F14/U1、材料S37/P32/I2，
敏感性19/71。全部31个先前前缀整记录均未改。指南82/101/231补充早于该方法
语义复核，但未早于所有运行和其他方法答案；作者仍非盲审/独立，不继承标签。
余seed2全部256项；四方法主C、材料、共同敏感性、家族配对区间/三seed家族内均值
须等全部语义闭合，不从前三方法选择模型或宣称采纳。全四方法原生F1保持。

229核查全部63条原始Source，其中ISOLATION明确为本比较设计的基线；“先前模型”
额外时间归属未被建立，因此U/S，不把正确六模型列表改错，也不发明相反历史事实。
唯一模型LME005父2465168/子2465173实际仍运行，active85、
{'COMPLETED': 80, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 365}；首69完整dict等于004。CPU存储跟随005已处理[69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84]，
累计85案例/510完整检查点逐字节重建一致。两进程不自动启动下一段，
新失败先等真实退出/结算后反思，仅显式续跑从未尝试尾段。空档成本最后paid31，
新增复核/Source229/闭合/progress计时全部保留待下一实际空档；活动模型期不离线计费。

Mem2Act最终1147绑定/公有400投影不变，实际400×2仍0，等待LME两方法全预测、
评分及归档真实闭合。完整763行目标尚需外部全实验、seed2/统计、Source-View/操作/
全成本、图表、论文结果和逐条要求审计，持续执行。

## v59 历史状态（2026-11-07）：seed1前192，唯一LME005及CPU存储继续运行

seed1前192整答/全部实际文本逐条审阅并绑定：C99/I37/W6/F39/U11，材料S103/P78/I11，
nativeDEV185/TRAIN7；旧160整记录不改，余320语义。DEV185为{'C': 97, 'F': 37, 'W': 6, 'U': 11, 'I': 34}、
材料{'S': 102, 'P': 73, 'I': 10}；TRAIN7为{'I': 3, 'F': 2, 'C': 2}、材料
{'P': 5, 'I': 1, 'S': 1}。不继承标签、不外推前缀，作者仍非盲审/独立，
固定共同122集合/同分母256和指南曝光时序保持；四方法主C/材料/家族配对统计仍待闭合。

167重新查完整12条原始Source，English三评测集明确，但附加Gutenberg语言组成未建立，
整答U/S；182完整152条原始Source将同步混合部署描述为可能方案而非完成事实，整答W/S。
两者均不以Host自己答案或外部常识作Source证据；原始模型结果不改。

LME唯一模型/HTTP worker005父2465168/子2465173仍RUNNING/clientCPU未结算，
实际命令核对；active75、{'COMPLETED': 70, 'FAILED_READING': 5, 'PREPARING_INPUT': 1, 'NOT_RUN': 375}，首69整dict相同。
CPU存储005父2466074/子2466075只处理该段终态，已存[69, 70, 71, 72, 73, 74]，
累计75案例/450检查点完整字节重建核对；不调用模型/HTTP/账本，
完整成本等实际退出及空档。活动模型期不离线结算，新after31计时继续保留待付。

Mem2Act1147绑定的最终协议/全400公有query-schema投影保持，实际400×2仍为0，
owner等待LME两方法全预测/评分/归档真实闭合。完整数据及同首Host配对、全审/改编
评分与归档入口虽已冻结，实际结果/全成本证据仍待；完整763行目标持续执行。

## v58 历史状态（2026-11-07）：Mem2Act完整协议/400公有输入冻结，第五次LME首失败保留

Mem2Act完整执行协议已冻结，1147代码/资源逐字节绑定；协议之后从此前已披露的
Source-only快照复制完整两文件8039404字节，再投影400原query/schema，全部整dict
相同，预测输入不含参考call/来源lineage/complexity。保留7无声明来源、16无匹配、
3部分缺失、11缺失ID及1schema/reference名称不匹配，不删项修补或gold过滤。
共同429会话16843回合库保持，341来源会话组件不当独立用户；不声称全历史字节未接触。

完整400只读Source/SDK/角色时钟/Store/Saver/目录/provider/NN审计、串行owner、最早
整首结果finalizer、独立改编评分/整payload审计、配对评分后无损归档入口均已实现并
冻结。owner复用LME同一stage锁，必须等LME两方法全预测/评分/归档实际闭合；最终
check-only真实返回未就绪，因此Mem2Act未启动，实际400×2为0。固定400全审须先于
主方法同首Host回放，基线runtime须留到主方法及两方法全审/评分审计之后才归档。

新增只读组件实际退出0：全16843 Source固定fixture及16844首Host前Source、1份实际
SDKpacket重建、Store/Saver/world/apps一致；另以8次既有真实NN/55257输入tokens核对
完整before/菜单/绑定/头/finite argmax和ID顺序，合成观察中断边界也保留完整数据。
无新NN/分词/HTTP/账本或真实400项；已有fullbank IO合成接线与真实NN效果证明分开。
Actual owner/cost/audit/metrics/archive须实际执行，不能由组件通过代替。

LME004已真实退出1，整子1171.674556CPU与parent0.254696611已计一次；11HTTP64100
已知tokens、新增unknown0/0。当前64完成、5首失败、382未尝试，索引68同类8192
输出上限/最终正文为空，prompt5707/预留14411<65536，误差0，非输入溢出。前58整dict
保持，所有首69结果/失败保留。提交4f0a0671及真实idle31后，已显式启动只含未尝试
69–450的005父2465168/子2465173，RUNNING/clientCPU未结算，实际命令及首69
整dict核对。纯CPU存储005父2466074/子2466075也已实际启动，只跟随这一段，
不调用模型/HTTP/账本、不自动启动下一段。CPU存储004也
已退出0、11项处理完成，累计69案例/414检查点完整字节核对；81.793699+0.026188883
CPU已在idle31按81.819887883计一次；同空档另计13条after30闭合计时22.32CPU，
原生成/limits/旧compute保持，新after31与活动005成本等真实退出/空档，活动模型期
不离线结算。seed1语义仍前160，余352；全量四方法主统计、
外部实际结果、完整成本/图表/论文与763行要求审计继续执行。

## v57 历史状态（2026-11-07）：seed1前160，全库Mem2Act接线通过，第四次Reader首失败保留

seed1前160整答/全部实际文本逐条审阅并绑定：C85/I27/W5/F34/U9，材料S89/P62/I9，
DEV160，旧128整记录不改。余352语义，未继承标签或外推前缀；四方法全量主C/材料/
共同122压力/家族配对统计仍待闭合。128另查170条原始Source，确认valence和dominance
均有回归方法，不以片段未检出当作事实错误。既有基线/主方法全256和原生四方法F1保持。

Mem2Act新执行入口准备快照含4份逐字节代码：最终freeze后投影400原query/schema、
复用完整共同库固定Host首快照、主方法仅改策略/checkpoint原生回放、独立离线改编评分。
新全16843 Source库接线检查v2已退出0：33686整Source比较、首完整provider请求及
Store/Saver/context/catalog一致，原模板和捕获字节不变；实际评测SDK4.52.3/.21.4。
这是合成query/schema、6模拟响应和1无权重handoff stub，真实模型/HTTP/业务/账本写0，
没有重跑旧8Source探针或执行真实400项。v1在首Host派发前因fixture原模板limits快照
与内存counter不一致失败；只修正复制fixture的budget_before，失败产物/计时保留。
完整400串行owner、全Source/SDK/NN/provider审计、最早首结果finalizer及最终执行freeze
仍待完成；公有任务投影尚未执行，实际400×2为0，不把接线通过当效果或完整原生TA。

LME003已真实退出1，父536181/子536184消失；整子1690.013888CPU与parent0.158571701
已计一次，16HTTP75048已知tokens、新增unknown0/0。当前54完成、4首失败、393未尝试。
索引57同类8192输出上限/最终正文为空，prompt2917/预留11621<65536，估计误差0，
非输入溢出。前42整dict相同，所有首58结果与失败保留；只登记未尝试58–450为004，
提交52edccb2及真实idle30后已显式启动004父714659/子714676，
RUNNING/clientCPU未结算，实际命令核对、首58整dict相同；存储004父715656/子715657
也已实际启动，只跟随这一段、纯CPU无模型/HTTP/账本写。存储003已退出0并存储16项，
累计58案例/348检查点，完整子/parent
成本112.91779500000001+0.027143931CPU已于idle30按112.94493893100001计一次。
同一真实空档还计62条闭合计时86.49000000000005CPU，包含fullbank IO两次计时及
Source110/v56快照失败；原生成/limits/既有compute保持。新after30成本和活动004整段
费用留待实际退出/空档，模型活动期不离线写账。完整763行目标持续执行。

## v56 历史状态（2026-11-07）：seed1前128，唯一LME续段与无损存储继续运行

seed1前128整答及全部实际文本逐条审阅/绑定完成：C70/I21/W5/F25/U7，材料
S74/P47/I7，DEV128，旧104整条记录不变。余384语义；不继承标签或外推前缀，
作者非盲审/独立，四方法全量主C/材料/共同122同分母压力/家族配对统计仍待闭合。

110的附加SVM方法归属重新查阅33条原始论文Source：5处均为关系/事件抽取，
没有建立SVM作为该文NER方法的说法，因此整答U/S，非断言SVM NER一般不可能。
最初误查episode索引、随后读取含Host输出的Source集合均保留；最终仅以原始论文
role/origin/session为证，未以模型自己答案背书。一次只读检查因SQLite BLOB/字符串
匹配失败，已按原生JSON解码修正，失败计时保留，数据/原结果/账本均未修改。

唯一LME模型/HTTP worker续段003父536181/子536184仍RUNNING/clientCPU未结算，
实际命令核对；snapshot active47、{'COMPLETED': 44, 'FAILED_READING': 3, 'PREPARING_INPUT': 1, 'NOT_RUN': 403}，首42整dict保持。
1135冻结代码仍逐字节相同。纯CPU存储003父537304/子537305只处理该命名段终态文件，
当前[42, 43, 44, 45, 46]已存储，累计47案例/282检查点的完整重建流逐字节核对；
共享完整基底位于case/output之外并保留依赖。它不调用模型/HTTP/账本、不启动后段；
其完整成本等实际退出与空档。已有451全审/首call回放不读逐步control，逐步原生回放
须先调用冻结restore_control恢复。完整Source/模型输入/首结果不减，磁盘仍约116GiB。

Mem2Act完整共同Source库及idle28/29费用闭合保持，实际400×2和最终执行协议仍待。
after29所有新计时（含只读失败）待真实空闲一次结算，活动模型期不离线写账。所有
既有内外部原始失败和审计/原生F1保持，完整763行目标持续执行。

## v55 历史状态（2026-11-07）：seed1前104，第三次Reader首失败保留

seed1前104整答/全部实际文本完成逐条审阅与原结果绑定：C59/I15/W3/F22/U5，
材料S61/P37/I6，DEV104，旧64整记录不变；余408语义，四方法主统计仍待闭合。
没有继承标签或以部分前缀外推效果，固定共同122压力集合及其曝光时序不变。

LME续段002真实退出1，整子220.73360300000002CPU、parent0.180903884已计一次；
2HTTP17342已知tokens、新增unknown0/0。当前39完成、3Reader首失败、409未尝试。
索引41是同类8192输出上限/最终正文为空，prompt6668/预留15372<65536，非输入溢出；
所有首42结果保留，前40整dict相同。提交42cdd299及真实idle29后，已显式启动
仅未尝试42–450的003：父536181/子536184，RUNNING/clientCPU未结算，命令核对。
首42整dict与上一段相同，当前active42；纯CPU存储003父537304/子537305也已实际启动。
存储follower002也已退出0，索引40/41无损存储完成，累计252检查点，完整子/parent
成本16.027667+0.026376141CPU已于idle29计16.054043141一次。无模型/HTTP/账本写；只跟随003的新计划复用
同一冻结代码，无自动下一推理段。完整Source和首结果不改、共享基底依赖继续保留。

Mem2Act完整共同Source库核验/idle28费用闭合保持，实际400×2及最终执行协议仍待。
真实idle29已一次结算37条闭合计时5.540000000000002CPU及存储002完整成本。首次
结算器在打开账本前因str/Path入口不匹配退出，反思及未写账证据保留，修正Path后成功；
该失败结算器未测CPU仍unknown非0。活动003模型期不离线结算，新after29成本留待
真实退出与空档。完整763行目标继续执行。

## v54 历史状态（2026-11-07）：首40项保留、无损存储闭合、完整Mem2Act历史库核验成功

LME续段001已真实退出1，父183645/子183647消失。该段32HTTP、130410已知tokens，
新增unknown0/0；整子3375.9150750000003CPU与parent0.19004935已计原账本一次。
当前38完成、两次Reader首失败、411未尝试；索引39与7同为8192输出上限、最终正文
为空，前者prompt5711/预留14415<65536，非输入溢出。两失败和全部最早整条结果保留，
不重试、不改预算/thinking/提示/Source，不当UNKNOWN或负gold。只登记索引40–450的
411项续段002，check-only通过。提交62953f26及真实idle28后已显式启动父482027/子482029，
命令核对、RUNNING/clientCPU未结算；首40整dict保持，当前active40。纯CPU存储follower
父483037/子483038也已实际启动并核对，只跟随这一命名段、无模型/HTTP/账本写。

磁盘估计漏算每步约324MB的完整执行器检查点，空间曾降至42GiB。单文件gzip仍不足，
改为独立完整压缩基底、相同原字节区间及新增原文字节；按完整行字节直接比较匹配，
没有SHA/摘要/内容指纹。实际同案例和跨案例恢复验证通过。已处理首40项240份检查点：
原77754447334字节，变为161670265新增压缩字节、117058574描述文件字节及46159702
共享完整基底字节；每份在移除原文件前均逐字节核对整条重建流。另将完整字节相同的
已结束result/attempt0硬链接，保留双逻辑路径，节约4340823597字节。完整Source、
状态、模型实际输入、首结果保持，SQLite/输入/队列不共享，空闲已回118GiB。

基底位于所有case/output树之外，后续归档须保留其依赖。需要原生逐步回放时先调用冻结
v2的restore_control恢复完整文件；已有451全审及配对首call回放不读取这些检查点。
冻结了只跟随一个已命名续段的纯CPU存储follower并通过终态owner契约：只处理终态
文件，随该段结束退出，独立留整子/parent成本，无模型/HTTP/账本写入或自动下一段。
这项存储修正不修复或重跑Reader首失败，不改变实验方法、评分或样本数。

Mem2Act父324883/子324885已退出0并消失。全429会话/16843回合的完整正文、角色、
origin、会话键及原生投影逐条核验通过，历史发生时钟不由捕获时间冒充，无query/reference
使用或gold过滤；模型/HTTP/业务/语义保存/预取/账本写0。整子1244.53287CPU与
parent0.060726831已在idle28按1244.593596831CPU单独计费一次，嵌套worker成本不再相加。这是共同Source库，
实际400×2仍为0，最终执行/首Host目录绑定/审计/改编指标协议仍待冻结和执行。

seed1前64整答及全部实际文本审阅闭合：C30/I10/W3/F17/U4，材料S33/P25/I6，DEV64，
旧16整记录不改。余448项语义；四方法主C、材料、固定共同122同分母256压力和家族
配对统计尚待闭合，前缀不外推。所有已完成内外部轨迹/审计/原生F1和历史失败保留。
实际idle28已一次结算122条闭合计时323.24999999999994CPU，原生成/limits保持；
新after28计时及活动存储follower完整成本等真实退出与空档后结算，模型活动期不离线
写账本。完整763行目标继续执行。

## v53 历史状态（2026-11-07）：seed1前16复核，Mem2Act完整历史库CPU准备冻结

seed1前16整答和全部实际收到文本已逐条审阅：C7/I4/W1/F3/U1，材料S8/P4/I4，
nativeDEV16。旧8整条记录保持，首失败及实际provider绑定保留，不继承其他方法标签，
不外推前缀效果。所有Source指南及82/101/231共同解释早于本方法语义审阅，但不早于
所有模型运行/其他方法答案，作者仍非盲审/独立。当前余496语义；基线/主方法全256
及原生四方法AnswerF1保持，四方法主C与家族配对统计尚未闭合。

为让完整历史库准备与唯一LME推理重叠，已冻结独立的Mem2Act纯CPU Source准备协议。
提交adf5b016之后已实际启动父324883/子324885，真实命令核对，当前原生
Source导入1792/16843，完整Source核验和CPU结算仍待真实退出。1137代码/资源文件逐字节绑定，协议之后复制完整两文件8039404字节全等，
QA文件未解析或展示。全429会话/16843回合将通过原生Source捕获形成共同初始库，
不按gold来源过滤、不减少历史；原始字段及角色保持，离线lineage仅在online投影去除，
原始文件完整保留，捕获时钟不冒充历史发生时间，后验逐条比对全部Source。

核对发现HTTP环境为transformers4.57.6/tokenizers0.22.2，而实际评测环境为4.52.3/
0.21.4。准备进程因此先固定后者，再附加相同HTTP依赖。CUDA可见设备为空，网络及
模型/client构造被禁止；无Host、NN权重、业务、预取、语义保存或账本修改。父进程
将测整子RUSAGE（含import/失败），退出后留待真实空闲一次结算，不重复嵌套Source
CPU，不用GNU包装启动器。这是Source准备，不能当第二推理worker或400项结果；
最终400×2预测/目录捕获/审计/评分/串行owner协议仍待冻结和实际执行。

LME唯一推理worker继续沿既定尾段运行，首第8项输出上限失败不重试，预算/提示/
thinking/图像/Source不改。idle27之后计时仍pending，活动期不离线结算。完整763行
计划及所有剩余交付物继续执行。

## v52 历史状态（2026-11-07）：主方法全256语义闭合，两次级seed余512项

主方法完成全部256整答和实际收到文本的审阅，C148/I39/Q0/W13/F52/U4，材料
S149/P92/I15/U0。整任务C148/256（57.8125%）；固定共同122压力扣69个C信用后
为79/256（30.859375%），同分母256。nativeDEV185为C98/I28/W10/F45/U4、材料
S110/P64/I11、压力49/185；TRAIN71为C50/I11/W3/F7、材料S39/P28/I4、压力30/71。
原256整答、52首失败及provider绑定完整保留，旧208整记录通过后续合并逐字保持。
U无完成信用且不自动当已知事实错误；作者非盲审/独立，指南曝光时序仍披露。

基线主C149/共同压力C71保持；主方法相对描述点差分别为−0.390625pp和+3.125pp。
不选择其中更好口径声称优势：两个次级seed各256份语义仍待审阅，四方法主C/材料/
共同压力、gains/losses、20k家族区间、各seed/来源分层及家族内均值尚未闭合。
原生整答AnswerF1和负向F1点差沿旧记录保持，不能与任务C混同或据此重选。

231的字面问题未指名词典，正文另有明确的VADER句分数神经输入机制。共同解释记录
这一有效路径，原DepecheMood指南不改；基线仅列组件无整合方法仍I/P，主方法给出
实际VADER输入仍C/P，原标签不改。该解释发生在两者手工审阅之后、两次级seed审阅
之前，不声称事前盲审；共同122集合和231未标记状态不变，未来renderer/binder会呈现。
82和101加注及时序继续保留。闭合证据位于主方法all256-source-author-quality-closeout-v1。

唯一LME尾段owner父183645/子183647仍RUNNING/clientCPU未结算，真实命令核对，
当前active18、状态{'COMPLETED': 17, 'FAILED_READING': 1, 'PREPARING_INPUT': 1, 'NOT_RUN': 432}。原前8整dict逐字继承，原第8项
8192输出上限失败保留，不重试；local_model_loads为空。活动期不另启模型/HTTP
worker或离线CPU结算。451×2实际覆盖、全Source/SDK/角色/时钟/图片/NN/Reader审计、
原生评分/Judge/审计/归档仍待完成，不能将当前预测进展当外部效果。

真实idle27仍为最近结算（71条计时18.56CPU），后续离线计时等下次真实空闲，不重收
原生/整客户端/parent/旧计时。Mem2Act仅模拟目录契约完成，实际400×2待执行。
完整763行目标、余512项语义、外部结果、Source-View/操作/全成本/图表/论文及要求
审计持续执行。

## v51 历史状态（2026-11-07）：主方法208整答，唯一LME尾段继续运行

主方法再完成24项整答及全部实际收到文本的审阅，前208为C115/I31/W10/F48/U4，
材料S122/P75/I11，nativeDEV185/TRAIN23。旧184整条记录保持，全部208绑定原全256
审计结果及首失败，不继承其他方法标签。共同122集合/每方法256分母和101加注曝光
时序沿v50保持；作者仍非盲审/独立。余560项语义=主方法48+两次级seed各256；
四方法整任务C/材料/共同压力、配对家族区间、各seed/来源分层和家族内均值仍待闭合，
不按前缀外推、不改候选/N/评分/预算、不声称采用。

唯一实际LME尾段owner父183645/子183647仍RUNNING/clientCPU未结算，真实命令核对。
当前原生driver active11、状态{'COMPLETED': 10, 'FAILED_READING': 1, 'PREPARING_INPUT': 1, 'NOT_RUN': 439}，前8整dict与原首次结果相同，
model_loads为空。第8项原8192输出上限失败和已付成本仍保留；继续仅处理此前未尝试
位置，不因PREPARING停留重新启动。活动期不另启模型/HTTP worker或离线CPU结算，
实际451全审计、原生评分/Judge、评分审计和归档仍待覆盖闭合。

v27已付71条计时18.560000000000002CPU，之后新增文档/复核计时留待下次真实空闲；
不重复原生/整客户端/parent/旧计时，未测CPU继续unknown非0。Mem2Act仅目录捕获
模拟契约通过，实际400×2尚未执行。所有M0-M4及原生四方法F1保持，完整763行目标、
外部结果/全Source-View/操作/成本/图表/论文/要求审计继续执行。

## v50 历史状态（2026-11-07）：主方法184整答、LME首失败保留及443尾部计划、Mem2Act目录模拟契约通过

LME首个owner父18071/子18073实际退出1并已消失，保留7完成、第8项Reader首次失败、
443未运行。错误是单次响应在8192输出token上限处以length结束且无最终content；
实际prompt3751、预留12455<65536、估计误差0、两张图片，故不是输入溢出或未知用量。
整阶段8HTTP/39934已知tokens、新增unknown0/0；整子1640.3464529999999CPU及
parent0.14274347已计原账本一次，未加载本地模型，不把该阶段标成全451闭合。
原响应/首结果保留，未把未完成推理当答案、UNKNOWN或负gold。

已登记并check-only通过只含原生NOT_RUN索引8..450的443项续跑计划。提交88356ac0
及实际idle27后已启动唯一owner父183645/子183647，真实命令核对，RUNNING/clientCPU
未结算；原前8整dict逐字继承，local model loads为空，独立日志保留，无自动队列。
固定提示、8192输出预算、thinking、图片、完整Source、方法和N不变，复用已有完整
pool模板；无自动队列或首结果重试。当前空闲期CPU计时先结算，再显式启动唯一worker。
最终须逐条核对最早已尝试祖先，完成全451 Source/SDK/角色/时钟/图片/NN/Reader wire
审计后才原生评分、评分审计和归档，不能将7项完成当作外部效果结论。

主方法新增88份完整答案及全部实际收到文本的审阅，前184为C98/I27/W10/F45/U4，
材料S110/P63/I11，nativeDEV184。旧96整条记录、实际结果与失败绑定逐字保持。
101发现原指南漏掉正文明确的NER+辅助RE联合训练：同一加注用于四方法，旧指南保留；
加注发生于基线101审阅和主方法101答案/材料曝光之后、主方法101手工标签之前，
所以不再声称全部指南早于相应语义审阅，也不声称盲审/独立。基线101F/S和固定共同
122集合（101仍不标记）不改。当前余584份语义结果，四方法整任务主C/材料/共同压力
同分母256、各seed/来源分层/家族内均值和20k配对家族区间仍待完成。全256原生F1
及其负向点差沿v49保持，未据部分语义前缀外推、重选seed或采用。

Mem2Act新建独立实验运行时，1262文件逐字比较仅functional.py的一个捕获guard条件
不同，允许既有capture-only目录进入首Host捕获；Product/default和当前LME运行时未改。
已安装模拟契约退出0：首个完整provider请求、Store/Saver/context/catalog相同，
8次旧Source比较、34份原捕获文件字节保持，world/语义写0。6个模拟provider响应和
1个内存策略stub验证完整后续Host循环及共享调用3/4，没有模型权重、真实HTTP、业务
调用或原账本写入，也没创建第二个持久预算。全局计数是内存测试fixture、legacy
ownership，不能据此宣称原账本租约、真实NN效果或400项已验证。实际400×2仍需冻结
完整输入/协议并执行审计与明确的MiLAi改编指标，不冒充作者TA或leaderboard。

真实空闲v27已一次结算71条闭合GNU计时18.560000000000002CPU；原生成/limits/
embedding和旧compute保持，不重复原生/整客户端/parent或idle1..26成本。扫描/结算/
启动器未加GNU包装，后续新计时待下次真实空闲，未测CPU继续unknown非0。完整763行
目标、外部451×2/400×2、旧64资格、全Source-View/操作/成本/图表/论文与要求审计仍执行。

## v49 历史状态（2026-11-07）：seed2全闭合、四方法原生F1配对统计、LME协议与完整输入冻结

协议提交3843f9b4之后，已显式启动唯一LME基线451预测owner：父18071/子18073，
真实/proc命令核对，RUNNING/clientCPU未结算，完整Source/Store初始准备中，
不能把PREPARING_INPUT算任务完成。无本地模型加载、无自动后续队列；活动期不另启模型/HTTP
worker、不离线结算。本阶段原生首次失败会停止，须保留结果和成本后只规划未尝试尾部。

seed2实际退出0，父3666509/子3666510均消失，保留195原生完成/61首次失败。616HTTP、
2,187,880已知tokens，新增unknown0/0。整子进程2398.03001CPU扣原生预测/加载后，
残余661.6200490536112及parent0.127463247计一次；GPU2区间2.293966455008421h包含等待。

全256只读审计退出0：19,188次原Source比较、962段原文及角色/origin/捕获和报告时钟、
256份完整首次provider请求一致；Store/Saver/world/应用保持，语义/业务0。
1,971次NN/11,790,893输入tokens（3454–9704），完整before/全部实际菜单绑定/头与
logit-prob-ID顺序/argmax通过，全部finite且truncatedFalse。没有重新推理/分词/HTTP。
审计86527及原生F1会话72549均已drain，不能重复轮询。

四方法全256原始整答官方AnswerF1及20,000次seed0家族bootstrap完成。
fixed0.0981909306413507、primary0.08804209206295316、seed1为0.08179025700801325、
seed2为0.08255053543397148。主模型点差−1.015个F1点，95%区间[−2.345,0.332]；
三种子家族内均值−1.406，区间[−2.568,−0.248]。分别报告nativeDEV185/TRAIN71、
各固定seed和家族内均值；256来源族不是768/1024独立样本。它是原生全文重叠F1，
不是整任务C，也不据此重选seed或声称采用/正优势。

主方法整答新增16条，前96为C50/I12/W7/F24/U3，材料S63/P28/I5，旧80完整保持。
许可推断81和基线数字归属82为未核实U/noC，不把Source无法确认当作已知事实错误；
baseline82重读没有该数字归属，旧C不改。基线全256 C149/共同压力C71保持同分母256；
四方法主任务C/材料/共同122压力及配对统计仍余672条语义结果，作者仍非盲审/独立。

LME先冻结协议、方法、预算、原生Reader/Judge/评分及串行阶段顺序，再复制完整输入：
1,135份代码逐字节绑定，5,129文件720,860,646字节全等；451问题、200轨迹、
5095状态/来源截图加29问题图像，共5124图像。配置继承仅改共同实验版本名，
fixed与laya/冻结seed0u32仅策略/checkpoint不同。16384为含头的总序列上限，
头cap2048在其中；已用独立clarification澄清原state+head措辞，数值/方法不改。
所有Small背景/公开问题/问题图像既有开发曝光仍披露，流程不冒充自主Host或未见背景确认。

bounded owner、终态finalizer、显式未尝试尾部注册已实现。完整451首次结果即使原生
FAILED也能闭合覆盖，绝不把末条失败重跑为成功；未尝试尾部不能冒充全闭合。
finalizer逐条比较最早已尝试祖先整dict，再创建一次固定别名；不存在自动队列。
只读Source/归档状态/完整NN输入/SDK及Reader整wire审计、原生保留Judge响应/规则/聚合
审计入口已实现并绑定组件证据，实际451全审仍在执行阶段之后，不能由组件检查代替。
通用轨迹8前向、3459旧Source、整包Source/角色/时钟/共享alias和LME两张实际交付图像
均通过只读契约验证。一条消息格式fixture测试退出1，改用已绑定的真实provider消息
后v2通过；失败计时和反思保留，无模型/首结果重试。

真实空闲v25已一次结算106条闭合计时118.97999999999998CPU，含上述失败和v47两条
first184失败。生成/limits/embedding不变，native/整客户端/parent/旧1..24未重收。
结算器未用GNU包装。after25的4条新进度/准入/验证计时已于真实空闲v26一次结算，
包含verify-v49误把字符串路径当Path的退出1；修正IO边界后v2通过，原结果与统计不变。
后续新计时仍pending，未测作者/检查等unknown非0。本检查点后的唯一冻结baseline451预测owner已实际启动；仍须全部外部实际任务、四方法语义与主统计、旧64资格、全成本/图表/论文/
完整要求审计，完整目标持续执行。

## v48 历史状态（2026-11-07）：基线全256语义闭合，LME实际策略捕获/无损归档适配器已实现

本轮新增56条完整回答及全部实际收到文本的审阅，基线全256闭合为
C149/I52/Q0/W15/F40/U0，材料S150/P75/I31/U0。主任务完成149/256（58.203125%）；
固定共同122例压力规则扣去78个完成信用后为71/256（27.734375%），分母始终256，
没有换成134个未标记例或为某个方法选子集。主标签、材料等级、原生替代标注不变。
nativeDEV185为C105/I35/W12/F33，TRAIN71为C44/I17/W3/F7。这只是已选256来源族的
基线结果，三个学习方法和配对效应尚未全闭合。Source作者非盲审/独立，指南、早期
pilot曝光及82加注时序继续披露。

基线旧200完整记录经216/224/240/256合并逐字保持，原始整答和失败provider绑定均保留，
40个F与原生216完成/40失败和全文F1的空串位置一致。材料与任务完成/原生状态分开。
原机械绑定的QUALITY_PENDING是历史快照，现由单独的
anchor-all256-source-author-quality-closeout-v1.json终结基线语义状态，没有改写旧结果。
主方法仍前80（C41/I11/W7/F20/U1），三学习方法合计还余688条逐条评审，不继承基线标签。

seed2仍为唯一实验worker，实际父3666509/子3666510命令均核对；快照130/256，
原生状态{'COMPLETED': 106, 'FAILED': 24}，clientCPU未结算，一个VERIFIED GPU2FP32缓存。旧主方法/seed1
全256机械输入审计和前三条件原生全文F1沿v46保持；没有新的模型/HTTP worker或活动期
离线结算。v24后计时继续pending，idle25尚未准备/执行，未测CPU为unknown非0。

外部LME适配器已具体实现：基线沿原生given-query调用，仅加真实检索/各控制步捕获；
主方法恢复同一完整pre-call快照，通过原生replay_retrieval仅替换laya/seed0u32策略，
断言完整首观察和全部合法绑定一致，再交由原生固定Reader及后续Judge。复用原生完整
closed-template复制，保留Source和图像及继续运行/最终归档所需元数据。它是固定Reader
流程，不冒充自主Host；451问题/200Small背景/29问题图像的既有开发曝光仍披露。

存储测量显示现可用约139GB，旧完整基底约120.5/96.3MB；按902例各八快照举例会达
约695GB，不能假设所有原始快照共存。适配器因此在每份原生SQLite在线备份后立刻调用
既有基底差分归档，每个重建字节核对后才移除原始before目录，完整基底、归档和映射
均保留以供恢复。实际归档契约验证7文件/121,794,392字节相等，退出0；安装环境接口/
依赖/AST协议验证也退出0，保留torch2.7.0+cu126/transformers4.52.3，未创建CUDA上下文/
加载权重、发送HTTP或写账本。它们证明组件契约，尚不是全451实际策略或Source审计。

外部最终输入/config/code/预算/评分/串行Reader-Judge-归档次序、bounded owner和完整
Source/角色/时钟/图像/SDK/NN归档状态审计仍待冻结；Mem2Act目录适配器也未完成。
不能直接继承QASPER无日期假设或将其拒绝recorded_tool_schemas的首Host回放入口套用。
证据在ROOT/external-own-policy-v1/preparation-v2.json及其中的归档/已安装契约receipt；
完整目标仍包括688条余下整答、seed2终态/成本、四方法配对统计、外部实际任务及论文等。

## v47 历史状态（2026-11-07）：基线200/主方法80整答，seed2运行，外部入口准备

本轮新增48条整答及全部实际收到材料的逐条审阅。基线前200为
C114/I40/W12/F34，材料S119/P52/I29，nativeDEV185/TRAIN15；主方法前80为
C41/I11/W7/F20/U1，材料S52/P23/I5，nativeDEV80。基线旧168、主方法旧64的完整
评审记录逐字保持，所有原始结果继续绑定各自全256原始记录。它们仍是未完成前缀，
不外推总体，不从另一方法继承标签；Source作者仍非盲审/独立。共同122/256敏感性
集合、主判据、材料等级及原生替代标注保持，四方法仍各保留256分母。

新前缀校验两次退出1均保留：首次误假设pilot8采用新阅读字段，随后漏处理六份早期
失败绑定的既有局部下标。现按实际旧字段和已声明global−8映射严格核对，除下标外
整个失败记录均相等；不加宽松fallback、不改旧记录/等级/首次结果。v3实际退出0，
后续baseline192/200与primary80合并均退出0。两条失败计时仍pending，待实际空闲
结算一次；反思见first184-review-reconciliation-failures-reflection-v1.json。

seed2仍是唯一实际实验，父3666509/子3666510的/proc命令均核对；快照63/256，
原生状态{'COMPLETED': 51, 'FAILED': 12}，clientCPU尚未结算，一个VERIFIED GPU2FP32缓存加载。主方法和
seed1已闭合的全256 Source/SDK/完整NN输入/首provider请求及原生全文F1证明沿v46保持。
没有启动第二个模型/HTTP worker或活动期离线结算；idle25尚未准备或执行。

外部准备已生成两份具体继承配置草稿，差异仅为fixed/laya及checkpoint；两份原生LME
评分代码与此前已检查副本整文件字节相等。它们尚不是最终执行协议或模型准入。
LME沿既有“自身策略检索→独立原生固定Reader→离线Judge/精确规则”流程，不能称作
自主Host；既有451问题、200Small背景和29问题图像的开发曝光继续披露。
检查还确认现有QASPER首Host捕获入口拒绝recorded_tool_schemas，不能直接套到
Mem2Act；需先具体实现并检查共享初始bank/捕获式工具目录/provider输入绑定。
Mem2Act薄CLI应调用现有物理JSONL读入函数；其严格调用、参数和JSON BLEU1为已披露
适配指标，不冒充作者TA或真实业务效果。此次未新开外部问题/历史/参考值、模型、
HTTP或账本写入，也未重跑图像探针、旧固定路径审计或调整输入预算。

证据位于final-confirmation-v1/anchor-first200-source-author-review-reconciliation-v1.json、
e3-aggregate-u32/first80-source-author-review-reconciliation-v1.json及
ROOT/external-own-policy-v1/preparation-v1.json。仍余744条语义结果、seed2全终态审计/
全文F1/成本、四方法配对统计、外部实际任务、全成本/图表/论文和完整要求审计。
完整目标持续执行，未宣告完成或采用新模型。

## v46 历史状态（2026-11-06）：seed1全256审计/全文F1/成本闭合，seed2已启动，168基线/64主方法整答

seed1/u32实际退出0，父3168683/子3168737均消失，保留205原生完成/51首次失败，不等于
205任务成功。实际565HTTP、2,136,058已知tokens、新增unknown0/0；整子进程
2546.614015CPU扣原生预测/加载后结算残余642.7612959579988和parent0.092552207一次。
GPU2作业区间2.123723988920295h包含Host等待，不作为CUDA活跃时间。

全256只读审计实际退出0（23103已drain）：19,188次旧Source比较、1,388段原文及角色/
origin/捕获与报告时钟匹配，Store/Saver/world/应用表保持，语义/业务写入0。256个首次
provider请求完整dict等于共有baseline。1,959次真实NN前向、12,353,161输入tokens，
3636–9706tokens，完整before/全部合法绑定/决策头及logit/prob/argmax逐项通过，
有限且truncated全false；实际SEARCH381/READ1561/HANDOFF17。没有重新推理/tokenize/
HTTP调用；完整实际观察/菜单不等于全部Source交付、答案正确或16k有效上下文。

seed1原生全文AnswerF1为0.08179025700801325（nativeDEV185为0.09293156442740273，
nativeTRAIN71为0.05276008978847731）。前三个已结束条件各自全256汇总已逐字串绑定：
fixed-prefix0.0981909306413507、primary0.08804209206295316、seed1上述值。
完整首答案不提取片段，51失败显式空串计零；官方原函数和完整分母保持。
原生token-overlap不是Source作者任务完成度，也未据此重选主seed或某个有利stratum；
主比较仍是冻结seed0，四方法完整统计仍待。

真实空闲v24一次结算98条新闭合GNU计时共66.59999999999998CPU，包括
verify-progress-v45和primary-first48-reconcile-v1两条退出1的失败计时；96条退出0。
未重收native/整客户端/parent/以前1..23费用，limits/gen/requests/embedding不变。
随后按冻结计划启动seed2/u32，父3666509/子3666510实际/proc已核对，
快照9/256，原生{'COMPLETED': 8, 'FAILED': 1}，一个VERIFIED GPU2FP32缓存加载。当前只有该
实验worker，活动期间v24后的新离线计时pending，未测作者/检查/启动/清理/结算仍unknown非0。

基线前168整答C97/I31/W10/F30，材料S104/P38/I26；主方法前64为
C34/I7/W7/F15/U1，材料S45/P15/I4，均nativeDEV前缀，不外推总体。主方法62的排他英语
断言无法由现有Source确认，保留U/noC而不宣称实际数据必然非英语。旧前缀记录完整保持，
各方法独立读整答和实际材料。主first48合并曾因case45手填的额外敏感性备注与固定集合不符
退出1；保持共同122集合和F/S不动，修正备注，保留v1/失败计时并生成v2。显示工具现直接
输出固定成员资格，减少重复手填；这不是模型重跑或按结果调整敏感性案例。

共同清单继续使用scope-inventory-all256-v2：122true/134false、四方法同例、分母各256，
主评分/材料/原生替代标注不改。v1错误布尔仍保留且不计分，前期材料待决项仍由共同
receipt终结。Source作者非盲审/独立，指南/加注时序沿v45披露。全部1024语义评分、四方法
配对统计、seed2全审计/成本、LME451/Mem2Act400实际原生流程、图表论文和完整完成审计仍待。

证据在final-confirmation-v1下：e3-aggregate-seed1-u32/audit-all256-v1/、
native-answer-f1-first3-methods-closeout-v1.json、anchor-first168-source-author-review-reconciliation-v1.json、
e3-aggregate-u32/first64-source-author-review-reconciliation-v1.json；idle-cost-settlement-v24.json在ROOT。
完整目标持续执行，没有子代理、新服务、第二账本、SHA校验、远端或Product写入。

## v45 历史状态（2026-11-06）：全256共同歧义清单、112基线/32主方法整答、两方法全文F1

Source/问题范围逐篇清单覆盖全部256，固定122个共同敏感性标记；四方法均在这些位置不给
confirmed-C信用，但每个方法仍保留全部256分母，主评分/材料等级/原生替代标注不变。
类别重叠计15项语言边界、41项可用Source缺失细节、82项范围/单位/描述层级。正文明确可答
而原标注含unanswerable的2/76/130/132/152/234/249不会被一律剔除。清单在基线80/主方法16
语义审阅之后形成，作者非盲审/独立，不能说来源专属判据完全预注册，也不按方法收益挑掩码。
此前baseline26/59与primary6材料待决项均最终P、首失败F不变；旧pending记录保留，
由单独的共同裁定receipt明确终结。

完整一致性验证发现清单v1写入错误：122个预先声明的索引正确，但defaultdict读取会插入键，
导致逐条布尔值全true。失败验证退出1和原v1均保留；v2从显式类别列表生成标记，已核对
122true/134false且逐条等于原声明集合，未重新选择任何案例或规则。错误布尔尚未用于
计算敏感性分数，现有主评分/材料/原生F1/模型结果保持；失败计时在下次实际空闲记一次。

Source指南82原先漏列了正文明确称作baseline的NearestNumber剂量规则和RandomTop3频率规则。
现在按原有“接受有据的连贯原问题回答”规则加入这组替代，四方法一致使用，不强制唯一
QA-PGNet原生答案。原指南保持，加注在baseline82答案审阅之后、对应学习答案审阅之前，
新增记录如实披露此时序；共同122标记未改变。所有原256指南/809整段原始证据保持。

基线前112整答和全部实际收到文本完成阅读/逐项绑定：C67/I21/W6/F18，材料S70/P23/I19；
旧96记录完整保持（经96也保持旧80）。主方法前32为C17/I3/W4/F8，材料S24/P7/I1，
旧16完整保持，均nativeDEV前缀，不外推总体或继承另一个方法的标签。具体错误分别回到
明确正文核对：primary26把未来US地域监测误作当前数据集；primary30混淆本文平方范数和
先前未平方EGL；baseline103把同一方intro→discussion的覆盖变化误作减去对手值。

两个已结束方法各自全部256原始首结果的官方全文AnswerF1已计算并逐字串绑定：
fixed-prefix为0.0981909306413507，primary为0.08804209206295316，主方法点差
−1.0148838578397545F1点。这是原生token-overlap指标，完整Source作者任务评分仍未闭合。
所有完成答案保持全文；40/52首次失败显式空串计零，且总分与既有官方missing处理完全相等。
不摘取答案片段、不改写成unanswerable、不修复失败；类型分组遵循官方best-reference归类
并包含失败空串，不冒充固定独立类型面板。没有把Source范围当原生整段EvidenceF1。
执行会话15529/46317均实际退出0并drain；无模型/HTTP调用和账本写入。

seed1仍为唯一实验worker，父3168683/子3168737实际命令核对，快照121/256，
原生{'COMPLETED': 97, 'FAILED': 24}，clientCPU尚未结算。冻结GPU2FP32单缓存和预算保持；seed2实际0，
主256全部机械/NN输入/Source审计和共有baseline闭合证明沿v44保持。v23后新离线计时
pending，活动期间没有写离线CPU成本。已准备v24脚本但未执行：等seed1真实退出/费用闭合/
进程消失，完成全256审计和原生全文F1后，再实际空闲结算新计时一次并启动冻结seed2。
未测作者/检查/启动/清理/结算CPU仍unknown非0。

证据：common-source-question-scope-inventory-all256-v2.json、
common-material-scope-adjudication-pending-cases-v1.json、source-author-guide-82-naive-baselines-addendum-v1.json、
anchor-first112-source-author-review-reconciliation-v1.json、
e3-aggregate-u32/first32-source-author-review-reconciliation-v1.json、
native-answer-f1-first2-methods-closeout-v1.json，均在final-confirmation-v1下。
全部1024语义评分/四方法配对统计、两随机种子完整审计成本、LME451/Mem2Act400和论文仍待，
不据前缀或原生F1调整候选/预算/N。完整目标持续执行。

## v44 历史状态（2026-11-06）：主实验全256真实审计通过，seed1运行，256指南/80基线/16学习整答

主E3seed0/aggregate/u32实际退出0，父2687557/子2687558均已消失，保留204原生完成/
52首次失败，不等于204任务成功。实际591HTTP、2,214,052已知Host tokens，新增unknown0/0；
legacy15/1不抹去。整子进程2,635.191604CPU已扣原生预测/加载成本后结算残余和parent一次，
GPU2作业区间2.135474490351561h包含Host等待，不当作CUDA活跃时间。

全256只读审计实际退出0（20554已drain）：19,188次旧Source逐值比较，1,513段原文及角色/
origin/捕获和报告时钟匹配，Store/Saver/world/应用表保持、语义/业务写入0。256个首次
provider请求完整dict均等于共享baseline；前16完整review/state/wire/失败/finite/forced
记录与全量对应项相等。2,036次实际NN前向、12,747,290输入tokens已计原生成本；长度
3477–9483，完整before/全部合法绑定/决策头及logit/prob/argmax逐值通过，truncated全false。
实际SEARCH343/READ1675/HANDOFF18。没有重新加载、tokenize、推理或审计HTTP。
这些证明实际观察状态/菜单完整，不证明所有Source交付、答案正确或16k有效上下文。

真实空闲v23一次结算29条新闭合GNU计时共44.680000000000014CPU，未重收native/owner/
parent/以前费用。随后启动已冻结seed1/u32，父3168683/子3168737实际/proc已核对；
快照30/256，原生{'COMPLETED': 25, 'FAILED': 5}，一个VERIFIED GPU2 FP32缓存加载，seed2实际0。
没有baseline重跑、候选/预算/N重选、自动重试或第二实验worker。seed1活动期间新增离线计时
pending；未测作者/检查/launch/cleanup/settlement CPU仍unknown非0。

Source专属指南已到全部256篇（nativeDEV185/TRAIN71），809个整段原始Source证据逐值绑定，
旧144指南保持；全部256在本研究仍是confirmation。新增解释包括手工定义模式规则与自动赋值、
释义评分/QA联合训练与候选生成器预训练、正文明确的第三类CNN架构，以及480名附加自然性
评测受试者不等于全研究唯一人数。指南并非全部早于执行/所有答案，作者非独立/盲审；
共同全256 Source/问题歧义清单和敏感性仍待，不靠native标注补缺表格。

基线前80完整答案/实际材料与全256逐项关联，C49/I16/W4/F11，材料S49/P17/I14；
主方法前16整答C10/I2/W2/F2，材料S11/P5，均是nativeDEV前缀，不外推总体。
各方法分别读整答和全部实际收到材料，不继承另一方法标签。主方法case8把Ordinal
Classification写成One-class，改变任务形式而记W；同例baseline正确Ordinal已核对。
精确可答性/范围沿冻结通则，完整Source有事实但没取到仍I；首次失败仍F。材料case26/59/
primary6及共同敏感性保持pending。原始全文nativeF1、全1024语义评分/统计/外部验证和论文
仍待，不因机械审计或前缀结果采用模型。一次只读显示脚本错用baseline失败输入schema，
检查真实键后改读actual_last_provider_messages；未改实验或重试，未测CPU不写0。

证据：final-confirmation-v1/e3-aggregate-u32/audit-all256-v1/、
source-author-guides-all256-closeout-v1.json、anchor-first80-source-author-review-reconciliation-v1.json、
e3-aggregate-u32/first16-source-author-review-reconciliation-v1.json、idle-cost-settlement-v23.json。
完整M5和原目标仍在执行。

## v43 历史状态（2026-11-06）：学习轨迹前16真实状态/NN输入审计通过，144指南/48整答

主E3seed0/u32仍由父2687557/子2687558原进程运行，快照150/256已结束，
原生状态{'COMPLETED': 115, 'FAILED': 35}，不是任务评分。GPU2 FP32缓存加载仍为
一个VERIFIED模型，secondary seed1/2实际0，没有重试或第二实验worker。

已复用原DEV64/D审计逻辑，对原清单前16首结果完成只读绑定，实际退出0，
会话10488已drain不再poll。14原生完成/2首次失败均包含：1,051次既有Source
比较，98段原文的内容/角色/origin/captured和reported时钟逐值匹配，
Store/Saver/world/应用表保持，语义/业务写入0；前16第一次provider请求
完整dict等于共享baseline，前8记录与原first8证明相等。

128次真实有限决策前向、815,069输入tokens已计native：输入范围4102–9310，
原生完整before、合法动作绑定、决策头、logits/probabilities顺序和最终选择
均逐值核对，数值有限、truncated全false。SEARCH19/READ109；这是实际
操作，不由配置字段猜次数。审计不重新tokenize/加载/推理，不重收模型成本；
36HTTP/121,977已知tokens已由原生支付。它只证明16条的完整实际观察和菜单
输入，不代表全部Source已交付、16k有效上下文、任务成功或全256已审完。

全256审计入口已准备：真实owner退出0/成本闭合/进程消失后，核对全部
provider输入、Source/SDK状态/时钟、NN输入和成本；前16的review/state/
first-wire/failure/finite/forced记录须与全量对应记录完整相等才复用。
当前prefix16成功不替代该终态门禁，也不启动另一模型。

Source指南已到144篇，新增112..143先于对应语义方法答案审阅，旧112份
逐值保留。来源解释包括：survey资源不等于新实验；NUS的2.6pp跨测试
模拟器，不是同测试条件下训练方法之差；MCScript13%是未达标注多数一致
而非不可答率；270M/280M Latvian语料为约13.5–14倍的有范围比较；金标准
特征分析标注不等于修复原始答案。所有未导出表格仍不靠native标注注入。

基线前48整答/所有实际收到材料与全256记录完整相等关联，原32判断保持：
C29/I11/W1/F7，材料S31/P9/I8，全为nativeDEV，不外推总体。新增32..39为
C7/I1，40..47为C3/I4/F1；来源作者非独立/盲审。精确数值缺失、问题范围
和语言等歧义保留共同敏感性，所有256分母保持，case26材料范围仍待统一。
标签不进入模型/拟合，也不改变候选/评分通则/预算/N。

v22及以前计时已付一次；本轮Source/NN审计、指南/整答及first48合并计时
在主worker存活期间pending，未测作者/检查/launch/cleanup仍unknown非0。
证据：e3-aggregate-u32/audit-prefix16-v1/、source-author-task-guides-prefix144-v1.json、
anchor-first48-source-author-review-reconciliation-v1.json；完整M5仍在执行。

## v42 历史状态（2026-11-06）：256基线完整绑定，主E3已实际启动

确认基线两段均实际退出0、父子进程消失、整客户端成本记一次。全部256首次
自主轨迹保留，原生COMPLETED216/FAILED40，不等于216任务成功。实际590HTTP/
1,985,393已知Host tokens，新增unknown0/0；共有baseline只按一次实际执行计费。
剩余248整子进程781.31931CPU和parent0.189366797CPU已付，native本地模型0。

全248绑定和全256合并均实际退出0（44683/20326已drain，勿复查句柄）：
1,012段实际原文逐字匹配，19,188次既有Source比较；18,932个完整Source加
256个当前user Source均逐值绑定初始Store。Store/Saver/Source/world/应用
检查通过，无语义或业务写入。前64的cases/results/review/失败输入/Store
效果完整record与全量相等，两段review除明确全局index外与全256记录相等。

真实空闲时，15条新增闭合GNU计时共24.54CPU在v22记一次，包含失败前缀v1，
limits/gen/requests/embedding不变，未重收native/owner/parent/以前费用。
随即启动冻结的主比较E3seed0/aggregate/u32，owner父2687557/子2687558，
实际/proc命令已核对。快照18/256结束，状态{'COMPLETED': 16, 'FAILED': 2}，
并非任务评分。一个实际GPU2/cuda:0模型加载已VERIFIED：FP32、threads4、
max16384/head2048、MHAfastpath/referencecompile关闭，冻结runtime-b64和
原DEV64预算/Host设置不变。没有新拟合、baseline重跑、输入裁剪或自动重试。
secondary seed1/2实际仍0；主worker存活期间不离线结算或启动第二实验。
另已逐值核对原清单前8个首结果的实际第一次provider请求：整个请求dict
与共享baseline相等，保留首次失败；这不表示响应或后续内生查询相同。
全256对应核对及实际Source/SDK/所有NN输入审计仍待。

Source指南现到前112篇，新增72..111先于对应语义方法答案审阅，原指南
逐值保留。前32整答案/实际材料的判定已逐条与全256最终记录相等绑定：
C19/I6/W1/F6，材料S21/P5/I6；这32条均nativeDEV，不外推全256。pilot8
主判C5/I2/W1；共同收紧来源/问题范围[0,6,7]时C2、分母8保持，后续对四
方法同样处理。原provisional notes保留；完整Source数值缺失时的精确限制
符合原任务条件，宽泛encoder问题接受有据的文档及逐句表示创新，不强制
唯一实现清单。完整256歧义清单、材料case26范围和全1024评分仍待，Source
作者非独立/盲审。标签不进入runtime或训练，不据此调候选/权重/预算/N。

证据：final-confirmation-v1/anchor-all256-binding-v1.json、anchor-first32-source-
author-review-reconciliation-v1.json、source-author-task-guides-prefix112-v1.json、
e3-aggregate-u32/learned-owner-v1.json、e3-aggregate-u32-inference-v1.json、
idle-cost-settlement-v22.json。最新first32合并及primary首8请求核对计时在v22后pending，活动期间
不结算；未测作者/检查/launch/cleanup CPU保持unknown非0。完整M5仍在执行。

## v41 历史状态（2026-11-06）：72篇指南，来源可答性按冻结任务统一处理

唯一基线worker父2223256/子2223258仍运行，本快照170/248已结束，
原生状态{'COMPLETED': 138, 'FAILED': 32}；首8不重跑，三个学习方法
实际0，client CPU在原owner真实终态计一次。v40前64机械审计及新增12份整答
复核保持原样，所有新离线计时仍等真实空闲才结算。

完整Source指南扩展到前72篇，新增60..71在对应语义答案审阅前完成，原60份
逐值保持。额外记录既有冻结规则的共同应用：完整Source无法建立的事实允许
精确说明限制；答案在完整Source、但方法未取到时仍是不完整。四方法同一
来源歧义敏感性、分母不变，native全文F1单列，不注入原生标注中的缺失表格。

新检查发现case60的原生unanswerable与明确SGNS/fastText方法描述不一致；
case63的“无非英语训练数据”只可能指下游零样本标签，不能覆盖明确的目标
语言LM语料训练；case68自然语言推广仍是未来验证，不能称为已实证。
这些解释不用于候选/预算/N调整，来源作者非独立/盲审。

指南写入曾在解析阶段发生tuple分隔符SyntaxError，未执行任何文件/模型操作；
现将手工解释放入JSON，由一个简短Source绑定脚本处理，避免重复嵌入长文到
代码。实际退出0，0.24CPU计时pending，失败的未测CPU仍unknown非0。
证据：source-author-task-guides-prefix72-v1.json、source-scope-rubric-application-
before-learned-v1.json、source-author-guide-extension-68-to71-v1.json。完整M5仍在执行。

## v40 历史状态（2026-11-06）：前64轨迹审计通过，60篇指南与新增12份整答复核

确认基线唯一实验进程仍为父2223256/子2223258；本快照148/248已结束，
原生状态{'COMPLETED': 119, 'FAILED': 29}，不是任务成功数。首8不重跑，
三个学习方法实际仍为0。冻结的256家族/1024首次轨迹、checkpoint、完整输入、
Host和工具预算不变；没有离线结算或启动另一模型/HTTP实验。

已结束前64的只读审计v2实际退出0：256段原文逐字匹配、4,561次既有Source
比较、Store/Saver/应用表全部通过；143HTTP/489,826已知tokens已由原生账本
支付，新增unknown0/0。全248结束后，必须将前缀每个完整record字典与全量
对应记录直接相等核对，才复用这些审阅。v1曾因误以为汇总usage也含完整trace
的usage_confirmed字段而失败；按真实整数tokens和逐结果unknown前后值修正，
失败计时保留，未重跑模型。

完整Source专属task guides已到前60篇，保留表格缺失、原生标注与正文冲突、
语言范围及作者/前人、数据集/预训练/评估单位的区别。通用判据仍是冻结的
“接受有依据的连贯原问题回答”，不以唯一gold串/证据ID替代任务含义。
全256原生依据早于首次模型，但Source作者并非独立/盲审，不能声称所有指南
早于所有答案。

新增全局8..19的12个整答案及所有实际收到的材料已逐条阅读：C6/I3/F3，
材料S7/P2/I3；它不是全确认面板的效果估计。失败case11实际已收到支持一个
允许替代范围的完整材料，仍为F；case17/19的材料不足，首失败也原样保留。
原pilot8的数值可答性和宽泛encoder创新性等范围裁定仍待统一完成，未冒充
完整20题最终评分，更未把这些标签用于策略或拟合。

已准备但未执行全256合并脚本与三个串行GPU2作业owner。合并将额外逐值
绑定18,932个完整Source到初始Store，并核对当前user Source、原allocation
及两段全部review记录。学习owner先记录整子进程/native残余及parent成本，
再验证产物，避免早期导入/产物失败抹去已耗CPU；异常仍停止、无自动重试。
所有新GNU审计计时等到真实实验空闲才结算，v21及此前/native/owner不重收，
未测作者/检查/启动/清理CPU为unknown非0。

证据：final-confirmation-v1/remaining248/prefix64-anchor-native-binding-v2.json、
source-author-task-guides-prefix60-v1.json、remaining248/anchor-source-author-reviewed-
global8-to19-v1.json、learned-owned-execution-preparation-v1.json。v40 manifest
引用完整v39和既有closeout，避免复制约914KB历史记录；历史证据原样保留。
完整确认、旧64查询资格、LME451/Mem2Act400、全成本/统计/论文图表尚未完成，
完整目标保持ACTIVE。

## v39 历史状态（2026-11-06）：确认所选256已在冻结后导出，基线未执行248族运行中

冻结记录先提交1ebe965e，然后才用既有QASPER source-only adapter导出256个
所选论文家族/18,932个Source单元，nativeDEV185/TRAIN71。保留所有标题/段落/
caption和首个原生问题，模型history没有检索query或答案/证据标签，离线
native替代标注与Source引用单列。解析了共享dev/train容器，不能声称未读取
任何其他字节；仅投影所选语义，nativeTEST未打开，old64保留查询亦未打开。
模型首次调用前，256个原生替代答案及字面Source证据basis已独立绑定；它是
离线依据，不冒充完整来源作者task guide或独立盲审。

确认fixed-prefix首8族实际一次完成8条完整自主Host轨迹，19HTTP/54,908已知
Host tokens、新增unknown0/0。实际最终输入/32段原文/609次完整Source比较/
Store/Saver/应用表均核对通过，新增8条正确标assistant的最终Source，没有
语义记录或业务写入。8个原生COMPLETED尚不等于8个任务成功，质量待审。
整子进程35.360213CPU、parent至计量点0.118245314CPU已记一次，模型加载0。

按原预定清单启动从未执行的248族，唯一实际worker父2223256/子2223258。
快照10/248闭合，状态按实际driver/进程重新核对；原首8不重跑、不重收。
完整DEV64配置、24共享生成额度、2048返回/观察、range256与Host8192不变，
原生train/dev混合通过不指定split过滤处理，不伪造all枚举。三个学习方法
仍未执行，后续各从同一实际pre-first-Host Store/Saver开始，总N1024冻结不变。
活动期间不离线结算或启动第二实验worker；新导出/首8审计CPU计时在v21后pending。

进度检查意外显示了两个首8基线答案，因此完整来源作者guides不能声称全部
在答案前写成、也不能声称blind。通用评分、方法/预算/N在语义导出前已冻结，
原生标注/字面证据basis在模型前已绑定；后续Source专属解释不得随方法结果
改变判据或候选。完整确认QA/统计、合格外评、全成本和论文图表仍未完成。

证据：final-confirmation-v1/source-export-closeout-v1.json、
source-review-guide-basis-before-model-v1.json、pilot8/anchor-native-binding-v1.json、
remaining248/anchor-owner-v1.json及冻结后的实际执行目录。完整目标保持ACTIVE。

## v38 历史状态（2026-11-06）：B/C完整审阅闭合，预留确认协议已冻结

66格完整新答案、实际packet、全文任务依据均逐条读过，按同一来源作者规则
完成裁定，没有把旧标签复制给新答案，也没有使用新增模型/Judge或训练。
来源作者非独立/盲审；这是旧暴露TRAIN诊断，不能增加独立确认来源数。

B52新结果complete15/qualified9/incomplete23/incorrect1/failed4，材料充分17、
不足34、unknown1；保留原比较完整18。质量优先配对为2部分收益/5损失/39tie/
6unknown，交付0收益/4损失/47tie/1unknown。完整成功0gain/3loss，差−5.77pp、
52家族20,000次seed0 bootstrap区间[-13.46,0]pp。读取覆盖57/57已修复，但
没有证据支持继续B192或追加拟合；抽到的合法范围常仍是引言/方法背景。

C7规则完整3/7，E3完整2/7；E3−规则−14.29pp，区间[-42.86,0]pp。规则左侧
答案质量2较好/3tie/2unknown，材料1较好/6tie。主判断接受真实Results::Human
Evaluation标题支持“是否做过任何人工评估”这一Boolean问题；统一不计该
heading-only支持的敏感性结果为2/7对2/7，七家族和分母保留。没有学习选择器
优越或菜单表达缺口的证据，不扩菜单、重采或补剩余1个读出名额。

规则强调任务含义而非强制某个引用ID或短字符串：参数模型三种配置都要保持，
共享超参数不是联合训练，训练/评估/预训练阶段不能互换，相关工作不等于本文
实验。FSE术语歧义保留unknown，不把原生No当唯一真值；Prolog接口、流量总数、
训练量匹配等全文确实未建立的信息允许精确范围限制。未导出的数值表格不能
靠原生标注注入Source。6次首次Reader执行失败保持失败/未知答案比较，材料
仍可独立判定。空字符串或thought等原生完成不会成为任务成功。

本次原生66HTTP/253,042已知tokens已付，新增unknown0/0；C本地7次输入32,401
已计native，不重收。v21真实空闲仅结算4条新增闭合质量准备/审阅/冻结计时
7.81CPU；此前20份结算及native/模型/客户端/parent未重复收取，未测作者/
检查/launch/cleanupCPU保持unknown非0。当前没有活动实验worker。

在held语义仍未打开时，实际冻结final-confirmation-v1/protocol-before-held-export.json：

- 全部256个已身份预留论文家族，nativeDEV185/nativeTRAIN71，每族首个原生问题。
- 强简单方法沿实际DEV64的fixed-prefix（policyfixed，不能误写成fixed_context）；
  主比较保留先前选定E3seed0/aggregate/u32，次要确认固定已完成的seed1/2同u32。
  共1024条首次完整自主Host轨迹，不挑确认最好seed、不新增拟合。
- 完整DEV64配置逐值继承，24个共享生成额度、policy reads4、additional reads8、
  return2048、观察2048、range256、complete-input16384/head2048、Host8192不变。
  原始每族首次Host前Store/Saver只捕获一次，三学习方法从该实际before重放。
  不给定检索query、不固定最终Reader、不裁K/菜单/Source/任务来通过容量。
- 预定N256，主指标为完整任务成功家族宏平均；所有F/U保留，native literalF1
  分开，来源分层、20k家族bootstrap、每seed及族内seed均值分别报告。不是
 768或1024个独立来源，三seed只是共同E1初始化下训练RNG差异。
- 最新开发方差0.203896605对应假设真+5pp时约640族的条件功效规划，不能保证
  N256功效。历史771不是当前要求。按全部已预留256执行，不按确认效果加减N；
  存在优势和至少+5pp分别要求区间支持相应下界，没有自动采用。

接下来才允许导出所选256正文/标注，继续自主Host确认、完整Source/SDK/输入/
答案审阅；旧64保留查询语义仍待按曝光资格单列处理。合格LME451/Mem2Act400
仍需自身策略/完整输入/原生任务和预算，LME既有发展曝光不能转为独立确认。
完整外评、成本统计与论文图表仍待，完整目标保持ACTIVE，没有缩小范围。

证据：b-c-repair-quality-closeout-v1.json、source-author-decisions-v1.json、
b-c-repair-full-closeout-v1.json、final-confirmation-v1/protocol-before-held-export.json、
idle-cost-settlement-v21.json；原packet/wire/全文依据/所有首次失败保持ignored。

## v37 历史状态（2026-11-06）：52 READ/7池首次执行及机械审计完成，66格质量待审

当前没有活动实验worker。B52 owner和C7 owner均实际退出码0、父子进程消失，
客户端CPU已记一次。B52实际52次HTTP/194,966已知Host tokens，48次原生COMPLETED/
4次首次FAILED；C7实际14次HTTP/58,076已知tokens，12次COMPLETED/2次首次FAILED。
新增unknown均0/0。没有重试首次失败，没有把完成字符串当任务成功。

B完整52绑定实际exit0，整个前12记录字典与完整52前缀逐值一致。52条新READ
均opened且所选范围进入实际Reader，159段原文按全文范围/角色/clock绑定。
3,829次完整前后Source比较与应用表一致，语义/业务写入0。原有5个覆盖状态
加新52个，旧57状态/56家族的 observed-Source READ执行覆盖达到57/57；新增
功能READ5＋本次52＝57预算上限。旧139/功能8首结果未重跑，52个保留比较的
Reader wire在packet之外逐值相同。B整子进程115.64851CPU、parent至计量点
0.08460277CPU各计一次，新增native模型CPU为空，没有启用GPU。

C固定7个原已获材料池完成真实Store准备，全部Store值保留、7格观察字段
实际无变化；HANDOFF原完整参数和顺序12/17/8/18/13/4/17保持，未扩菜单或
重跑前缀。14格实际均只执行一个合法HANDOFF，没有新取证。18段交付原文、
1,222次Source比较和应用表一致，语义/业务写入0；七个Reader对在packet外
逐值一致。没有旧完整绑定及整个Reader wire同时相同的结果可复用，实际
复用0、新增14读出，累计47/48、18/24状态，不填剩余额度。

C的7次实际E3 forward逐条核对完整state、原HANDOFF参数/头ID/顺序、logits/
probabilities/选择与预检一致，3,837–5,127 tokens，总32,401已由native计量，
无截断。GPU2FP32一次VERIFIED加载，MHAfastpath/TF32/referencecompileFalse。
NativeDecision仍来自未改runtime-c-handoff8；早期C8没有GPUutility，复用
后来D的通用进程wrapper，未添加运行时文件或改变策略算法。C整子进程
56.893255 CPU＝已计load/predict12.543705536＋残余44.349549464，parent
0.221215714另计一次。GPU作业区间0.102402046小时包括Host等待，不是纯CUDA。

初版v37快照writer仍要求C7处于RUNNING，而读取时该作业已经完成，断言在
写文件之前停止。随后核对实际owner/进程/原生终态，按完成状态记录；没有
模型、Source、账本或首结果改动。另一次只读检查误假定早期C8包含GPUwrapper，
按实际文件清单改用已有Dutility。未测检查/作者/launch/cleanup CPU记unknown，
非0。真实空闲v20仅将7条新增闭合准备/绑定/预检计时46.83CPU记一次；此前
20份结算、模型/native/客户端/parent费用不重复，limits/生成/请求/embedding未改。

下一步是完整66格的来源作者答案/材料审阅及配对胜负/tie/unknown。B的48次
原生完成及C的12次完成都还不是完整成功数；来源字面绑定、打开/交付完成、
状态无副作用和完整模型输入分别成立，不能代替语义质量。沿旧已曝光TRAIN
任务/全文依据审阅新答案，不从旧结果复制标签，不增加拟合/状态/重复。
仅使用这批已曝光来源的审查包和实际before，冻结前不打开全量rawQASPER中
可能含held/reserved的语义。held256/old64查询/原生TEST语义仍未打开。

完整目标继续：质量及开发结论闭合后，冻结最终候选/权重/评分/预算/N，再
做合格确认与LME451/Mem2Act400自身策略、完整输入、曝光、全成本/统计/论文
图表。D/K/三训练RNG种子负结果和解释范围均保留；没有SHA校验、子代理、
新服务、第二账本、退款、Product或远端变更。

证据：b-repair-read52-full-binding-v1.json、coverage-closeout-v1.json、
c-repair7-native-v1/mechanical-source-input-audit-v1.json、两个owner、
idle-cost-settlement-v20.json；实际packet/wire/trace和Source副本保持ignored。

## v36 历史状态（2026-11-06）：缺失52 READ正在首次执行，前12格机械绑定完成

v35旧输出42格/来源作者审阅/实际输入与成本已闭合并提交680bb90f。
本轮将52个冻结动作转换为原有双提名准备：每状态新READ加首个已执行旧比较。
现有exact-nominations入口实际准备52状态/104个完整合法绑定，完整核对后，
执行清单只保留52个新READ，未补状态、菜单或旧比较调用。原runtime-b-functional8、
原生replay/given-readout未改变，全部52before仍使用原连续账本。

唯一活动实验为父进程1437174、子进程1437175，实际/proc命令已核对，
快照时41/52读出有终态，工具记录42/52；完整质量尚未评分。作业按原
supplied-request/emptyK、fixed_context reads4/continuation2与原实际剩余额度执行，
不是自主Host。用量已知的首次未完成响应保持失败，仅继续未执行格。

前12个结果已核对完整首动作、已执行前缀未重跑、共同续行、真实回包/Reader输入，
与各自保留旧比较的wire在packet之外逐值一致。12个新READ均实际opened且所选范围
进入实际Reader输入，35段原文逐字/角色/clock绑定；728次完整Source比较与
应用表一致，没有语义记录或业务写入。该段11次读出COMPLETED/1次首响应FAILED，
不把读取/交付完成当答案成功；未知/质量标签没有从旧结果回填。

为避免上轮监控父进程中断，有限的52格owner改为独立会话启动并将输出写文件，
仍是单次有限作业，不是新服务/重试平台。owner在启动前保存原账本快照，终态
以实际子进程rusage扣已计native后记录剩余CPU一次。活动期间不做离线结算；
新增准备/前缀绑定计时保持pending。未触及GPUs0/1或启用本地学习模型。

C的7个冻结已获材料池与既有单数入口prepare_handoff_comparison.py已核对，
实际Store准备/模型/Host仍为0。仅在B52实际终态、客户端计量完成及空闲后，
进行原生F1准备、HANDOFF完整菜单相等与实际准备输入容量检查，再做rules/E3
handoff-only，最多14个新读出、累计47/48和18/24状态。一次只读检索误写复数
路径，已依据实际rg结果纠正，未导致状态、模型或账本变更，未测CPU为unknown。

完整目标继续：B52全审/覆盖与C7之后，才冻结候选、权重、评分、预算、N并打开
预留确认语义；LME451/Mem2Act400自身策略/完整输入/曝光、全成本和论文图表仍待。
活动证据为b-repair-read52-owner-v1.json、execution-plan-v1.json、execution-v1/、
prefix-12-binding-v1.json及c-repair-existing-native-preparer-contract-v1.json。

## v35 历史状态（2026-11-06）：旧输出检索性首42格闭合，52 READ/7池仍待执行

本轮完成固定7个原生 before 的14条件准备、14个首次原缓存工具结果、40次
实际 Host 读出、93次学习模型 forward、42格完整质量/来源/View/操作/输入审阅
及 v19 空闲结算，属于实质进展。当前没有活动实验 worker。最终确认、外评、
全成本和论文仍未完成，没有缩小完整目标。

固定首8家族中 A02 的初始 Host 失败，没有已完成旧回答，保留其6格不可识别
干预的 inventory，不换家族或后续回合。其余7家族各一个原缓存 content-flow
same-sources ready-state，均在第一次当前 provider dispatch 之前。原当前最终
回答未进入 before；旧 initial:final 回答保持 assistant 角色，完整存在原实际
Host 消息中。新控制 query 等于当前公开请求，保留全部实际先前交付 K 引用，
并使用同一固定预算。完整 Host 旧消息、回包及 provider 选项逐值保持。

单独冻结 runtime-d-old-output-v1，只纳入既有 Source 排除支持的三个 adapter
文件，正式 runtime-d-update32 未改。OFF 在普通当前请求排除之外，仅将已证实
的旧回答 Source ID 加入语料/排名和观察/打开两条边界；不删除 Source，不改
角色、版本、时钟、可见性，不按 gold、答案词或质量过滤。实际 ON/OFF Host
frame 的 request 字典逐值相同；干预只改变新增工具取证，不擦除 Host 已知回答。

14份完整初始 Laya 输入中，A05 的7条 K 产生20,096/19,335个状态 tokens，
在16,384上限分别会丢4,342/3,563，两个学习格保留结构性 F/unknown，未加载
或调用该格模型、未派发 Host，也没裁 K/菜单/预算。其余12学习轨迹实际
93次 forward 输入4,141–9,795，总643,723 tokens已由原生记账；完整before、
K、参数绑定、菜单/head ID顺序和 logits/probabilities/选择均一致，无截断。

| 旧输出新增可检索性 | 原缓存 C/Q/W/F | 增量缓存 C/Q/W/F | E3 u32 C/Q/W/F |
|---|---:|---:|---:|
| ON | 4/0/0/3 | 4/2/1/0 | 2/1/1/3 |
| OFF | 4/2/0/1 | 6/0/1/0 | 2/2/1/2 |

总计 C22/Q7/W4/F9，材料 complete27/partial13/unknown2。F包含7次用量已知的
首次 Host 未完成响应和2次完整输入容量失败，全部保留。A14 的 `...`、A33
的空字符串虽通过既有原生完成检查，均按完整任务非回答记Q，不冒充执行F
或成功。A16四个完成答案均沿用旧学位简称，没取得本人已接受的完整 transcript
更正，记W；其他正确学号/日期/merit不补足主要错误。

另5个Q保留主要数值/当前角色，却把 Kevin 的诊所位置这一助手推测，或 Tom
历史职称这一事实，表述成已确认的测量/图表来源。逐格争议原句和说明已保存，
不把这一来源作者判断当独立盲审；这些是同7个已曝光 TRAIN 家族的相关条件，
不是42个独立未见任务。材料完整性按实际任务所需支持判断，不强制原文重复：
A29本人72/74更正可直接支持当前单一轨道；旧助手回述/回答不能冒充本人来源。

每方法的 ON−OFF 完整成功差：原缓存0pp、增量−28.57pp、E3 0pp；20,000次
seed0家族bootstrap区间分别[-42.86,42.86]、[-57.14,0]、[-42.86,42.86]pp。
原缓存和E3各1gain/1loss，增量0gain/2loss。第一轮生成 seed 未配对，且包括
首次响应失败和上述二级来源表述差异，不支持总体检索回流有害/无害、学习
优越、等效或采用。Host 本来保留旧回答，因此该因子也不能单独解释正式D
所有 final-arrivals 失败。

476次完整旧 Source 值比较、原生 sources() 只读投影和应用表均一致，没有
canonical semantic record/业务写入。118次实际 K 引用读取通过；225次合法选择
为REFRESH33/SEARCH36/READ116/HANDOFF40，操作结果211次（HANDOFF26）。
OFF指定旧 Source 不出现在任何实际控制器状态/菜单或新回包；ON有6格将旧
回答作为4段原文/2个View节点新增交付。实际 Host 49次View出现、16个完整
不同payload、9次当前工具View均绑定原始角色/时钟/全文并审阅；字面忠实
不证明引用为真或任务覆盖。原问题回包仍只是问题，不能变成新本人事实。

失败修正保留，未重执行首次模型/Host结果：

- 准备器把 SourceObservationBudget 误当三参数构造。首个A01公共bank保留，
  按原生两参数接口继续，未清空重建身份。首次失败计时保留。
- 收集器错误地要求K引用数等于投影容器数；原生会把A14的4引用合为3容器。
  改为比较完整 project_packs 和实际引用读取数。已执行5个首次工具结果原样
  复用，只运行另9个；先前17.417007535和续段30.033362399 CPU各计一次。
- 监控句柄及原父进程中途丢失，但 /proc 证实同一个原子进程仍工作，随后
  原驱动42格和推理记录完成且子进程消失。未重启实验。退出码未被父进程
  回收，明确记unknown，不伪造exit0。原驱动/OS可观测子进程CPU下界199.51秒
  扣原生116.483697845后，残余83.026302155只记一次；丢失父进程和未观察到的
  cleanup/recovery/作者CPU保持unknown，非0。GPU从启动到观察终态区间上界
  0.307077718小时，包括所有Host等待，不是纯CUDA时间。
- 中间进度文字漏计一个早期Host F，已依据完整驱动计数更正；原结果未改变。

实际40次HTTP/343,013已知Host tokens，新增unknown0/0。133个共享生成额度
预留是93次本地调用＋40次读出，不是133次HTTP。基线收集器CPU共47.450369934
先前已付，未再次收取。v19在真实空闲时仅结算10条新增闭合计时47.67 CPU，
包括失败准备/审查与纯元数据READ提名；原生、收集器、客户端及此前18份结算
未重复计账，limits/生成计量/请求/embedding未改。没有SHA校验、子代理、新服务、
第二账本或远端写入。

下一步52条缺失 observed-Source READ 已按冻结动作准备纯元数据双绑定提名：
新READ加同状态首个已执行原比较。尚未调用原生准备器/工具/模型；执行只
包含新52条，不重跑旧比较。随后固定7个已获材料池作rules/E3 handoff-only，
最多14次新读出。开发修复闭合后才冻结最终候选/权重/评分/预算/N，再打开
held256论文和old64查询语义；LME451/Mem2Act400仍需自身策略、完整输入、
曝光资格、真实首结果与全成本，最终图表/论文仍在完整范围。

主要证据：`d-controls-v1/old-output/old-output-control-closeout-v1.json`、
`old-output-family-comparison-v1.json`、`reviews-v1/`、`owner-v1.json`、
`idle-cost-settlement-v19.json`，均位于本执行ROOT；运行时与实际wire保留ignored。

## v34 历史状态（2026-11-06）：原生已知 View K 控制首九格闭合，保留工程失败

本轮实际完成固定三个家族的原生 Store/K/新来源准备、九格首结果、来源与
View/应用/动作/完整输入审计、逐条质量审阅和 v18 空闲结算，属于实质进展。
当前没有活动实验进程。旧输出可检索性控制、52 READ/7池补采及最终确认、
外评、全成本与论文仍待执行，完整目标未完成。

按已声明的方法顺序，在固定首八家族的 24 方法单元中选择首个合格 donor，
最多每家族一个 before，得到原缓存 A05/A33/B03。增量缓存 B03 不增加一个
独立状态，另五个无合格 View 的家族保留，未以较好结果或后续回合填充。
原生准备真实复制 Store、打开已完成交付 snapshot 引用并导入固定新来源
12/8/8条。A05 保留首 View revision1，虽然当前缓存 revision7；打开后的
投影与旧实际回包逐值一致，查找不改 Store，旧 Source 值保持不变。

明确声明的 K 只含首个 View 引用；实际 Host 历史仍保留所有 7/1/1个旧
回包及其他完整字段，因此没有把一个显式引用当全部 Host 知识。三方法从
同一原生 captured before 执行，原缓存首次工具结果直接复用，没有重执行。
每个实际请求均通过原生引用读取和原额度，新增来源、query、read_goal、
返回预算与原生菜单保持共同合同。没有 given-readout with K。

| 家族 | 原缓存 | 增量缓存 | E3 u32 |
|---|---:|---:|---:|
| A05 | F：发送前模板拒绝 | W：仍答旧3B | Q：3A正确，租期/3C缺失 |
| A33 | Q：家庭实测遗漏 | Q：家庭实测遗漏 | W：声称只有诊室实测 |
| B03 | W：Priya仍在原团队 | Q：仅要求再检索 | W：Priya仍在原团队 |

合计 C0/Q4/W4/F1；实际发送的八个输入均材料 partial，未发送格材料 unknown，
未把预备/拒绝的 packet 算作 Host 已收到。来源作者审阅，非独立盲审；这是
三个已有 TRAIN 暴露的相关家族，非九个独立未见任务。A05 原缓存的首次
读出因我的 frame 工程错误未发到后端，不能归因于策略质量。完整三方法
有效共同 Host frame 仅 A33/B03 两家族；A05 增量/E3 仍使用共同有效 frame，
三方法原生工具 packet 的 before 比较则保留。不能借此声称学习胜出、等效
或总体零作用。

A05 的 E3 实际读到本人更正为 3A，并把 3D 留为助手专有信息，但没读到
租期 March14 next year 和尚未取得文件的下月3C计划。助手“已更新 profile”
只是转述，不是实际保险、地址或 typed record 更新。A33 的旧诊室5ft11和
他人身高被保持，但家庭晨间、赤脚、门框实测5ft11.25均未取回；治疗好奇
不能变成实测增高，也没有提供医学建议。B03 原缓存和 E3 读到新增临时职责，
正确保留 Senior Technical Lead，却漏掉 Priya 已换项目/经理的本人报告。
部分回包只含旧的内生公开问题；它不是新的本人事实。

八个实际 provider 请求与真实响应 trace、保存的 wire 逐值一致。21 次 Host
可见 View 出现、10 个独立完整 payload，以及两个原生当前工具 View 均
做来源角色/时钟/全文绑定与审阅；其中 A05 工具 View 没有进入实际 Host
请求，不得记 Host 可见。新 View 只是忠实引用问题、阳台或治疗好奇等
原文，不能凭字面忠实证明当前任务覆盖或引用内容本身属实。

九格共有 165 次完整旧 Source 值比较均相同，原生 sources() 投影读取不
改 Store，应用表一致，没有 canonical semantic record 或业务写入。原生
K读取9次，每格1次。52次选择均在实际合法菜单中：REFRESH7、SEARCH9、
READ27、HANDOFF9；操作结果48次，其中HANDOFF5。三个 E3 格的24次实际
forward 均核对完整 before、参数、菜单/头 ID/顺序、logits/probabilities 和
选择，输入9,361–13,552 tokens，总287,238输入 tokens已计入原生成本，
没有截断或新模型重放。它不证明整个来源库交付或外部大语料输入可容纳。

失败与修正全部保留，首次结果没有替换：

- 最初误用缺 LangGraph 的 CUDA 环境，导入即停止，尚未创建 Store 或模型。
  现有 Host 环境完成原生准备，合并 CUDA/Host 依赖经实际导入确认。
- v1 在 A05 原缓存首次原生工具返回后，因 frame 预期字典漏了原生
  given_retrieval_request 元数据而停止。工具结果完整保留，v2没有重执行。
- v2 复用该 packet，首次 Host 读出却因我在历史中间追加 system 消息而被
  Qwen模板发送前拒绝。HTTP0、E3加载0，原生生成槽0→1已消耗，不退款、
  不重置、不重发。v3只执行剩余八次工具比较和八次首次读出。新上下文
  追加在原首 system 完整文本之后，其他旧消息/选项逐值不变，并用实际
  tokenizer预检完整wire。v1/v2代码、无效frame、首失败和成本均保留。
- 只读绑定审计又暴露了三个目录/投影假设：sources()添加formation_status，
  与底层行结构不同；发送前拒绝没有发出trace事件，文件也不存在；
  history.sources为空，初始7条实际来自initial请求的incoming_sources。
  按原生投影、已知零派发失败分支、既有完整初始来源绑定修正，没有删除
  未知字段、伪造缺失输入或改动 Source/模型结果；失败审计计时保留。

实际 API 为8次 HTTP、75,003已知 Host 总 tokens，新增 unknown0/0；E3仅一次
GPU2 FP32加载、24次本地forward。本地输入287,238 tokens与Host总tokens
分开报告。33次新共享准入预留=24本地+9读出槽，其中1次发送前失败；不是
33次HTTP。v1/v2/v3子进程CPU合计144.330480秒已各自入账，含原生/加载
86.856223秒、客户端残余57.474257秒，父协调开销单列账本phase。声明GPU
作业区间合计0.060982小时含失败导入和Host等待，不是活跃CUDA时间或货币。

确认所有控制进程退出、九格质量/材料/动作/输入闭合后，v18一次性结算
16个闭合离线计时、46.74 CPU秒，包含准备与绑定失败步骤。原limits、
generation、requests、embedding未改，原生、失败协调器、客户端和前次
成本没有重复计费。作者/未计时CPU unknown，不是零；结算未被GNU time
包裹，不得重跑v17/v18。

下一步为固定首八家族、七个合格状态的旧Host输出可检索性on/off控制。
它须保留完整实际首HTTP输入、旧回答/回包/K，单独冻结Source排除运行时，
仅改变工具额外检索资格，不删除来源或清除Host旧知识。还需原生 before/
K/新请求/真实packet/backend模板准入验证，随后执行固定52READ/7池补采。
最终候选/checkpoint/评分/预算/N冻结、held256与旧64确认、合格LME451/
Mem2Act400 own-policy/full-input/曝光审计、全成本与论文范围均保留；held及
原生预留test语义正文未读取。

## v33 历史状态（2026-11-06）：三方法新 32 家族全量闭合，实际空闲结算完成

本轮补审最后 80 条，并完成 E3 全量绑定、SDK、实际动作、有限输入审计、
三方法家族比较及 v17 离线结算，属于实质进展。E3 parent28715/child28722
已实际退出，owner COMPLETED/exit0/client CPU 已记账，执行会话 80986 仅
收尾一次。三项新 32 家族正式任务均已关闭；没有活动实验 HTTP/模型进程，
没有重试模型首结果，GPU0/1 服务与 Product 未改动。

| 指标（各 320 请求 / 32 家族） | 原缓存 | 增量缓存 | E3 u32 |
|---|---:|---:|---:|
| C / Q / W / F | 67 / 65 / 121 / 67 | 65 / 56 / 135 / 64 | 95 / 68 / 99 / 58 |
| 材料 complete / partial / insufficient | 84 / 222 / 14 | 76 / 223 / 21 | 133 / 183 / 4 |
| C 且材料 complete | 53 | 48 | 80 |
| 实际收到的 View 引用 / 含 K 出现 | 42 / 163 | 25 / 117 | 0 / 0 |
| HTTP 首响应 | 480 | 490 | 442 |
| 已知 Host 总 tokens | 2,934,163 | 2,873,111 | 2,738,589 |
| 整个子进程 CPU 秒，已记账一次 | 571.723529 | 563.933311 | 1,349.571590 |

统计单位为 32 个已 TRAIN 暴露、相关的生成来源家族，每族两流程、五请求，
不是 320 个独立未见样本。全部首次失败保留，仍由来源作者审阅，非独立
盲审。三方法各 64 个 final-arrivals 请求均 C0、材料 complete0；E3 的
64 个 intermediate-arrivals 仅 C2、材料 complete2。较高总体 C 不能解释为
最终更新问题已解决，更不能自动采用方法。

| 配对差值 | C 宏平均差（百分点） | 家族 bootstrap 95% 区间 | 位置 gains / losses |
|---|---:|---:|---:|
| 增量缓存 − 原缓存 | −0.625 | [−5.3125, 4.3750] | 32 / 34 |
| E3 − 原缓存 | +8.750 | [2.5000, 15.3125] | 56 / 28 |
| E3 − 增量缓存 | +9.375 | [2.5000, 16.2500] | 58 / 28 |

这些是 20,000 次 Random0、32 家族簇重采样的条件描述区间。外生来源的
正文、角色、发生时间与顺序一致；运行 ID/采集时钟差异单独保留。全部
64 个初始完整 HTTP 请求逐值相同，但首批检索参数没有任何一对完全相同，
缺首批检索的位置为 1/3/1。后续自主 query、内生历史及到达状态均可分歧，
故不能将此统计直接归为控制器的同 before 因果收益或 held 确认结果。

E3 真正退出后，先全量绑定确认退出 0，再单独运行 SDK 审计确认退出 0。
完整核对旧 310 条记录字典、provider 输入、答案、Source 绑定及零次 View
记录与全量包相同，之后复用同方法判断、重校全部锚点/Fmask，最后审完
10 条。SDK 的 320 回合含 5,590 次旧 Source 值比较，全相同；新增 262 个
最终助手 Source，Saver 消息一致、应用表/业务状态一致、业务写入 0。
View 命名空间变化 0，不代表更新成功。

实际动作审计覆盖 784 次合法选择：SEARCH109、READ653、HANDOFF22；
操作结果 782 个，其中 HANDOFF20。127 次工具尝试/返回、2 次材料拒绝、
7 次普通已知原文引用读取；没有 USE_VIEW 或 REFRESH_VIEW。实际当前回包
有 551 个原文 packet，其中外生459、内生92，角色 user293、assistant258；
含历史 K 的绑定共 2,228 个原文范围。224 个位置未查询，4 个查询位置没有
当前外生原文范围。这些计数与“已存 Source”“内部观察”和交付效果分开。

完整有限输入审计核对 784 次实际 forward 的原生 before、全部绑定参数、
菜单顺序、决策头、logit/probability ID 和最终选择，逐值相同。输入范围
2,521–9,208 tokens，总 4,604,680 输入 tokens 已计入原生模型成本，所有
truncated=false；没有重新分词、模型加载、forward 或 HTTP。此检查只证明
这些实际给定观察和菜单的完整性，不证明整个来源库交付、Host 正确使用，
也不证明外部 LME/Mem2Act 全语料的 own-policy 输入能够容纳。

新增审阅中，D18 的普通已知原文读取没有被当成受控 View K。D19 区分
照片迁往 SSD 与未报告关闭的手机备份，以及离线已启用和请求 Work/Finance
优先的不同状态。D23 区分已飞、已取消和未订 Boston/拟议 HR 更正，未
验证机型座位布局。E11 未把每周生产率当库存，把 500 箱旧订单误标发票
的回答记 Q，750 箱确认/1,000 箱条件报价、JarSource12箱×12及旧发票
500套×50均需各自原话。F08 区分历史参考、更正/未决邮件差异与当前可用性。
F12 不给 721 补提供方，也不把 745 模拟或 Kevin731 当已观察本人读数。
F14 的 313 实际读到本人转交完成原话并记 C/材料 complete；最终家庭读数
与模板例值未读到，不能以正确诊室基线取代完整报告。这里没有财务/医疗
建议、实时验证或实际交易/记录转交。

保存 D21 批注时，一个错误锚点令整批拒绝，旧 260 条判定完整保留。我把
9,3 的专注音乐助手转述误认为朋友电影转述。核对实际回包和完整答案后，
将明确限定于已取回证据的两条遗漏记 Q；仅有开场白的 COMPLETED 输出
也记 Q 而非 F。修正作者脚本成功退出后才汇总，失败说明和计时保留。
只读成本检查另一次把 idle_settlements 字典当列表触发 TypeError，无状态
或账本改动，未计时 CPU 保留 unknown；过大的历史字典展示不用于判分。

E3 原生模型 CPU671.773663、加载7.743320、客户端残余670.054607 秒合计
上述 1,349.571590 秒，已由 owner 记账一次。本地 GPU2 FP32 的整个作业
区间为 2.726773 小时，包含 Host 等待，不是活跃 CUDA 计算时间。shared
generation calls=1,226=442 HTTP+784本地 forward；不是 1,226 次 HTTP。
原生新增 unknown 用量0/0，历史 unknown 保留，远端硬件和货币成本未知。

确认三项任务质量/SDK/动作/owner CPU/家族比较闭合、实际进程全部退出后，
v17 一次性结算 99 个闭合离线计时、172.83 CPU 秒，含三项失败命令。
原 limits、generation、requests、embedding 未改，早期结算、模型、加载及
客户端成本没有重复计费；作者及未计时 CPU unknown，不是零。不能重跑
v17；计时扫描写入器和结算命令没有被 GNU time 包裹。

下一步仍需原生已知 View K、旧输出可检索性控制及固定 52 READ/7 材料池
补采。View 候选为固定首八家族的 24 方法单元、4 个合格单元、3 个家族，
至多每族一个 before×三方法，进一步资格前最多9次条件读出。现有原文
预算准备器和旧 CPU 协调器并不实现 View K/新到达/A100 门禁；入口合同
核对已保存，但实际原生 K、Store/full frame 和控制调用仍为 0。正式冻结
运行时没有 Source 排除选项，旧输出控制须单独冻结已验证适配的运行时，
保留完整 Host 旧回答/回包/K，仅改变工具额外检索的来源资格。

最终候选/checkpoint/评分/预算/N 冻结、held256与旧64确认、合格 LME451/
Mem2Act400 外评、全成本与论文图表仍待完成。held 与原生预留 test 的语义
正文未读取；历史公开来源暴露继续按开发数据报告。完整目标仍 active。

## v32 历史状态（2026-11-06）：E3 前 240 条完整来源审阅闭合

本轮新增七个完整家族、70 条逐条审阅，属于实质进展。唯一正式 worker
仍为 parent28715 / child28722 / exec80986，写入快照已关闭 262/320；实际
`/proc` 与冻结配置相符。GPU2 FP32、运行时、数据、Host 和 GPU0/1 服务
未改动，没有模型重试、额外 HTTP、真实 Store 控制或离线成本结算。

| 指标 | E3 前 220 | E3 前 240 |
|---|---:|---:|
| C / Q / W / F | 65 / 42 / 71 / 42 | 73 / 44 / 78 / 45 |
| 材料 complete / partial / insufficient | 85 / 132 / 3 | 97 / 140 / 3 |
| C 且材料 complete | 52 | 60 |
| 实际收到的 View 引用 / 含 K 出现 | 0 / 0 | 0 / 0 |
| 已在原账本记录 HTTP | 300 | 325 |
| 已知 Host 总 tokens | 1,891,022 | 2,044,856 |

240 条来自 24 个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求，
不是独立未见任务；来源作者审阅，非独立盲审。195 个完成、45 个失败均
保留首次结果。中间 48 个请求中 C1、材料 complete1，最终 48 个请求中
C0、材料 complete0；整批 320、不可变 SDK、实际动作及 owner CPU 尚未闭合。

先绑定实际关闭的 220 条，完整逐值核对旧 170 条记录字典、provider 输入、
答案、Source 绑定与所有 View 记录，才复用同方法判断；之后同样完整核对
220→240。七次保存和两次审阅汇总均确认实际退出 0 后，才进入依赖步骤。
失败按最后已响应输入审材料，未发送的已存正文不算交付，失败答案不算
后续 K；未跨方法复制分数，未重跑首结果。

C07 初始 Tawaraya/June 与已替换的 Sowaka 区分正确。后来的 Sowaka
June20–25、June19 计划抵达与住宿空档、尚未接受的 Hoshinoya 保留及
Takayama 晚十月意向未完整取回。178 虽取回早期 Takayama 研究原话，仍
缺当前京都订房和抵达更新，不能据旧原话声称当前住宿仍是 Tawaraya。
C10 把整体练习正确率 65–68% 标成 topic scores 的初始回答记 Q；材料
完整的 186 缺关键改期原话引语，187 补齐后可记 C。后来的已订 June21、
仅有条件的 June14、Becker72% 与各主题 68/73/76 未读取。36 天/87 小时
仍是报告中的假定规划窗口，没有独立计算成当前剩余时间或提供应试建议。

C23 的 190 从运行日期 November2026 推断护照到期年 2027，实际本人报告
明确为 September14,2025，记 W。另一流程的 June2025 可由明确到期年及
此前三个月缓冲推导，并非用采集时钟补年。妻子的 March7,2026 与儿子的
估计月份分开；早五月计划、放弃 April11 空位与尚未预约的五月日期更新
没有取回。未验证护照通行规则或执行预约。
C26 初始 200–202 答案正确但材料 partial：本人日期/面试组/地点已收到，
2pm 更正只有准确的助手转述。205 本人材料齐备，206/207 却把助手确认句
当本人报告引语，记 Q；206 还改写了引号内时间标点。后来的 3pm 确认与
4pm 待确认提案、Rina April16 更新未读取，没有日历写入或年份/时区推断。

C29 的可选 $45 橄榄树被漏答，陶瓷茶具被写成木制，部分回答还把 Emily
给母亲的披肩写成她给自己的物品。213 漏掉“可能只送橄榄树”的新想法，
按遗漏记 Q，没有把尚未决定的想法判成已完成换礼。216 的所谓本人引语
拼接了 Marco、茶具和助手更新。最终本人明确下单付 $65、三天后发货，
214/219 未读到而仍否认交易确认，记 W；报告中的购买与真实工具交易、
未来发货与已送达仍分开。
D02 初始更正、购买日和两年保修原话完整；226 在引号内将 think about
改成 think of，记 Q。后来 1920x1200 的本人系统检查与保持该条目的指令、
PSREF 争议和旧邮件解释均未读取。这里只审归属报告，不独立认证物理面板
或保修覆盖。D17 初始设备默认值与 Firefox 设置原话完整，237 却把助手
愿意向 IT 确认的承诺当政策原话；后来的 work Edge/home Chrome、Firefox
设置未迁移、Chrome 部署延期等未取回，没有实际设置修改。

只读检查进展文件时，我先假定顶层有 D 字段，触发 KeyError；随后依据
实际键 D_optional_incremental 更新写入器。失败没有改动审阅或实验产物，
未计时 CPU 保留 unknown；过大的 manifest 展示被截断，没有据此判分。
输入审计仍仅覆盖旧前 120 条、274 次实际 forward，没有外推到 240 条或
外部大语料。62 个闭合 post16 计时共 62.25 CPU 秒待结算，包含既有失败；
作者/未计时 CPU unknown。receipt17 未执行，原生 HTTP/本地模型成本仍
由唯一活动 worker 记入原账本，没有二次计费。

下一审阅位置 index240/D18，扩展前完整核对现有 240 条。正式 E3 真正
结束后先全量绑定，确认成功再串行 SDK 审计，之后补齐整批质量、实际
动作、完整输入与成本审计。三方法家族比较、实际 K/旧输出控制、52 READ/
7 池补采、最终候选/评分/预算/N冻结、held 确认、合格外评和论文范围
继续保留。预留确认与原生测试语义正文未读取，完整目标仍 active。

## v31 历史状态（2026-11-06）：E3 前 170 条完整来源审阅闭合

上一轮完成前 120 条和输入审计，本轮补审已关闭的五个完整家族，属于实质
进展。唯一正式 worker 仍为 parent28715 / child28722 / exec80986，快照关闭
211/320；实际 `/proc` 与冻结配置相符。GPU2 FP32、运行时、数据、Host 及
GPU0/1 服务未改动。没有重跑模型、追加实验、真实 Store 控制或成本结算。

| 指标 | E3 前 170 |
|---|---:|
| C / Q / W / F | 55 / 29 / 55 / 31 |
| 材料 complete / partial / insufficient | 69 / 98 / 3 |
| C 且材料 complete | 45 |
| 实际收到的 View 引用 / 含 K 出现 | 0 / 0 |
| 已在原账本记录 HTTP / 已知 Host 总 tokens | 231 / 1,445,791 |

这是 17 个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求，非
170 个独立未见任务；仍由来源作者审阅，非独立盲审。全部首次失败保留。
中间 34 个请求中 C1、材料 complete1；最终 34 个请求中 C0、材料 complete0。
整批 320 质量、SDK、实际动作、owner CPU 和三方法比较仍待闭合。

本轮直接绑定实际已关闭的 170 条，完整逐值核对旧 120 条记录字典、provider
输入、答案、Source 绑定和零次 View 记录，再复用同方法判断并重校全部
锚点/Fmask。未生成中间未执行前缀或跨方法复制分数。所有新答案均完整
阅读，失败只按最后已响应输入判材料，不把已存或未发送材料算作后续 K。

B26 初始 Austin/Portland、已搬迁与未提出访问计划的状态正确；准确的额外
中间名复述不强制要求一个无关的唯一 gold Source ID。后来 Chloe 已实际
搬到 Eugene、下月才搬回 Portland，Austin 行程从 mid-September 意图改为
第二周目标，航班仍只在研究、Chloe 能否参加未知，这些均未取回。上一个
孩子较早出生，不会把第二胎 late-September 的预产期改成更早日期。
C01 初始 firm240 与尚未安装正确，潜在亲友线索不是一个已收到的报价；
原话流程中无角色标记的助手引语仍记 Q/材料 complete。新 firm260、DIY
May10、条件245组合、非正式210和他人承包商230未读取，没有实际电工或
历史 forget 对应的 Store 删除操作。

C02 初始一条流程完整材料足以透明计算 grant 的 April15 提前目标，回答
正确计算可记 C；另一流程虽同样具备材料，却只答 lease 的 April22，记
Q/材料 complete，提供的准确原话仍可满足已答部分的引语要求。后来的
grant硬截止14/目标11、书面 notice/拒绝口头、被否决的 grant延期22 与
lease个人目标22的不同作用未取回。草拟和计划发送不变成已提交；没有
法律验证或虚构具体年份。

C04 初始诊断原文、医生/科室/医院/时间、条件 ENT 和朋友就诊材料完整。
把过去已停看的 Dr.Tan 单独标成未实施改期提案记 Q；合并标题中明确按
已停止就诊描述的回答可记 C。楼2/层4仍仅属于内镜，没有推成复诊房间。
后来已改至 April28、未实施 April30 提议、鼻窦症状消退及朋友 May5 预约
未取回。这里仅审来源报告，没有医学建议或真实预约修改。
C05 初始航班 May18–25/IKXR47/每人往返640正确。原话流程先只得到日期
片段，后来获得用户 reference 后可完整回答航班问题，不强制补齐未询问的
酒店 Source；额外用助手“pencil in”作改动已解决的原话证据仍记 Q。后来
真正改到 May26、两人地面预算3200且不含机票、获批休假与并未改票的
May28提案、拒绝变更费用及朋友旧预订未取回；一次查询只补到了放弃
Faroe 的原话，仍缺日期和预算更新。没有独立航空验证或真实改签。

已有输入审计仍只覆盖前 120 条的 274 次实际 forward，没有重跑或外推到
170 条，更不能用它代替整库交付、Host正确性或外部大语料可容纳性。三族
View候选、旧输出可检索性、52 READ/7池补采仍未原生执行。49 个闭合
post16 计时共 42.00 CPU 秒 pending，作者/未计时 CPU unknown；receipt17
仍仅准备、未执行。活动期间原生模型和 HTTP 成本照常入原账本，离线成本
不混入 owner 的原生差量计算。

下一审阅位置 index170/C07，扩展前完整核对现有170条。E3 实际结束后仍
先全量绑定、再串行不可变 SDK 审计，完成整批质量/动作/成本后做家族比较
和空闲差量结算。全部控制/补采、最终候选/评分/预算/N冻结、held确认、
合格外评、全成本和论文范围保留。预留确认正文和原生预留测试语义内容
未读取；历史 LME 等公开来源曝光继续按原审计作开发数据，不宣称未见。
完整目标仍 active。

## v30 历史状态（2026-11-06）：E3 前 120 条闭合，实际决策输入核对完成

上一轮完成前 80 条审阅，本轮补齐至 120 条并审计实际模型输入，属于实质
进展。唯一正式 worker 仍为 parent28715 / child28722 / exec80986，写入快照
关闭 145/320，实际 `/proc` 与原配置相符。GPU2 FP32、运行时、数据、Host
及 GPU0/1 服务保持不变，真实控制和离线成本结算均未执行。

| 指标 | E3 前 120 |
|---|---:|
| C / Q / W / F | 36 / 20 / 39 / 25 |
| 材料 complete / partial / insufficient | 41 / 76 / 3 |
| C 且材料 complete | 26 |
| 实际收到的 View 引用 / 含 K 出现 | 0 / 0 |
| 已在原账本记录 HTTP / 已知 Host 总 tokens | 163 / 1,039,549 |

统计单位是 12 个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求，
不是 120 个独立未见任务；仍由来源作者审阅，非独立盲审。80→90、90→100、
100→110、110→120 的全部旧记录字典、provider 输入、答案、Source 绑定和
View 前缀均逐值相同后，才复用同方法判断并重校锚点/Fmask。整批 320 的
质量、不可变 SDK、实际操作、owner CPU 与三方法比较仍待闭合。

B05 初始共同选择 Iris 的原话完整，明确的 Elara 新备选位次却没有用户确认；
把朋友自己孩子的 Matteo/Luca 写成给本用户的提案，也与归属不符。随后
共同改回 Elara，再出现妻子提议 Iris、用户尚未同意的分歧未读取；旧原话
引用正确不代表当前共同决定正确。B12 多次查询主要得到同一份号码更正，
最初误抄的号码与后来真实停用、仅拟议恢复的号码分开判断。邮箱、短信
偏好、周末响应、旅行与维修代管均有各自材料要求，没有实际消息或表单
提交。一次普通已知原文引用读取不等于预定的受控 View K 查找。

B21 初始岗位、$82,000、更正历史、工作周和已开始的咨询安排正确；一条
流程缺用户考试原话，材料 partial，另一条具备完整原话。后来工资再次更正
为 $82,500、未来仅拟议 $85,000 和秋季跨项咨询审批未读取。没有补货币
辖区、年份或独立 HR/薪资验证。B25 按明确的第二/第四个星期五解释复现
规则，不把含混 biweekly/bimonthly 词自动改判成无间断十四天周期。完整
用户原话已可用的原话流程，仍两次把助手的机器人活动复述当“我的报告”
引语，分别记 Q/材料 complete。四月生效的周二新时段、周四原时段、每周五
活动、已停钢琴与未确认攀岩，以及之后五月提案和另一孩子日程未取回。

保存最后十条批注时，我把 index113 的问题引语写成另一回合的措辞，字面
校验拒绝了整批写入，旧 110 条保持原样。我又在该命令失败后过早调用汇总，
汇总因只有 110 条而拒绝。两次失败说明和失败汇总计时保留。只把问题引语
改为实际答案片段、保留判定及模型首结果，确认保存命令退出 0 后再单独
运行汇总 v2，120 条成功闭合；未放宽字面校验或重跑模型。失败作者 CPU
未计时，保持 unknown；保存 v2 和失败/成功汇总计时均进入待结算差量。

新增只读审计覆盖前 120 条里全部 274 次实际有限决策。先按冻结投影重建
输入，再解码 `literal_tables_v1`，逐值核对完整原生 before、所有 action 的
target/parameters、顺序、决策头和 logits/probabilities 的 ID，以及最终选择。
这些均通过。初查时把 questions 字典误作列表导致 KeyError，直接比较编码
表和原生列表也返回 false；正确解码后比较，未改活动运行时、投影或数据。
这些初查 CPU 未计时，保留为 unknown，没有模型重放。

| 实际决策输入审计 | 结果 |
|---|---:|
| 已记录本地 forward / 新 forward | 274 / 0 |
| 实际输入 tokens 最小 / 最大 | 2,521 / 9,126 |
| 已计入原生计量的本地输入总 tokens | 1,597,256 |
| 输入/参数/菜单 ID/顺序核对 | 全部一致 |
| 记录中的 truncated | 全部 false |
| shared generation calls | 437 = 163 HTTP + 274 本地决策 |

冻结的 `NativeDecision.predict` 在完整序列或决策头超出容量时会拒绝 forward；
当前上限为 max_len16384/head_max_len2048，概率仍标记未校准。此审计没有
加载模型、重新分词、forward、HTTP、真实 Store 访问或成本账本写入。它
证明的是这些已提供原生观察与菜单在模型输入中的完整性，不是整个 Source
银行都已交付、不保证 Host 使用正确，也不证明 LME/Mem2Act 大语料能够
完整容纳。上述本地 tokens/calls 已由原生计量，不在审计中重复计费。

46 个闭合 post16 离线计时共 35.63 CPU 秒 pending，包含先前失败复用、本轮
失败汇总、作者保存 v2 和实际输入审计；作者/未计时 CPU unknown。receipt17
仍仅准备、未执行。下一审阅位置 index120/B26，扩展前须完整核对现有 120
条及所有 View。E3 真实退出后先全量绑定、再串行不可变 SDK 审计，完成
整批质量/操作/成本后做家族比较和空闲差量结算。三族 View 候选的进一步
原生资格、真实 K/旧输出控制、52 READ/7 池补采、最终冻结确认、外评、
全成本和论文仍待完成；held 正文与 test split 未读取，完整目标 active。

## v29 历史状态（2026-11-06）：E3 前 80 条闭合，八家族候选证明收齐

上一轮完成 E3 前 40 条审阅，本轮继续实际完成前 80 条，属于实质进展。
唯一正式 worker 仍是 parent28715 / child28722 / exec80986，快照关闭 85/320，
实际 `/proc` 配置与原生 driver 已核对。GPU2 FP32、冻结运行时、Host、数据
及 GPU0/1 服务未改变；没有追加模型实验、真实 Store 控制或成本结算。

| 指标 | E3 前 80 |
|---|---:|
| C / Q / W / F | 26 / 11 / 27 / 16 |
| 材料 complete / partial / insufficient | 29 / 48 / 3 |
| C 且材料 complete | 19 |
| 实际收到的 View 引用 / 含 K 出现 | 0 / 0 |
| 已在原账本记录 HTTP / 已知 Host 总 tokens | 107 / 678,236 |

这些位置来自八个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求，
非 80 个独立未见任务。由来源作者审阅，非独立盲审。中间 16 个请求中 C1、
材料 complete1；最终 16 个请求中 C0、材料 complete0，整批 320、SDK、效果、
owner CPU 和三方法比较仍未闭合，不能据此前缀采用方法。

40→50、50→60、60→70、70→80 均先完整比较所有旧记录字典、provider 输入、
答案、Source 绑定与 View 记录，再复用同方法判断并重校锚点/Fmask。第一次
50 条复用因我在绑定命令仍运行时提前启动而失败；绑定已写出 packet，但尚未
写出 View 文件。失败步骤未写判定。我等待原绑定成功后才以新计时执行复用，
保存失败说明和原计时，不改模型结果、不补防御性文件回退。后续依赖步骤
显式确认前一命令实际退出。该离线失败成本仍计入 pending。

A16 将“收到的材料中缺 merit”与“系统未记录分类”的全局否认分开判断。
失败回合虽收到扩展学位名称，更正不会自动进入后续已完成回合的 K；
JSON_ACTION_MALFORMED 与截断分别保留。后续短名称恰好符合证书更正，却把
更正历史说成只有 Computer Science 误会，仍不是完整正确回答。最终查询
主要返回旧 Host 答案和旧问题，含真实范围截断及一个材料额度拒绝。
A29 同样将当前数字与适用范围分开：74 的记忆错误、72 的更正、暂时报告
适用的 78，以及最终欧洲轨道限定必须按各自请求时间判断。最终答对 72，
若同时否认 78 通知与 Pedro85 的历史，仍判 W；没有引入“某角色永远更权威”
的控制器规则。

A33 初始原话完整、答对诊所测量与旧执照、他人数据；后来漏掉晨起赤脚的
居家测量可记 Q，但否认已报告的未来预测记 W。未从助手文字推断诊所测量
时间、赤脚规程或治疗效果。B03 初始原话同样完整，额外将 Tom 的过去职位
说成图表条目、或否认已收到的其他同事职位，分别保留为 Q。后来 David
继续任 Senior Technical Lead 并不抵消新增临时职责、Priya 调组和未获批准
永久职务提案的覆盖要求。没有执行 HR、证书、课程或医疗操作。

三方法的预定八家族初始 View 候选证明已全部收齐，只读封存 JSON，没有
实际 K 查找、Store 克隆或控制读出：

| 方法 | 符合初始 View 条件 | 初始失败保留 | 初始无接收 View |
|---|---:|---:|---:|
| 原缓存 | 3 | 1 | 4 |
| 增量缓存 | 1 | 1 | 6 |
| E3 | 0 | 0 | 8 |

24 个方法单元里四个候选仅涉及 A05、A33、B03 三个来源族，B03 跨方法重复
不会增加独立来源或第二个状态。其余五个家族保留不合格状态，不用后续
回合、较干净 View 版本或其他家族填满。按每族最多一个 before、三方法的
原协议，在进一步原生资格核对前至多九次条件读出；这是容量上界，不是
已选定/已执行结果。实际 native K、同 before、完整 Host 历史和兄弟回执、
新到达上下文与输入绑定仍须在正式运行结束后证明。

另只读核对了 52 READ 补采的现有入口：显式 nominated_actions 要求两个或
三个真实 action ID，`--branch-sampling` 没有 first-action 选项。实际准备时应
用冻结的新 READ 加同 before 已执行过的原绑定作为比较提名、精确选择状态，
再筛出仅新 READ 的执行清单；旧提名不重跑，不添加填充控制。共同
fixed_context reads4、续行两步和真实剩余额度保持；目前仍未准备或执行这些
原生分支。旧 139/功能八项、57 状态及 C 的 24 状态/48 读出上限保持原样。

receipt17 仍仅准备、未执行；31 个闭合 post16 离线计时共 15.41 CPU 秒 pending，
含失败复用，作者/未计时 CPU unknown。下一审阅位置 index80/B05；扩展前
完整核对现有 80 条。E3 真正结束后先全量绑定、再串行不可变 SDK 审计，
全质量/动作/成本闭合后做家族比较和空闲差量结算。真实 K/旧输出控制、
52 READ/7 池补采、最终冻结确认、外评、全成本及论文范围保留；held 正文与
test split 未读取，完整目标仍 active。

## v28 历史状态（2026-11-06）：E3 前 40 条来源审阅闭合

上一轮完成增量全量闭合并启动 E3，属于实质进展。本轮核对同一实际配置的
parent28715 / child28722 / exec80986 仍在运行，快照关闭 42/320。唯一正式
HTTP/本地模型 worker、GPU2 FP32、冻结运行时、配置和 Host 均保持不变。
没有重跑模型首结果、追加并发实验、执行真实 Store 控制或离线 CPU 结算。

| 指标 | E3 前 40 |
|---|---:|
| C / Q / W / F | 16 / 6 / 9 / 9 |
| 材料 complete / partial / insufficient | 15 / 23 / 2 |
| C 且材料 complete | 9 |
| 实际收到的 View 引用 / 含 K 出现 | 0 / 0 |
| 已在原账本记录 HTTP / 已知 Host 总 tokens | 55 / 341,875 |

这是四个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求，非 40 个
独立未见任务或完整方法结果；仍是来源作者审阅，非独立盲审。九个首次截断
全部保留。三个扩展边界分别完整比较 10→20、20→30、30→40 的全部原记录
字典和 View 记录，再复用同方法判断并重校锚点/Fmask。新整理的复用脚本只
完成这些逐值核对与锚点验证，没有按正文相似度复制跨方法分数。

A02 的中间到达增加评审、入职日、员工号和办公信息，却没有改变所问名称，
因此已有原话仍可能足以回答；员工号没有被用来推断年份。内容流程缺用户
本人经理原话，虽答对名字仍记材料 partial；原话流程具备完整核心材料。
在真正 vendor 表单和更名撤销尚未报告之前，将习惯性错名标为旧 vendor
模板或已取消名称，记额外分类断言 Q。最终新增的更名后撤销事实则必须读到，
不能用旧名称未变来替代状态解释。

A05 初始七份原文完整区分当前、旧址与亲友地址。直接称“我已保存 ZIP”的
行政效果断言，与明确标注“助手曾确认保存”的转述分开判断。原话答案中的
额外小引语把原文 mixing up 改写为 mix up，保留为原话忠实度 Q，核心地址
正确与材料完整不受混淆。后续实际 3A 更正、明年 3 月 14 日租期、仅拟议的
3C 和最终撤销未读取；连续失败仍只保留真实最后已响应输入，不增加后续 K。
没有执行地址、保险、邮政或租约操作。

A14 初始两流程分别缺用户申请编号原话或用户国籍/护照原话，但可从助手
复述答对核心值，因此答案 C 与材料 partial 分开记录。原话流程下一次查询
已得到完整用户材料，回答却把助手“I've noted…”作为“我的报告”引语，记
Q/材料 complete；后一次改引用户真实提交原话，记 C。两份首结果都保留。
后来更正的当前护照、仅将来可能生效的编号和公司模板中的他人编号没有
取回。这里没有独立验证护照签发、国籍规则或给予移民建议。

已准备 `compare_d_new32.py`：要求三方法全 320 项的整答、View、SDK、动作及
owner CPU 闭合后，核对共同外生来源，单列运行时 ID/捕获时钟差异、初始
完整 HTTP 输入和首查询批次，再按 32 个来源族做 20,000 次 seed0 重采样。
主指标 C、材料完整和补充联合指标分开报告，不把 320 条当独立样本，也不
从逐方法不同查询的自主结果直接推断控制器因果。脚本仅语法检查，三方法
正式比较未执行、没有采用或确认结论。

也已准备 receipt17 结算脚本，仅做 AST 检查、未导入或执行。它要求上述三
方法全量闭合、完整家族比较和实际空闲后，才差量结算 receipt1..16 后的
计时，保持额度与 generation/embedding 不变；实际结算不可 GNU 包装。
receipt17 文件仍不存在。当前 15 个闭合离线计时共 5.24 CPU 秒 pending；
作者/未计时 CPU unknown，活动期间未写成本账本。

下一审阅位置 index40/A16；扩展须完整核对当前 40 条记录及全部 View。
E3 真正退出后仍先全量绑定，再串行不可变 SDK 审计，补齐整批质量、动作和
成本。真实 View K/旧输出控制、52 READ/7 池补采、最终冻结确认、外评、
全成本和论文范围全部保留，held 确认正文与 test split 未读取，目标 active。

## v27 历史状态（2026-11-06）：增量全量闭合，E3 正式运行

增量 worker child3591601 正常退出，320 个首结果完整保留。按既定顺序先全量
绑定实际输入，再审计不可变的逐轮 SDK 状态，随后完成整答、View、实际动作和
成本闭合。在真正空闲时执行一次 receipt16，再手动串行启动 E3 新组 320 项。
现在唯一正式 worker 是 parent28715 / child28722 / exec80986，快照关闭 18/320；
实际 `/proc` 配置与原生 driver 已核对。保存的 E3 update32 在 GPU2 以 FP32
加载验证通过，MHA fastpath 与 reference compile override 为 false。
GPU0/1 的既有 Host 服务、冻结运行时、数据、Host 输入和 Product 未改动。

| 指标 | 新组原缓存全 320 | 新组增量缓存全 320 |
|---|---:|---:|
| C / Q / W / F | 67 / 65 / 121 / 67 | 65 / 56 / 135 / 64 |
| 材料 complete / partial / insufficient | 84 / 222 / 14 | 76 / 223 / 21 |
| C 且材料 complete | 53 | 48 |
| 实际接收 View 引用 / 含 K 出现 | 42 / 163 | 25 / 117 |
| 已记录 HTTP / 已知 Host 总 tokens | 480 / 2,934,163 | 490 / 2,873,111 |

这些是 32 个相关、已有 TRAIN 暴露的生成来源族，每族两流程、五请求；由来源
作者审阅，非独立盲审。主指标 C 的来源族宏平均分别为 0.209375 与 0.203125，
联合材料完整只是补充指标。E3 尚未结束，三方法完整家族配对分析和采用结论
仍待完成。增量的 128 个中间/最终位置材料 complete 均为 0，中间 C1（A02
所问名称未变）、最终 C0/64；不能将此结果写成更新链路已经改善。

全量绑定包含 929 份带原角色/时钟的原文范围；前 300 条记录字典、provider
输入、答案、Source 绑定及全部 117 次 View 与完整结果逐值相同后，才复用
已保存的 285 条同方法判断并重校锚点/Fmask，再审阅剩余 35 条。没有跨方法
复制成绩。新增 E11 的两个 View revision1/2 与 F08 的一个 revision1 均保持
原值，全部 25 个实际引用、117 次接收已审完；文本忠实与当前覆盖、Host
角色使用和外部实际效果分别判断。

E11 后续的已确认 750 箱、JarSource 144 罐、仅条件提供的 1000 箱和历史
500 sleeves 发票未取回。初始把已完成的配方单位转换归入未来计划、或把
配方 ounces 标为发票单位，分别保留为额外状态/分类断言 Q。F08 后来的
7742 更正、未解决的 7740 邮件主题和最终正文核对未取回；助手说“及时取到”
不等于用户明确报告取件完成。这里只审合成历史代码，没有实际访问或验证
承运商规则。F12 分数缺失与全局否认分开判断；F14 助手的医学解释不升级为
医生报告，后续已完成的资料转移也不能被旧回答否认。没有外部账户、订单、
诊断或真实资料转移操作。

SDK 审计覆盖全部 320 回合，5,563 次旧 Source 值比较保持原样，成功回合
新增 256 个最终助手 Source，Saver 消息一致、应用状态保持，41 回合 View
命名空间发生变化，审计写入为 0。报告中继承的 mutable-bank 失败说明已明确
标为更早审计实现的历史反思；本条件的 SDK 全量审计首次运行即通过。
动作审计首次因把 controller-result 事件数等同所有工具返回而停止。只读定位
到 index60/245 的两份 `read_limit_exhausted` 回执后，按实际 ToolMessage ID、
逐值相同的 payload 和明确的零操作错误包修正审计，失败计时保留；没有重跑
模型或工具。修正审计覆盖 690 次合法选择、678 次操作、369 READ、54 REFRESH、
3 USE_VIEW；180 次工具尝试/返回中的两个错误仍保留，不自动变成 Host F。
247 份当前接收原文包含 165 份外生来源与 82 份问题/旧 Host 输出。

对全部三个实际 USE_VIEW 的完整轨迹核对发现，它们仅在初始请求 index200、
230、265 内发生：显式 known refs 为空，没有新增/待处理事件，随后直接
HANDOFF，没有后续 READ；其中 D17 是失败回合，其材料不算后续完成回合的 K。
最终 64 个位置中只有 8 个发起查询，两个收到当前外生原文范围。上述是自主
流程的观察证据，尚未执行的同 before、真实 View K 加更新控制仍必须完成。

增量进程 CPU 563.933311 秒、wall 9740.840520 秒与 490 HTTP 已由原 owner
在原账本入账一次，新增未知 generation/embedding 为 0/0。receipt16 在空闲期
一次结算 76 个闭合离线命令、211.76 CPU 秒，包含失败审计/Ruff，未改额度、
generation 或 embedding，未重复计原生/模型/客户端成本。E3 启动后新增四个
闭合离线计时 1.50 CPU 秒仍 pending；作者/未计时 CPU unknown，不作零成本。
不在 worker 活动期执行离线 CPU 结算，也不 GNU 包装扫描计时的写入器。

E3 前 10 条完整回答已审阅：C3/Q1/W5/F1，材料 3 complete/5 partial/2 insufficient，
联合 C+complete3，实际收到的 View 为 0。它只对应一个相关 TRAIN 来源族。
初始空回执与后续原话取回分别保留，内部 READ 不当作 Host 已收到材料；最终
首次截断也保留。下一位置 index10/A02，扩展前须完整比较已有十条记录。
E3 实际退出后仍先全量绑定、再串行 SDK 审计；随后全质量/操作/成本闭合、
三方法统计，再完成真实 K/旧输出控制、52 READ/7 池补采、最终冻结确认、
外评、全成本和论文。held 确认正文与 test split 未读取，完整目标仍 active。

## v26 历史状态（2026-11-06）：增量前 280 条整答和接收 View 闭合

唯一正式 worker 仍是 child3591601 / exec4286，v26 写入时已关闭 297/320，仍在
运行；实际 `/proc` 配置已核对，冻结运行时、数据、Host 和 Product 未改动。
前 280 条完整回答及全部 22 个接收 View 引用、含历史 K 的 102 次出现已由
来源作者审阅，非独立盲审。所有首次失败与实际已响应边界保留。

| 指标 | 增量缓存前 280 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 60 / 46 / 114 / 60 |
| 材料 complete / partial / insufficient | 70 / 194 / 16 |
| C 且材料 complete | 46 |
| 不同实际接收 View 引用 / 含历史 K 出现 | 22 / 102 |

这些位置属于 28 个相关 TRAIN 暴露生成来源族，每族两流程、五请求，不是
280 个独立未见任务或完整 320 成绩。112 个中间/最终位置材料 complete 均为 0；
中间 C1（A02 所问名称未变）、最终 C0。完整方法的 SDK、效果、操作轨迹、
整进程 CPU 与三方法配对结果仍未闭合，不能据此前缀采用方法。

扩展时分别完整核对 240→250 的 240 条记录和 67 次 View、250→260 的 250/67、
260→270 的 260/72、270→280 的 270/92。记录字典、provider 输入、答案、Source
绑定和 View 逐值相同后，才复用同一方法原判断并重校全部锚点/Fmask；
基线仅用于字面正文/角色去重，没有跨方法复制成绩。本轮新增七个接收引用、
35 次出现：D19 一个、D21 四个、D23 两个，各七节点、五次整份副本逐值相同。
D21 原话流程的三个引用 revision1/2/2、Source ID 与 metadata 投影保持原样；
同一解释文本不代表独立证据或相同的缓存生成次数。

D18 多轮查询把键盘高度扩写为手机厘米/英寸尺寸，主要返回旧问题和旧 Host
答案。初始 tall 与语言配置内容正确，原话材料仍部分不足；后来 medium、
笔记本 US International 西班牙文布局、仅计划的 short 测试及未添加韩文没有
取回。原话初始回合确实使用四个已知原文引用，随后收到 read-limit 工具错误，
最终仍完成正确内容，分别记 C/partial 和实际工具错误，不改判为 Host 执行失败。
D19 一条流程仍用旧 200GB 并否认主目录；另一流程初始完整区分了实际 2TB/
Core_Vault、照片和备份与助手的目录建议。后来已降回 200GB、照片迁到 4TB SSD，
离线激活与 Work/Finance 优先级请求、尚未做的月度克隆和仅考虑的促销均未读取。
这些判断沿合成来源报告，不验证真实厂商功能或账户状态。

D21 提供了材料完整而角色使用错误的具体例子：初始内容回答把助手推荐的
Boards of Canada 写成用户明确的专注音乐偏好，判 W/材料 complete；下一个
重复请求仍用相同材料，却没有该项错误，判 C。两份首次结果都保留，不能挑选
较好的后答或视为新来源。最终查询又返回旧 Host260，将同一错误带回回答。
原话流程初始引用正确，后来未读取已确认的 Discovery、仅暂时看好的 Homework
和新放松偏好，仍把 RAM 写成当前最爱。View 的文本、角色、时钟忠实继续与
嵌入声明正确性、当前覆盖和 Host 使用分别判断。
D23 的核心座位偏好和旧旅程基本完整，但出现将助手的 midday 细节写成用户
旅程时间、将日志维护当成已实现效果的额外断言；后来 Tampa 旅程、已取消
Seattle、尚未预订 Boston、待核对 CRJ900 布局和仅要求草拟的 HR 更正未取回。
未将其变成实际机型验证、订票或 HR 写入。

前缀已在原账本记录 432 HTTP、2,568,026 已知 Host 总 tokens，新增未知 0/0；
162 次工具尝试/返回、两个工具错误，609 控制步、598 操作、322 READ、
26 材料拒绝、八次普通已知原文引用读取，218 份当前原文和 22 份当前 View。
这些普通引用读取不等于尚未执行的受控 View K 验证。receipt15 后现有 67 个
闭合计时共 170.52 CPU 秒 pending，含失败 Ruff；作者/未计时 CPU unknown。
本轮重读了全量绑定、不可变逐轮 SDK 审计、整答汇总和结算入口，只确认关闭
顺序与所需文件，未在活动期间执行它们或重复测试。v16 实际结算仍未执行。

下一审阅位置 index280/E11；扩展前完整比较 280 条记录及 102 次 View。
原生结束后先全量绑定，再串行 SDK 审计，完成全部质量/操作/成本闭合，
真正空闲时一次结算后手动启动 E3 新组 320。真实 K/可检索性控制、52 READ/
7 池补采、最终冻结确认、外评、全成本及论文范围保留；test split 与 held
确认正文未读取，完整目标仍在执行。

## v25 历史状态（2026-11-06）：增量前 240 条整答和接收 View 闭合

同一唯一正式 worker child3591601 / exec4286 在 v25 写入时关闭 252/320，仍在
运行；实际 `/proc` 配置已核对，冻结运行时、数据、Host 与 Product 未改变。
前 240 条完整回答及全部 15 个实际 View 引用、含历史 K 的 67 次接收已由来源
作者审阅，非独立盲审。47→53 的所有新增首次失败均保留。

| 指标 | 增量缓存前 240 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 48 / 40 / 99 / 53 |
| 材料 complete / partial / insufficient | 55 / 169 / 16 |
| C 且材料 complete | 37 |
| 不同实际接收 View 引用 / 含历史 K 出现 | 15 / 67 |

统计单位仍是 24 个相关 TRAIN 暴露生成来源族，每族两流程、五请求，并非
240 个独立未见任务或完整 320 分数。96 个中间/最终位置材料 complete 均为 0；
中间 C1（A02 所问名称未变）、最终 C0。整批 SDK、效果、操作轨迹和总成本
尚未闭合，也没有三方法完整家族配对比较或采用结论。

本轮完整核对 200→210 的 200 条记录和 45 次 View、210→220 的 210/60、
220→230 的 220/60、230→240 的 230/65，记录字典、provider 输入、答案、Source
绑定和 View 均逐值相同后，再复用同一方法原判断并重校锚点/Fmask。
基线仅用于字面正文/角色去重，没有跨方法复制分数。新增六个实际接收引用、
22 次出现分别为 C26 三个引用/15 次、D02 一个/五次、D17 两个/两次。

C26 初始材料完整且多数回答正确。内容流程两次重复查询返回两个引用不同、
Source ID 和七节点文本相同的 View，投影中 raw companion 与共享 metadata
的写法不同，已分别核对；它们不是独立证据，也不证明创建了两个缓存对象。
原话流程的一条主引语混合用户与助手文字，判 Q/材料 complete。后来真正改到
3:00PM、仅拟议 4:00PM 和 Rina 的新信息没有取回。C29 的选定、重新考虑、
已付款、未来发货分开判断：只漏报付款的回答 Q，与直接否认物流报告的 W
分别保留；准确引用已回答部分，不代表橄榄树、他人礼物和效果状态都已回答。

D02 原话流程保留实际收到的 View revision2，各 Source revision1，没有改成
较干净版本。其初始用户 2560×1600 更正、购入日和保修卡原话完整，之后
1920×1200 的 OS 读数与指示未取回。用户的 Linux 设置时间只有 mid-March，
这个 View 没有添加年份；这些判断是报告一致性，不是实际面板或保修验证。
D17 初始失败回合实际收到了两份完整原话 View，因而 F/材料 complete；
这两份 View 仅出现在该失败请求的最后已响应输入，后来完成回合的 Host 输入
并未保留它们。后续仅收到问题文本的已完成回答判 Q/insufficient，最终失败
保留 F/insufficient，不能把存储中存在的材料算作已知 K。另一流程的助手复述
与原话引语义务、设备默认与应用覆盖、历史 Firefox 与新 Edge 分别核对。

已知 View 控制协议和原生 `_known_materials` 的只读源码核对再次确认：既有
`prepare_pair` 面向原文已知材料，不能直接覆盖 View K。真实控制仍须保留
实际选中的初始 pre-final snapshot、原引用和版本、完整 Host 上下文，并从
新原生到达状态取得正确上下文；实际引用查找和同 before 核对尚未执行。
本轮没有新的代码或机械测试重跑，也没有触发真实控制、Store 克隆或模型调用。

前缀已在原账本记录 369 HTTP、2,130,596 已知 Host 总 tokens，新增未知 0/0；
137 次工具尝试/返回、一个工具错误，524 控制步、515 操作、281 READ、
25 材料拒绝、4 已知引用读取，186 份当前原文及 15 份当前 View。
receipt15 后现有 55 个闭合离线计时共 126.38 CPU 秒 pending，含失败 Ruff；
作者/未计时 CPU unknown，v16 实际结算未执行。原生结束后先全量绑定，再
串行 SDK 审计，完整质量/操作/成本闭合且真正空闲后，才一次结算并手动启动 E3。

下一审阅位置 index240/D18，扩展前完整比较 240 条记录及 67 次 View。
增量尾部、E3 新组 320、真实 K/可检索性控制、52 READ/7 池补采、最终冻结
确认、完整外评、成本与论文范围保留；test split 和 held 确认正文未读取，
完整目标仍在执行。

## v24 历史状态（2026-11-06）：增量前 200 条闭合，补齐首轮 Host 输入组合

唯一正式 worker 仍是 child3591601 / exec4286，v24 写入时已关闭 208/320；
实际 `/proc` 配置已核对，冻结运行时、数据与 Host 未改变。前 200 条完整回答和
全部九份实际 View、含历史 K 的 45 次接收已由来源作者审阅，非独立盲审。

| 指标 | 增量缓存前 200 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 40 / 28 / 85 / 47 |
| 材料 complete / partial / insufficient | 45 / 143 / 12 |
| C 且材料 complete | 30 |
| 不同实际 View / 含历史 K 出现 | 9 / 45 |

这些位置属于 20 个相关 TRAIN 暴露生成来源族，每族两流程、五请求，并非 200 个
独立未见任务、完整 320 分数或方法采用证据。80 个中间/最终位置材料 complete
均为 0；中间 C1（A02 所问名称未变）、最终 C0。整批 SDK、效果、操作轨迹、
总成本及三方法家族配对比较仍未闭合。

本轮先完整核对 160→170 的 160 条记录和 40 次 View，再依次核对 170→180 的
170/40、180→190 的 180/40、190→200 的 190/45；记录字典、provider 输入、答案、
Source 绑定和 View 均逐值相等后，才复用同一方法原判断并重校锚点/Fmask。
新增 C10 View 的七节点全文、角色、版本、时钟和 raw companion 已审阅，五次
整份接收副本逐值相同，包含两个失败回合。助手的备考建议、通过率和相对时间
仍是助手原话，不因忠实引用而成为用户事实。基线仅用于字面正文/角色去重。

C05 内容流程只收到问题文本，四个已完成回答明确限定当前上下文不足，判 Q/
insufficient；另一流程初始原话足够，后续未读取 May26 改签及两人共用、排除机票
的 $3,200 地面预算。C07 的 Sowaka 名称后来重新与当前预订一致，但旧凭据没有
见证 June20–25、June19 早到空档、Takayama 研究和未接受 Hoshinoya 保留，不能
据此判完整成功。C10 继续区分 58% 内容完成与 65–68% 总体练习准确率；最初
June14 正确的流程也没有取得后来 June21 实际预约和仅有意向的 June14。
C23 则出现把未取回妻子日期写成“用户未提供家属日期”，以及把助手查询名额
建议写成用户所说的问题；earlyMay 计划、已拒绝 April11 名额与已预约不能混同。
一次作者判断写入因未转义引号在解析阶段退出，文件仍为 192 条；确认长度后，
连续写入并重校至 200，原失败记录保留，未重跑实验结果，未计时 CPU 为 unknown。

另行核对旧 Host 输出可检索性控制时，确认现有 `prepare_controlled_readout`
绑定已完成回合的 pre-final snapshot 和最终 provider 输入，不能代替本因素冻结的
same-sources 第一次 provider 派发前输入。因此新增 ignored 实验辅助函数
`d_old_output_readout.py::prepare_first_dispatch_readout`，直接组合该首轮输入：
复用现有 `append_fresh_request` 序列化新的声明调用和 placeholder，再逐值保留
整个原消息序列和所有 provider 设置；`readout_batch` 与 `substitute_receipt`
仍负责完整批次及只允许最终回答的已有路径。旧 Host 回答和旧工具回执继续留在
完整上下文里，工具可检索性开关由另行冻结的 Source 获取配置实现。

两个隔离字典 fixture（JSON-action、原生工具模式）通过：原消息的全部字段、
测试用 reasoning 字段、历史回答和回执保持，on/off Host 输入逐值相同，只替换新
placeholder，既有最终回答限制生效。它们没有克隆真实 Store、执行原生 K 查找、
修改真实 donor 或调用模型/原账本；不是实际控制任务成绩。真实运行仍须在正式
三项结束后冻结独立运行时/配置，核对 physical-before/native inventory、Source
等价性、实际 K 与新调用绑定，取得真实工具回执后串行条件 readout；实际控制和
Host readout 均为 0。原冻结首八族/七合格格、失败 A02 与所有预算保持。

此前缀已在原账本记录 310 HTTP、1,785,739 已知 Host 总 tokens，新增未知 0/0；
117 次工具尝试/返回、一个工具错误，452 控制步、446 操作、247 READ、21 材料
拒绝、4 已知引用读取，161 份当前原文和九份当前 View。receipt15 后 43 个闭合
计时共 86.56 CPU 秒 pending，包含失败 Ruff 和本轮 frame fixture；作者/未计时
CPU unknown，v16 实际结算未执行。整批结束先全量绑定、再串行 SDK 审计，完整
质量/操作/成本闭合后，才按已准备脚本在真正空闲边界一次结算并启动 E3。

下一审阅位置 index200/C26，扩展前完整比较 200 条记录及 45 次 View。E3 新组
320、真实 K/可检索性控制、52 READ/7 池补采、最终冻结确认、外评、全成本及
论文范围保留；test split 和 held 确认正文未读取，完整目标仍在执行。

## v23 历史状态（2026-11-06）：增量前 160 条整答和 View 闭合

同一唯一正式 worker child3591601 / exec4286 在 v23 写入时已关闭 169/320，
仍在运行；实际配置已从 `/proc` 核对，冻结运行时、数据和 Host 未改动。
前 160 条完整回答及八份实际 View、含历史 K 的 40 次接收已由来源作者审阅。

| 指标 | 增量缓存前 160 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 35 / 19 / 65 / 41 |
| 材料 complete / partial / insufficient | 39 / 114 / 7 |
| C 且材料 complete | 25 |
| 不同实际 View / 含历史 K 出现 | 8 / 40 |

这里只包含 16 个相关 TRAIN 暴露生成来源族，每族两流程、五请求，不是 160 个
独立未见任务或完整 320 成绩，也非独立盲审。64 个中间/最终相关更新位置材料
complete 均为 0；中间 C1（A02 所问名称未变）、最终 C0。完整方法的 SDK、效果、
操作轨迹、总成本及三方法配对比较仍未完成，不能从此前缀采用方法。

本轮依次核对完整前缀后复用同一方法原判断：110→130 比较 110 条记录和 20 次
View，130→140 比较 130/20，140→150 比较 140/30，150→160 比较 150/35。
记录字典、provider 输入、答案、Source 绑定和 View 均逐值相同，再重校全部
锚点/Fmask。新增两份 C01、一份 C02、一份 C04 View，各七节点、五次接收；
完整正文、角色、版本、时钟及 raw companion 都已审阅，同一 ref 的整份接收副本
逐值相等。基线仅用于字面正文/角色去重，没有跨方法复制答案分数。

B25 需要保留每月第二、第四个周五与四月每周五的区别，以及周二和周四不同的
四月游泳时间。中间五次查询只得到问题文本、一条空闲日原话及材料拒绝后的空
返回，不能计作取得完整更新。B26 的当前 Eugene 与已确认下月搬回 Portland
不同；Austin 意向和预产期也没有成为已订机票或已出生事实。
C01 初始 View 完整，仍有一条回答把三月中旬询价误写为搁置时间；后续 $240
也没有更新到正式 $260，附条件 $245、非正式 $210 和他人 $230 未区分。
C02 六个初始阶段回答都已有原始截止日和通用三天规则，却没有算出 grant 的
April 15 目标，判为 Q/材料 complete。两个原话回答准确引用了原截止日和规则，
引语义务满足仍不代表算术完成；后来的 April14/11、书面通知和被否决的 April22
延期则未送达。C04 只核对报告一致性，未作临床建议或预约操作；初始原话 View
完整，另一流程的助手复述则缺 9:30 和原话见证，后续 April28 与未做的 April30
改期、ENT 已无需复诊等更新仍未收到。

此前缀已在原账本记录 251 HTTP、1,470,901 已知 Host 总 tokens，新增未知 0/0；
98 次工具尝试/返回、一个工具错误，377 控制步、371 操作、205 READ、
18 材料拒绝、4 已知引用读取，131 份当前原文、八份当前 View。整进程 CPU
仍待原生关闭。receipt15 后现有 30 个闭合离线计时共 54.16 CPU 秒 pending；
作者/未计时 CPU unknown，不填 0，活动期间没有结算或重计原费用。

已准备下一次真正空闲时使用的 `settle_d_new32_incremental_idle_v16.py`，尚未
执行。它要求当前 owner 完成并记录客户端 CPU、实际进程消失、全 320 整答/SDK/
操作审计闭合且没有其他实验 worker。读取器兼容原 GNU 显式字段、verbose 格式，
以及只在首行保留非零退出码的旧失败计时，原计时文件没有改写。首次只读验证因
精确浮点比较失败，随后检查发现尚未读取旧失败首行退出码；原失败记录保留，改用数值容差并读取
GNU 非零首行后，两种原始计时、失败计时、27 个当时待结算命令及两文件语法
核对通过。验证只读计时/AST，未导入执行结算脚本，未打开或写入原账本；
这些未计时检查 CPU 保持 unknown。后续进度和结算扫描器不能套 GNU 外层计时。

下一审阅位置 index160/C05。扩展前须完整比较 160 条记录及 40 次 View；原生
结束后先全量绑定，再串行 SDK 审计。新组 E3 320、真实 K/旧输出可检索性控制、
52 READ/7 池机制补采、最终冻结确认、完整外评及论文范围保留；test split 和
held 确认正文未读取，完整目标仍在执行。

## v22 历史状态（2026-11-06）：增量前 110 条整答和 View 闭合

同一唯一正式 worker child3591601 / exec4286 在 v22 写入时关闭 132/320，仍在运行。
前 110 条整答和全部四份实际 View、含历史 K 的 20 次接收已完成来源作者审阅：
C25/Q9/W46/F30，材料 complete24/partial82/insufficient4，同时满足 C 与材料
complete 为 17。11 个相关 TRAIN 暴露生成家族并非 110 个独立未见任务；
完整方法 SDK、效果、操作轨迹、总成本和方法比较尚未闭合。44 个中间/最终位置
材料 complete 均为 0；中间 C1（A02 所问名称未变）、最终 C0。

扩展前，完整前 80 条记录字典、provider 输入、答案、Source 绑定和 10 次 View
与 prefix110 逐值相等；随后复用同一方法的 80 个原判断，重校全部锚点/Fmask。
新增 B05 两流程的实际 View 各有七节点、五次接收，完整文本、原始角色、版本、
共享/独立捕获时钟与 raw companion 均已核对；每流程的整份接收 View 逐值相同，
没有把两流程不同 Source ID 与时钟视为相同。基线仍只用于字面正文/角色去重。

B05 显示初始完整材料不能保证后续共同决策状态正确：回答没有重新查询，漏掉
共同改回 Elara，之后又把妻子想用 Iris、用户仍想用 Elara 写成已完成共同切换。
其中一个原话请求的核心初始事实正确，但用编辑过的助手 Matteo 复述作引语，
虽然实际 View 中已有用户原话；因此答案 Q 与材料 complete 同时保留。
B12 必须区分原始笔误 3742、后来真正退役的 3724、当前 3790 和仅拟议的号码转回；
初始不加限定的“旧退役号”与明确写为“退役/错误号”的部分表述分别判断。
B21 全部十条回答错误使用 $78,000，漏掉初始 $82,000 和 Tuesday–Saturday 更正，
随后 $82,500、更高薪资提议与待批准咨询任务仍未送达。最终一次查询实际返回
旧 Host105 与助手考试复述，没有补上新的用户陈述，不能仅凭发起查询计为更新成功。

前缀实际已记账 174 HTTP、1,021,671 已知 Host 总 tokens、新增未知 0/0；
68 次工具尝试/返回、一个工具错误，273 控制步、270 操作、153 READ、
11 材料拒绝、4 已知引用读取，95 份当前原文和四份当前 View。receipt15 后
18 个闭合离线计时共 32.99 CPU 秒仍 pending，作者/未计时 CPU unknown，
运行期间没有结算、重跑首结果或改动冻结方法。下一审阅位置 index110/B25，
扩展前须完整比较 110 条记录及 20 次 View；全量结束先绑定、再串行 SDK 审计。
后续正式 E3 320、实际控制和机制补采、冻结确认、外评及论文完整范围保持。

## v21 历史状态（2026-11-06）：增量前 80 条整答和 View 闭合

唯一正式 worker 仍是 child3591601 / exec4286，v21 写入时已关闭 119/320；实际配置
已从 `/proc` 核对，冻结运行时、数据与 Host 设置未变。前 80 条回答与全部实际 View
由实现/来源作者完成审阅，非独立盲审；其中 24 个首次执行失败全部保留。

| 指标 | 增量缓存前 80 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 22 / 7 / 27 / 24 |
| 材料 complete / partial / insufficient | 18 / 58 / 4 |
| C 且材料 complete | 14 |
| 不同实际 View / 含历史 K 出现 | 2 / 10 |

这里只包含 8 个相关 TRAIN 暴露生成来源族，每族两流程、五请求，不是 80 个独立
未见任务或完整 320 成绩。中间更新阶段 16 位置 C1、材料 complete0，唯一 C 是
A02 所问名称未变；最终阶段 16 位置 C0、材料 complete0。完整方法的 SDK、效果、
操作轨迹与整进程成本仍待原生终态后核对，不能从此前缀采用方法。

扩展时，完整前 20 条记录字典、provider 输入、答案、Source 绑定及五次 View
与 prefix80 逐值相等后，才复用同一方法原判断并重新校验全部锚点/Fmask。
基线仅用于字面相同正文/角色/来源的去重阅读，没有跨方法复制分数。
B03 的七节点 View 完整文本、每个角色/版本/时钟绑定，以及五次接收副本逐项核对；
整份接收 View 逐值相同。它忠实包含初始用户陈述，却没有后来附加的临时职责、
Priya 调组、旧组织图和永久角色提议，忠实与当前覆盖继续分别判断。

审阅区分了几类失败机制：A16 初始是截断失败，后来只收到问题文本的已完成回答
属于材料不足，且把 `policy_handoff` 当作隐私拒绝缺乏依据。A29 初始用户更正本身
已包含 WriteInPT、72/74 和分母，完整支持不要求逐一取回所有指定 witness ID；
最终虽然再次答对 72，却未说明 78 只适用于欧洲轨及 Pedro85 的归属。
A33 则把实测 5′11″ 误当旧认知，再推导出未报告的实测 5′10″，后续无查询回答
持续沿用。失败回合曾收到的正确原文没有被当作后来完成回合的 K。
B03 的用户经理陈述同时包含 David 的职称和报告线，可独立见证两个结论；
原文完整性按实际语义支持判断，不绑定唯一指定的职称 Source。

前缀费用为 136 HTTP、785,260 已知 Host 总 tokens、新增 generation/embedding
未知均 0，已在原连续账本；59 次工具尝试/返回、一个工具错误，229 控制步、
226 操作、127 READ、11 材料预算拒绝、4 已知引用读取，返回 77 份当前原文和
两份当前 View。没有再次记账或活动期间结算。receipt15 后现有 15 个闭合离线
计时共 28.97 CPU 秒待真正空闲一次结算，含失败 Ruff；作者/未计时 CPU 仍 unknown。
一份新 close-prefix80 计时采用 GNU verbose 格式，保留原文件，进度读取器按其
原始 user/system/wall 字段解析；后续结算器也须兼容这一格式，不能重跑已闭合操作。

下一审阅位置是 index80/B05。扩展前须完整比较全部 80 条记录及 10 次 View。
新组增量尾部/E3 320、原生 K 与旧输出可检索性控制、52 READ/7 池补采、最终冻结
确认、完整外评及论文图表仍在范围内。基准 test split、held 确认正文未读取。

## v20 历史状态（2026-11-06）：增量前 20 条闭合，实现声明的来源获取范围

同一增量缓存 child3591601 / exec4286 在 v20 时实际关闭 78/320，仍为唯一实际实验
HTTP 作业。前 20 条整答与所有实际 View 已完成来源作者审阅：C8/Q2/W6/F4，
材料 complete6/partial14，同时满足 C 与材料 complete 的为 4；一个 View、含历史 K
的五次出现已逐项核对。这里只包含 A01/A02 两个相关 TRAIN 暴露来源族，不是完整
320 评分、20 个独立未见任务或方法采用证据。第一族初始获得了用户原始职位更正与
经理陈述，后续晋升、薪资和拟议职位仍未送达；第二族中间阶段名称没有变，最终
宣布后搁置的改名及旧模板信息未送达，且一个回答把旧错误名称再次标成“已更正”。

扩展前，完整前 10 条记录字典、provider 输入、答案、Source 绑定以及全部五次 View
记录，与 prefix20 逐值相等；复用同一方法的原判断并重新校验锚点/Fmask。
基线仅用作字面相同正文/角色/来源的去重阅读，没有跨方法复制答案分数。
前缀实际增量为 30 HTTP、162,928 已知 Host 总 tokens、新增未知 0，已在原账本；
10 次工具调用、45 控制步/操作、25 READ，返回 16 份当轮原文与一个 View。
下一审阅位置为 index20/A05，全量 SDK/副作用与整作业费用仍须原生关闭后核对。

为执行已冻结的旧 Host 输出可检索性因素，新增了一个明确可选的获取范围参数：
`IntentRetrievalMemory.control_excluded_source_refs`，通过
`memory_control.excluded_source_refs` 进入 functional 与 STATE 装配。
默认集合为空。声明的 Source ID 与当前公共请求 Source 的既有排除集合合并，
同一集合同时传给原生 Source 排序和 `EvidenceOperations` 的观察/获取路径，并记入
读取策略与 trace。它不删除 Source、不改说话人或可见性，也不撤销已知材料或旧 View；
实际控制的候选格仍须满足缓存 View 未绑定所选旧输出，并完成原生等价性/K 检查。
公开 Host 工具 schema、权限、Product 与依赖未变，运行中的冻结副本没有新增参数，
正式三方法比较继续使用原冻结实现。控制实验须另外冻结包含该实现的运行时。

相关 24 项隔离机械测试通过，其中两个新增条件检查：被声明排除的旧助手 Source
不进入初始观察、排序范围或交付；同为 assistant 角色的 fixture 建议及用户来源继续保留；
三个原 Source 值均不变。测试使用临时 SQLite 与脚本/固定策略，没有实际外部模型
HTTP、原实验账本写入或真实实验 Store 克隆，不能作为控制 Host 的任务成绩。
四个文件语法、Ruff、package DAG 和 tools inventory 检查通过；首次 Ruff 发现一处
101 字符行，已缩短，原失败计时保留。沿用既有依赖，未声称全仓库 CI 或远端核对。
实现记录为 `old-output-searchability-implementation-v1.json`；实际已捕获 before/full frame、
原生 K 查找、条件 readout 与质量/成本闭合仍未执行，原来的冻结协议没有改写。

增量方法首 8 个预定 content 初始格的 View/K 元数据证明现已收集：只有 B03 具备实际
初始 View、完成的最终 Host 输入和不可变 pre-final inventory；A16 首次初始失败，
A01/A02/A05/A14/A29/A33 没有实际初始 View。所有格保留，不换后续回合或来源族。
基线原有 A05/A33/B03 三个合格格保留，E3 候选格及原生同 before 三方法控制仍待执行。

成本结算仍止于 receipt15；本轮 12 个闭合离线计时共 26.02 CPU 秒待真正空闲一次结算，
包括失败的 Ruff。作者/未计时 CPU 仍 unknown。其余增量尾部、E3 新组 320 条、
真实 K/可检索性控制、52 READ/7 已读池机制补采、最终冻结确认、外评及论文图表
均继续属于完整目标；基准 test split 与 held 确认正文未读取。

## v19 历史状态（2026-11-06）：新组基线 320 条全量闭合，增量方法启动

新 32 族原缓存基线已正常结束：原 exec4305 返回 0、child2956519 消失，原生 320 个
首次位置全部关闭，其中工程完成 253、首次执行失败 67。任务结束后先全量绑定、再做
逐轮 SDK/副作用审计，两项均通过，随后完成全部答案、View 和操作轨迹审阅。
完整前 290 条记录字典、provider 输入、答案、Source 绑定及前 154 次 View，与全量
320 逐值相等；原判断复用并重新校验锚点/Fmask，没有重跑模型或工具结果。

| 指标 | 原缓存新组 320 |
|---|---:|
| 完整正确 C / 部分满足 Q / 错误 W / 执行失败 F | 67 / 65 / 121 / 67 |
| 材料 complete / partial / insufficient | 84 / 222 / 14 |
| C 且材料 complete | 53 |
| 来源族宏平均完整成功 | 20.9375% |
| 实际原文范围（含历史 K） | 883 |
| 不同实际 View / 含 K 出现 | 42 / 163 |

统计单位是 32 个 TRAIN 暴露生成来源族，每族两流程、五请求；320 个位置相关，
不能当作 320 个独立未见任务。完整回答由实现/来源作者审阅，并非独立盲审。
各阶段合并两流程后如下，未按成功与否删掉任何首次位置：

| 阶段（各 64 位置） | C / Q / W / F | 材料 complete |
|---|---|---:|
| 初始 | 28 / 16 / 14 / 6 | 28 |
| 同来源重复 | 19 / 23 / 14 / 8 | 27 |
| 无关来源到达 | 20 / 14 / 12 / 18 | 29 |
| 中间相关更新 | 0 / 9 / 37 / 18 | 0 |
| 最终相关更新 | 0 / 3 / 44 / 17 | 0 |

两个相关更新阶段的全部 128 个位置，完整回答和材料完整均为 0。这是基线结果，
尚未证明所有失败由同一个工具控制问题造成，也没有形成新方法采用结论。
SDK 审计对 5,578 次旧 Source 值的逐轮比较均保持原值；253 个新最终输出保持 assistant
角色，Saver 消息及应用状态核对通过，36 个回合发生 View 命名空间变化。所有失败回合
的真实状态也在审计中。42 个 View 的全部 163 次出现已审阅完整文本和角色时钟，
字面忠实继续与嵌入声明的正确性、当前覆盖及 Host 使用分开。
例如失败 index262 的 View 原样引用旧 Host 把助手建议的艺人当作用户偏好的答案，
角色仍为 assistant，该失败 View 也未成为下一已完成回合的 K。

操作审计确认 724 个选择 ID 全部出自当时实际菜单：138 SEARCH、372 READ、
155 HANDOFF 选择、59 REFRESH/build，USE_VIEW 为 0；实际操作结果 676 个，其中
HANDOFF 结果 107 个。当前回合收到的 225 份原文中，118 为 assistant、107 为 user；
161 份外生 fixture、64 份运行中的旧问题/旧回答。213/320 回合没有发起当轮检索。
107 个发起检索的回合中，45 个没有收到当轮外生原文范围；这不排除其中通过 View
收到部分外生内容，不能把“无外生原文”写成“无任何新信息”。
末尾医疗案例还出现了把助手解释归到医生名下、已完成记录转移仍称待办的问题，
说明 Source 保存正确不等于回答对角色和业务状态的使用正确。

基线实际费用为 480 HTTP、2,934,163 已知 Host 总 tokens，新增 generation/embedding
未知均为 0；shared generation calls 同为 480。整子进程 CPU 571.723529 秒、
wall 9,935.951884 秒，已由原 owner 在原账本一次记录；本方法没有本地学习模型 GPU
作业区间。远端硬件/币价没有测量，作者及未计时 CPU 仍 unknown，不能报为 0。
在确认实际空闲且完整闭合后，receipt15 一次结算 30 个离线计时命令共 87.78 CPU 秒；
没有重计原生/客户端/早前费用，也没有修改 token 计数或限额。

已手动串行启动冻结的 `new32-view_cache_incremental`：parent3591596、child3591601、
exec4286，v19 时实际关闭 8/320。它是当前唯一 HTTP 作业，没有本地学习模型推理。
新组 E3-u32 320 条仍未启动。活跃期间不结算离线 CPU，不执行原生控制/Store 克隆，
不修改运行时、数据或 Host 设置；任务结束后同样先全量绑定，再做 SDK 审计。
可在它运行时审阅实际已关闭前缀，不能跨方法复制答案分数。
真实 K、旧输出可检索性控制、52 个 READ 与 7 个已读池补采，以及最终冻结确认、
外部评测和论文图表仍是完整目标的一部分。held/test 内容未打开。

v19 后的增量前缀记录：同一进程最近核实关闭 22/320；前 10 条（一个相关的 A01 来源族）
已完整审阅，C4/W4/F2，材料 complete6/partial4，C 且材料 complete4。
一个实际 View、含 K 的五次出现已核对。15 HTTP、85,806 已知 Host 总 tokens、
新增未知 0，已在原账本；receipt15 后两个离线计时共 0.48 CPU 秒待空闲结算。
这些小前缀不承担完整方法评分或采用结论。基线只用于字面相同正文/角色的去重阅读，
没有跨方法复制分数；继续扩展时仍须逐值核对整个已审前缀并重校验所有锚点。

## v18 历史状态（2026-11-06）：前 250 条审阅闭合，冻结回流控制

新组原缓存仍由同一 child2956519 / exec4305 单路运行，记录时实际关闭 283/320。
前 250 条完整答案审阅闭合：C52/Q51/W94/F53；材料 complete64/partial172/insufficient14，
同时满足 C 与材料 complete 的为 39 条。33 个不同 View、含历史 K 的 133 次出现，
均已审阅原文、角色与时钟。它们来自 25 个相关的 TRAIN 暴露来源族，不能当作 250 个
独立未见任务或完整 320 成绩。保留全部 53 个首次执行失败，另一个工程完成但只有
开场白的回答仍按未完整满足任务判断，没有改成执行失败。

前缀实际费用为 377 HTTP、2,321,428 已知 Host 总 tokens、新增未知用量 0，已经在
原账本。当前轮累计 144 次工具调用、574 控制步、535 操作、293 READ、14 次材料准入
拒绝、2 次 known-ref read，返回 177 份原文与 33 份 View。
完整前 200 条记录字典、provider 输入、答案、Source 绑定和前 106 次 View 记录，与
prefix250 逐值相等；复用原判断并重新校验锚点/Fmask，没有重新生成。
当前审阅目录为 `new32-view_cache-prefix-0250`，下一条 index250/D19。

本批进一步分开了材料忠实与内容正确：D02 的一个 View 原样引用 fixture assistant
写下的“mid-March 2024”，而用户原报告只有 mid-March，没有年份。这个新增年份属于
被引用的助手内容，不能归为 View 的字面改写，也不能提升为用户证词。后来的 1920×1200
操作系统读数和用户保留指令没有送达，旧 2560×1600 摘要因此不能承担当前依据。
礼物案例也分开选择、下单付款、发货和送达；价格相同不代表读取到了付款状态更新。

计划 9.3 的旧 Host 输出可检索性因素已有独立冻结协议和实际材料证明，尚未执行控制。
沿首 8 个预定来源族，固定 baseline 内容流 same-sources 回合在第一次 provider 请求前
的真实 Store/完整输入。7 族具备实际初始最终 Host 输出 Source；A02 初始失败，没有
已完成旧输出，按规则保留不合格格，不换后续回合或来源。逐值匹配实际 provider payload
与 trace，并验证旧输出 Source 正文等于初始实际答案、角色为 assistant、当前最终输出
尚未进入 before。既有缓存 View 均不绑定所选旧输出；准备过程没有工具/模型执行、
原生 Store 克隆或账本写入。

两种条件只改变这些实际旧输出 Source 能否进入新获取的检索池；三方法的 Source
原值、角色、时钟、修订、可见性、目标、完整 Host 输入和预算保持相同。使用已有
`search_sources(excluded_source_refs=...)` 与 `EvidenceOperations` 的排除边界，
仍须补一处窄适配把同一排除集合传到检索和 Source 观察/获取两条路径，然后在真正
空闲时核对原生 before 快照、完整 frame 与 known-reference lookup，执行条件 host-readout。
Host 已在原上下文中的旧回答继续保留，因此它测量额外工具可检索性的作用，不能声称
从 Host 认知中移除了旧回答。实际 K 禁止使用 given-readout。最多 8×2×3＝48 次
readout 是资格筛选前上限，当前 7 个合格格最多 42 次；首次失败、成本和相关族均保留。
这不替代正式自主 Host 结果，目前回流证据仍属观察。

证据为 `old-output-searchability-protocol-v1.json` 与
`old-output-searchability-donor-first8-v1.json`；完整 provider 输入保留在 ignored artifacts，
机器可读进度只包含协议和元数据摘要。真实旧 View K 控制、其他新组两方法各 320 条、
v17 预留的 52 READ/7 已读池补采均仍未执行，未扩大菜单或追加训练。
成本止于 receipt14；22 个闭合离线计时共 48.96 CPU 秒待真正空闲时一次结算，
作者/未计时 CPU 仍 unknown。完整目标继续执行，held/test 内容未打开。

## v17 历史状态（2026-11-06）：前 200 条审阅与旧绑定覆盖核清

新组原缓存仍是同一 child2956519 / exec4305 单路作业，记录时实际关闭 247/320。
前 150、200 条完整答案与实际 View 均已完成来源作者审阅，保留全部首次失败：

| 字面顺序前缀 | 来源族 | C/Q/W/F | 材料 complete/partial/insufficient | C 且材料 complete | 不同 View / 含 K 出现 |
|---|---:|---|---|---:|---|
| 150 | 15 | 33/34/52/31 | 43/94/13 | 27 | 20/89 |
| 200 | 20 | 40/40/77/43 | 55/131/14 | 34 | 27/106 |

这些是相关的 TRAIN 暴露生成来源族；前缀不代表完整 320 评分或独立确认。
前 200 条实际费用为 306 HTTP、1,879,133 已知 Host 总 tokens、新增未知用量 0，
已经由原账本计费。实际当前轮有 123 次工具调用、486 控制步、453 操作、249 READ、
12 次材料准入拒绝、2 次 known-ref read，返回 146 份原文和 27 份 View。
原缓存不能因名字碰巧与后续重订相同而获得更新成功：例如京都案例仍否认明确日期、
提前到达与未订行程。护照案例一次查询确实恢复了妻子的日期，后续儿子的估计日期、
续期窗口和取消号源取舍仍未送达；保留局部恢复与后续失败。
View 字面忠实、当前材料完整和 Host 正确使用继续分别判断。

扩展审阅前，完整前 150 条记录字典、实际输入、答案与 Source 绑定，以及前 89 次
View 记录，与 prefix200 逐值相等；复用了原判断并重新校验全部锚点/Fmask。
当前目录 `new32-view_cache-prefix-0200` 已有 200 条判断，下一条为 index200/C26。
全 320 SDK/副作用、整作业 CPU 和尾部质量仍待关闭。任务终止后先全量绑定，再逐轮
SDK 审计，随后才能完成整组结论；前缀审阅不替代这些步骤。

旧 57 TRAIN 状态的实际缺口现已按原 before 与完整动作参数核清。
139 个原有分支和本轮 8 个功能分支，均对实际前缀、首动作、公共续行和 Reader wire
重新做只读绑定验证，没有执行模型或重跑工具。只有原有 1 个加本轮 4 个状态执行过
observed-Source READ，尚缺 52 个。B64 的 128 个 before 与 C8 的 8 个已读池均不与
这 57 个原 before 重合，因此不能代替缺失绑定。

已按固定 seed0 和原生参数覆盖冻结这 52 个合法 READ，未准备原生干预或执行。
计入功能切片的 4 个 observed READ 与 1 个 context READ 后，新增 READ 最多仍为 57。
它们沿原给定请求、fixed_context/reads4/首步后最多两个普通决策及实际剩余预算；
57 个实际 task 的 known_evidence 数组均为空，故这里可用 given-readout，结果仍属条件机制。

另有 18 个原状态具备至少两份实际已得材料和三个 HANDOFF 候选。已从尚未使用的池中
按 seed0 预留 7 个，计划同池同完整菜单比较 rules 与保留 E3-u32 的 handoff-only。
保守把功能切片 3 次 HANDOFF、C8 原 24 次和后续 6 次新 readout 都计入同一上限：
已有 33 次，预留最多 14 次，总计最多 47/48 次、18/24 个已读集合状态。
这不是已执行结果，不为填满剩余额度加样本，也不扩大菜单或训练。
这些补采安排在三项冻结新组作业之后串行执行，原结果和失败不重跑。
证据为 `b-repair-binding-coverage-v1.json`、
`b-repair-remaining-observed-READ-bindings-v1.json`、
`c-repair-acquired-pool-reservation-v1.json`。

真实 K 控制、匹配的旧 Host 输出可检索性因素仍待执行；目前观察不能替代控制结果。
成本结算仍止于 receipt14；18 个新的闭合离线计时共 33.31 CPU 秒待真正空闲时一次结算。
活跃 Host 期间未结算，作者/未计时 CPU 仍 unknown。其余新组两方法各 320 条、
最终冻结/held 确认、外部评测与论文图表仍属完整目标，没有缩减。

## v16 历史状态（2026-11-06）：前 100 条审阅闭合，扩大已关闭前缀

新组原缓存基线仍为同一 child2956519 / exec4305 单路作业，记录时关闭 174/320。
前 100 条完整答案现已全部审阅：C23/Q25/W32/F20；实际材料为
complete25/partial63/insufficient12，同时满足 C 与材料 complete 的为 17 条。
这对应按预定字面顺序的 10 个 TRAIN 暴露来源族，不是完整 320 评分或独立确认。
该前缀的原生工程完成为 80，保留全部 20 个首次失败；实际费用增量为
155 HTTP、966,557 已知 Host 总 tokens、新增未知 0，已经由原账本计费。

全部 15 个实际 View、含 K 的 67 次出现，均完成了原文/角色/时钟审阅。
“忠实引用”与“引用内容正确”继续分开：A33 的失败 index68 收到一个两节点 View，
原样引用两份先前 Host 错把已测 5'11 归为旧信念的答案，角色仍为 assistant。
它没有添加这项错误，也没有给出实际用户测量报告，不能作为当前测量的正确见证。
随后已完成回合没有继承该失败 View，只继续使用更早 K。另有命名案例显示，
相同名字 Iris 再次出现，不代表夫妻重新共同同意；旧 K 会错过当前分歧与截止日期。

已另行绑定前 150 个已关闭位置（119 工程完成、31 失败、89 次实际 View 出现）。
完整前 100 条记录字典、实际输入、答案、Source 绑定，以及前 67 次 View 出现，
均与较早前缀逐值相等；复用了这 100 条原审阅并重校验所有锚点/Fmask，未重新生成。
当前审阅目录为 `new32-view_cache-prefix-0150`，下一条为 index100/B21 content。
尚未审阅的新尾部不获得推断分数，全 320 的 SDK/副作用和 whole-owner CPU 仍待关闭。

本轮再次核对原计划第 9.2/9.3、11 和 12 节：目前对旧 Host 输出回流的观察，
不能替代“旧输出是否可检索”的匹配状态控制因素；首 8 族的 K 证明也不能替代原生
reference lookup、三方法相同 before/完整 Host frame 和实际 host-readout。
这些控制仍待执行，旧 57 TRAIN 缺失 READ/最多 24 个已读集合机制补采的实际覆盖
也须按原绑定逐项核对，不以 B64、C8 或新组结果自动抵销。正式运行期间不改数据或策略。

成本仍止于 receipt14；13 个闭合离线计时共 14.43 CPU 秒待真正空闲时一次结算，
当前 Host 活跃时未结算，作者/未计时 CPU 仍 unknown。其余新组两方法各 320 条、
上述控制与必要机制修复、最终冻结/held 确认、LME/Mem2Act 及论文图表仍未完成。

## v15 历史状态（2026-11-06）：新组前缀审阅闭合，真实 K 条件保留缺失格

新 32 族原缓存基线仍由同一 child2956519 / exec4305 单路运行，记录时关闭 119/320。
已完整审阅最先关闭的 50 条（5 个已有训练暴露的生成来源族），C12/Q13/W16/F9；
实际材料为 complete9/partial33/insufficient8，同时满足 C 与材料 complete 的为 6 条。
这是字面顺序前缀，不是完整 320 分数、无偏抽样估计或独立确认。原生工程完成为 41 条，
与完整答案成功仍分开。该前缀实际费用增量为 75 HTTP、491,235 已知 Host 总 tokens，
新增未知用量为 0；这些费用已在原账本，不再次计费。

前 50 条实际收到的 9 个 View、含历史 K 的 45 次出现，均审阅了完整原文、角色和时钟。
A05 初始内容流一次批次形成 7 个 View 修订，interpretation 逐值相同，但保留每个实际
ref/revision 和元数据；重复内容并不增加独立事实。忠实旧 View 不能证明新单位号、租期、
拟议/取消的单位重命名已送达。部分答案也把用户原先报告的 ZIP/旧租期混入
“assistant-only”分组，属于答案对来源的归类缺陷，与 View 字面忠实分开。

已另行绑定最先关闭的 100 条（80 工程完成、20 首次失败，67 次实际 View 出现）。
前 50 条记录的完整字典、实际输入、答案、来源绑定及前 45 次 View 出现，与较早前缀
逐值相等，复用了原审阅并重新校验锚点与 Fmask，没有重新生成。
当前累计审阅前 60 条，C14/Q16/W17/F13，材料 complete13/partial35/insufficient12；
前 60 条实际收到的 10 个 View、46 次出现已审阅。下一条为 A33 content 的 index60。
其中失败 index58 收到的单节点 View，只是原样引用 Host 先前的“未检索到分数”答复，
角色仍为 assistant，不能把它当作用户分数证据或 Store 中没有分数来源的证明。
该失败回合的 View 也没有自动进入之后已完成回合的 K。

基线首 8 个预定 TRAIN 来源族的初始格已全部收集：
A05/A33/B03 有实际初始 View receipt、completed-final Host wire 和不可变 pre-final inventory
证明；A02 初始首次失败；A01/A14/A16/A29 未实际送达初始 View。所有格均保留，
不换后续回合或其他来源族。A05 仍选择首个 rev1，并保留完整 Host K 中 7 个修订与后续
存储状态的实际差异。其他方法的候选格、原生 known-reference lookup、相同 before/完整
Host frame 的三方法控制和 host-readout 仍未执行，禁止用 given-readout 携带 K。

时间语义审阅还记录了两类 Host 行为：把摄取日期当成原对话日期，以及在询问当前事实时
自行加入较早的 as_of 截止。保留原请求，不把这些日期改写为用户报告时间，也不凭一次
输出断言它们独立造成了检索失败。正式运行时、来源、预算和方法配置均未修改。

原账本保留历史 generation unknown16/embedding unknown1，与该前缀新增 0 分开。
成本结算仍止于 receipt14；10 个新的闭合离线计时共 8.61 CPU 秒待真正空闲时一次结算，
当前 Host 运行期间未结算，作者/未计时 CPU 仍 unknown。全作业关闭后仍须全量绑定、
逐轮 SDK/副作用审计和完整费用闭合，然后才能复用前缀审阅并完成全 320 评分。
其他新组两方法各 320 条、真实 K 控制、最终冻结/held 确认及外评全部仍为完整目标的一部分。

## v14 历史状态（2026-11-06）：D 旧 8 族三方法审阅与比较全部闭合

v14 后续进度：同一新组基线实际关闭至 65/320，仍为唯一 HTTP 作业。
已另外绑定前 50 个已关闭位置（41 工程完成、9 首次失败、含 K 共 45 次 View 出现），
在独立 prefix 目录开始来源审阅，不触及运行尾部。首族 A01 的两流程共 10 条答案已审阅，
等级为 C/C/F/W/W/C/F/C/W/F；一个实际 View 的 5 节点和 5 次出现已确认忠实。
这不是完整 50/320 评分。全作业结束后，仍按原流程进行全量绑定/SDK 审计，只有逐值确认
答案、状态、实际输入与来源均等于该 prefix，才复用已经完成的审阅；不重跑模型。

旧组全部 240 个首次位置的完整答案、实际材料与 View 均已审阅，原缓存 80 个既有结果复用：

| 方法 | C / Q / W / F | 材料 complete / partial / insufficient | C 且材料 complete | HTTP | 已知 Host tokens | whole-child CPU 秒 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 原缓存 | 19 / 30 / 13 / 18 | 35 / 39 / 6 | 19 | 132 | 772,264 | 152.31894432 |
| 增量缓存 | 11 / 32 / 16 / 21 | 17 / 59 / 4 | 10 | 121 | 731,954 | 142.015116 |
| E3 u32 | 19 / 21 / 20 / 20 | 38 / 42 / 0 | 15 | 110 | 708,416 | 331.829985 |

答案 C 与材料完整性继续分开，不改写主分数。E3 有四个 C 仍缺原始用户见证：
最终 incident 内容流的 11/5 来自忠实的 fixture-assistant 复述，初始预算内容流三次的
1500 储蓄也只收到 assistant 复述；实际角色未提升为 user。显式索取自己原话的流程中，
assistant 引用仍不能代替用户原话。补充交集为 19/10/15；三方法最终更新的 16 个位置中，
材料 complete 都为 0，不能把偶然正确内容或旧 K 忠实当作更新读取成功。

统计单位为同一 8 个 DEV 来源族，每族同时保留两流程、五轮和失败。
20,000 次 Random0 配对来源族重采样得到条件描述性区间：

| 差值 | 完整率差 | 描述性 95% 区间 |
| --- | ---: | --- |
| 增量 − 原缓存 | −10pp | [−30, 6.25]pp |
| E3 − 原缓存 | 0pp | [−15, 15]pp |
| E3 − 增量 | +10pp | [1.25, 18.75]pp |

样本族少、来源已暴露、作者评审不盲，区间条件于这些首次 Host 生成，不是独立确认。
16 个初始流程的首个 HTTP 请求载荷在每个方法对之间都逐值相等，但首个检索参数
每对均为 0/16 相等，Host 在内部策略动作之前已产生不同查询，不能隔离控制器因果效应。
声明的 Source 内容、角色、出现次序与原事件时钟逐值相等；各运行的原生 Source ID 和
摄取 observed_at 不同。首次离线比较错误要求这两项也相等，现逐字段明确保留差异；
各自实际输入的角色/时钟绑定未放宽，没有重跑工具或模型。

E3 的 shared generation calls 295 包含 110 HTTP 与 185 次本地策略选择，不能写成 295 HTTP。
已知 Host tokens 较少不等于全成本较低；CPU、原模型训练/加载、0.746116064 小时本地
GPU 作业区间（含等待）均独立保留，远端硬件与货币成本仍未知。

新 32 族原缓存作业继续单路运行，child2956519 / exec4305，v14 时关闭 56/320。
其余两方法各 320 个位置尚未开始。纯离线收集了前 54 个已关闭位置中的初始 K 条件：
首 8 族已有 6 个基线初始格可检查，A01/A14/A16/A29 未实际送达 View，A02 初始首次失败，
A05 有首个 View rev1 的实际 receipt、completed-final wire 和 pre-final inventory 证明；
同一完整 Host 输入含 7 个 View 修订，不能改选最后一个修订来制造干净缓存。
后两初始格及其他方法候选格仍待形成；原生 known-reference lookup、相同 before 的
三方法控制和完整 host-readout 尚未执行。缺失格保留，不换后续回合或别的来源族。

新增 5 个闭合离线计时共 3.28 CPU 秒尚待真正空闲时一次结算，其中保留失败比较计时；
当前 Host 运行期间没有离线结算。完整目标保持 active：新 32 族全矩阵与审阅、真实 K 控制、
必要机制修复、最终冻结、held 确认、LME/Mem2Act 全评和论文统计仍未完成。

## v13 历史状态（2026-11-06）：D 增量策略全量审阅，旧组 E3 执行结束

`old8-view_cache_incremental` 的 80 个完整答案已逐条审阅，仍包含全部首次失败：
C11/Q32/W16/F21；实际材料为 complete17/partial59/insufficient4。
完整成功率为 13.75%，原缓存基线的既有首次结果为 19/80（23.75%），继续复用且不重计费。
这是 8 个暴露过的 DEV 来源族，每族 10 个相关位置；没有采用增量策略或增益结论。
来源作者参与实现，评审并非独立或盲审。

所有 5 个实际 View（包括历史 K 共 21 次出现、147 个节点绑定）均审阅了原文、
角色、来源和时钟，未发现新增推断或改写原文。材料忠实与当前覆盖分开判断：
新号码、预约时间、工资等更新未进入实际 Host 输入时，忠实旧 View 仍可能支持过时答案。
完整材料下也观察到 Host 将“Lena 注意到并笑了”推断为她吃了辣菜且耐辣度高，
这属于答案推断越界。失败回合收到的完整材料不会自动进入后续已完成 Host 历史。

实际当前轮 trace 的 170 个选择均来自当时合法菜单：24 SEARCH、94 READ、
14 REFRESH_VIEW/build、38 HANDOFF（其中 34 个有 operation_result），没有 USE_VIEW。
80 轮中有 54 轮没有 Host 检索；其余 26 轮有 9 轮没有收到新的外生原文范围。
当前实际送达的 59 处原文为 assistant32/user27，外生40/运行内生19。
无检索、新检索选材遗漏更新、旧问题/旧答案回流、完整材料下答案越界必须分别报告；
不能把读操作次数、缓存中对象存在或到达数量当作新增事实已被 Host 收到。

`old8-e3-aggregate-u32` 已完成全部 80 个首次位置：60 工程完成、20 失败，
110 HTTP / 708,416 已知 Host 总 tokens，新增未知 0。542 处实际原文范围全部绑定，
没有实际送达 View；全部 80 轮不可变 SDK 状态已审计，旧 Source/world/application 保持，
60 个新最终输出仍为 assistant，Saver 消息一致，没有 View 命名空间变化。
whole-child CPU 331.829985 秒由原生/加载 153.670087696 与客户端剩余 178.159897304
各计一次，本地单 GPU 作业区间 0.746116064 小时（包含等待，并非活跃 CUDA 时间）。
目前只审阅前 40 条，C13/Q8/W12/F7，不能当全 80 评分。下一条为 index40 的 D25 content。
E3 同样出现不检索更新，以及 7 次 READ 返回旧报告/问题/Host 答案却没有新号码的情况。
两方法实际 Host 查询及内生历史不同，尚不能隔离内部策略的因果效应。

新 32 组按冻结矩阵开始 `new32-view_cache`，child2956519 / exec4305，320 个首次位置；
它是当前唯一 HTTP 工作进程，原两个旧组作业均已关闭，不能因观察句柄丢失而重跑。
新组增量策略/E3 各 320 个位置尚未执行；各方法仍顺序人工启动，无自动队列。
新 32 族是已有训练暴露的生成 MemOps 对话，不能称未见来源或自然历史确认。
前 8 个新 TRAIN 来源族的实际同 before/旧 View K 控制仍必需：最多每族一帧，
必须有真实初始 View receipt 和 completed-final Host wire；缺失格保留，三方法使用同一
实际 before、完整 Host frame 和已送达引用，经原生查验后用 host-readout，禁止 given-readout 带 K。

成本 v14 在两个旧组作业及绑定/SDK 审计关闭后、新组开始前，一次支付 5 个闭合计时命令
6.76 CPU 秒；模型、加载、客户端和较早费用均未重记。作者/未计时 CPU 仍 unknown。
本轮仅新增离线审阅和记录工具，正式配置、数据、运行时与模型未修改；离线检查的大小写
锚点错误和进度脚本缩进错误已修正，未触发任何模型/工具重跑。
M3 三 seed 的完成结论保持；D 全矩阵、实际 K 控制、全体答案/角色/时间/更新审阅、
最终候选与计分/预算/N 冻结、held 确认及 LME/Mem2Act 全评仍待完成，目标保持 active。

## v12 历史状态（2026-11-06）：三 seed 审阅闭合，D 首方法结束

保留 E3 的三次固定 u32 轨迹与完整答案已全部审阅，来源族始终为同一 64：

| seed | C / I / Q / W / F / U | 对简单基线 25/64 的差值 | 描述性 95% 家族区间 |
| --- | --- | ---: | --- |
| 0 | 40 / 8 / 6 / 0 / 9 / 1 | +23.4375pp | [10.9375,35.9375]pp |
| 1 | 33 / 10 / 4 / 1 / 14 / 2 | +12.5pp | [-1.5625,26.5625]pp |
| 2 | 29 / 16 / 6 / 0 / 11 / 2 | +6.25pp | [-7.8125,21.875]pp |

在每个来源族内对三个 seed 等权取均值，完整数为 34/64 对 25/64，+14.0625pp，
区间 [3.125,25]pp。共同撤去三个解释敏感问题 3/8/56 的 C 信用，仍保留 64 族，
均值为 32/64 对 25/64，+10.9375pp，区间 [0.520833,21.354167]pp。
这是给定三份实际拟合与各自首次 Host 生成、一个基线首次生成的条件描述，
不能把 192 个轨迹当 192 个独立来源，也不能推断完整训练链或所有训练随机性的分布。
两个新 seed 的单独区间均跨零；不挑最高 seed，不据此自动采用或扩量。
原生完整字符串 F1 为 0.0894039 / 0.1203132 / 0.1026735，继续与完整答案质量分开报告。

D `old8-view_cache_incremental` 已结束 80 个首次位置：59 工程完成、21 失败，
121 HTTP / 731,954 已知 Host 总 tokens，新增未知为 0；whole-child CPU 142.015116 秒
已由原 owner 一次记账，无本地模型 GPU。实际 59 个最终输入与 21 个失败最后响应输入、
219 处原文字面范围，以及包含历史 K 的 21 个 View 出现均已绑定；147 个节点与元数据匹配。
全部 80 个不可变的逐轮关闭快照已核对：旧 Source、world/application 保持，
59 个新输出是 assistant Source，Saver 消息一致，10 轮记录到 View 命名空间变化。
首个离线检查误用了已继续运行的 live bank，读到后续轮次来源；已改用每轮捕获的 after
和 closed inventory，保留失败计时，没有重跑模型或工具。

当前只完成该方法前 5 个完整答案的来源审阅，等级为 C/C/Q/W/F，不是全 80 分数。
A19 的新号码在中间三条实际到达来源中已确认，但 Host 没有再次调用检索，
沿用旧 K 中“号码待提供”的错误答案；最终 13 条到达也没有检索，并发生首次输出截断。
这直接定位到自主 Host 的请求／到达信息使用环节，不能只归因于工具内部 READ/HANDOFF。
无当前检索可以合法使用已收到的 K，但来源数量提示不等于已读到新增事实。

D `old8-e3-aggregate-u32` 的另 80 个位置现已启动，child2789465 / exec62075，
GPU2 FP32；它是当前唯一模型／HTTP 工作进程。新 32 族的三项各 320 位置尚未执行，
实际同 before / 旧 View K 控制、全体角色时间／更新／View 与答案质量仍待完成。
原 80 个缓存基线及其 19 个完整答案保留复用，不再生成或计费。

来源族均值的差值样本方差为 0.2038966，检测真实 +5pp 对零差异的条件近似约需 640 族；
这不是最终样本分配或功效保证。D 仍可能改变最终候选，确认前的方法、checkpoint、
计分、预算及样本量尚未冻结，held 256 论文和旧 64 query 内容仍未导出／审阅。

成本结算 v13 在首个 D 方法及输入／SDK 审计结束后、下个方法开始前，
一次支付 5 个闭合计时命令 5.61 CPU 秒；所有既有原生、模型、加载和客户端成本未重记。
作者及未计时 CPU 仍是 unknown。完整目标依然未完成；以下为更早历史记录。

## v11 历史状态：两次复现拟合和 Host 已闭合，D 正式流程运行中

E3 seed1/2 均按原始 FP32 双卡配方完成 128 更新、2048 draws、全部评测点和导出。
实际训练输入为 10,549,642 / 10,607,432 tokens，总计 21,157,074；两作业 whole-child CPU
合计 12,279.603772 秒、两卡作业区间合计 3.877508 小时，原生与客户端剩余分别只计一次。
每个新 seed 的 860 dev＋64 feedback-dev 初始首选、logits 与输入 tokens 均与 seed0 逐值一致；
数据、初始化、完整长度、调度、窗口和原配方字段已核对。这是固定 E1 初始化的训练随机性复现。

两个固定 u32 的 DEV64 自主 Host 作业也已各完成 64 个首次轨迹：

| 方法 | 工程完成 / 失败 | HTTP | 已知 Host 总 tokens | 原文字面范围 | 来源作者完整答案 |
| --- | ---: | ---: | ---: | ---: | ---: |
| E3 seed0 u32（原参考） | 55/9 | 135 | 461,096 | 380 | 40/64 |
| E3 seed1 u32 | 50/14 | 138 | 540,229 | 351 | 33/64 |
| E3 seed2 u32 | 53/11 | 147 | 490,699 | 248 | 待审阅 |

新两作业用量未知新增均为 0，全部完成／失败实际输入与 Source 范围已绑定，无 unmatched；
128 个 Store/Saver/application 状态均已只读审计，原 Source 值保持，新增输出仍是 assistant 来源。
seed1 全部答案等级为 C33/I10/Q4/W1/F14/U2，失败和未知都在 64 分母。
seed0 到 seed1 的差异显示单次开发结果有波动，不能挑最好 seed；训练 RNG 和随机 Host 生成也同时变化。
来源作者参与实现，并非盲审或独立评审。seed2 全部答案及按来源族聚合的 seed 比较仍待完成。
原生完整字符串 Answer F1 分别为 0.0894039 / 0.1203132 / 0.1026735，排序与完整成功不同，
继续独立报告，不抽取短答案、重写 unanswerable 或修复失败。

D 已启动 `old8-view_cache_incremental` 的 80 个连续 Host 位置，child2599138 / exec22180；
它是当前唯一 HTTP 工作进程，不并发启动其他作业。另四个 D 正式作业未执行。
原缓存基线保留其已有 80 个首次结果及 19 个完整答案，不重新生成或重新计费。
新增 32 族 histories 的 schema 元数据在正式运行前与既有 `host_intent_stream_histories_v1` 对齐，
原元数据副本保留，公共问题与 Source 内容未改变；五份实际 native config/input freeze 和位置数通过验证。
完整 1120 个新位置、实际旧 View K 控制、角色时间、更新、材料和 Host 质量审阅仍为必要工作。

外评记录已按实际文件重新核对。LME 的 200 个 Small 历史全部有先前接触，后续输入开发已处理
全部 451 个公共问题和 29 张问题图像，旧 42 个手工问题 ID 清单不能当未接触边界。
22,822 个原文页面的覆盖检查已结束；另一个全公共问题固定路径检查实际只完成 501/902，
还有 1 个部分启动和 400 个未启动位置，pid662822 已不存在，不能把 stale RUNNING 当仍运行或完成。
其中 row231 的一个完整检查路径有两步超过控制器输入上限。

对这个已知状态使用当前已有 observation2048/range256、完整原始库，机械复核仍有两步溢出；
对同一八个状态使用既有 compact JSON 仅减少语法空格，所有状态值和完整动作可逐值还原，
但仍有一步溢出。这些均为 0 模型／0 评分标签的输入检查。
该轨迹由简单 FixedContext 策略产生，简单策略本身不调用 Laya 编码器；因此这是潜在学习输入风险，
不是已经观察到所选 Laya 的两次失败。需要实际 own-policy 状态与完整输入协议核验，
不能只为使诊断通过而缩短预算、截菜单或静默更换推理投影。当前复现和 D 的投影均未改变。
Mem2Act 的 400 任务、429 sessions、16843 turns 及元数据缺口保留；旧 33 个回归数是测试，
不代表 33 个已执行的原生发布任务。正式 Store 摄入、Host 和指标仍待最终冻结后执行。

闲置结算 v10/v11/v12 分别一次支付 78.39 / 89.77 / 4.18 CPU 秒；
原拟合、预测、加载和 owner 剩余 CPU 均未重计。作者及未计时工作仍是 unknown。
没有新服务、第二账本、子代理、SHA 校验或远端写入。此前暂停／恢复丢失的旧 PTY 句柄
通过实际 owner、driver 和 /proc 核对为已结束，没有以句柄丢失为由重跑模型。

证据：`e3-retained-replication/{fit-closeout,answer-review-closeout,native-agreement}.json`、
`d-update32/old8-view_cache_incremental-owner.json`、`external-metadata-readiness-reconciliation.json`、
`lme-known-overflow-observation2048/audit.json` 与 `lme-known-overflow-compact-length-comparison.json`。
完整目标仍未完成；以下 v10 及更早段落为历史记录。

## v10 历史状态：D 可选路径已实现，原生工具切片闭合，正式 Host 待执行

E3 seed1 已正常结束全部 128 更新、2048 draws、最终评测与导出，训练输入为
10,549,642 tokens；whole-child CPU 6086.632939 秒中，原生 6058.777763 与剩余客户端
27.855176 各计一次，两卡作业区间共 1.925072 小时。seed2 已串行启动（child1861976，
exec2604），目标 128 更新、2048 draws、10,607,432 tokens，尚未结束。
两个固定 u32 的 DEV64 Host 作业已在 `e3-retained-replication/host-plan.json` 预定，
还未执行。原五方法的 25/25/33/32/40 结果与 C8 负结果保持，不挑最好 seed。

新增可选 `view_cache_incremental` 保留原 `view_cache`。它仅在用途、对象、时间范围匹配时
复用 View；已验证实际交付引用且 View 内容、revision、时间和完整位置表匹配时，可以省去
重复返回。混合 K 投影若省略了位置表，可能仍重复 View，不虚构已知身份。
该缓存路径每个实际调用最多补一条合法 Source READ，再由既有完整 packet 额度决定交付。
显式 `original_source` 请求继续使用已有 reads4 路径；USE_VIEW 不确认或清除 pending arrivals。
词覆盖只作导航，询问、旧建议和 assistant 输出仍保留原角色，不当已证实事实。

实现中发现新路径在时间不匹配后落回旧 Cache，可能再次 USE_VIEW；已改为合法刷新或原文获取。
原生 schema 允许字符串 read_goal，代码按该实际接口处理；同一策略对象也会按实际工具调用
重置增量上限。6 项新原生检查与 48 项既有相关检查通过，1 项既有 MemPursuit 测试因包缺失跳过；
Ruff、包 DAG 和 tools Product 依赖清单通过。保留首次测试失败与计时，不升级依赖，不声称完整 CI。

预定 8 个旧背景的初始 content 工具切片中，7 个有实际捕获，B30 没有该捕获，保留缺位，
没有换成后续轮次或另一流程。7 个实际请求从原 before、菜单和额度执行一次可选策略，
没有新模型调用或 Host 回答。它们都从无 View / 无 K 状态开始，属于真实冷启动工具机制，
尚未验证实际暖缓存 USE_VIEW 或 K 复用。共 13 次 READ：5 个缓存路径各 1 次，
2 个显式原文路径各 4 次；返回 3 个 View＋raw packet、9 处字面 Source 范围，
其中角色为 7 assistant / 2 user。原 Source 值保持，extractive 节点逐字绑定原文，
返回 View 结构与实际持久化结构一致。E15 有一次 View 超预算，原文单独交付成功；
这只是 packet 机制，不能当任务成功，也不自动触发整个 1024 矩阵。

D 三方法协议已在新增 32 族正文投影前冻结：共用最强旧表示 extractive View，
保持 Host thinking=True、rich 接口、2048 返回、24 共享调用、8 控制步和 8 additional reads。
旧 8 族的缓存基线代码及七份共享执行器/Host 文件与原 E5 冻结版本逐字一致，
可以复用原 extractive2048 的 80 个首次结果及其失败和成本；19/80 优于旧 raw13/80、generated8/80。
新两策略仍须在旧 8 族完整运行 160 个位置，新 32 族三方法须运行 960 个位置；
总计 1120 个新自主 Host 位置，加 80 个已有基线，共 1200 个正式位置。
`d-update32/matrix-plan.json` 的五个新作业均未执行；训练仍占用 GPU 2/3，不并发启动 HTTP。

新增 32 个 TRAIN 背景的 64 条连续流程和每方法 320 个请求已闭合来源准备。
29 份先前来源合同按文件匹配复用，A02/C02/D02 三份由当前作者完整阅读各 24 个原生对话 turn 后编写。
768 个对话 turn 仅供离线来源审阅，实际 Host 最终原生前缀为 736 个不同 Source，
在最后用户 cut 后的 assistant turn 不进入 Host；另有每流程一条明确构造的 USB 位置干扰。
原角色、内容、顺序和所有前缀用户证据均已绑定；Host histories 不含原生 answer、operation、difficulty 标签。
原生 JSON 容器已解析，包括共存元数据字节；没有把该字节访问说成零，只投影对话角色与正文。
中间自然批次 A02 对所问工作名称字段无关，其他 31 族涉及增补、更正、适用范围、状态或不确定性，
不能统称无关，也不是 31 个相同的数值翻转。USB 控制按各自请求审阅了无关性，包括笔记本配件情形。
这些背景已有 TRAIN/来源暴露，MemOps 是生成的 benchmark 对话，不是新未见数据或自然实测。

实际同 before / 已知旧 View 的 Host 控制仍未运行：预定前 8 个新增 TRAIN 背景，
每族最多一个有真实 View 交付引用和 completed-final Host wire 证据的状态，缺位保留。
三方法使用同一完整受控 Host frame、实际 K 和新来源，经 native delivered-snapshot 查验，
使用 host-readout；不能用带 K 的 given-readout，也不能将连续聊天等同于声明了已知 View。
这类条件控制与完整自主流程分开报告。

新 D 计时、测试和原生工具切片计时共 69.29 CPU 秒尚待训练结束后一次结算，
原生切片已计入账本的 CPU 为 0；作者及未计时工作仍是 unknown，不记 0。
所有原模型、原基线和既有成本保留；没有第二账本、服务、审核 Agent、SHA 校验或远端写入。

证据：`d-update32/{protocol-before-body-projection,old8-state-and-baseline-audit,source-author-contracts,`
`new32-histories,new32-source-requirements,new32-source-preservation,matrix-plan,`
`optional-native-initial-slice-closeout}.json`。以下 v9 及更早段落保留为历史形成记录。

## v9 历史状态：五方法已闭合，保留 E3 复现，D 仍待实现

DEV64 的五方法、320 个完整答案与实际输入全部完成来源作者审阅。该作者也参与实现，
并非盲审或独立评审。所有首结果和失败保留在每方法 64 族分母中。

| 方法 | 完整答案 | 工程完成 / 失败 | HTTP | Host prompt＋completion tokens | 原生字面 Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| fixed-prefix | 25/64 | 49/15 | 143 | 528,693 | 0.0774154 |
| E1 u16 | 25/64 | 45/19 | 154 | 622,629 | 0.0802133 |
| B0 u33 | 33/64 | 59/5 | 139 | 504,911 | 0.0947629 |
| B1 u33 | 32/64 | 53/11 | 151 | 580,186 | 0.0978627 |
| 既有 E3 aggregate u32 | 40/64 | 55/9 | 135 | 461,096 | 0.0894039 |

E3 对 fixed-prefix 为 17 gains / 2 losses，+23.4375pp，描述性 95% 家族 bootstrap
区间 [10.9375,35.9375]pp；对 B0 为 12/5，+10.9375pp，区间 [-1.5625,23.4375]pp。
B1 对 B0 为 12/13，-1.5625pp，区间 [-17.1875,14.0625]pp。
将三个来源解释敏感问题 3/8/56 的完整信用对所有方法同时撤去，仍保留 64 族，
计数为 25/25/30/31/38；E3 对简单方法为 15/2，+20.3125pp，区间 [9.375,31.25]pp。
这项事后敏感性不替代主指标，也不构成独立裁决。

五方法共 722 次 HTTP、2,697,515 个已知 Host 总 tokens，新增未知用量为 0。
全部 320 个结束状态（含 59 个失败状态）的 Store/Saver/application 已只读核对；
每方法 4,343 个初始 Source 值保持，实际输入绑定 1,733 处原文字段且无 unmatched。
最终 assistant Sources 是输出，不能当事实；没有 semantic-record 写入。
原生 F1 采用实际完整回答和原生全部答案，不抽取短答案、不重写失败或 unanswerable，
其排序与来源作者完整成功不同，不能代替主指标。

所有 64 族的首个 Host provider 请求在五方法间逐字一致，但五者首轮实际检索参数列表
完全一致的族为 0/64；因此完整轨迹包含随机 Host 查询变化，不能将端点差异孤立归因于
控制器或新数据组成。E3 的旧 457 slots、128-update 调度、双卡 FP32 与新 B 配方的
528 slots、66-update 调度、单卡 BF16 也不同。实际返回 Tool.content 正文均不超过 2048 tokens。
E3 whole-child CPU 为 692.684918 秒，其中原生预测 506.823635、加载 7.990816、
剩余客户端 177.870467 各计一次；GPU 作业区间 0.5468298 小时含 Host 等待。
简单方法 CPU 为 203.499353 秒。较低 Host tokens 尚不能证明全成本占优。

E3 仅保留为开发参考。精确 seed1/2 配方已冻结并启动：复用原冻结 runtime、数据和
FP32 双卡 argv，仅 seed、输出目录、compute-phase 改变；每次仍为 128 更新、2048 draws，
评测点 0/16/32/64/128，后续自主 Host 固定评估 u32，不挑最好 seed。
这衡量同一固定 E1 u16 初始化下的训练随机性，不是完整训练链三次独立拟合。
seed1/2 预期实际训练 tokens 分别为 10,549,642、10,607,432；实际结束后核对。
当前 exec2604、seed1 child1638434，随后 seed2 串行；无并发 HTTP。

所保留 E3 也完成 C8 原菜单诊断：8 次真实 HandoffOnly 投影后的本地 forward，
8 个选择全部复用 30 个已有绑定中的最早首次结果，新增 Reader 调用为 0，完整答案 1/8；
与其他学习模型相同，低于 fixed_context/rules 的 4/8。未发现应扩菜单的表达缺口。
该诊断不等同完整自主反馈策略；可优先保留简单材料选择职责。

D 的 9 个旧 post-REFRESH READ＋HANDOFF 机制探针已闭合，但可选增量策略、
实际 old View / known-evidence 控制、旧 8 背景全流程与新加入 D 的 32 个 TRAIN 背景
自主 Host、同信息比较仍未完成。不能从原生 View＋raw packet 推断任务提升。
新 32 已有历史 TRAIN/来源暴露；不称未见、自然实测或独立确认。

按当前 E3 对简单方法的族差值样本方差 0.2457837302，近似检测真实 +5pp 对零差异
在双侧 5% / 80% 下约需 771 个独立族；这只是条件规划，预留 256 不保证该功效。
最终方法、checkpoint、计分、预算与确认样本量仍须在 held 内容打开前冻结。
当前 64 族是已曝光开发；held 256、旧 64 query 确认内容未导出/审阅，native test 未打开。

成本仅用原账本：v8 在五方法结束后、C8 E3 之前结算 10 个计时命令 24.68 CPU 秒；
v9 在 C8/复现准备完成后、复现启动前结算 2 个计时命令 1.04 CPU 秒，均只计一次。
E3 C8 whole CPU 31.074597＝原生 15.060130＋客户端 16.014467 已另计一次；
作者及未计时 CPU 仍为 unknown，不记 0。所有第一失败和意外 A 重复调用的成本保留。

证据：`task-dev64-development-selection.json`、`task-dev64-paired-selection-progress.json`、
`task-dev64-cost-and-entry-audit.json`、`task-dev64-all5-native-agreement.json`、
`c-handoff8-e3-saved-choices.json`、`e3-retained-replication/{plan,driver}.json`。
以下分包记录保留形成过程；本节与 v9 manifest 是当前状态。

## P0：已取得真实运行证据

GPU 2、3 是独立的 A100 PCIe 40GB；每进程仅见一张卡，进程内为 `cuda:0`。
GPU 0、1 上的既有服务没有变动。运行环境仍为 Torch `2.7.0+cu126`、CUDA `12.6`、
Laya SDK `0.4.8` 与 `train_with_declared_attention.py` 初始化，不升级依赖。

训练入口新增 `--device`、`--parallel-mode single|legacy-dp`、`--precision float32|bf16`
和可选 allocator 份额。默认仍为 legacy-dp/FP32；BF16 限于单卡路径，显式 autocast
仅覆盖 forward，SDK 返回 FP32 logits 后计算损失，参数和 Adam 状态保留 FP32。
窗口、pair 同批、末窗口分母、学习率与目标语义沿用原实现。

两臂从同一 E2 初始化开始，各完整训练 512 条 TRAIN 数据、32 次更新。
包含全部 6 个 change pairs，最长 9,869-token 输入、最长 1,120-token head、最多 45 个候选。
两臂实际窗口、选项置换及 639,380 个训练输入 tokens 逐值一致；未丢弃输入。
前 4 更新计入全成本，稳态统计使用后 28 更新。

| 实测项 | FP32 | BF16 |
| --- | ---: | ---: |
| 训练段秒数 | 245.754 | 105.758 |
| 稳态平均秒/更新 | 7.570 | 3.229 |
| 稳态输入 tokens/秒 | 2,629 | 6,164 |
| 峰值 allocated GiB | 10.26 | 9.25 |
| 峰值 reserved GiB | 18.23 | 17.49 |
| 512 行落盘重载后首选变化 | 0 | 1 |

稳态时间比 2.345× 只描述这个 profile。其 operation 比例和长度分布不同于完整 A 面板，
不能直接承诺完整训练工期。reserved 已包含 allocated，不相加。
共同 FP32 推理下，update0 的 512 个首选全部一致，update32 两臂有 508 个一致。
两臂均完成全部 512 条保存后重载，并核对实际模型输入、tokens 与数值。
SDK 实际导出 170 个 FP16 权重 tensors，重载为 FP32；BF16 臂 index177 的首选变化前
margin 为 0.0250。保留这一变化，候选选择必须核对落盘模型，不能将内存模型分数冒充落盘行为。
9,869-token 实例已成功执行；这不证明有效 12k 上下文。

证据：`p0-plan.json`、`p0-data/preparation.json`、`p0-analysis.json`、
`p0-{float32,bf16}/` 与 `p0-{float32,bf16}-reloaded/`。
原生单卡/BF16、完整 pair、梯度累积、mask/padding、保存重载等相关 61 项测试通过；
提名和交付相关另 27 项测试通过。Ruff、包依赖与工具 Product 依赖边界通过；未声称完整仓库 CI 通过。

## A：实际暴露修复，两个完整 seed0 拟合已闭合

同一源码分别用 `legacy` 与 `native-priority` 生成 10k 条件家族面板。
先保留原选择，再在同一实际条件的已知负例槽内替换；change 端点不可替换。
对替换优先保留可完整形成的 stable-negative 关系。

| 数据项 | A0 legacy | A1 native-priority |
| --- | ---: | ---: |
| query 家族 | 10,000 | 10,000 |
| 条件行 | 39,982 | 39,982 |
| 正例 / 负例 | 20,008 / 19,974 | 20,008 / 19,974 |
| 具备原生负例的条件 / 实际覆盖 | 9,540 / 5 | 9,540 / 9,540 |
| change pairs | 6 | 6 |
| stable-positive pairs | 80 | 80 |
| stable-negative pairs | 9,968 | 433 |
| 加入既有 replay 后有效训练行 | 44,868 | 44,868 |

共替换 9,535 条负例。正例、replay、公共 dev、每条件正负槽数及逐槽损失权重一致；
保留原 row slots，使正例和 replay 的选项随机身份不随重排变化。
stable-negative 信号同时变化，不能声称只改变了一个负例计数。
选入覆盖与完整拟合中的实际抽样均已核对；实测 tokens 和覆盖见下文完整训练记录。

源记录核对发现 E2 实际使用 `max_len=16384`、head 上限 `2048`、encoder LR `5e-6`，
操作 replay 使用 accepted-set likelihood。两臂共同继承这些实际值：条件单一正目标与 CE 等价，
操作 replay 保留 set 语义；不把模板中的 `12288`、`2.5e-5` 或 replay soft-CE 混入处理。
同一原 E2 起点、full 参数、BF16、micro2、窗口16、relative weight0，
各 1 次完整遍历/2,805 更新，检查点为 0/702/1403/2104/2805，末窗口4行。
profile 输出不作为初始化。预定选择规则和完整命令保存在 `a-seed0-plan.json`。

两个正式作业的共同 update0 在3,068个dev和64个feedback-dev上，首选、输入tokens及全部logits逐值一致。
702检查点已经实际落盘，已观测的诊断为：

| 检查点 | 条件家族平衡准确率 | 操作家族准确率 | 旧8对支持条件变化联合正确 |
| --- | ---: | ---: | ---: |
| 共同起点0 | 0.752563 | 0.778851 | 6/8 |
| A0 update702 | 0.890389 | 0.801943 | 1/8 |
| A1 update702 | 0.820530 | 0.801919 | 5/8 |
| A0 update1403 | 0.885107 | 0.798606 | 1/8 |
| A1 update1403 | 0.828600 | 0.782987 | 5/8 |
| A0 update2104 | 0.895039 | 0.793754 | 1/8 |
| A1 update2104 | 0.845812 | 0.799413 | 5/8 |
| A0 update2805 | 0.885959 | 0.803642 | 1/8 |
| A1 update2805 | 0.824376 | 0.800519 | 5/8 |

A1减少了A0在这组诊断上的退化，但尚未超过初始化；不能凭一个检查点选择最终模型。
两臂均已完成预定2,805更新、恰好44,868行一次遍历、末窗口4行，进程正常退出。
A0/A1实际输入37,502,475/37,318,166 tokens，实际抽到原生负例条件5/9,540，
GPU作业时间2.3430/2.3810小时；每臂22,434次单卡microbatch forward。
窗口、选项置换、逐槽权重、完整输入、全部检查点、评测计量与原账本相应单次phase已核对。
预定门槛下两臂均提名2104；落盘行为与旧32族条件任务已闭合，自主Host和新来源确认仍待执行。
该表为内存模型统一FP32推理，不替代新128条件家族或自主Host。
证据为 `a-diagnostics-through-2805.json`、`a-full-fit-closeout.json`。

新的128条件DEVELOPMENT家族来自既有canonical DEV新query分配，排除旧32和已预留64查询家族，
没有跨分区重分配。原生矩阵8,744行：已知8,202、未知542、稳定对3,830、变化对0。
在新模型输出前按两种结构层各取首8个未知对应单元做来源判断：新增12个可归因标签、4个仍未知，
复核视图形成3,840稳定对、2变化对、530未知对；原生视图与gold保留不动。
判断仅为提供材料的适用性，不认证外部事实、医疗或来源可信度；歧义/可信度未决保留unknown。
这2个变化对不足以支持稳健条件泛化结论；8,744行也不等于8,744个独立家族。
三模型（初始化及两臂提名）的7个GPU3落盘评测已全部正常退出；新面板原生与复核标签共用一次实际预测，
初始化旧公共3,132个已核对的实际落盘起点预测复用，不重复模型调用。

新128族原生标签上的家族平衡准确率：初始化0.661798、A0提名0.883766、A1提名0.838801；
复核16视图分别0.661067/0.884680/0.838142。仅2个来源复核变化对的家族联合正确率为
0.5/0/0，不能从分类提升主张条件变化泛化。旧8对按其实际5个query家族聚合为
0.866667/0.1/0.4；“8对”不是8个独立家族。
落盘分析见 `a-saved-evaluation-closeout.json`。当前不扩大A20k、不自动追加seeds或A→B。
另已完成两提名模型在旧32族任务面板的31个真实完整菜单状态预测；
按实际完整绑定、同before/续行/readout匹配复用旧首结果。补核发现此前索引漏纳E3的22个闭合绑定，
导致A新增11次HTTP中有1次重复了较早E3绑定，实际新绑定为10个。
重复的WSJ状态首动作、续行和packet完全一致，较早回答因把n-gram LM误说成最佳端到端模型而qualified，
较晚回答更好；主统计恢复较早结果，不挑选后一次。两份输出、源审和全部费用都保留。
较早E1/E2/E3评分保持，缺失状态仍保留在32族分母。

| 旧32族条件任务 | raw delivery | 初始化E1-u16 | A0-u2104 | A1-u2104 |
| --- | ---: | ---: | ---: | ---: |
| 完整成功 /32，较早首结果口径 | 14 | 14 | 15 | 15 |

A0/A1相对初始化均为3 gains/2 losses，差值+3.125pp，来源族bootstrap描述性95%区间
[-9.375,+15.625]pp；两臂的完整成功指示逐族相同，A1相对A0没有新增成功。
旧16/32汇总由此次较早首结果核对取代，不能再作为权威任务结果。
该面板不提供native-priority的任务采用依据；A20k、更多seed和A→B均未触发。
完整回答中的无依据“所有标注均自动完成”“明确手工调参”等扩展保留为qualified，
没有因为核心片段正确就升级为完整成功。旧“existing approaches”的统一宽范围解释保持，
不临时收窄成四个基线名。条件readout与自主Host分别报告。
证据：`task-first-outcome-registry-v2.json`、`a-task32-closed-choices-v2.json`、
`a-task11-outcomes-for-review.json`、`a-task11-author-decisions.json`、`a-task32-results-v2.json`；
原生完整字符串F1单列于`a-task32-native-agreement-v2.json`，没有替代完整任务指标。

## B：先补真实功能，保留原首结果

已有 57 个 TRAIN 状态的动作和完整参数 inventory 已保存。
新增可选 `parameter_coverage` 提名模式，使用合法菜单、已有执行类型覆盖和固定 seed，
排除 observe-only、分页观察与相同绑定，不查看答案或质量结果。
原 fixed_context/acquired_raw_delivery 行为保持可复现。

8 个真实后续状态均满足 argmax、baseline、alternative 三个完整绑定互异。
新执行只包括此前未执行的 8 个 alternative：2 full observed-Source READ、2 range READ、
1 context READ、3 实际材料 HANDOFF。argmax/baseline 的旧首结果不重跑。
这是一组已曝光 TRAIN 功能切片，不增加独立来源数。
原 capture 均为显式 supplied request、`host_request_generated=false`、空 known refs，
故沿既有 `--given-readout`；结果属于条件 readout，不能称为自主 Host 成绩。
8个状态现已完成Source、执行边界、完整参数、packet和readout wire绑定及来源作者质量评审。
4个observed-Source READ均实际打开并返回所选范围；全部16个返回范围匹配实际Source正文与角色。
新替代完整回答1/8、原baseline3/8；答案比较为5 tie/3 baseline更好，
交付为4 tie/3 baseline更好/1 unknown。8个新HTTP、30,879已知生成tokens、新未知用量0。
这是功能和负面监督证据，不能从“Source已读”推出质量增益。
后续提名沿既有非空材料判断排除空HANDOFF子集；已经执行的空交付及失败结果不修改、不重跑。

证据：`b-repair-inventory.json`、`b-functional8-actual-nominations.json`、
`b-functional8-branches-v2/`、`b-functional8-execution/`。
质量证据为 `b-functional8-quality-review.json`。

## C：原菜单、同已读池的真实比较已闭合

从实际捕获的8个已读状态选择每族一个状态，均有至少2份已取得材料和3个合法HANDOFF候选。
沿既有F1入口准备，8个完整菜单均与原菜单逐值相同；没有新增候选、重新取得材料或重跑前缀。
fixed_context、rules、保留的E1 delivery-only-u16分别执行一次HANDOFF及给定请求readout。
学习候选在现有CPU路径运行，4线程，2/3卡继续留给配对A拟合；这不是A100推理延迟测量。

| 方法 | 完整 /8 | readout失败 | 已知生成tokens | 已计本地模型CPU秒 |
| --- | ---: | ---: | ---: | ---: |
| fixed_context | 4 | 0 | 23,831 | 0 |
| rules | 4 | 0 | 17,011 | 0 |
| E1-u16 learned | 1 | 2 | 30,267 | 380.644 |

全部24个首次位置、62个原文范围、实际HANDOFF和readout输入已绑定；24 HTTP、71,109已知生成tokens、
新增未知用量0。两次失败保留在完整任务分母；涉及失败readout的答案偏好为unknown，交付可独立判断。
CPU表只列已经由native计量记录的模型部分；整进程447.88 CPU秒还包含客户端等工作，不能重复相加。
这组条件readout结果不是自主Host或未曝光确认，也不能从CPU成本换算A100延迟。

三个状态明确存在“材料已取得、合法集合已有、学习选择却丢掉关键材料”：UAR指标、词义/句法区分、
模型参数数量。另有OpenIE和树库增量规模的上游获取缺口；TutorialVQA既丢掉已取得的部分指标，
也缺少尚未取得的tolerance accuracy。FSE/regularization仍保留原来源判断中的限定与unknown。
rules/learned在一个状态收到完全相同的packet和wire，不将其措辞变化当作选材收益。
这些证据支持优先补完整参数/集合监督，当前没有需要扩展HANDOFF菜单的证据。

之后又在相同8个实际池上取得E1初始化、B0-u33、B1-u33的24次实际GPU3选择。
核对源码后按现有`HandoffOnlyPolicy`在编码前限制决策菜单；执行器原始完整菜单仍保留，
不是对完整菜单argmax做事后屏蔽。8个输入均与生产策略的实际投影逐值一致。
旧完整绑定复用较早首结果，新增仅6个不同HANDOFF，经既有首动作干预执行，续行0、READ0。
全部实际receipt、同wire条件与原始Source范围已绑定，5次readout完成、1次首次失败。
源审后E1/B0/B1均完整1/8，原两个简单方法各4/8；新选择仍包括空集或缺关键事实的单段。
没有菜单表达缺口或采用依据，保持失败和全部已计成本。
证据：`c-handoff8-saved-plan.json`、`c-handoff8-new6-outcomes-for-review.json`、
`c-handoff8-new6-author-decisions.json`、`c-handoff8-retained-model-results.json`。

证据：`c-handoff8-selection.json`、`c-handoff8-v2/`、`c-handoff8-bound-results.json`、
`c-handoff8-quality-review.json`。三个方法仍只是这个功能切片的比较，不作采用结论。

## 新来源的实际分配

沿既有1,169篇论文allocation，扣除实际已采集的64个TRAIN家族，从既有TRAIN分配中选取新的64家族，
保留原生问题和4,502个Source单元；每族使用第一个既有问题，实际reached states及分支已全部采集。
另从parent中尚未使用的身份元数据分配新的64任务DEVELOPMENT家族，并预留256确认家族
（185 native-dev、71 native-train），各组及旧64族核对互不交叉。
确认正文与标注尚未导出/查看；冻结候选、规则、预算后才使用。公开预训练隔离未获认证，
256也不是+5pp的功效保证。新128条件开发家族属于另一数据轨，其实际原生/复核标签结果见A节。
证据为 `source-allocation-v1.json`；分配接续parent和实际使用记录，不直接套用历史unused计数。
采集已准备为8＋56两个串行段，配置预检查完成且模型调用为0；见 `b64-collection-plan/plan.json`。
释放GPU后使用现有FP32推理路径，保留关闭reference_compile的既有初始化并记录实际设备、精度和峰值显存；
checkpoint没有持久化该encoder标志，不能仅换解释器后依赖其默认值。

首8族实际GPU采集现已闭合：64次本地决策、395,334本地输入tokens、8次HTTP、31,730已知生成tokens，
8个首次readout均完成、新未知用量0。实际加载记录验证cuda:0/物理GPU2、FP32、4线程、MHA fastpath关闭、
reference_compile关闭；峰值allocated2.305GB、reserved7.999GB，整客户端206.85秒含Host等待。
这不是与历史CPU批次的纯硬件因果比较，也不是质量胜出结论。
剩余56族也已在相同冻结collector下正常退出。完整64族共512次本地决策、3,115,914本地输入tokens、
64个HTTP readout全部完成、237,960已知生成tokens、新未知用量0。
两段实际query/public task、完整输入及首次readout均已核对，见 `b64-full-collection-reconciliation.json`。

来源状态提名现增加可选`acquired_parameter_support`：每族最多2个实际已获材料且具备互异
argmax/baseline/alternative的状态，缺口保留。`--exact-nominations`防止准备器回填未合格状态。
旧默认初始/后续采样保持可复现；48项相关检查通过，并在旧真实捕获上零模型调用复核16状态/48绑定。
新首8族也选入16状态/48互异绑定，其中3个满足既有单剩余槽terminal READ复用协议，
保留其原始首readout；45个新绑定现已正常退出。
其余56族实际选入112状态/336绑定，其中23个同样复用首结果，313个新绑定也已正常退出。
全B64达到128个合格状态、384个真实完整绑定，358个新分支与26个原始等价末READ首结果。
B0/B1仍共用完整菜单与一次实际baseline；这些是64族而非384个独立来源。
358个新分支共358次HTTP、1,257,699已知生成tokens、新未知用量0；384个绑定中
373个readout完成、11个首次readout失败。全部1,613个Source范围、角色、完整首动作、
已执行前缀与共同续行、同一Reader wire中实际packet均已绑定，失败未重试。
26个复用readout成本保留在原64族前缀采集，不再收取；baseline实际执行128次，供两面板共享。
证据：`b64-branch-closeout.json`及两段`outcomes-for-review.json`。

## B64：配对训练与旧32族任务已闭合

384份实际交付包已逐一源审，记录充分94、部分106、不足178、不确定6。
原生标注只作来源线索：表格标题不能恢复数值，截断段落不能补全缺失实体，
实际Queensland结论95%与原生答案96%的差异原样记录，Brier/ROC的适用范围分别保留。
六份不确定材料来自同一“baseline”含义未决的来源，两状态比较保持unknown。
完整回答现已完成全部64族、384个实际首结果的来源作者审查：
107完整、199不完整、60带无依据内容或推断、1核心错误、11首次失败、6未决。
实际闭合拟合文件中的新增256个answer比较始终保持unknown，未用后续审查回填训练。
交付标注没有被转换为回答成功。部分回答在材料充分时仍误述共享组件、初始化或方法组合，
也有粗粒度材料partial但能通过合法的宽范围解释回答问题的情况，两层指标不互相替代。

| 新128状态纯delivery监督 | B0 argmax↔baseline | B1 alternative↔baseline |
| --- | ---: | ---: |
| 方向比较 | 9（左5/右4） | 23（左2/右21） |
| tie | 117 | 103 |
| unknown | 2 | 2 |

97个状态的两比较同时为tie，常见原因为双方都缺必要事实；tie并不表示任务成功。
覆盖提名得到更多方向，其中21/23偏向baseline，不能据此声称提名有效或扩大192/256族。
若下一批采集有依据，应利用真实可见请求与证据缺口改进提名，不只平衡动作类型。
交付质量按本轮TRAIN编译时固定的充分/部分/不足粗粒度比较；同为部分的tie不表示事实集合完全相同。

完整回答的B0比较为左优19/右优12/tie85/unknown12，B1为左优10/右优32/tie72/unknown14。
两面板均没有已知左右方向相反的answer/delivery比较；新增答案方向主要来自原delivery粗粒度tie，
分别23和25个。27个完整答案对应旧材料代理的partial，主要涉及宽范围问题的合法替代证明、
聚合改进值或代理要求的额外清单；不能把代理定义差异自动称为训练目标的因果缺陷。
字面相同packet的配对分别4和13个，B1其中3个仍产生不同方向的答案偏好，体现单次生成变化。
这些是TRAIN首次读出的事后诊断，没有重跑或挑选较好答案，没有启动answer-first补训或扩大样本。
来源说明及对应实际readout见`b64-answer-review-full.json`和`b64-postfit-quality-diagnosis.json`。

两臂均使用相同完整菜单、状态、旧400行、E1-u16起点及E3实际纯delivery配方：
quality-tie、component-sum、replay accepted-set权重0.25、encoder/head LR 5e-6/1e-4、
shared_actions、full参数、BF16单卡、micro2/窗口16。
每臂528个slots，两次实际暴露，1,056行、66更新，预定检查点0/17/33/66，
完整输入预算均5,756,552 tokens。最长原生输入11,882 tokens，state/head无裁剪；
这仍不是有效12k上下文的认证。两独立作业分别使用GPU2/3，原账本短写锁保持。

共同训练前评测的操作家族接受率0.778851、纯delivery方向准确率0.949554。
完整66更新均已正常退出，各实际1,056行、5,756,552 tokens；原528个slots各遍历两次。

| 检查点 | B0操作接受率 | B1操作接受率 | B0纯delivery方向 | B1纯delivery方向 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 0.778851 | 0.778851 | 0.949554 | 0.949554 |
| 17 | 0.781510 | 0.781915 | 0.713170 | 0.749851 |
| 33 | 0.786732 | 0.775427 | 0.941741 | 0.842039 |
| 66 | 0.785654 | 0.774003 | 0.910491 | 0.749107 |

按已冻结的非零提名/操作回退2pp门槛/最早tie规则，两臂均提名33；提名不表示采用。
GPU作业区间分别0.534955/0.540089小时，整子进程CPU分别3,072.901/3,097.578秒；
native及客户端残余各计一次。allocated/reserved峰值单列在两臂`compute.json`，不相加。
共同起点的实际GPU完整菜单及两提名落盘模型共93状态评测已闭合。
完整复用索引含136个有效before下较早首绑定，B仅新增5个不同绑定，均完成实际来源/输入绑定和源审。

| 旧32族条件任务 | raw delivery | 共同初始化 | B0-u33 | B1-u33 |
| --- | ---: | ---: | ---: | ---: |
| 完整成功 /32 | 14 | 14 | 13 | 13 |

两臂相对初始化均为1 gain/2 losses，差值−3.125pp，描述性95%区间[-15.625,+6.25]pp。
B1相对B0为1 gain/1 loss，差值0，区间[-9.375,+9.375]pp。
旧面板没有支持新增覆盖监督的任务收益；当前没有B候选采用，也不触发192/256扩量或额外seed。
证据为`b-full-fit-closeout.json`、`b-task32-results.json`及`b-task32-native-agreement.json`。
数据与配方见`b64-delivery-author-guide.json`、`b64-matched-training/plan.json`；
终态审计及落盘菜单准备脚本`close_b_fits.py`已对实际闭合两臂执行。

## 新64族：真实自主Host正在执行

在导出选中的64篇新DEVELOPMENT正文之前，冻结五个方法、完整请求/额度与评分协议：
最强既有简单fixed-prefix、共同E1-u16初始化、B0-u33、B1-u33及旧E3-aggregate-u32研究参考。
E3参考仍未被采用，其原128更新/457 slots与新两臂不同，不能用于隔离数据组成的因果比较。
原生dev容器由解析器读取，但只投影这64篇论文、4,279个Source单元；未导出或语义检查预留确认内容，
未打开native test。新64族从此属于方法选择开发曝光，不是确认集。

fixed-prefix先执行8族，捕获每题实际首次Host前Store/Saver，再对未执行56族按同协议首次运行。
两段均已正常退出，全64族49流程完成、15首次失败；143次HTTP、528,693已知tokens，新增未知用量0。
49个完成的最终输入、15个失败的最后已响应输入分别绑定，共252个原文范围，0未匹配。
全64完整答案已逐题源审：25完整、11不完整、9带无依据内容、1核心错误、15首次失败、3范围未决。
主指标完整25/64（39.0625%），失败与未决均留在64分母；未决问题的范围单列，不强行套用原生答案。
材料为29充分、20部分、12不足、3未决，不能把49流程完成直接当任务成功。
其余四方法使用相同64个真实初始快照，仅覆盖策略/checkpoint，保持原始任务、初始Host上下文与额度。
E1-u16已完整退出：45流程完成/19首次失败，其中15输出截断、4JSON动作格式失败。
154次HTTP、622,629已知tokens，新增未知用量0；45个完成final和19个失败最后已响应输入均已绑定，
321个原文范围、0未匹配。完整回答现已全部源审：25完整、13不完整、5带无依据内容、19失败、2未决。
B0-u33也已完整退出：59流程完成/5首次输出截断，139次HTTP、504,911已知tokens，新增未知用量0。
59个完成final和5个失败最后已响应输入共372段原文范围，0未匹配。
B0完整回答也已全部源审：33完整、14不完整、9带无依据内容、5失败、3未决。
B1已正常退出：53流程完成/11首次失败，含7输出截断、4JSON动作格式失败；
151次HTTP、580,186已知tokens，新增未知用量0；408段原文范围逐字匹配，0未匹配。
B1全部完整回答仍待源审；E3参考已接续运行。实时状态见最新progress。
没有提供检索query、强制检索或改成最后单次Reader；Host自己生成工具请求并完成任务。

| 新64族自主Host | fixed-prefix | E1-u16 | B0-u33 | B1-u33 | E3参考 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 来源作者确认完整 /64 | 25 | 25 | 33 | 待审 | 待执行闭合/审查 |

E1相对fixed-prefix为8收益/8退步，差值0，来源族描述性95% bootstrap区间[-12.5,+12.5]pp。
B0相对两者均为13收益/5退步，差值+12.5pp，区间[0,+25]pp；各方法仅一个首次随机轨迹、训练seed0，
尚未完成五方法选择、复现或独立确认，不能归因于单独的数据组成因素。失败与未决继续留在64分母。
收益/退步指来源作者完整认定的变化，未决项没有被宣判为已知失败。

逐题来源说明在结果后编写，作者非独立、非盲审。原文补核发现预处理论文的附加实验确有第四层，
并非初述三层与结论四层相矛盾。通用“完整、忠实且回答实际问题”原则保持；具体范围解释均有旧说明及修正记录。
对三个依赖宽范围解释的题目（模型描述、示例实验与正式benchmark、视觉语境检查与空间对齐），
另做统一不计完整认定的事后敏感性分析，所有方法仍保留64分母：B0为30/64，其余两者25/64，
差值+7.8125pp，区间[-3.125,+20.3125]pp。这不替换主指标，也不是独立复核或确认。
证据为`task-dev64/source-author-reviews.json`和`task-dev64-paired-selection-progress.json`。

既有官方QASPER evaluator另行处理三个闭合方法的原样完整字符串，Answer F1分别0.077415、0.080213、
0.094763，未提取短答案、重写unanswerable或修复失败。它只是选中开发面板的字面一致度，
不能替代完整任务成绩，也不是全量原生benchmark或原生整段Evidence F1。

首8族实际5流程COMPLETED/3FAILED，20次HTTP、84,582已知tokens，新增未知用量0。
三次输出截断保持首次失败；5个完成的最终provider输入及3个失败的最后已响应输入分别绑定，
共32个原文范围逐字匹配，0未匹配。失败请求的输入可证明材料可见，不代表完成最终回答。
成功结果显式记录语义receipt为0，失败结果省略该字段，因此另行核对实际Store/Saver/业务数据库。
fixed-prefix、E1、B0与B1共256个终态均已只读审计，包括50个失败状态；每方法4,343个初始Source值
逐值保留，含64个当前任务Source。四方法分别新增49、45、59、53个正确标为assistant的最终回答Source，
没有新语义记录，world及业务表与共同before相等，Saver末checkpoint消息与实际结果逐值相等。
临时writer输入映射、操作journal与Saver变化明确保留，不把它们称为语义提交。
这只核对独立论文任务的状态行为，不认证答案事实，也不代替D包的更新/View/业务功能实验。
证据：`task-dev64/protocol-before-body-export.json`、`task-dev64/plan.json`、
`task-dev64-answer-review-closeout.json`、四方法`SDK-state-audit.json`及完成/失败输入审查包。
来源作者并非独立或盲审；通用评分在正文投影前固定，逐题来源说明在实际运行后编写。
宽问题可接受其他有依据的证明；原生yes/no冲突、caption缺数值、全研究缺失与单包未取得分别处理。

接口诊断发现：B64的64个给定请求均为通用purpose，无required_points；
新自主首8族实际发出12个工具请求，其中9个带read_goal及共21个required_points，3个省略read_goal。
这是未配对的输入分布差异，不能解释同协议旧32族的B回归，也不证明因果。
若后续机制修复有依据，应在合法TRAIN来源取得实际Host请求及合法已知证据，而不是把新DEV状态用于拟合。
已有按请求选材规则和同before执行器继续复用。详见`request-interface-diagnosis.json`。

## 失败与改进

profile 准备首次引用不存在的 JSONL 写入函数，在模型调用前退出；
改用项目已有的逐行 JSON 写法，保留失败计时。
8 状态准备首次继承 initial1/post1 配额，实际选入16状态，触发精确状态核对失败；
确认 `--include` 是提名而非过滤后，使用既有 initial0/post1 配额，另建 v2，实际准确选入8状态。
保留失败目录和反思记录，没有修改捕获、放松核对或重试模型首结果。

8状态绑定最初误要求每次READ后都有下一次观察；实际step7只有一个控制槽，执行器正确地直接
返回budget_exhausted。修正分析器，核对真实opened结果、最后槽位与实际返回范围，不虚构下一观察。
C准备发现既有F1入口漏传`exclude_given_requests`，真实checkpoint配置核对因此失败。
配置保持严格相等，补齐原参数；新增SQLite回归修复前失败，修复后27项相关检查通过，
实际8个状态重新准备成功且原菜单不变。失败目录、计时和反思均保留，没有模型重试。

B64首次启动的fixture仍是自主请求格式，给定请求入口缺少`retrieval_request`，在任何模型/HTTP调用前退出。
协调器还因系统Python3.10不能导入StrEnum而未写完状态/成本；实际进程退出及零调用已另行核对，
已测wrapper CPU列pending，丢失的整进程/启动CPU为unknown不填0。
修正为既有native-question适配器、独立given-v2数据与输出，协调器使用项目Python3.11并在计量前
先保存实际终态；没有重试已执行任务。此次也说明“配置prepare通过”不能代替请求fixture入口兼容性验证。

B64面板编译首次直接使用CUDA Python，漏用原依赖/attention wrapper，因缺少langchain_core在
导入阶段退出，尚未创建输出或调用模型。修正为现有`train_with_declared_attention.py`后编译成功，
未升级环境或更换backend；失败日志、计时和`b64-preparation-import-reflection.json`保持。

本轮复用索引遗漏E3的22个已完成绑定，导致一次不必要的A重复，已按更早首结果修正统计；
这也验证相同材料的单次生成变化能使完整成功计数上浮，不能选择较好后答。
新自主输入分析最初混用了条件读出字段、成功结果receipt字段和“完成final输入”定义；
按已存在的自主格式及E4失败输入补充协议修正，保留三份失败日志/计时，未重跑任何模型。

SDK审计首次把结果导出的`sources`当成原始Store行直接比较，发现实际`sources()`会按语义历史
派生`formation_status`。改为按原生投影核对，同时继续逐值检查原始Source未变；失败计时保留。
安装的serializer构造参数与导入警告所提参数不一致，按实际签名使用原有默认构造，未升级依赖。
B64事后join首次误把两段的局部record_index当全局下标，改用384个唯一完整readout路径及来源匹配。
进度写入器首次读到自己尚未闭合的GNU计时文件；改为在该计时结束后写入摘要，保留失败成本，
没有将缺失用量补0。以上均为离线分析失败，没有模型重试或原结果替换。
另一次B0状态审计被提前并行发出，所依赖的绑定结果清单尚未写出，因此缺文件退出。
改为等待绑定正常完成后串行审计，所有64个状态核对通过；失败计时保留，未增加模型调用。

## D：先核对来源资格

旧E5继续保留8个已曝光开发族、两流程各5请求的来源与首次结果。现已按原有两份背景划分，
预留32个本次D实验尚未使用的TRAIN背景：14个Update、18个TrajectoryOps，与旧8族不重合。
选择只使用既有operation_type与背景身份，没有因答案或方法表现筛选；新选正文尚未投影，方法和请求时序未冻结。
这些背景已有TRAIN及来源审查/训练曝光，MemOps本身为生成的基准对话，不能称为全新、自然采集或独立确认数据。
没有重分配calibration/test，也没有为凑数量打开预留确认内容。下一步先检查旧8族真实合法菜单与
View后继续READ的功能切片，再固定三方法、2048预算与同一来源到达/请求时序，复用已有来源切点并逐项核对自然更新。
来源身份及曝光边界见`d-update32/source-reservation.json`；当前没有D新模型执行。

已在旧generated-2048实际捕获中找到9个成功REFRESH_VIEW后的状态，分属5个旧背景。
原CacheMemoryPolicy源码与旧运行时逐字相同，9次均选择HANDOFF，但现有菜单仍允许READ。
按已有`source_relevance`对控制器实际已见内容提名，每状态仅选一个现有READ绑定，
在原冻结运行时的真实before副本中执行READ，再按既有首动作干预终止为HANDOFF；没有新建View、
重跑前缀或生成Host回答。9个首packet均为View＋原文，材料拒绝0，新增HTTP/本地模型调用0。
9段原文均逐字绑定到未改变的Source，原View解释文本不变；定位别名和共享capture metadata按
原生`project_packs`投影核对，没有将导航位置当作已打开的原文。

这些READ中3段是user、6段是assistant，角色保持原状；词汇相关不等于用户原话或已证实事实。
这个功能切片没有证明View事实正确、Host任务收益或旧View的USE_VIEW复用；仍需实现可选增量策略，
核对实际已知证据与clean/pending旧View，再固定三方法共同builder、2048预算和请求时序。
旧8完整流程与32个新增TRAIN背景的正式执行、来源审查及同信息对照均未由此完成。
实际packet与边界记录见`d-update32/old8-native-read-probe-closeout.json`。

初次把原始缓存的绑定/metadata直接与packet比较时得到不同；补核原生投影后确认其会精简引用别名、
改为当前原文短标签或`support_not_opened`，并拆分共享metadata。现已分别验证解释文本不变和
定位/角色/时钟投影一致，旧比较报告保留，没有重跑读取或模型。

## 全范围剩余要求（按v49证据更新）

| 里程碑 | 当前证据 | 仍需执行 |
| --- | --- | --- |
| M0 | 双独立单卡/P0精度、统一FP32与落盘复验闭合 | 后续实际新风险再定向验证 |
| M1 | 原生负例覆盖、旧57状态、8功能及52新READ全审闭合，执行覆盖57/57 | 保留所有tie/loss/unknown；不追加B192或拟合 |
| M2 | A/B主拟合、B64 384结果、C8/新7池14格、DEV64五方法与来源/输入审阅闭合 | 不扩菜单或拟合；将完整负结果纳入最终结论 |
| M3 | E3固定初始化下三训练RNG种子u32/DEV64与家族统计闭合 | 不选最好seed、不自动扩A20k/B192/额外种子；最终采用依完整开发与确认结果 |
| M4 | 旧8/新32三方法全部正式流程、K9及旧输出42控制/审阅/完整输入/成本闭合 | 保持因子解释边界；与B/C诊断合并开发结论，不把最终更新失败归为单一原因 |
| M5 | 四方法全256机械/NN输入/原生全文F1及家族配对统计闭合；基线语义256/primary96；idle25闭合；LME完整输入/预算/代码/串行流程冻结，owner及只读审计入口实现 | 672条余下整答/四方法主C与压力配对；执行LME451及Mem2Act400并全审计；旧64资格、全成本/图表/论文/完整审计 |

所有规模和 seed 扩展遵循原计划的信号条件，不把多问题、状态、重复或 seed 当作新来源。
最终允许简单方法获胜；局部 loss、动作准确率和材料覆盖不能代替来源族宏平均 Host 完整成功。
主比较报告 gains/losses、家族 bootstrap 区间及全部失败，不能从旧32族或这个8状态功能切片宣称独立泛化。

所有工作沿原连续账本
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`。
两训练进程退出且无模型HTTP活动后，原v79的75项45.39CPU及本轮38项残余458.5458CPU已各结算一次；
C已计native380.6442CPU先行扣除，P0及A拟合/重载模型成本没有重复计账。
2026-11-05在实际模型空闲后，新增13条离线计时共159.4CPU秒另行结算一次，见
`idle-cost-settlement-v2.json`；此前计时和模型/客户端成本未重复收取。
后续实际空闲边界v3/v4/v5又分别仅结算新增5.63/14.99/5.10 CPU秒；
原生拟合、落盘评测及Host客户端费用由各自owner记录并扣除已计native部分，没有重复收取。
此后新增离线计时仍pending，活动模型期间不结算。B64客户端按动态模型load/predict两个phase
扣除已计部分后记录残余，避免另一卡评测phase污染归属；未测作者工作记unknown，远端硬件/货币成本未测。
GPU单元测试未单独测量GPU-hours，不能计为0。P0拟合/重载及C的native CPU已经记录，
后续idle结算须从整客户端成本中扣除这些已计部分；不得重复计账。
P0/A训练器进程内时钟之外的解释器/依赖导入及CUDA admission未单独计量，不填0。
新B拟合owner测量整子进程CPU，并在终态扣除其本臂已计native CPU后仅记录客户端残余。
E1新DEV64整子进程CPU587.1393秒，含已计本地预测405.1912及加载8.6032秒；
客户端残余173.3448秒另计一次。GPU作业占用区间0.731988小时，包含等待Host的时间；
它与HTTP已知tokens分别报告，不等于纯GPU计算时间。新增审查/SDK审计计时仍pending，
活动模型期间不离线结算；作者阅读与未测命令CPU保持unknown非0。
B0整子进程CPU697.7689秒，已计预测512.1397及加载8.2139秒，客户端残余177.4153秒各计一次；
GPU作业占用区间0.564241小时。实际E1/B0均退出后、B1启动前，将新增27条闭合离线计时共15.05CPU秒
结算至原账本一次，见`idle-cost-settlement-v6.json`；失败分析计时包括在内，模型/客户端费用未重复收取。
B1整子进程CPU651.0116秒，含已计预测446.1397和加载8.7188秒，客户端残余196.1530秒另计一次；
GPU作业占用区间0.786338小时。B1及D的9个无生成读取全部退出后、E3启动前，新增14条闭合计时
共59.9CPU秒已在`idle-cost-settlement-v7.json`结算一次。D重放保留旧前缀的逻辑调用/trace，
新增用量由原账本差值确认为0，不能把拷贝的旧vllm响应再次计费。后续计时在E3活动期间保持pending。
实际SDK路径、安装版本和已核对的forward/导出实现另存 `runtime-environment.json`。
本轮没有改变 Product 的公开 Schema/API、权限或 Canonical 行为；没有推送或合并。

开发诊断的独立PNG/SVG/PDF及范围说明位于 `development-figures/`，已完成图面检查；
它们不代表最终论文/确认结果已经完成。
