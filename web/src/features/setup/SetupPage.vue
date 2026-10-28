<script setup lang="ts">
import { useApp } from '@/store/useApp';

const app = useApp();
</script>

<template>
  <main class="wrap">
    <div class="page-head">
      <h1>配置自己的 Key</h1>
      <p>没有配置 Key 时，工具运行在演示模式——页面是真实数据的历史快照（截止日期见页顶横幅），
         只能看有限的示例标的。申请自己的 AppID 后即为实时全市场数据，额度充足，全程免费。</p>
    </div>

    <section class="card">
      <div class="step">
        <div class="step-no">1</div>
        <div class="step-body">
          <h3>获取 AppID（免费）</h3>
          <p>
            <a class="big-link" href="https://open.winmale.com" target="_blank" rel="noopener">open.winmale.com →</a>
          </p>
          <p>微信扫码登录（注册即送免费额度）→「我的」→「开放平台」→「我的应用」→
             「查看应用信息」，复制 <code class="inline">client_id</code> 和
             <code class="inline">api-key</code>（即 client_secret）。</p>
        </div>
      </div>

      <div class="step">
        <div class="step-no">2</div>
        <div class="step-body">
          <h3>页面内粘贴保存（推荐）</h3>
          <p>点下面的按钮（或页面右上角「数据源 Key」），粘贴 client_id 与 api-key，
             <strong>验证通过立即热切换</strong>，无需重启。</p>
          <p>Key 只存本机工具数据库，不入 git、不回显；随时可在同一窗口
             「清除并回到演示」。</p>
          <div class="toolbar" style="margin-top:10px">
            <button class="primary" @click="app.openKeyDialog()">🔑 打开保存窗口</button>
          </div>
        </div>
      </div>

      <div class="note">
        保存后演示模式立即热切换为实时（无需重启），顶栏徽章变成「已用自己的 Key」。
      </div>
    </section>

    <section class="card">
      <details class="advanced">
        <summary>高级：命令行方式配置（可选，页面保存之外的兼容途径）</summary>
        <div class="adv-body">
          <p>页面保存的 Key 存本机数据库；以下两种传统方式仍然可读，适合无网页的
             服务器/脚本场景：</p>
          <p><strong>方式 A：环境变量启动</strong>（按操作系统任选其一）</p>
          <pre class="block"># macOS / Linux
export WMSHARE_CLIENT_ID=你的client_id
export WMSHARE_CLIENT_SECRET=你的api-key
python run.py

# Windows（CMD）
set WMSHARE_CLIENT_ID=你的client_id
set WMSHARE_CLIENT_SECRET=你的api-key
python run.py

# Windows（PowerShell）
$env:WMSHARE_CLIENT_ID="你的client_id"
$env:WMSHARE_CLIENT_SECRET="你的api-key"
python run.py</pre>
          <p><strong>方式 B：写入凭证文件</strong>
             <code class="inline">~/.wmshare/credentials.env</code>
             （Windows 为 <code class="inline">C:\Users\你\.wmshare\credentials.env</code>）：</p>
          <pre class="block">WMSHARE_CLIENT_ID=你的client_id
WMSHARE_CLIENT_SECRET=你的api-key</pre>
          <p>凭证内容不要提交到任何 git 仓库；也不要直接分享存了 Key 的
             <code class="inline">data/fptools.db</code>（里面还有你的快照数据，
             分享前先在页面「清除 Key」）。读取优先级：页面保存的数据库 &gt;
             环境变量 &gt; 凭证文件。</p>
        </div>
      </details>
    </section>

    <section class="card">
      <div class="card-head"><h2>遇到问题</h2></div>
      <table class="troubleshoot">
        <tbody>
          <tr><td>403 / POLICY_DENIED</td>
              <td>确认 Key 复制完整、未过期；你的 AppID 策略需允许所调用的接口。换 Key 后立即生效，无需重启。</td></tr>
          <tr><td>429 / 频繁限流</td>
              <td>数据源小时额度用完。工具遇 429 会自动退避重试一次；等下一个整点恢复，或换一个额度充足的 Key。</td></tr>
          <tr><td>某字段显示 —</td>
              <td>该标的此字段接口未返回（如无分红史、指标缺失）。工具不做猜测填充，缺失会显式标在该行「数据说明」。</td></tr>
          <tr><td>价格略低于盘中价</td>
              <td>现价取最新一根日 K 收盘价。这是工具的取数口径，保证全市场一致、可回放。</td></tr>
        </tbody>
      </table>
    </section>

    <div class="footer">
      <div>本工具仅做持仓数据的统计聚合，不构成任何投资建议；数据来自 wmshare，最终以上市公司公告为准；历史分红不代表未来。</div>
    </div>
  </main>
</template>

<style scoped>
.step { display: flex; gap: 16px; margin: 20px 0; }
.step-no {
  flex: none; width: 30px; height: 30px; border-radius: 50%;
  background: var(--accent); color: #fff; font-weight: 640;
  display: flex; align-items: center; justify-content: center; font-size: 14px;
}
.step-body { flex: 1; }
.step-body h3 { margin: 4px 0 8px; font-size: 15px; }
.step-body p { margin: 0 0 10px; color: var(--text-2); }
.big-link { font-size: 15px; font-weight: 620; }
code.inline {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 1px 7px; font-size: 13px;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
.advanced { font-size: 13.5px; }
.advanced summary {
  cursor: pointer; font-weight: 620; color: var(--text-2);
  padding: 4px 0;
}
.adv-body { margin-top: 12px; color: var(--text-2); }
.adv-body p { margin: 10px 0; }
pre.block {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 14px 16px; overflow-x: auto;
  font-size: 13px; line-height: 1.7;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  margin: 10px 0;
}
.note {
  background: var(--warn-soft); border: 1px solid #fde68a;
  border-radius: var(--radius-sm); padding: 12px 14px; font-size: 13px;
  color: var(--warn); margin: 14px 0;
}
.troubleshoot td:first-child { white-space: nowrap; font-weight: 600; }
</style>
