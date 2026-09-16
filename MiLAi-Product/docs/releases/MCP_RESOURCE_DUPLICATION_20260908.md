# OAuth 授权页 RESOURCE 重复

2026-09-08，用户报告一个 AUTHORIZE 页面把同一 MiLAi 地址显示两次。
此前建议移除旧连接未针对这个问题；本问题是单次请求中的重复 resource。

公网 protected-resource metadata 当前只声明一次
`https://milai.aigcit.com:7960/mcp`。
本机 Codex 0.153.0 使用两个临时命令行配置，分别发起 DCR 并生成授权 URL：

| 配置 | 实际 resource 参数 |
| --- | --- |
| URL + 显式 oauth_resource | 同一完整 URL 两次 |
| 仅 URL，自动发现 | 同一完整 URL 一次 |

只解析并输出 resource 参数，未记录完整授权 URL、state、PKCE、token 或凭据。
两个进程均在生成 URL 后终止，未进行账号登录、授权确认、token 兑换或记忆操作。
DCR 创建了诊断客户端注册；未撤销用户现有连接。

已修正两份客户端示例和当前 runbook，移除重复的显式 oauth_resource。
用户 Windows 上的现有配置尚未由本机修改：在实际连接表中删除该行，
重新发起登录并使用新链接；无需删除连接或记忆，也不要手工修改旧授权链接。
原有 scopes 保持。认证服务器、MCP 运行代码及数据库无需变更或重启。

旧版本客户端曾缺少 resource，不能将本次本机结果扩大为所有客户端行为。
用户端新授权页面仍待确认。此配置修复不构成新增工具读写或模型实验验收。
Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE。
