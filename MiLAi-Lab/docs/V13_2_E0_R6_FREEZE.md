# v13.2 R6 原24/48开发实验冻结

R6已完成新的输入/源码/环境/route/ledger冻结，状态FROZEN_READY，尚无质量结果。[runtime](../data/manifests/v13-2-e0-r6-runtime.json)、[事前设计](../data/manifests/v13-2-e0-r6-design.json)与[工程验收](../data/manifests/v13-2-direct-support-acceptance.json)分别记录准备、限定验收和实际执行身份。

实际入口为tools/run_v13_1_d0.py，Source33a72b3由Root2eeb7b74999bd7de5b513f66b9b498445648c727转入；211源码map8c466d3ca839ea0db5aaa722ae20ffa6c11460c8f1d5c068e53921b6cb6551ce。报告基线5b67f69。Source所有树HOLD，Root独占原连续账本，所有真实generation/embedding串行1；使用现有7860 Qwen3.6-35B-A3B-FP8和7861 bge-m3，无部署或升级。Python与十项包身份保持原R5冻结的3.11.13/既有SDK。

新空root为artifacts/v13-2-development-r6/E0-normal-r6。原fixture仍24轨迹/48公开消息，原rubric、Host/writer基础提示和业务工具合同保持；不新增benchmark/gold/holdout。新config只新增memory_support_contract=direct_support_v1并更新实验说明，显式event_bound_v1/read_handle_v1、compact_v1、bank_prefix。Host12/output4096/temp0、writer1/repair0、普通材料2048/max6保持；generation_admission_profile仍legacy，不声明四臂共同inclusive12已验收。

本轮是trigger/支持叶分离、实际读版整字段等值复用、按trigger抑制重复维护、同Source字面对象ID、完整可逆支持metadata与正文分配的联合改动。新增metadata可减少交付正文，完整history/Source不保证；没有纯压缩归因、语义蕴含verifier、问题类型分支、强制额外read或独立泛化结论。原R0–R5结果、失败和费用各自保持。

独立新wire审计器、解码器、SDK重开及后检脚本在运行前复制到offline-tool-freeze并记录hash。Root九项parent控制、13解码控制、11明确合成metadata控制与12原压力包校准限定通过，95原R5 Host wire全部原审计字段一致；这些均不是R6实际请求或模型质量证据。新profile的实际trigger/field map/完整版本/复用parent须对本轮实际只读SDK重开进一步核对。

只读GET/models两route200、无generation/embedding，连续账本保持26f46d5fe3aeeaf0e399587098311e6d15bfacf01a0f231aca759207e6b0398b。实际prepare回执1fbc1808f1adbbf7c2a850be4a2bcc164aea1f9cb3e4b1bce94804271e9d805c，前后211源码/388测试/315配置均相等，禁socket且0模型/embedding；input-freeze SHAf74b5dd8bf30fb4045c4df4140c5464c724f9f9c4cb729dd86c3324734891f40。

提交并核对远端freeze后，Root parent按首尝试串行24，普通失败仍保留完整分母，不重跑或择优拼接。任何实际gold/future/scorer泄漏、wrong-owner交付或假durable成功停止受影响运行。结束后按独立SDK→实际wire→原collector→完整原rubric顺序分别审计任务与完整支持来源，维护状态/错误/所有费用均保留。

论文和项目原件可经[资料库](V13_2_DESIGN_LITERATURE.md)查看，651文件/57本地链接的版本/hash与已有设计反思保持。D4共同reader/cache/形成/B6/HTTP闭包与D5独立验证仍未完成，Product NO_GO，原完整计划active。
