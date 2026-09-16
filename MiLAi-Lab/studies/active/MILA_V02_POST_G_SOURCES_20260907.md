# G结束后的公开来源更新

MILA-V02-05 v0.24工程增量。续做会话现在可以收到G完成之后才提供的新文件观察，
不将新决定提前放入G，也不替G改写旧State。完整D0/D3与正式D4/D5仍未完成。

## 实现与边界

- `run_v02_e2e_generality.py`新增可选`post_g_source: {path, sha256}`配置。初始来源和续做
  来源分别锁定；评价合同对照续做来源，G只接收初始文件。缺省行为不变。
- `v02_post_g_sources.py`验证普通文件观察包，当前支持新增文件。旧观察的路径、URI、
  时间、全文和hash必须保持；修订须使用新的普通路径及可区分版本的来源URI。尚不支持覆盖/删除
  原观察的阶段变更，也不推断新材料是否在语义上推翻旧理解。
- G子进程返回、退出码0、任务及分配记录COMPLETED、checkpoint可比较、文件已冻结后，
  才能准备新增来源。与G产物重名/路径冲突直接拒绝。
- 复用`v02_public_snapshot.capture_verified`，通过公开Hook/SDK持久捕获，再公开GET核对
  完整Evidence正文、身份、来源、时间、项目及当前资格。原G/A/B准备也使用同一函数。
- A/B分别捕获同一新增内容，使用不同Evidence身份；两组均已核验才发布ready记录。
  失败保留部分回执，不启动续做、不自动重试。准备记录绑定配置、来源、G退出、冻结文件、
  checkpoint和原项目映射的hash；消费前重新核对。
- Host先复制并核对完整G文件，再追加新来源和各臂引用。旧L1/L2支持不添加新来源；
  材料解释及是否写回仍由Host决定。可选来源回查在A/B使用完整续做来源清单，默认仍关闭。
  读取与每次发送前继续执行现有FileDisclosure资格检查。

这是Lab编排增量，没有新Product API、数据库实体、业务schema或治理权限。
原始来源保真要求不变；不删除首尾或缩短内容来获得成功。

## 实际执行

配置`configs/v02-post-g-source-engineering.json`，模型发送关闭。
产物`artifacts/v02-e2e-generality/post-g-source-engineering-20260907a/`。
Product pin仍为`84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`，
运行前及终态审计通过。脚本G是明确标记的工程fixture，不是模型会话或真实Agent产物。

| 检查 | 直接结果 |
|---|---|
| 原来源G/A/B公开准备 | 3条完整Evidence，三组独立项目 |
| G后新增来源 | A/B各1条，共2条；全文相同、身份不同；准备耗时2.420秒 |
| 旧State保存与续做绑定 | 三个State身份；A/B旧payload仅重绑定原引用，不附加新来源支持 |
| 新进程冷读 | A、B、撤权后A、未受影响B共4进程，15次完整文件读取 |
| A新增来源撤销 | 发现入口隐藏该文件，直接读拒绝；旧State支持未撤销，仍可恢复 |
| B与G保真 | B新增文件仍可读；A/B工作区hash相同；G全文及旧记忆不受改写 |
| 清理 | API、worker、G及4冷进程终止；PG exit0、无OOM、卷保留；公网与共享模型未改 |

`terminal-audit.json`核对5份来源metadata、3个State身份、4个冷进程及版本、15个完整读回
hash、两臂文件等同和G不变。保存回执、metadata、checkpoint、冷读和撤销记录均保留。
新增模型、tokenize、付费调用均为0；脚本分配标记SCRIPTED，不记作模型G。
新增来源准备时间单列，原始导入保留各自capture/readiness时间。整链墙钟未单独计量，
总物理HTTP次数未汇总（另有资格metadata、初始化和握手），不填零或当成本验收。

17项新单元回归覆盖部分失败/UNKNOWN、重复准备、原观察变更、覆盖G产物、G未结束、
无变化、映射漂移、已呈现来源撤销和协调器停止。部分捕获失败是受控异常注入，未称为
本次真实网络失联证据；既有公开UNKNOWN测试保留原归属。

## 检查与剩余工作

实际执行命令：

```bash
uv run python tools/check_v02_post_g_sources.py --root artifacts/v02-e2e-generality/post-g-source-engineering-20260907a --config configs/v02-post-g-source-engineering.json
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

Lab 468 passed（5.07秒）；边界、Ruff、mypy 30文件及构建通过。Product代码未改，未重复
Product全量测试。无迁移；去掉可选配置即保留旧流程，不能删除准备回执模拟重新开始。

四条D5资料通过新phase_contract：两个无新增、两个各新增1文件，原manifest SHA仍为
`7e884ae847e44acbfe7101aa7f331b0b257d1171a15100633caf8742f3748b8a`。这只是机械核验，
没有模型调用，不将fixture当真实G，没有改变PREPARED_NOT_EXECUTABLE。

下一步补齐同一真实G完成点上的表示/结构变体公开保存、冷恢复及实际输入对比编排。
本次A/B阶段来源机制不自动构成五臂D5编排。混合负载保存门、完整部署公平、正式开发链
与指定家族泛化仍缺；SIM12完整来源下的解释失败不被工程结果消除。
Schema保持0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。
