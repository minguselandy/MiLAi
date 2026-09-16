# MILA-V02-05：减少实验范围检查的重复扫描

2026-09-07（Asia/Shanghai）执行，沿用20260906标识。Product pin保持
`10f713352d53d245fa3ad27e6a283b3a09410031fe7149c7e2ee18ed8afbbe86`。
只修改Lab检查器；没有Product源码、API、schema、权限、Canonical或migration变更。

## 已定位的观测开销

公开运行i的返回后检查约36ms。检查器对结构化响应的完整JSON逐一查找1000个禁止
标识（500个Evidence ID及500个source marker），重复扫描同一字符串。当前实际响应
约55KB，既有Runtime JSON序列化观察不足1ms，未据此更换序列化实现或减少响应字段。

Lab现在在全部来源回执齐备后，将所有禁止标识通过`re.escape`编译为一次字面量匹配，
每次调用仍序列化结构化响应的所有字段并检查是否包含任何禁止子串。没有增加词边界、
限制字段、截断正文或只查选中Evidence。空集合永不匹配；包含空串的集合仍判定泄漏。
原set扫描路径保留，用于直接对照。来源集合在本次固定批次内不变，编译不跨批次缓存。

实际调用仍执行完整响应model_dump、范围检查、状态检查和响应摘要。原`elapsed_ms`
及300ms停止门槛保持；一次编译发生在客户端调用前，成本单列为离线CPU观察，未声称
其在线成本为零。不能将检查器效率改进当作Product算法或服务性能改进。

## 等价与组件成本

离线证据：`artifacts/v02-e2e-generality/p1-disclosure-scan-offline-20260906a/`。
使用原i保存的98个完整结构化响应，两种实现的返回Evidence集合与判定相同。33个
负控在新增嵌套诊断值或键中插入禁止标识，均由原实现与新实现拒绝；负控不发送服务。
9个新增单元控制覆盖空集合/空串、重叠、正则元字符、Unicode/转义、键/嵌套值，
及1000标识集合中的首中尾位置；被比较的仍是原JSON编码后的字面量子串语义。

affinity0/1下交替10轮同一响应完整范围检查CPU中位：35.836→6.059ms；一次编译
24.955ms。包含JSON序列化，不包含网络、Runtime或协议反序列化；不作为SLO。

## 相同Product的公开复测j

配置`configs/v02-scoped-recall-disclosure-scan.json`，原始证据
`artifacts/v02-e2e-generality/p1-scoped-recall-20260906j/`。
相对i只修改实验标识、前序记录、改动说明和上述Lab检查器。Product pin、1000条来源
capture body摘要、工具目录、2CPU/1GiB、同核SMT 0/1、池8、最大并发8、24请求/轮、
重试0、源文512/2048/8192及首尾、完整判据、整体300ms停止规则均保持。

| 轮次 | 整体P95 ms | 收到响应P95 ms | 返回后检查P95 ms |
| --- | ---: | ---: | ---: |
| c1-r0 | 136.091 | 129.726 | 7.976 |
| c1-r1 | 137.862 | 131.518 | 6.587 |
| c1-r2 | 119.703 | 113.317 | 8.422 |
| c8-r0 | 662.906 | 655.972 | 13.656 |

c8首轮仍超300ms，后两轮未执行。分位数不能相加或相减。i与j即使Product相同，也
是不同时间的新实例运行；实验检查同步占用事件循环及CPU，能够影响其他在途调用。
本次结果不能量化单独Runtime收益，不能把i的815.119→j的662.906ms写成Product加速。

20批readiness及3个项目范围控制通过。MCP99（97个明确预算受限DEGRADED、1个MISS、
1个预期拒绝），SDK1021，Runtime1125（1000×201、125×200，其中resolve98）。不同层级
计数不相加，DEGRADED不记成HIT。结束后将j的98个完整结构化响应再次用原扫描和新
匹配器对照，判定一致；99个事件分段耗时之和与原整体耗时相等。

## 验证、清理与剩余工作

- `uv run milai-lab-check-boundary`：通过。
- `uv run pytest -q`：337通过，2.78s。
- `uv run ruff check src tests tools`、`uv run mypy src/milai_lab`：通过（30源码文件）。
- `uv build`：sdist/wheel成功；Product pin再次核对通过。

无Product代码变化，未重复上一轮最终pin的真实PG1104测试；该历史证据不升级为本轮
新测试。独占API227349、worker227350、MCP227473已不存在，PG确认停止，数据保留；
共享服务未改。模型生成与Provider tokenize均0。

后续回到当前Product完整请求的剩余CPU及等待成本，不重复计算已经省去的Context、
raw语义或实验检查工作；继续保持资源和300ms边界。完整P1/P2/P4、正式D4/D5、模型
效果及通用性仍未通过，Schema仍为`NO-GO FOR SCHEMA FREEZE`。
