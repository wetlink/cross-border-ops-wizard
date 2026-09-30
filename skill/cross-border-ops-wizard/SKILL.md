---
name: cross-border-ops-wizard
description: Use when operating the cross-border access lifecycle from overseas VPS onboarding and x-ui/3x-ui/VLESS/Reality delivery through purchased residential/static proxy intake, client-specific chained egress, and AdsPower/RoxyBrowser/BitBrowser profile configuration. 触发：新 VPS 搭代理、部署 x-ui/3x-ui、配置 DNS/证书/网关/防火墙、分发或排障节点、购买家宽/静态出口 IP 后验真、通过 VPS 为手机或浏览器增加独立出口、配置 AdsPower/RoxyBrowser/BitBrowser 全局代理与窗口、核对浏览器实际出口、生成交付 runbook。适用任意云厂商与代理服务商，适配 Claude Code、Codex、WorkBuddy、OpenClaw 等智能体。
---

# VPS 运维纳管魔法师 (cross-border-ops-wizard)

GitHub: [wetlink/cross-border-ops-wizard](https://github.com/wetlink/cross-border-ops-wizard)

覆盖跨境访问资产从入口到出口的完整生命周期：把境外 VPS 从“裸机”推进到可维护的 x-ui/3x-ui 与 VLESS/Reality 节点，也把新购家宽/静态代理推进到独立链式出站、手机节点、指纹浏览器环境和实际出口验收。

- **云厂商无关**：主流程不绑定具体厂商。腾讯云 Lighthouse 作为内置 profile（注意其云防火墙独立于系统防火墙、需在控制台单独放行，默认网卡 MTU 常为 8500）；其他云按同一套元组纳管。
- **跨智能体**：本 SKILL.md 为标准格式，可装入 Claude Code / Codex / WorkBuddy / OpenClaw 的 skills 目录（见仓库 `scripts/install.sh`）。执行类操作统一放在 `scripts/` 下的纯 bash / python，不依赖某个 agent 的专有工具。

# 触发场景

用户出现以下意图时使用：

- 手头有一台新开的境外 VPS（任意云厂商），想搭代理 + 管理后台。
- 同时有域名，需要把域名解析、证书和 VPS 服务串起来（无域名时可走纯 IP 简化路径）。
- 希望部署 x-ui / 3x-ui 管理界面，方便团队接入、维护跨境工具。
- 配置 DNS、证书、HTTPS 网关、面板入口和健康检查。
- 排查节点不可达、证书异常、端口不通、面板不可访问、下载慢/丢包/线路差。
- 排查 VLESS/Reality 全线 EOF、Clash/Mihomo fake-ip、客户端配置热加载后重启回滚等复合故障。
- 新购家宽或静态代理后，验真出口、处理代理域名多 A 记录，并配置 AdsPower/RoxyBrowser/BitBrowser。
- 让手机或本机应用通过“VLESS VPS 第一跳 -> 指定代理出口”稳定切换 IP。
- 排查 3x-ui 热加载暂时可用、重启后客户端/出站/路由丢失的问题。
- 修复“窗口能用但全局代理列表没有记录”或“代理已添加但未关联窗口”等资产关系问题。
- 生成运维 runbook、交付手册、敏感信息清单。
- 对已有节点做阶段性验收和交接。

# 工作原则

- 先读后改：先确认目标主机、云厂商、区域、IP、域名、SSH alias 和用途。
- 一次只处理一个明确目标，旧节点默认只读。
- 云防火墙、系统防火墙、证书、账号和密钥操作前先确认。
- 敏感信息不进 git。真实密钥、x-ui 后台地址、一次性链接和账号密码只写入本地受控文件或用户指定的安全位置。
- 交付材料分层：公开 runbook 写结构和检查方法；敏感手册只在用户明确要求时写入凭据。

# 工作流程

1. 规划：
   - 明确用途、云厂商与区域、预算、域名、管理员、团队人数、交付范围。
   - 参考 `references/sop.md`。
2. 纳管：
   - 记录 provider、region、instance_id、public_ip、os、domain、alias、role。
   - 验证 SSH、DNS 和基础系统信息。
3. x-ui、网关与证书：
   - 配置域名解析。
   - 按目标系统安装并初始化 x-ui / 3x-ui 管理界面。
   - 一键部署可用 `scripts/node-wizard.sh deploy --alias <a> [--domain <d>]`（幂等；preflight 不过会给云操作清单并退出，修好重跑）。
   - 配置 HTTP 健康检查、HTTPS 网关和面板入口。
   - 申请并验证证书。
4. 端口与边界：
   - 明确哪些端口公开，哪些只允许本机或内网访问。
   - 云防火墙与系统防火墙保持一致（Lighthouse 等需在控制台单独放行公网端口）。
5. 验收：
   - 参考 `references/verification.md` 执行服务、端口、HTTP/TLS、速度和日志检查。
   - 用户反馈“下载慢/卡”时，按 verification.md 的“线路与丢包诊断”分段定位（先排除服务端，再看 VPS↔客户端这一段的丢包/路由），不要只看客户端测速数字。
   - VLESS/Reality 故障按 verification.md 的事故排查顺序分层处理，不要先重装或重生密钥。
6. 出口 IP 与指纹浏览器（按需）：
   - 新购家宽/静态代理或需要修复浏览器代理关联时，读取 `references/fingerprint-browser-egress.md`。
   - 必须按“全局代理库 -> 环境/窗口关联 -> 浏览器内实际出口 -> 全局关联回读”验收，不以控制台代理测试代替最终验收。
7. 链式出口（按需）：
   - 需要 VPS 第一跳和独立代理出口时，读取 `references/chain-egress.md`。
   - 优先使用 `scripts/xui_chain_egress.py`：只读识别新版/旧版 API，dry-run 后从 VPS 预检上游，再备份、写入专属客户端/出站/路由、force restart、读回并验收完整 VLESS 出口。
   - 保留用户指定的既有 AI/默认出口；将重要旧链路加入私密 regression manifest。共享规则、已有默认出站或不明客户端归属必须停止，不自动覆盖。
   - 新用户路由须先于域名规则，原有 API/安全拦截仍在前面。真实部署必须给预期出口；旧版需提供 VPS 的 public-host。交付仅使用验证通过的链接文件。
   - 热加载成功不算完成；必须在强制重启后重新读回并通过实际出口测试。
8. 文档：
   - 参考 `references/documentation.md` 输出 runbook、敏感交付手册和操作命令。
   - 使用 `scripts/render_node_materials.py` 生成本地材料骨架。

# 关键命令

生成节点材料骨架：

```bash
python3 scripts/render_node_materials.py \
  --alias team-sg \
  --domain node.example.com \
  --public-ip 203.0.113.10 \
  --out-dir ./output/team-sg
```

新增或更新一条 3x-ui 链式出口前先 dry-run：

```bash
python3 scripts/xui_chain_egress.py chain-upsert \
  --xui-env ~/.config/vps-ops/node-x-ui.env \
  --proxy-env ~/.config/vps-ops/proxy-chains.env \
  --proxy-prefix IPNEW \
  --inbound-id 1 \
  --client-email phone-new \
  --outbound-tag phone_exit_new \
  --public-host node.example.test \
  --expected-exit-ip 203.0.113.20 \
  --output ~/.config/vps-ops/phone-new-delivery.json \
  --dry-run
```

验收时至少检查：

- SSH 是否可登录。
- DNS 是否解析到目标 IP。
- x-ui 管理界面是否可登录。
- 健康检查是否返回成功。
- HTTPS 证书是否匹配域名。
- 公开端口和私有端口是否符合设计。
- 服务日志是否没有持续报错。

一键起节点 / 验收 / 开关后台。引擎是多文件结构（entrypoint + `lib/`），需先把整个 `scripts/` 目录同步到 VPS 再以 root 运行（任意 agent 经 SSH 调用同一命令）：

```bash
# 1) 同步引擎到 VPS（首次或更新时各一次）
rsync -a scripts/ <alias>:/opt/node-wizard/
# 2) 以 root 运行
ssh <alias> 'bash /opt/node-wizard/node-wizard.sh deploy --alias <a> --domain <d>'
ssh <alias> 'bash /opt/node-wizard/node-wizard.sh verify --alias <a>'
ssh <alias> 'bash /opt/node-wizard/node-wizard.sh panel-open --alias <a> --domain <d>'
ssh <alias> 'bash /opt/node-wizard/node-wizard.sh panel-close --alias <a>'
```

# 注意事项

- 默认只交付受限文件，不展示私钥、密码、订阅链接或一次性 token；用户明确要求时可在当前私密交付渠道提供其节点链接，但不放入公开仓、日志或公共文档。
- 不把真实节点材料提交到公开仓库。
- 没有用户确认时，不改云防火墙、不重启关键服务、不覆盖现有配置。
- 如果当前信息不足，先输出待确认清单和只读检查命令。
