# 贡献指南

欢迎参与！这是一个个人维护的开源小工具集，节奏不快但认真对待每一个 PR。
开始之前请读一遍 README 的[许可与合规](README.md#许可与合规请先读)与[免责声明](README.md#免责声明)：
工具只做事实与统计聚合，**任何改动都不得引入买卖建议、目标价或仓位指令**。

## 环境要求

- Python ≥ 3.10（后端零第三方依赖，`pip install -e ".[dev]"` 只装 pytest）
- Node ≥ 18.18 + npm（仅前端开发需要）
- 真实数据依赖 [wmshare](https://github.com/open-winmale/wmshare)（可选：不装也能跑，
  自动进演示模式）——BSD-3-Clause 开源

## 本地开发

```bash
# 后端（一条命令启动，http://127.0.0.1:8787）
PYTHONPATH=src python -m bigwinner.shouxi

# 前端（开发态热更新，/api 代理到 8787）
cd web && npm install && npm run dev

# 改后端后需重启进程；改前端保存即生效
npm run build      # 产物输出到 src/bigwinner/shouxi/web_dist/，后端自动托管
```

## 测试

```bash
python -m pytest tests -q     # 全部离线，不需要凭证
cd web && npm test            # vitest + vue-tsc
```

约定：

- 取数层 `Fetcher` 是可替换接口，新逻辑必须能用 `FakeFetcher` 离线测——
  **不接收依赖真实凭证/网络的测试**。
- 数值断言写具体期望值，不写 `assert result` 式的摆设断言。
- 缺失显式化：取不到的数据留空并标注，**不要**静默填 0（这是本项目的硬规矩，
  见 README「设计原则」）。

## 提交信息

用 conventional commits，中文描述，一行说清动机：

```
feat(shouxi): 分红日历支持按年过滤
fix(bigly): 推荐区间在空窗口时误报「无解」
```

## 提交 PR

1. 一个 PR 一件事；大改动先开 issue 对齐方向。
2. PR 描述写清：动机、改动点、验证方式（跑了哪些测试/如何目检）。
3. 新增用户可见功能请同步更新 README 与 CHANGELOG（Unreleased 段）。
