# v12 S5：通用模型适配与方法组装

状态：本地工程验证完成，远端 CI 与发布待完成。源码基线为
`2bc50583d02b86dd70ceb25f42eed43b9082f413`。实验仍暂停。

## 实际断点与选择

原 `providers/langmem_chat.py` 直接解释 C、M1、ODR、边界呈现与 freshness projection，
并导入这些方法。竞争解释是这些分支属于不可分离的模型协议，或它们是插入协议流程的
研究策略。实际分支使用方法状态与控制器，并按配方启用，支持后者。

结构修复保留通用消息转换、工具协议、容量、HTTP、usage 和解码，把具体策略放入显式方法组装。
接口设计与时序见[Provider 决定](CODE_ARCHITECTURE_V12_PROVIDER_DECISION.md)。
不能用通用名称的包装器、动态导入或全局注册隐藏反向依赖。

兼容范围明确：旧 Provider 模块继续导出 canonical 通用类的同一对象；当前使用方法参数的
调用者迁移到方法拥有的构造入口。通用类不能静默接受不再生效的旧方法参数。
历史构造调用按原提交复现；本阶段应证明当前显式组装后仍保持原请求与结果合同。

## 待核实证据

在受影响实现修改前冻结旧源码和合成输入，使用 MockHTTP 比较 ordered request、原始 HTTP
字节、工具目录与调用 ID、容量/usage、delivery 顺序、错误和副作用。覆盖 JSON/native、
工具续接、空/多个记忆、system/current_request、实际回执和现有 C/M1/ODR/projection 配方。
迁移前捕获和三组完整迁移后字节对照已完成；本阶段独立完成了下述工程检查与安装验证。

| 冻结输入 | 覆盖 | bytes / SHA256 |
|---|---|---|
| [协议/时序](../data/diagnostics/code-architecture-v12/provider-manual-golden.json) | 27 个用例；实际 VLLMClient 与 MockHTTP，方法替身用于明确控制时序/错误 | 535,791 / `1cced3e58619b1286af8072de7a39767dc4b2d24014a91767cc1451dba6f0950` |
| [真实方法](../data/diagnostics/code-architecture-v12/provider-real-golden.json) | 44 个已有参数化测试通过，保留真实 C/M1/ODR/projection/boundary 控制器与原断言 | 15,454,160 / `f942ce5f82911693ecc31eb2aed4a565add5ea9520934eaa01a27f06001e69ac` |
| [错误与边界](../data/diagnostics/code-architecture-v12/provider-edges-golden.json) | 23 个 Provider、8 个数学函数、4 个 embedding 用例 | 255,207 / `7f37646a2ea815d6d71d9820e77e304b758e032537537cfc6ef977e6369baf1e` |

Root 分别核对了 39/78/46 个实际加载模块，均来自冻结副本，哈希与迁移前清单一致。
三份公开文件与捕获文件全字节相同。原始 HTTP 字节、错误、usage/capacity、持久化和真实回执
属于对照内容；不能用“进程退出正常”代替比较。

首批 27 个手工协议/时序用例已在冻结旧源码上捕获；具体方法由测试替身控制，真实控制器另行验证。
其中 `json_zero_tools` 保留旧实现实际发生的 HTTP 后空 `oneOf` SchemaError；不将其解释为
任务成功，也不在结构迁移中修复。native 不支持组合则保留 HTTP 前拒绝。

真实方法首次捕获为 37 通过、7 失败；记录器使用 `dataclasses.asdict` 深拷贝运行时对象，
触及不可复制的线程锁。第二次缩小 journal wrapper 的字段后为 39 通过、5 失败，同类错误仍存在于
其它记录入口。两次失败 JSON 和日志保留；它们不是通过的 golden，也不是原方法的语义失败。
第三次仅在记录器中提取真实 journal thread ID、记录执行器是否存在，避免复制执行器；
从同一冻结旧源码捕获的 44 个原测试全部通过，形成上表真实方法 golden。
旧实现没有为适应记录器而修改。

迁移后的首次对照发现一次机械替换误伤：调用被错误命名为 `m1_recipe_action_schema` /
`odr_recipe_action_schema`，导致 NameError，真实方法检查为 38 通过、6 失败。
修复只恢复两个真实函数名，未改变协议或测试期望。初次 after 文件与日志保留。

修复后，手工对照第二次 after、真实方法第二次 after 与边界首轮 after 均与各自冻结 before
及上表公开 golden 全字节一致；真实方法的 44 个原断言再次全部通过。
Root 独立核对了三组完整文件。通用 `RequestTransform.project`、交付观察和响应 hooks
的检查结果见下节；S7 全局边界与远端 CI 仍待完成。

本次审阅的 14 份已修改既有 unit 测试，移除 import 节点后的完整 AST 与 S4 提交相同；
当前变化只迁移构造/辅助函数入口，没有删除原断言或改写预期来取得通过。

## 工程验收

canonical 实现分别为 `providers/chat_bridge.py`、`providers/request_pipeline.py`、
`methods/langmem_recipe.py` 和 `memory/embeddings.py`。配方只拥有方法状态和 hook 组装，
继承通用生成、容量、绑定及 HTTP 流程。新构造拒绝方法参数与 live fields 均有独立检查。
通用 `_action_schema/_action_prompt` 不再接收 C 的 `memory_result` 参数，当前 C 调用者
显式使用方法拥有的 helper；相关 schema/prompt 字节已纳入原 golden 比较。

- 受影响 Foundation 检查 307 项通过；2 项既有 local-artifact 用例按原归属排除，没有新增 skip。
- 受影响 Mem0 配方 1 项通过；最后三处 canonical 导入收敛后的 identity/facade 检查 22 项通过。
- Core 37、Foundation discovery 154、Foundation explicit 67 个文件 strict mypy 通过；
  新 canonical 4 个文件和最后 3 个导入调整也有定向 strict 检查。这些覆盖有交集，不相加为唯一文件数。
- 最终 Ruff、两项 boundary、verification matrix 通过。Root 扫描全部 9 个 Provider 模块，
  未发现具体方法、runner、baseline、benchmark 或 scorer 的静态导入。
- 34 个既有模块递归去除 import 后的执行 AST 相同；归一化函数原 AST 相同。
- 最终 18 个改动 runtime 模块在工作树、sdist 和 wheel 中逐字节一致。全套公开 fixture 与
  helper 进入 sdist；新无依赖安装的 Core 检查和借用已有依赖的 Foundation `-I` 检查通过。
  安装环境回放手工 27 例及边界 35 例，所有加载的 Lab 模块来自新安装目录。
  真实方法 44 例在源码环境通过，不冒称安装环境再次运行了全部真实 graph。

最终 sdist SHA256：`149642290f11f37bdd3a71e22fe692bab1ef7e76cdb48240ab2549dc7f8d169b`。
最终 wheel SHA256：`20ea607109d6152b53ddbe03ad2ab2c94c1a51115465031bd804b5be72fa3b22`。
初次包与最后三处导入调整前的检查证据均保留，没有为发布重复运行未受影响的 307 项检查。

首次失败、修复及精确源码身份见[工程证据](../data/diagnostics/code-architecture-v12/s5-engineering-evidence.json)。
S6、S7 与最终发布仍未完成；本阶段不推导方法的语义收益。

本轮不修标签回流、额外动作或记忆适用性，不改提示、模型参数、工具权限或预算。
测试中的合成 usage 属于临时测试账本，不能混入连续真实实验成本。
