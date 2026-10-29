# big-winner 开发者任务入口
# Windows 用户：双击 setup.bat / run.bat，或 python setup_wizard.py。
# 命令口径唯一来源见 AGENTS.md（本文件只做引用，勿在此展开新口径）。

.PHONY: setup run build-web doctor test

setup:      ## 交互式安装向导（数据依赖/界面/Key，每步可跳过）
	python3 setup_wizard.py

run:        ## 启动服务（门户 :8787）
	python3 run.py

build-web:  ## 构建网页版门户（需 Node ≥ 18.18）
	python3 setup_wizard.py build-web

doctor:     ## 环境体检（加 JSON=1 输出 JSON）
	python3 setup_wizard.py doctor $(if $(JSON),--json)

test:       ## 跑测试（需先 pip install pytest）
	python3 -m pytest
