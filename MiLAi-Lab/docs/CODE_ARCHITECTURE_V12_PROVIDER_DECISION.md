# v12 Provider 注入与构造兼容边界

状态：S5 实施前设计决定，尚不是效果或等价验收结果。
依据：计划第8、15、16、39节；旧 `providers/langmem_chat.py`、Agent 组装与 M1/ODR/C 调用者。
Root 采用 Astra 对这一具体跨层冲突的只读建议，最终实现由 Sol 负责。

## 冲突与选择

旧类同时承担通用传输和研究配方，直接接收 `m1`、`odr`、`projection`、`request_view`、
`memory_protocol` 等构造参数，且调用者在构造后修改部分字段。标量 `memory_protocol="C"`
必须由某处解释为研究策略；若旧 Provider 自动解释，就无法同时满足无方法知识的目标边界。

保留自动解释意味着在 Provider、旧 facade 或动态注册中隐藏方法逻辑；只删字段又会让
Pydantic 静默忽略参数。两者均不接受。

选定：通用 Provider 与方法拥有的显式构造适配器分离。当前内部 recipe 调用者更改构造入口，
旧 provider 路径只 re-export canonical 通用对象。通用类拒绝未知构造字段，不静默接受方法参数。
历史实验按原提交运行；当前兼容导入不承诺原方法参数的自动组装。

## 最小职责

- 通用 chat bridge：消息/工具转换、通用协议、容量、HTTP、usage、通用解码。
- 通用 request pipeline：RequestTransform、DeliveryObserver、ResponseHook 及最小请求/响应数据。
- method-owned recipe adapter：具体方法的 schema/prompt/投影/响应处理，以及可变方法状态。
- runner/Agent recipe：显式选择并注入所需适配器。

方法构造适配器可用一个明确命名的 subtype；仅负责构造、属性/设置器和 hooks 组装。
不得覆盖 `_generate`、HTTP、容量或计账。hooks 必须读取实时 recipe state，不能捕获构造时
的 `memory_protocol`/`memory_turn`，否则稍后的 Agent 赋值会失效。

Provider 不检查方法类、方法名称或 opaque attachment 内容。无需通用插件平台、全局注册表、
动态导入、持久状态层或 Reviewer。实际文件数服从职责，不能为目录图新建无用包装。

## 必须保持的时序

1. recipe/native 不兼容检查与原通用 native 检查次序。
2. 回执与工具过滤，boundary 投影，JSON 历史处理和当前请求材料，原 schema/prompt 扩展顺序。
3. 完成最终请求后才预占容量并进入 delivery scope；HTTP 和 usage 仍由原 client 唯一负责。
4. 成功 HTTP 后按原顺序记录 projection/request-view delivery；退出 scope 后发出方法 delivery 事件。
5. delivery 可能早于输出合法性验证；HTTP 失败不能伪造成功 delivery。
6. schema 失败的 M1/ODR 记录、C 已有 recognizable-final 特例、M1 commit→ODR accept 的次序。
7. 原异常传播/转换、C 回执验证、最终 projection output 记录以及容量拒绝行为。

这些时序由冻结的有序请求、HTTP 字节、事件、容量状态、回执和异常对照验证。
不能趁重构修正旧失败或删掉困难控制用例。

## 验证范围

覆盖普通 JSON/native、多个工具及续接、空/多记忆、两种材料位置、C 的有效/无效/修正/耗尽，
M1 delta 与失败，ODR/freshness 与拒绝，projection v21 空/实际材料，HTTP 与输出解码失败，
以及生成前容量拒绝。工具 ID、请求体、source snapshot、usage 与事件次序均保留。

另外验证旧 provider facade 与 canonical 通用对象相同，recipe 的可变属性转发有效，
Provider 无方法导入和方法专属分支，未知方法构造参数明确失败。
此文件是设计决定；最终证明仍须落在 S5 的实际 capture、测试和受影响 CI 上。
