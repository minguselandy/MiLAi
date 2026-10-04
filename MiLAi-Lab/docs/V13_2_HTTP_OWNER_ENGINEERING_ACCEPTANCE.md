# v13.2 全客户端 HTTP owner 限定工程验收

最终 Source `02e619e` 已逐字节转入开发分支 `28671c3`。默认仍为 legacy；显式 `serialized_ledger_owner_v1` 使用既有连续账本的稳定 sidecar 租约，共享一个预算与请求互斥，从持久预约覆盖到实际 HTTP、原 trace、结算和退出。它不改变提示、参数、来源选择、角色/hash、Store/CAS、算法或自动重试策略。

Root独立核对2083索引文件与5锚点、115原命令及13非零记录、31嵌套进程及5fork控制，保存9753源码快照校验和122真实symlink说明。原件归档不执行Source recorder或上游参考。八组真实默认raw请求/响应、消息和账本对照相同，仅排除事件wall_seconds；五个受保护职责的字节和AST相同。最终214运行/393测试/316配置完整map与执行版本一致，详见[机器验收](../data/manifests/v13-2-http-owner-engineering-acceptance.json)。

Root在最终字节副本执行59控制、ruff8、mypy6和双边界；实际D0/P5/micro入口、Host与writer、原生callback seam及8默认wire均有原件。旧79控制在provider清理改动前运行，保持其旧阶段身份。转入后主树双边界再次通过；未重跑无影响的整套旧测试。

独立清理复现验证实际HTTPX资源关闭；before-close异常、真实transport.close异常和no-op三类均保留登记、closing与原lease，竞争进程BUSY，原拒绝实例及清理cause保留。即使HTTPX已标CLOSED也不宣称资源清理完成。Root只在观察保存后显式清理合成资源，运行时不自动retry。

事前手工账本oracle实际执行五事件/11完整状态，含503、unknown和真实子进程exit77，最后generation requests7、charged257/known46/unknown3，embedding charged23/known18/unknown1；原历史未知和opaque字段保持。另检查九DTO字段及嵌套response_format漂移、实际file fsync→replace→directory fsync→dispatch、同一sidecar inode/另进程BUSY、响应emit期间互斥与同线程拒绝、fresh process精确历史读取，以及known/bool/negative/string/absent五种实际回包用量。布尔/字符串/缺失保持unknown，负数拒绝而不退款。这些均是明确合成费用，不是服务器账单或模型质量。

42条预先审查项有41条限定工程证据，部分初始化项仅证明已返回HTTP客户端的清理。SDK构造器在返回对象前抛错的内部资源不作完整保证；native SDK依赖seam仍为mock。合作Linux范围不覆盖非合作tamper、hardlink或跨机器。关闭失败保留lease和错误链，不承诺任意SDK自动恢复。

Root两次原审计失败（摘要map缺files；scope hash漏decorator）与执行版本/partial outputs保存，修正不覆盖；若当时after maps不可得，明确不倒补。Source首版本实际未关资源的独立反例及13原非零命令仍留存。研究反思采用[已保存HTTPX清理参考](V13_2_DESIGN_LITERATURE.md)，同方向的通用生命周期修正，不按URL、语言或案例特判。

资料保持17论文/18项目参考、784文件/152本地链接，原PDF/HTML、固定版本方法源码、URL/UTC/SHA和中文范围均可查看，入口是本地 `artifacts/v13-2-design-literature/index.html`。[公开目录](../data/manifests/v13-2-design-literature-catalog.json)与[阅读总结](V13_2_DESIGN_LITERATURE.md)已提交；原资源本地保留。

历史Root `fixed_flow.py` direct-budget入口不在本轮范围，原R0/R7不重跑。下一固定流先创建新owner-aware Root驱动、有限生命周期检查，再另冻配置/cohort并完成GitHub前置核对。完整计划ACTIVE；48状态仍4 PASSED_SCOPED /27 PARTIAL /1 NOT_PASSED /16 NOT_VERIFIED，E0 NOT_PASSED、D4 NOT_ADMITTED、Product NO_GO。0新实际generation/embedding HTTP；这次工程通过不升级实际研究门禁。
