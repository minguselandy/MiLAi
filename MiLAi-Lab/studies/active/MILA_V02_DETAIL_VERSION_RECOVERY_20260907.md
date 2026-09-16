# MILA-V02-05：保留L2版本的公开保存与冷恢复

状态：`RETAINED_DETAIL_VERSION_ENGINEERING_VERIFIED / FORMAL_E2E_NOT_ENTERED`。
补充T11及D1/D3的具体缺口：使用普通版本文件与已有State引用，即可保留和发现旧L2，
并在独立冷进程中核验当前引用。没有新增历史版本数据库、公开工具、语义模块或模型调用。

## 已验证的五个冷进程

通过公开MCP保存两份完整合成来源及两个State版本，L2分别为`details-v1.md`和
`details-v2.md`。两个版本的来源独立，正文保留Unicode、CRLF、首尾及多页内容。
每个冷进程经公开GET核验实际State版本身份和完整payload，使用现有Host文件工具和
逐次来源资格检查；读取从`list_files`发现开始，按稳定hash分页直到EOF，逐字节比较完整正文。

| 场景 | 实际结果 |
|---|---|
| 新L2文件存在但State仍引用旧版 | 冷恢复仍为State V1；两份普通文件都可发现和完整读取 |
| 正式保存State V2，保留旧文件 | 恢复准确的V2身份；旧、新L2继续可发现及完整读取 |
| 当前L2路径被覆盖 | B装配报`DETAIL_VERSION_UNAVAILABLE`，正常冻结文件读取报`SOURCE_CHANGED`；旧版仍可读 |
| 当前L2文件缺失 | 装配报`DETAIL_OUTSIDE_SNAPSHOT`，文件工具明确不可用；不伪造当前版本，旧版仍可读 |
| 撤销旧版独立来源 | 旧L2从文件发现结果隐藏，直接读取被拒绝；新State及独立新L2、普通独立文件仍可用 |

正常B装配均无L2正文预载。故障注入后将文件恢复为原字节，最终所有工作区文件hash与
初始manifest相等。这里的“旧版可读”依靠显式保留的普通文件，不声称Product拥有历史
State GET或自动历史文件服务，也不保证未保留的版本可恢复。旧引用识别是机械判断，
没有评价Agent能否正确理解版本适用性。

## 实现、失败与清理

新增`tools/check_v02_detail_versions.py`，复用现有公开服务管理器、MCP observer、
State适配器和文件工具。Product源码及pin保持
`56a0dab6df6dedd4540d3cc5a59fc1f9013505275e91cb7050b3d8eb56482e0c`。
成功运行根：`artifacts/v02-e2e-generality/detail-versions-20260907b/`，含运行前源码摘要、
公开保存回执、五个冷进程结果、文件工具页及清理复核。当前源码摘要与运行前记录一致。

首次a运行使用了通用`product-pg`名称，复用了旧卷，生成凭据与旧数据库密码不符，
迁移连接失败；尚未导入来源或写State。旧同名容器被重建后停止，持久卷未删除。
这是实验设施命名错误，不是Product持久化失败或一次独占实例验收；保留a目录及失败记录。
修复使用运行专属compose名称，并在任何prepare/cleanup之前检查是否已有容器或卷。
两个单元负控分别证明占用时不启动、不停止既有服务，也不创建运行目录。

成功b的API、worker、6个临时MCP及5个冷客户端进程均已退出；PG停止、未OOM，数据保留。
共享vLLM和公开MCP未修改。PG 2CPU/1GiB、进程CPU0/1；本轮是正确性验证，不是服务压测。

显式脚本MCP调用14次：2次来源保存、两次State保存流程各3调用、5次冷GET、1次来源撤销。
来源metadata HTTP GET及初始化另有开销，未单独记录物理总数，不能把14写成全部服务请求。
模型及Provider tokenize均0；不将工程劳动或服务成本记为零。

## 交付检查与剩余范围

Lab `uv run pytest -q`：**359 passed，2.71s**；boundary、Ruff `src tests tools`、
mypy `src/milai_lab`（30源码文件）、build均通过。两个新增namespace测试单独2通过。
Product源码未改，不重复运行Runtime回归或借用历史测试数作为本次结果。

T11已取得“保留普通版本文件”映射下的直接证据；原生Host、未声明来源的自动识别、
Agent语义质量及完整服务隔离仍不由本轮证明。D4/D5未进入，新增模型额度仍0。
用户已接受当前约532.5ms；本轮没有继续300ms微优化。下一步保持真实闭环主线，
推进剩余隔离/故障与Host成本条件。Schema仍`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
