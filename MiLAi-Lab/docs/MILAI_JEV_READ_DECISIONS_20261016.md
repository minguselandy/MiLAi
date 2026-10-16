# 有界读端决策：数据、零样本与训练执行

完整执行目标仍为 ACTIVE／未完成。本轮继续原瓶颈评审的读端优先路线；下列前缀诊断不替代 Reader 问答、正常 Host 或整个质量—成本闭环。

## 已完成的实际工作

独立工作树 `jev-read-decisions-20261016` 从 `20bc06d6` 建立。本轮代码冻结 `ff38d22b`；同名瓶颈工作树存在其他会话改动，原件保留，没有整体合并或覆盖。Product、公开 Schema/API、权限和 Canonical 未变。

MuSiQue-Full train 镜像已完整下载并解析：476,696,984 bytes、39,876 行。官方下载入口曾返回 quota exceeded；因此保留镜像来源，不声称已核实与官方归档全文等价。没有执行 SHA 校验。来源：[作者仓库](https://github.com/stonybrooknlp/musique)、[下载镜像](https://huggingface.co/datasets/bdsaglam/musique)。不混入官方 dev/test 或其单跳种子训练库。

问题变体、共享单跳 ID 和相同支持段落合并为 896 个连通家族；排除跨划分目标证据暴露后，train/dev/calibration/test 分别保留 25,269／1,149／1,221／1,763 行。共同非目标背景另记，不能称百科背景完全独立。该家族生成器当时是 sibling 工作树的未提交工具；冻结产物及参数已保存，本分支不伪称其来源为后续代码提交。

第一轮按家族抽取一组可回答／不可回答变体，然后展开 BM25 实际前缀和离线支持前缀。不会因长家族含有更多变体而采样更多事件。

| 划分 | 家族 | 原始行 | 读取状态 | 可监督 | 遮罩 |
|---|---:|---:|---:|---:|---:|
| train | 64 | 124 | 556 | 467 | 89 |
| dev | 24 | 46 | 203 | 164 | 39 |
| calibration | 24 | 42 | 186 | 145 | 41 |
| test | 24 | 44 | 195 | 153 | 42 |

监督允许多个缺失互补项及字面等价支持。证据已足够与当前池无有用补充是两个不同 STOP；原始全文可回答但检索缺证据、无法排除其他证明的状态遮罩，不伪造“证据不存在”。标签是已标注证明的监督，仍不代表枚举了全部语义等价支持。

运行投影仅含问题、已打开材料和候选的本地别名／标题／正文；答案、answerable、支持标记、分解问题、家族 ID 留在离线 metadata。最多 8 个候选、4 次决策，无重叠子集穷举。预算用尽、候选读完均不等于证据充分。候选正文确实由控制器处理，这部分成本必须计入。

全部 1,140 个完整状态经过原生 tokenizer 和目标格式审计；max_len=4096、head_max_len=384，最长 2,137 tokens，输入或选项截断为零，非法目标为零。calibration/test 仅做格式、长度检查，没有模型推理。

此前下载的 50 行预览保守视为作者暴露，涉及 35 个家族。首批采样的 train/dev/calibration/test 分别与其中 0／2／0／1 个家族重叠。当前 dev 明确作为开发诊断；未来盲测必须排除那一个 test 家族，不重新宣称其未见，也不靠重新洗牌消除既有暴露。

## 原始 Laya 的首次真实诊断

原始 multilingual checkpoint 在 CPU 完成 dev 的 203 次前缀推理，首次输出全部保存。164 项有监督状态中接受 15 项，家族平均接受率 0.068；39 项遮罩仍保留，不计成成功。缺失互补为 13/78，池内不足 STOP 为 1/73，充分 STOP 为 1/13。按标注证明，有 18 次无依据充分停止、6 次无依据耗尽停止、73 次不必要继续。

选择首个剩余 BM25 候选的简单前缀参照为 34/164；这不是最终 QA 准确率，也不是完整 reranker 基线。当前结果不支持原模型开箱即用，更不支持用置信度跳过读取。

真实消耗为 203 个 forward、203 条编码序列、262,964 输入 token、390.71 秒墙钟、1,436.09 秒进程 CPU，峰值 RSS 约 2.25 GiB。状态 tokenize 203 次；原生选项头内部 tokenize/cache 次数尚未完整计数。CPU 消耗已写入原连续账本 `compute.laya_reader_prefix`，无新增 HTTP 或生成 token 记账。

## 资源位置与用户 GPU 授权

模型、数据、Python、环境和缓存都位于 `/cra/memory/mx_memory` 下。旧训练环境的解释器曾链接到 `/root/.local/share/uv`；本轮已复制解释器到当前目录并建立新的环境，旧环境保留。

- 数据及固定派生文件：sibling `jev-read-bottleneck-20261016/MiLAi-Lab/artifacts/jev-bottleneck/data/musique/`。
- 基础权重：`jev-training-20261016/MiLAi-Lab/artifacts/jev-training/models/laya-multilingual-base/`。
- 本轮运行和 CUDA 环境：当前 Lab 的 `artifacts/jev-reader/`。
- CPython：`/cra/memory/mx_memory/.local/share/uv/python/`；HF/Torch/pip 缓存：`/cra/memory/mx_memory/.cache/`；uv 缓存：`/cra/memory/mx_memory/.uv-cache/`。
- 后续命令先载入 `artifacts/jev-reader/runtime/env.sh`，显式设置缓存与临时目录。

用户明确允许释放且只允许操作 `milai-unified-v8-v9-native-host-r2`（7862，GPU 2、3）。已确认请求为零后正常停止原容器；两卡各剩 3,513 MiB 占用。bge-m3（7861）和 bge-reranker（7961）的容器、PID 与分配保持不变，其他模型未动。恢复命令是 `docker start milai-unified-v8-v9-native-host-r2`，必须先检查训练是否仍占卡。

CUDA 训练脚本限定 `CUDA_VISIBLE_DEVICES=2,3`，使用原生完整 encoder+head、普通 soft-CE、按事件再按家族归一化，保留原始及每轮同输入 dev 结果，不读取 calibration/test。CUDA 环境安装及训练当前状态以实际进程和 run.json 为准，不把准备完成写成训练完成。

## 首次双卡失败与直接修复

`ce-gpu-v1`（`b57c29ef`）已终止／FAILED：GPU 零样本仍为 15/164，随后完成 29 次优化器更新、464 条成功训练序列；最后三条不足批次触发 ModernBERT 默认编译与 DataParallel 的 FX/Dynamo 冲突。132.18 秒墙钟及失败开销已入原账本。失败批次另外提供 3 条／3,501 tokens，不能把它们算成成功编码；原始异常、首次输出与成本保留，未生成完成 checkpoint。

修复使用 ModernBERT 原有 `reference_compile=False` 普通 MLP 路径，并新增尝试／成功计数区分。修复已通过真实双卡 batch=4 后 batch=3 的前向／反向检查，两部分梯度均非零。新运行 `ce-gpu-v2` 从 `8c6cb000` 启动，PID 4093998／exec 37838；本检查点仍在运行，计划四轮，原始 GPU dev 为 15/164。新输出另用目录，不覆盖首失败。该修复不增加模型、标签或回退决策。首轮产生的 348 KiB Triton 默认缓存已在进程终止后迁入 `/cra/memory/mx_memory/.cache/triton-first-gpu-run/`；后续 Triton、Inductor 和 CUDA 缓存也已显式指定当前目录。

## 尚需完成

同输入 GPU 零样本／普通 CE 曲线及保存权重；普通监督小 reranker 和 logits 简单基线；固定 k 与自适应 STOP 分开比较；互补后果目标、独立校准与完整处理计量；未暴露 LongMemEval 的正常 Reader 质量—成本闭环；MemOps/MEME 写端与 W/B 必要边界、独立连续轨迹。原有 D0—D4 失败和简单控制优势继续保留，不用本轮准备工作抵扣这些要求。

本轮 11 项直接检查、Ruff、运行模块 strict mypy、包和工具依赖边界通过；全仓测试与远端 CI 未运行，未发布或合并。相关数据、长度和首次输出汇总见 [机器清单](../data/manifests/jev-bounded-reader-preparation-v1.json)。回退源码可用本轮之前的 `20bc06d6`；运行产物原样保留。Product 仍 NO_GO。
