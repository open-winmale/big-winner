/* 内置体验 Key 主动提示：进页即弹模态框（「暂不」仅当前会话内不再弹），
   配置自己的 Key 后服务端返回 trial=false，永久不再出现。样式内联，不依赖 base.css。 */
(function () {
  function modal(info) {
    if (document.getElementById("trial-key-mask")) return;
    var mask = document.createElement("div");
    mask.id = "trial-key-mask";
    mask.style.cssText = "position:fixed;inset:0;z-index:1000;background:rgba(15,23,42,.45);"
      + "display:flex;align-items:center;justify-content:center;";
    var card = document.createElement("div");
    card.style.cssText = "max-width:430px;width:calc(100% - 48px);background:#fff;border-radius:10px;"
      + "padding:22px 24px;box-shadow:0 12px 40px rgba(0,0,0,.18);font-size:14px;line-height:1.7;color:#1f2937;";
    card.innerHTML =
      '<h3 style="margin:0 0 10px;font-size:16px">正在使用内置体验 Key</h3>'
      + '<p style="margin:0 0 12px">当前页面通过<b>共享体验 Key</b> 取数：额度有限，'
      + '高峰期容易限流影响使用。建议配置自己的 Key（个人研究免费、额度充足），'
      + '既不影响他人，也让自己稳定取数。</p>'
      + '<p style="margin:0 0 16px;font-size:13px;color:#6b7280">'
      + (info.setup_url
          ? '在「配置我的 Key」页粘贴 client_id 与 api-key 即可，立即生效、无需重启。'
          : '设置环境变量 <code>FINPIPE_CLIENT_ID</code> / <code>FINPIPE_CLIENT_SECRET</code> 后重启，'
            + '或从门户页（:8787）进入「配置我的 Key」。')
      + '</p>';
    var row = document.createElement("div");
    row.style.cssText = "display:flex;gap:10px;justify-content:flex-end;";
    var later = document.createElement("button");
    later.textContent = "暂不，继续使用";
    later.style.cssText = "border:1px solid #d1d5db;background:#fff;color:#374151;"
      + "border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13px;";
    later.onclick = function () {
      try { sessionStorage.setItem("trialKeyHintDismissed", "1"); } catch (e) { /* 隐私模式忽略 */ }
      mask.remove();
    };
    row.appendChild(later);
    if (info.setup_url) {
      var go = document.createElement("a");
      go.href = info.setup_url;
      go.textContent = "配置我的 Key →";
      go.style.cssText = "background:#1d4ed8;color:#fff;text-decoration:none;"
        + "border-radius:8px;padding:7px 14px;font-size:13px;font-weight:600;display:inline-block;";
      row.appendChild(go);
    }
    card.appendChild(row);
    mask.appendChild(card);
    document.body.appendChild(mask);
  }

  if (sessionStorage.getItem("trialKeyHintDismissed")) return;
  fetch("/api/appinfo").then(function (r) { return r.json(); }).then(function (info) {
    if (info && info.trial) modal(info);
  }).catch(function () { /* appinfo 不可用（如 demo 站）不提示 */ });
})();
