"""setup_wizard 纯逻辑测试：安装回落决策、doctor 组装、set-key 守卫、Key 验证。

交互壳（input 循环）不做自动化，靠本机实跑验证；这里只测可注入的纯函数。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import setup_wizard as wiz  # noqa: E402


# ------------------------------------------------------------- 安装回落决策

def test_wmshare_install_plan_with_git_prefers_gitee_then_github_then_zip():
    plan = wiz.wmshare_install_plan(has_git=True)
    labels = [label for label, _ in plan]
    assert labels == ["pip install git+Gitee", "pip install git+GitHub",
                      "下载 ZIP 安装（Gitee，无需 git）"]
    assert plan[0][1].startswith("git+https://gitee.com/")
    assert plan[1][1].startswith("git+https://github.com/")
    assert plan[2][1] is None  # ZIP 方案不依赖 git


def test_wmshare_install_plan_without_git_skips_pip_vcs():
    plan = wiz.wmshare_install_plan(has_git=False)
    assert [label for label, _ in plan] == ["下载 ZIP 安装（Gitee，无需 git）"]


def test_version_lt_compares_numerically():
    assert wiz._version_lt("v9.3.1", (18, 18))          # 字符串比较会误判 9 > 18
    assert wiz._version_lt("v18.17.0", (18, 18))
    assert not wiz._version_lt("v18.18.0", (18, 18))
    assert not wiz._version_lt("v22.1.0", (18, 18))
    assert not wiz._version_lt("garbage", (18, 18))     # 解析失败不拦用户


# ------------------------------------------------------------- set-key 守卫

def test_set_key_guard_allows_when_no_credentials():
    assert wiz.set_key_guard("none", force=False) is None


def test_set_key_guard_blocks_existing_without_force():
    reason = wiz.set_key_guard("db", force=False)
    assert reason and "db" in reason and "--force" in reason


def test_set_key_guard_force_overrides():
    assert wiz.set_key_guard("env", force=True) is None


# ------------------------------------------------------------- Key 验证

def test_validate_key_success_with_fake_client():
    class FakeClient:
        def call(self, *_args, **_kwargs):
            return {"bars": []}

    ok, msg = wiz.validate_key("cid", "sec",
                               client_factory=lambda c, s: FakeClient())
    assert ok and "通过" in msg


def test_validate_key_failure_does_not_leak_exception():
    def bad_factory(_cid, _sec):
        raise RuntimeError("403 forbidden")

    ok, msg = wiz.validate_key("cid", "sec", client_factory=bad_factory)
    assert not ok and "403" in msg


# ------------------------------------------------------------- 凭证来源

def test_credential_source_none_by_default(monkeypatch):
    for var in ("WMSHARE_CLIENT_ID", "WMSHARE_CLIENT_SECRET",
                "OPEN_PLATFORM_CLIENT_ID", "OPEN_PLATFORM_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home",
                        lambda: Path("/nonexistent-home-for-test"))
    assert wiz.credential_source() == "none"


def test_credential_source_detects_db(monkeypatch):
    for var in ("WMSHARE_CLIENT_ID", "OPEN_PLATFORM_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home",
                        lambda: Path("/nonexistent-home-for-test"))
    from bigwinner.common import credentials
    assert wiz.credential_source() == "none"
    credentials.save("cid", "sec")
    assert wiz.credential_source() == "db"


def test_credential_source_detects_env(monkeypatch):
    monkeypatch.delenv("WMSHARE_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPEN_PLATFORM_CLIENT_ID", raising=False)
    monkeypatch.setattr(Path, "home",
                        lambda: Path("/nonexistent-home-for-test"))
    monkeypatch.setenv("WMSHARE_CLIENT_ID", "cid")
    assert wiz.credential_source() == "none"  # 只有 id 没有 secret 不算
    monkeypatch.setenv("WMSHARE_CLIENT_SECRET", "sec")
    assert wiz.credential_source() == "env"


# ------------------------------------------------------------- doctor 组装

def _patch_report_parts(monkeypatch, *, wm=True, node=True, built=True,
                        source="db"):
    monkeypatch.setattr(wiz, "wmshare_info",
                        lambda: {"installed": wm, "version": "1.7.2" if wm else None})
    monkeypatch.setattr(wiz, "node_info",
                        lambda: {"installed": node, "version": "v22.0.0", "npm": node})
    monkeypatch.setattr(wiz, "web_dist_built", lambda: built)
    monkeypatch.setattr(wiz, "credential_source", lambda: source)


def test_build_report_live_mode_when_credentials_and_wmshare(monkeypatch):
    _patch_report_parts(monkeypatch, wm=True, source="db")
    report = wiz.build_report()
    assert report["mode"] == "live"
    assert report["hints"] == []


def test_build_report_demo_mode_without_wmshare_has_hint(monkeypatch):
    _patch_report_parts(monkeypatch, wm=False, built=False, source="db")
    report = wiz.build_report()
    assert report["mode"] == "demo"
    assert any("install-wmshare" in h for h in report["hints"])


def test_build_report_no_credentials_hints_page_setup(monkeypatch):
    _patch_report_parts(monkeypatch, source="none")
    report = wiz.build_report()
    assert report["mode"] == "demo"
    assert any("set-key" in h for h in report["hints"])


def test_cmd_doctor_exit_codes_follow_mode(monkeypatch, capsys):
    _patch_report_parts(monkeypatch, source="db")
    assert wiz.cmd_doctor(as_json=True) == 0
    _patch_report_parts(monkeypatch, wm=False, source="none")
    assert wiz.cmd_doctor(as_json=True) == 1
