# 安全策略

## 报告漏洞

请**不要**用公开 issue 报告安全漏洞。使用 GitHub 的
[Private vulnerability reporting](https://github.com/open-winmale/big-winner/security/advisories/new)
（仓库 Security 页 → Report a vulnerability），或通过 GitHub 私信联系维护者
[@deadkingyy](https://github.com/deadkingyy)。

请在报告中包含：影响范围、复现步骤、可能的修复思路。通常 **7 天内**会有首次回复；
确认后尽快修复并发布补丁版本，披露在修复版本发布之后。

## 范围

- **本仓库**（bigwinner 工具代码、前端、打包脚本）——直接报告。
- **wmshare SDK / 上游 API**（api.winmale.com）——请到
  [open-winmale/wmshare](https://github.com/open-winmale/wmshare) 按其安全策略报告。

## 设计上的安全边界

- 凭证（AppID / api-key）只保存在本机 `~/.wmshare/credentials.env`（权限 600），
  服务端任何接口**不回显** Key 本体；网页换 Key 时先真实验证再落盘，失败不落地。
- 服务默认只监听 `127.0.0.1`，不暴露公网；SQLite 存档（`src/data/fptools.db`）
  只含持仓与快照数据，已被 gitignore，不入库。
- 演示模式快照只含公开行情数据（贵州茅台），无任何用户个人信息。
- 本项目无后端第三方依赖（标准库实现），依赖面集中在可选的 wmshare 与前端构建链。
