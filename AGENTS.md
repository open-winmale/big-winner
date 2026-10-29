# AGENTS.md — 安装 / 配置 / 启动 Runbook

本文件是 big-winner 安装、配置、启动命令的**唯一权威口径**。人类手动安装、
AI agent 自动化安装、CI/脚本都按这里的命令执行；README 与 Makefile 只引用
不展开。全部命令幂等，可重复执行。

## 0. 获取源码

```bash
git clone https://gitee.com/open-winmale/big-winner.git   # 国内首选
# 备选：git clone https://github.com/open-winmale/big-winner.git
cd big-winner
```

小白替代：在 Gitee/GitHub 网页点「下载 ZIP」解压（无需 git；后续命令相同）。

## 1. 环境体检

```bash
python3 setup_wizard.py doctor --json    # Windows: python setup_wizard.py doctor --json
```

退出码：**0 = 实时就绪**（有凭证且 wmshare 可用）；**1 = 可启动，演示模式**
（缺凭证或缺 wmshare，属正常状态，工具自动用历史快照）；**2 = 内部错误**。

JSON 关键字段：`python.ok`（≥3.10）、`wmshare.installed`、`credentials.source`
（`db` / `env` / `file` / `none`）、`mode`（`live` / `demo`）、`hints[]`
（下一步建议命令）。`node` / `web_dist` 只是信息字段，不影响退出码。

## 2. 按需补齐（doctor 不为 0 时）

```bash
# 数据依赖 wmshare（PyPI 无发行版；内部自动 Gitee → GitHub → ZIP 三级回落）
python3 setup_wizard.py install-wmshare

# 新版网页界面（可选；无 Node 时工具运行于经典多页界面，功能完整）
python3 setup_wizard.py build-web          # 需 Node ≥ 18.18

# 数据源 Key（AppID + api-key，open.winmale.com 免费申请）
python3 setup_wizard.py set-key --client-id <AppID> --client-secret <api-key>
```

`set-key` 说明：

- 默认联网验证（调一次真实行情），验证失败**不落地**；
- wmshare 未装时必须加 `--no-verify` 才保存（与页面保存同口径提示）；
- 覆盖已有 Key 加 `--force`；
- ⚠️ secret 会进 shell history：交互终端请引导用户在页面右上角
  「数据源 Key」粘贴保存；`set-key` 面向 agent/脚本场景。

## 3. 启动

```bash
python3 run.py          # 前台运行，门户 http://127.0.0.1:8787（--port 可换）
```

后台运行由调用方自行处理（nohup / systemd / 计划任务）。日志横幅会标明
当前是实时模式还是演示模式。

## 4. 验证

```bash
curl -s http://127.0.0.1:8787/api/key-status
```

- 实时模式期望：`{"custom": true, "demo": false}`
- `{"custom": false, "demo": true}` = 演示模式（无凭证时自动进入，非故障）

## 约定与边界

- 凭证优先级：数据库 `data/fptools.db` > 环境变量（`WMSHARE_CLIENT_ID` /
  `WMSHARE_CLIENT_SECRET`）> `~/.wmshare/credentials.env`；后两者只读兼容。
- `data/` 已 gitignore；分享机器或仓库前确认不含 `data/fptools.db`。
- 不要把 Key 写进仓库、issue 或截图。
- 页面里换 Key 热切换实时生效，无需重启（`/api/key-save`）。
