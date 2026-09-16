# G主动保存的新来源进入独立续做分支

MILA-V02-05 v0.26工程增量。正常G通过公开`milai_evidence_capture`保存新观察时，旧编排器
只知道初始来源映射，随后会拒绝这些新引用，无法开始续做。现已在G退出并冻结后，根据
真实调用/回执核对完整观察，再通过公开接口分别保存到独立续做项目。新增来源不再丢失。

## 实现与边界

`v02_g_source_fork.py`接在共同G完成点之后、未来来源更新和续做启动之前。复用既有
完成/冻结检查，不改G文件、State或初始来源。新映射全部确认后才发布；部分失败保留
回执和UNKNOWN，不自动重放、不清空G、不通过另做G来制造实验机会。

核对内容包括完整正文、source_type/ref、subject、speaker、原始source_context与观察时间。
来源上下文继续记录原来的会话/轮次，续做项目不冒充观察发生地。时间格式与公开类型补入
的null默认值可以归一化，正文首尾、换行及Unicode保持。公开GET不提供data_classification，
因此由可关联的捕获回执核对分类，以及项目、正文hash/长度和来源身份；不能从不存在的字段
或当前相同内容反推操作结果。

所有确认的新观察都进入各分支，包括尚未被记忆引用的观察；只重绑已声明的引用字段。
不会给L1/L2附加所有新来源，也不会替换正文中像UUID的文字。每条新Evidence身份独立，
既有分支映射保留。当前资格在复制前及结束时检查，续做仍通过既有FileDisclosure检查。
配置、调用记录、checkpoint、文件引用及完成点的摘要在准备前后核对。

该功能是Lab实验隔离编排，不新增Product数据库克隆、记忆schema或日常用户保存步骤。
公网用户继续按可信登录身份保存自己的私人记忆，未改部署、权限或Canonical治理。

## 真实公开链结果

配置：`configs/v02-g-source-fork-engineering.json`。
成功目录：`artifacts/v02-e2e-generality/g-source-fork-20260907b/`。
Product运行前及终态pin均为
`84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`。

使用独占Runtime/PG、真实HTTP MCP与固定脚本G。G通过正常Host dispatch和来源资格检查
读取初始文件、捕获两条观察、写出真实L1/L2文件并保存State。第一条观察支持文件/记忆；
第二条在产物之后捕获，只进入可回查来源。G实际退出后才分叉。

| 观察 | 结果 |
|---|---|
| 来源保存 | 3条初始来源＋G新增2条＋A/B各复制2条，共9条Evidence |
| State | G/A/B共3个独立身份，操作回执与GET版本/正文分别核对 |
| 冷恢复 | 4个新客户端进程；10次完整文件读取、7次公开来源全文读取 |
| 支持关系 | 新增第一条被重绑；第二条可读取但未附加到记忆支持 |
| 隔离撤权 | A支持来源撤销后State正文与2个相关文件隐藏；B仍完整可读 |
| 输入保真 | 两臂完整文件相同，原G完成点摘要和checkpoint保持 |

来源准备3.979秒；成功工程链含初始化及清理40.191秒。HTTP物理总次数未汇总，不填零；
准备和冷读取成本记录不能重复加到总墙钟。新增模型、tokenize、付费及模拟completion均为0。
读取由脚本选择，没有实际模型输入或语义判断；这些计数不能证明自主保存策略或泛化收益。

首次目录`g-source-fork-20260907a/`因适配器误读GET的data_classification字段失败。
已存1个State和6条Evidence（含A首条复制）保留，A操作回执为RECEIPTED、后续未启动；
不能把异常误报成提交失败。该失败耗时23.509秒。修复后使用新的工程fixture目录，
没有新增真实Agent G或覆盖旧失败。两套独占PG均停止、exit0且无OOM，API/worker/G及
冷客户端PID终态已核对，卷保留，共享模型及公网服务未触碰。

`terminal-audit.json`核对完整观察、声明支持、文件与输入摘要、State版本、pin与进程终态。

## 回归与剩余任务

执行命令：

```bash
uv run python tools/check_v02_g_source_fork.py --root artifacts/v02-e2e-generality/g-source-fork-20260907b --config configs/v02-g-source-fork-engineering.json
uv run milai-lab-check-boundary
uv run pytest -q
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

17项新增单元回归涵盖四续做分支、未引用来源、回执重放去重、未知/冲突回执、来源资格、
完整正文、公开回执绑定、分类改变、身份复用、部分失败与准备期间输入变化。
全量Lab514 passed（6.81秒）；边界、Ruff、mypy 30文件及构建通过。Product代码未修改，
不重复其全量回归。没有迁移或API变化，三臂和五臂编排均复用已有公开保存接口。

完整D0/D3与正式D4/D5仍未完成。D5资料仍须补具体变体绑定及执行配置入口；实际G若没有
可用结构机会，保留NOT_APPLICABLE，不补造字段或重做G。混合负载保存门和SIM12语义负
结果保持，不由本次机械闭环通过改写。Schema仍为0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。
