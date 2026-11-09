# 已关闭D捕获的无损存储与原路径恢复

磁盘普通可用空间实测为0，含root预留区约35GB。当前目标新增的五个D原生作业都已退出，
含旧baseline80复用的全部1200首轮及Source/输入/操作/质量审计已关闭；其中新增五作业的10个
frozen-retrieval-calls/frozen-host-messages目录共26,643,763,892原始文件字节
（24.814GiB），现按原生固定偏移块格式保存为
637,562,898归档字节（608.027MiB）。
没有丢弃Source正文、状态、角色、时钟、原Host消息或NN输入。

原生archive_case在移除每个raw目录前，重建并逐字节比较全部文件；5个原driver保留原路径，
整文件字节未变。另实际恢复一个完整捕获树，逐511,095,747字节、
4462个文件核对payload/去重引用、文件mode和mtime_ns后才清理该临时副本。
全部永久归档、每目录回执与immutable-empty-base保持。没有SHA或内容指纹门禁。

[机器凭据](../data/manifests/a100-closed-D-capture-storage-20261109-v1.json) ·
[执行入口](../tools/archive_a100_closed_D_captures.py) ·
[D原审计](MILAI_A100_PLAN_D_AUDIT_20261109.md)

这里只改已关闭产物的物理存储；D原标签、数值、首结果、权重和冻结科学协议均不变。
Mem2Act的fixed runtime/首次Host快照/common bank、原进程和LME数据都未触碰，
primary仍必须沿原400实际快照重放。现有工具的原路径在归档后暂不存在，不能据此重新采集。
可选D复查或最后全计划原生复验前，先通过原生restore_case恢复对应目录，再执行原审计。

归档器是普通CPU命令，与原Mem2Act固定worker并行，无模型/HTTP/业务或账本调用；
归档/验证及本轮其他普通/失败GNU计时待实际idle138付一次，不另加native/whole存储phase。
操作前后的实际磁盘余量另存于机器凭据；同时Mem2Act仍有真实写盘，因此不把两次余量差
当作受控压缩性能或因果延迟比较。未测编排/启动/清理CPU保留unknown_not_zero。

每个归档都必须连同empty base保留，并按记录恢复原路径，示例只恢复第一棵树：

```python
import json, sys
from pathlib import Path
root = Path("artifacts/a100-development-20261104").resolve()
sys.path.insert(0, str(root / "external-own-policy-v1/frozen-mem2act-v1/runtime/src"))
from milai_lab.harness.case_archive import restore_case
closed = json.loads((root / "closed-D-capture-storage-v1/closeout.json").read_text())
row = closed["records"][0]
assert not Path(row["original"]).exists()
restore_case(Path(row["archive"]), Path(row["base"]), Path(row["original"]))
```

恢复仅重建字节，不重跑Host、前缀或模型。保存归档可再次重建；恢复所需空间要在实际执行前
核对。Mem2Act全800、两方法Source/评分/归档、最终成本/论文图表及全763行完成审计仍待闭合。
