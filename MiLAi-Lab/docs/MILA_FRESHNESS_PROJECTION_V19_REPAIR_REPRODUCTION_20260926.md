# v19 修复复现入口

终态 `COMPLETE_WITH_FRESHNESS_LIMITATIONS`，详见[结果](MILA_FRESHNESS_PROJECTION_V19_REPAIR_RESULTS_20260926.md)。A1/A2/A3分别1/3、1/3、2/3；没有方法通过全部三例。发布不需重跑模型、测试或build。本页提供独立复现合同，不自动启动新一轮。

## 各阶段的冻结源码

| 阶段 | 源码位置 | lock/mapping |
| --- | --- | --- |
| A1原Notice | Git `d0367aab36c15b39bdd4e2c1fd7a92a542f66fcf` | 原v19 lock；mapping `1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa` |
| A2隔离 | Git `b753347c79edfbad06083a443b6de7f3d0fc8f1c` | lock SHA `398669b26e9bd26a9b909f9920ab5525972377602f46d21b9ab97b1311395c27`；mapping `03c8923a0069b53ca6fe516fd89b882a14e0aa20bce68aca6ddb824932304460` |
| A3精确刷新 | 本交付中与A3 lock匹配的源码 | lock SHA `5a6a514f8e6281dda30565378e0824314ba2db8e7ec27f0dc1845de87d56169b`；mapping `bfc5c27631a9c41625446bc6cc6617e7a30417b39e23229a2ec6e85fc4105555` |

A2/A3各59runtime文件和6个validation hash分别冻结。新A3源码不能冒用旧A2 lock；复现A2应使用其独立提交。A1也应使用修改前提交，不能将当前工具的兼容notice入口冒充本轮A1原始环境。A0只是原B1参考，没有本轮运行结果。

原LangMem commit、`uv.lock`、Postgres public Store、Host `Qwen3.6-35B-A3B-FP8`、embedding `bge-m3` 和tokenizer身份沿用。不要改vLLM parser、thinking、上下文、max_tokens或容器参数。`uv sync --frozen --group dev --group baseline-langmem` 是依赖安装合同；本次使用现有环境，发布未重新安装。

## A3配置与命令

从[配置模板](../configs/milai-freshness-projection-v19.json)建立ignored本地配置，填写原tokenizer路径及model/service identity，为trace、checkpoint、sidecar、容量记录、journal及连续budget设置独立路径。DSN只从 `MILAI_LANGMEM_POSTGRES_DSN` 环境变量读取。使用新的run ID与空namespace，不覆盖本轮目录；旧账本只能作为history引用，不能重置累计费用。

从MiLAi-Lab目录运行，替换 `<run>` 和 `<config>`。prepare是零模型验证，run是真实调用：

```bash
uv run --no-sync python tools/run_milai_freshness_projection.py schema \
  --arm a3_exact_refresh --fixture data/fixtures/milai_odr_v19_changed.json

uv run --no-sync python tools/run_milai_freshness_projection.py prepare \
  --config <config> --run <run> --arm a3_exact_refresh \
  --lock data/locks/milai-freshness-projection-v19-a3.lock.json \
  --fixture data/fixtures/milai_odr_v19_changed.json \
  --mechanism-freeze data/manifests/milai-odr-v19-changed-freeze.json \
  --output artifacts/<run>/prepared.json

uv run --no-sync python tools/run_milai_freshness_projection.py run \
  --config <config> --run <run> --arm a3_exact_refresh \
  --lock data/locks/milai-freshness-projection-v19-a3.lock.json \
  --fixture data/fixtures/milai_odr_v19_changed.json \
  --mechanism-freeze data/manifests/milai-odr-v19-changed-freeze.json \
  --prepared artifacts/<run>/prepared.json \
  --output artifacts/<run>/run --stage <run>
```

retained/irrelevant使用对应fixture/freeze和独立run。A2在其固定提交使用同样命令形式，arm换成 `a2_quarantine`、lock换成A2。A1使用原 `tools/run_milai_odr.py`、`--arm freshness_only --mode mechanism`，其余合同见[旧复现入口](MILA_ON_DEMAND_RECONSTRUCTION_V19_REPRODUCTION_20260926.md)。旧页F-only未运行状态属于旧v19，本次新结果由新manifest补充，不改写历史。

真实调用并发1，原fixture经public工具seed/update，runtime不读评分真值。核对初始X@1实际search和交付、更新后wire、批准后的业务调用、Host写入和搜索。retained不能仅凭8通过，irrelevant的精确Y读取必须列出。判定遵循[预先冻结协议](../data/manifests/freshness-v19-repair-evaluation-protocol.json)。

## 证据与检查

本机原始证据在ignored `artifacts/freshness-projection-v19-repair/`：九个 `{a1,a2,a3}-{changed,retained,irrelevant}-r1` 目录、budget及阶段快照、环境回执、prepare/run/analysis脚本和唯一build回执。Git未发布原始Provider正文、数据库或私密配置；公开结果包含关键artifact SHA和逐请求动作/投影摘要。

将 `freshness_exact_read` 的request_id、namespace、memory_id、expected_revision、返回body及状态，与 `freshness_projection` 和实际wire关联，再核对 `request_material.coverage=PROJECTED_REFRESHED`、原search source及原checkpoint。即时read事件只代表已读取，不能单凭它认定Provider已收到正文。B1额外读取与新exact read分开。

27条窄测、静态检查、唯一build及wheel/sdist SHA见[verification](../data/manifests/freshness-v19-repair-final-verification.json)。A2提交59+6文件按Git对象独立核对，见[checkpoint回执](../data/manifests/freshness-v19-repair-a2-source-checkpoint.json)。旧M1异常期望漂移独立提交修复，旧运行语义保持冻结。
