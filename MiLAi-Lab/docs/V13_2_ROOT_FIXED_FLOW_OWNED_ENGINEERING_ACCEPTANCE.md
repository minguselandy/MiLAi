# v13.2 Root固定观察流入口：工程验收与后续实验边界

新入口 `tools/run_v13_2_fixed_flow_owned.py` 把原固定流的一次真实公开事件边界放入已接受的默认关闭共享HTTP owner中。外层owner覆盖SDK/SQLite关闭、最终原回执落盘和退出；实际Host/embedding使用同一entry_budget。实际当前user Source与配置hash绑定沿用D0合同，writer沿用已接受的公开类型/原反馈通信配置。原Root fixed_flow.py、R0–R7运行、默认配置与Source214代码保持，不重跑旧root。新文件是Root实验驱动，不改变Product Schema/API/权限/Canonical或公开Store。

最终入口15项离线检查通过：2形成×2交付×legacy/owned共8格、4种调用前拒绝、构造失败、实际transport.close失败、unknown writer。使用真实已安装SDK/SQLite、合成非零历史账本与MockTransport，socket禁止；0实际生成/embedding HTTP，不能算模型样本。首次12项通过保留先前版本；首次ruff12错误和mypy2个arg-type错误原件保存，最终ruff/mypy与package/tools边界通过，不用末次通过覆盖原失败。

关闭失败原件显示HTTPX CLOSED而真实transport抛错，登记及lease仍保留，竞争owner被拒绝。unknown writer的一次付费保守占用保留，formation为pending/effect unconfirmed；boundary completed仅表示入口结束，不表示形成成功。没有自动重试/退款或最终回答改写。SDK构造器在返回资源前抛错的内部资源仍不在可证明范围；本验收不是独立Judge或完整native SDK/四臂inclusive12/24验收。

Root另核对8条原命令、执行前后完整runtime/tests/configs/all-tools maps和原ledger hash、快照字节、11份最终控制原件与外层AST作用域。383个原件入索引、7条symlink记录元数据；index与后写seal另作hash anchors。有限证明与Source59控制分开，不能相加成模型质量分母。原48条要求保持4 PASSED_SCOPED/27 PARTIAL/1 NOT_PASSED/16 NOT_VERIFIED。

查阅的[官方RunnableConfig](https://reference.langchain.com/python/langchain-core/runnables/config/RunnableConfig)、[固定langchain-core1.6.5源码](https://github.com/langchain-ai/langchain/tree/c5ab14d42a3e22865c9def909de0b11d70b0bbf0/libs/core)及[固定CPython3.11.13 typing](https://github.com/python/cpython/tree/498b971ea3673012a1d4b21860b229d55fc6e575)已保存原文/URL/UTC/响应/hash/中文范围。三个LC文件与安装字节相同，typing与解释器字节相同；cast返回同一config，不验证运行时值或增加模型输入。官方rolling页与固定源码分别记录，未升级SDK。归档首GET200后progress路径拼接失败原件保留，恢复只复用已下载原字节，未重下/覆写。当前资料17论文/19项目参考组/807独立核验文件/159本地链接，0问题，第三方代码未执行。

下一实际E1必须新配置/观察流/root、冻结全部输入与已接受profiles、远端核对后由Root串行调用。固定流逐边界检查pending/中断/Source和保存真实性，随后才运行8条自由Host；两种固定交付均机械激活读取，不冒称自由Host选择。原形成提示/合同差异逐项披露，不把所有共同改进与R0差别解释为单因素。E2/E0、四臂和独立泛化门槛继续按完整原计划推进。

[机器验收记录](../data/manifests/v13-2-root-fixed-flow-owned-engineering-acceptance.json)；本地原件 `artifacts/v13-2-root-fixed-flow-ownership-engineering/final-byte-review-first/`；[资料索引与反思](V13_2_DESIGN_LITERATURE.md)。回滚main95bf708bfd8aac9f7855485166e3bf739928b949。完整计划ACTIVE，E0 NOT_PASSED、D4 NOT_ADMITTED、Product NO_GO，本阶段没有新实际cohort。
