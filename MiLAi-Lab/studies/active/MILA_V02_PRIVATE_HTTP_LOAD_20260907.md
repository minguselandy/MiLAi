# 私人用户HTTP负载与冷恢复

当前指定负载下，两个经过签名验证的私人用户均完成读取；普通用户在热点阶段及其后
满足冻结50ms客户端P95目标。新MCP/客户端恢复相同版本，停用合成热点用户后普通用户
仍可读。不是任意负载下的公平保证，也不填补混合导入保存长尾或正式D4/D5。

## 实现和执行范围

Lab新增`tools/check_v02_private_http_load.py`，只用已锁定公开SDK、嵌入式`build_server`、
认证配置/签名校验器和公开Runtime接口；不导入Product测试/私有helper。认证服务器发现和
JWKS用离线合成响应，token仍走真实验签、audience、scope、私人身份绑定。MCP和Runtime
均为真实loopback HTTP，PG真实持久化；不是公网TLS或真人OAuth登录测量。
异步State/resolve factory及计时开关对应现有CLI配置，结论限定该嵌入式服务装配。

`configs/v02-private-http-load.json`在执行前冻结：两个subject在同一Runtime tenant的
私人项目，6份带各自完整来源引用的State＋994条独立噪声项目State，总1000条；三种文本
主体512/2048/8192字节，完整首尾和换行不删除。普通20读/s、热点80读/s，三个阶段
各5秒（普通baseline、双用户hot、普通recovery）。客户端分别最多2/6在途、无队列/重试，
API线程和池8、2 CPU affinity、PG 2 CPU/1 GiB。读取计划时刻至完成计时，失败分母保留。
热点恢复按预定有限阶段执行，不因目标失败扩大负载或重复旧请求。
Product pin `84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`，未改Product源码。

## 实际证据

主运行`artifacts/v02-e2e-generality/private-http-load-20260907b`：

| 阶段/用户 | 计划/实发/完成 | P95 / P99（ms） |
|---|---|---|
| baseline 普通 | 100 / 100 / 100 | 14.822 / 16.383 |
| hot 普通 | 100 / 100 / 100 | 22.129 / 25.444 |
| hot 热点 | 400 / 400 / 400 | 21.063 / 31.355 |
| recovery 普通 | 100 / 100 / 100 | 14.072 / 16.223 |

700次全完成、无拒绝/超时，逐读核对完整payload与state_version_id；六个State及来源引用
各自不同。冷热阶段顺序固定、数据库缓存共享，未做因果性能改善估计；客户端本身有2/6上限，
不能据此宣称服务器已经能约束无限热点或按私人用户预留资源份额。无须据此新增限流模块。
46次Host调度采样只覆盖主线程调度及共享Host计数，不是完整进程CPU/RSS或独占I/O归因。

主运行新gateway/client中两人六份State均恢复，随后停用检查的脚本断言预期401，实际403，
因此`cold-result.json`保留FAILED。现有认证合同对未准入subject为403，是测试断言错误。
修正后只在`private-http-disabled-followup-20260907a`重启原保留PG、新API/MCP/客户端，
保持hot停用，取得403 `subject_not_admitted`及普通用户三次完整读取；没有重跑700次负载，
没有重新启用hot。旧cold失败与新补充回执分开，不能把旧运行整体改称成功。

首次`private-http-load-20260907a`在SESSION种子建立时409停止、0负载读取：来源未提供
配置session标识，与SESSION来源资格合同不符。补齐source_context后才进入b；未削弱权限。
该4次工具尝试（3完成/1错误）及独占环境清理保留，不计入有效负载样本。

## 验证与剩余出口

终态脚本`artifacts/v02-e2e-generality/audit-private-http-load-20260907.py`已执行：
700测量＋12预热＋6冷恢复＋3停用后读取，共721次唯一关联MCP/Runtime计时；源正文与
保存payload按冻结配置重建核验，读取由固定runner逐项比较。原始逐读正文没有wire转储。
两个PG环境最终exit 0、无OOM；所有自有API/worker/MCP/client已退出，卷保留，共享服务未改。
工具调用记录合计737次（含首轮失败），另有catalog及2次停用原始HTTP探测；994次公开SDK
噪声State写入另列。此数不是包含初始化/health/握手/能力协商的所有HTTP物理请求总数。
无新增模型/tokenize/付费，总账69请求、1,304,756 raw不变。

`uv run milai-lab-check-boundary`、`uv run pytest -q`（451通过，4.44秒）、
`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30文件）、`uv build`通过。
Product未改，不重复其已通过且不受影响的套件；无迁移/回滚/权限变更，未部署公网。
Schema 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。

本次是明确首版客户端边界下的私人用户负载/冷恢复证据，不是全D3。剩余重点仍是冻结
混合导入保存门失败与实际部署资源边界；先核对已有完整工程证据和可复用范围，避免重新
扩成全矩阵或重复无新原因的负载。正式D4/D5保持完整范围且未进入。
