/* 收息佬 · 前端
   交互模型：市场切换 + 单框搜索添加 → chips（含市场徽标）→ 一键生成。
   持仓数据结构带 market 字段：cn → 600036；hk → hk.00700（SDK 需前缀）。 */
(function () {
  'use strict';

  /* ---------------- 状态 ---------------- */
  const positions = [];   // {code, market, name, shares, cost, buy_date, tax_rate}
  let currentMarket = 'cn';

  /* 账本状态：独立于 xray 结果；默认年度汇总，逐笔明细折叠 */
  let ledgerOpen = false;
  let ledgerData = null;
  let ledgerYear = '';
  let ledgerTax = { mode: 'auto', flat_rate: null, year_rates: {} };
  let ledgerTimer = null;
  let ledgerYearsKey = '';

  /* 收息驾驶舱状态 */
  let calendarData = null;
  let calendarMode = 'positions';
  let calendarHorizon = 30;
  let calendarMarket = 'cn';
  let calendarTimer = null;
  let calendarWatchlist = null;
  let marketCalendarCache = null;
  let marketPreviewPromise = null;
  let marketPreviewMarket = null;

  /* ---------------- 工具函数 ---------------- */
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const DASH = '<span class="muted">—</span>';
  const mktLabel = (m) => m === 'hk' ? '港' : (m === 'us' ? '美' : 'A');

  function fmtMoney(v) {
    if (v == null || !isFinite(v)) return DASH;
    const abs = Math.abs(v);
    if (abs >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
    if (abs >= 1e4) return (v / 1e4).toFixed(2) + ' 万';
    return v.toFixed(2);
  }
  const fmtPrice = (v) => (v == null || !isFinite(v)) ? DASH : v.toFixed(2);
  function fmtMoneyCcy(v, ccy) {
    if (v == null || !isFinite(v)) return DASH;
    const prefix = ccy === 'HKD' ? 'HK$' : (ccy === 'USD' ? 'US$' : '');
    return prefix + fmtMoney(v);
  }
  function fmtPriceCcy(v, ccy) {
    if (v == null || !isFinite(v)) return DASH;
    const prefix = ccy === 'HKD' ? 'HK$' : (ccy === 'USD' ? 'US$' : '');
    return prefix + v.toFixed(2);
  }
  const fmtPct = (v, d) => (v == null || !isFinite(v)) ? DASH :
    (v * 100).toFixed(d == null ? 2 : d) + '%';
  const fmtInt = (v) => (v == null || !isFinite(v)) ? DASH : Number(v).toLocaleString('zh-CN');
  function fmtSigned(v) {
    if (v == null || !isFinite(v)) return DASH;
    const color = v > 0 ? 'var(--up)' : (v < 0 ? 'var(--down)' : 'var(--text-2)');
    return `<span style="color:${color}">${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%</span>`;
  }
  function fmtSignedMoney(v) {
    if (v == null || !isFinite(v)) return DASH;
    const color = v > 0 ? 'var(--up)' : (v < 0 ? 'var(--down)' : 'var(--text-2)');
    return `<span style="color:${color}">${v > 0 ? '+' : ''}${fmtMoney(v)}</span>`;
  }
  function marketFromCode(code, market) {
    const m = String(market || '').toLowerCase();
    if (m === 'hk' || m === 'us') return m;
    const c = String(code || '').toLowerCase();
    if (c.startsWith('hk.')) return 'hk';
    if (/^\d{5}$/.test(c)) return 'hk';
    return 'cn';
  }
  const marketOf = (p) => marketFromCode(p.code, p.market);
  const chipKey = (p) => marketOf(p) + ':' + p.code;
  const taxSourceLabel = (s) => ({
    auto: '自动', position: '单票覆盖', year: '年度覆盖',
    flat: '统一税率', hk_default: '港股默认', fallback: '估算(缺买入日)'
  }[s] || s || '自动');

  function defaultBuyDate() {
    return `${new Date().getFullYear()}-01-01`;
  }

  function normalizePosition(p) {
    let tax = '';
    if (p.tax_rate !== '' && p.tax_rate != null) {
      const n = Number(p.tax_rate);
      if (isFinite(n)) tax = n > 1 ? n / 100 : n;
    }
    return {
      code: p.code,
      market: marketFromCode(p.code, p.market),
      name: p.name || '',
      shares: p.shares,
      cost: p.cost == null ? '' : p.cost,
      buy_date: p.buy_date || defaultBuyDate(),
      tax_rate: tax,
    };
  }

  const plainMoney = (v) => (v == null || !isFinite(v)) ? '—' : fmtMoney(v);
  const plainPct = (v) => (v == null || !isFinite(v)) ? '—' : (v * 100).toFixed(2) + '%';

  /* ---------------- chips ---------------- */
  function renderChips() {
    const box = document.getElementById('chips');
    const empty = document.getElementById('chips-empty');
    document.getElementById('pos-count').textContent =
      positions.length ? `${positions.length} 只标的` : '';
    empty.style.display = positions.length ? 'none' : '';
    box.innerHTML = positions.map((p) => `
      <div class="chip">
        <span class="chip-mkt mkt-${marketOf(p)}">${mktLabel(marketOf(p))}</span>
        <span class="chip-code">${esc(p.code)}</span>
        <span class="chip-name">${esc(p.name)}</span>
        <input class="chip-shares num" data-shares="${esc(chipKey(p))}"
               value="${esc(p.shares)}" title="持股数" inputmode="numeric">
        <span class="chip-unit">股</span>
        <button class="chip-del" data-del="${esc(chipKey(p))}" title="移除">×</button>
      </div>`).join('');
  }

  function addPosition(p) {
    const key = chipKey(p);
    if (positions.some((x) => chipKey(x) === key)) {
      const input = document.querySelector(`[data-shares="${key}"]`);
      if (input) { input.focus(); input.select(); }
      return;
    }
    positions.push({
      code: p.code,
      market: p.market || 'cn',
      name: p.name,
      shares: p.shares || 1000,
      cost: p.cost == null ? '' : p.cost,
      buy_date: p.buy_date || defaultBuyDate(),
      tax_rate: p.tax_rate == null ? '' : p.tax_rate,
    });
    renderChips();
    renderHoldingsEditor();
    scheduleCalendarRefresh();
    const input = document.querySelector(`[data-shares="${CSS.escape(key)}"]`);
    if (input && !p.silent) { input.focus(); input.select(); }
  }

  /* ---------------- 持仓明细：成本（选填）/ 买入日 / 税率覆盖 ---------------- */
  function updateHoldingsSummary() {
    const summary = document.getElementById('holdings-summary');
    if (!summary) return;
    if (!positions.length) {
      summary.textContent = '持仓明细：成本（选填）/ 买入日 / 税率覆盖';
      return;
    }
    const n = positions.length;
    const noCost = positions.filter((p) => p.cost === '' || p.cost == null).length;
    const cls = noCost ? 'warn' : 'ok';
    summary.innerHTML = `持仓明细：成本（选填）/ 买入日 / 税率覆盖
      <span class="badge ${cls}">成本 ${n - noCost}/${n}（选填）</span>`;
  }

  function renderHoldingsEditor() {
    const box = document.getElementById('holdings-editor');
    if (!box) return;
    updateHoldingsSummary();
    if (!positions.length) {
      box.innerHTML = '<div class="muted" style="font-size:12.5px">先添加股票。</div>';
      return;
    }
    const rows = positions.map((p, i) => {
      const mkt = marketOf(p);
      let taxPct = '';
      if (p.tax_rate !== '' && p.tax_rate != null) {
        const n = Number(p.tax_rate);
        if (isFinite(n)) taxPct = String(Number((n * 100).toFixed(4)));
      }
      return `
        <tr>
          <td class="sym-cell"><span class="chip-mkt mkt-${mkt}">${mktLabel(mkt)}</span> ${esc(p.code)}</td>
          <td>${esc(p.name || '')}</td>
          <td class="num"><input class="input-sm num" data-idx="${i}" data-field="shares"
                 inputmode="numeric" value="${esc(p.shares)}" style="width:88px"></td>
          <td class="num"><input class="input-sm num" data-idx="${i}" data-field="cost"
                 inputmode="decimal" value="${esc(p.cost)}" placeholder="${mkt === 'hk' ? 'HKD' : '元'}" style="width:88px"></td>
          <td><input class="input-sm" type="date" data-idx="${i}" data-field="buy_date"
                 value="${esc(p.buy_date || '')}" style="width:140px"></td>
          <td class="num"><input class="input-sm num" data-idx="${i}" data-field="tax_rate"
                 inputmode="decimal" value="${taxPct}" placeholder="自动" style="width:76px"></td>
          <td><button class="link" data-del-idx="${i}" title="移除">×</button></td>
        </tr>`;
    }).join('');
    box.innerHTML = `
      <div class="toolbar holdings-bulk">
        <label>全部买入日 <input type="date" id="bulk-buy-date"></label>
        <label class="switch"><input type="checkbox" id="bulk-buy-only-empty" checked> 仅填空白</label>
        <button class="ghost" id="bulk-buy-apply">应用</button>
        <span class="muted">|</span>
        <label>全部税率 <input type="number" id="bulk-tax-rate" min="0" max="100" step="0.1"
               placeholder="如 20" style="width:74px"> %</label>
        <button class="ghost" id="bulk-tax-apply">应用</button>
        <button class="ghost" id="bulk-tax-clear">清空覆盖</button>
      </div>
      <div class="table-scroll">
        <table class="holdings-table">
          <thead><tr>
            <th>代码</th><th>名称</th><th class="num">股数</th><th class="num">成本价 <span class="muted">(选填)</span></th>
            <th>买入日期</th><th class="num">税率覆盖 %</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="muted" style="font-size:11.5px;margin-top:6px">
        成本价选填（按报价币种，港股 HKD），填了才有成本股息率与浮盈；
        买入日期默认今年 1 月 1 日，用于按持有时长估红利税；
        税率覆盖留空 = 按规则自动（A 股按持有期，港股默认 20%）。
      </div>`;
    bindHoldingsBulk();
  }

  function bindHoldingsBulk() {
    const buyApply = document.getElementById('bulk-buy-apply');
    if (buyApply) {
      buyApply.onclick = () => {
        const day = document.getElementById('bulk-buy-date').value;
        if (!day) return;
        const onlyEmpty = document.getElementById('bulk-buy-only-empty').checked;
        positions.forEach((p) => {
          if (!onlyEmpty || !p.buy_date) p.buy_date = day;
        });
        renderHoldingsEditor();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      };
    }
    const taxApply = document.getElementById('bulk-tax-apply');
    if (taxApply) {
      taxApply.onclick = () => {
        const raw = document.getElementById('bulk-tax-rate').value;
        if (raw === '') return;
        const rate = Number(raw);
        if (!isFinite(rate)) return;
        positions.forEach((p) => { p.tax_rate = rate / 100; });
        renderHoldingsEditor();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      };
    }
    const taxClear = document.getElementById('bulk-tax-clear');
    if (taxClear) {
      taxClear.onclick = () => {
        positions.forEach((p) => { p.tax_rate = ''; });
        renderHoldingsEditor();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      };
    }
  }

  function syncChipShares(idx, value) {
    const p = positions[idx];
    if (!p) return;
    const input = document.querySelector(`[data-shares="${CSS.escape(chipKey(p))}"]`);
    if (input) input.value = value;
  }

  function syncHoldingShares(idx, value) {
    const input = document.querySelector(
      `#holdings-editor [data-idx="${idx}"][data-field="shares"]`);
    if (input) input.value = value;
  }

  /* ---------------- 搜索联想 ---------------- */
  let debounceTimer = null;
  let dropdown = null;

  function closeDropdown() {
    if (dropdown) { dropdown.remove(); dropdown = null; }
  }

  function buildDropdown(anchor) {
    closeDropdown();
    dropdown = document.createElement('div');
    dropdown.className = 'sym-dropdown';
    anchor.appendChild(dropdown);
    return dropdown;
  }

  function pick(item) {
    addPosition({ code: item.code, name: item.name, market: item.market || currentMarket });
    const input = document.getElementById('sym-search');
    input.value = '';
    closeDropdown();
    input.focus();
  }

  async function query(q) {
    try {
      const resp = await fetch('/api/symbols?q=' + encodeURIComponent(q)
                               + '&market=' + currentMarket);
      const data = await resp.json();
      const results = data.results || [];
      const box = buildDropdown(document.getElementById('search-box'));
      if (!results.length) {
        box.innerHTML = '<div class="sym-empty">无匹配；A 股可直接回车输入 6 位代码</div>';
        return;
      }
      const asOf = data.as_of ? `<div class="sym-fresh">代码目录快照 ${data.as_of}</div>` : '';
      box.innerHTML = results.map((it, i) => `
        <div class="sym-item${i === 0 ? ' active' : ''}" data-i="${i}">
          <span class="sym-code">${esc(it.code)}</span>
          <span class="sym-name">${esc(it.name)}</span>
        </div>`).join('') + asOf;
      box.querySelectorAll('.sym-item').forEach((el) => {
        el.addEventListener('mousedown', (e) => {
          e.preventDefault();
          pick(results[Number(el.getAttribute('data-i'))]);
        });
      });
    } catch (_) { /* 搜索失败静默 */ }
  }

  /* ---------------- 结果渲染 ---------------- */
  function renderKpis(d) {
    const kpis = [
      { label: '组合总市值', value: fmtMoney(d.total_market_value),
        sub: d.fx_note ? 'CNY 折算 · 含港股' : 'CNY', cls: '' },
      { label: '组合年股息', value: fmtMoney(d.total_dividend),
        sub: 'CNY', cls: 'accent' },
      { label: '组合股息率 · 市值加权', value: fmtPct(d.portfolio_yield), cls: 'accent' },
      { label: '成本股息率', value: fmtPct(d.portfolio_cost_yield),
        sub: '总年息 ÷ 总成本 · 只汇总有成本的标的', cls: d.portfolio_cost_yield != null ? 'accent' : '' },
      { label: '组合总利润', value: fmtMoney(d.total_profit),
        sub: 'CNY · 财报币种折算', cls: '' },
      { label: '浮动盈亏', value: fmtSignedMoney(d.portfolio_pnl),
        sub: 'CNY · 只汇总有成本的标的', cls: '' }
    ];
    return `<div class="kpis">` + kpis.map((k) => `
      <div class="kpi ${k.cls}">
        <div class="label">${esc(k.label)}</div>
        <div class="value">${k.value}</div>
        ${k.sub ? `<div class="sub">${esc(k.sub)}</div>` : ''}
      </div>`).join('') + `</div>`;
  }

  function renderTable(d) {
    const rows = d.rows.map((r) => `
      <tr>
        <td><span class="chip-mkt mkt-${r.market || 'cn'}">${mktLabel(r.market)}</span> ${esc(r.code)}</td>
        <td>${r.name ? esc(r.name) : DASH}${r.market === 'hk' ? ' <span class="currency-tag">HKD</span>' : ''}${r.price_estimated ? ' <span class="badge warn">估价</span>' : ''}</td>
        <td class="num">${fmtInt(r.shares)}</td>
        <td class="num">${fmtPriceCcy(r.price, r.currency)}</td>
        <td class="num">${fmtMoneyCcy(r.market_value, r.currency)}</td>
        <td class="num">${fmtPct(r.weight, 1)}</td>
        <td class="num">${fmtPrice(r.eps_ttm)}${r.market === 'hk' && r.eps_ttm != null ? ' <span class="currency-tag">CNY</span>' : ''}</td>
        <td class="num">${fmtPriceCcy(r.dps_ttm, r.currency)}</td>
        <td class="num strong">${fmtPct(r.div_yield)}</td>
        <td class="num strong">${fmtPct(r.cost_yield)}</td>
        <td class="num">${fmtPct(r.payout, 1)}${r.market === 'hk' && r.payout != null ? ' <span class="currency-tag">待核验</span>' : ''}</td>
        <td class="num">${fmtMoneyCcy(r.annual_dividend, r.currency)}</td>
        <td class="num">${fmtSigned(r.pnl_ratio)}</td>
        <td>${r.missing && r.missing.length
            ? r.missing.map((m) => `<span class="badge warn">${esc(m)}</span>`).join(' ')
            : '<span class="muted">·</span>'}</td>
        <td class="cell-action"><button class="btn-analyze" data-diagnose-code="${esc(r.code)}" title="分红持续性分析"><svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析</button></td>
      </tr>`).join('');

    return `<div class="table-scroll"><table class="xray-table">
      <thead><tr>
        <th>代码</th><th>名称</th><th class="num">持股</th><th class="num">现价</th>
        <th class="num">市值(原币)</th><th class="num">占比</th><th class="num">每股利润</th>
        <th class="num">每股股息</th><th class="num">股息率</th><th class="num">成本股息率</th><th class="num" title="现金分红 ÷ 归母净利润">分红率(TTM)</th>
        <th class="num">持仓年息(原币)</th><th class="num">浮动</th><th>数据说明</th><th>分析</th>
      </tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr>
        <td colspan="4">合计（${esc(d.total_currency || 'CNY')}）</td>
        <td class="num">${fmtMoney(d.total_market_value)}</td>
        <td class="num">100%</td>
        <td class="num">${DASH}</td>
        <td class="num">${DASH}</td>
        <td class="num">${fmtPct(d.portfolio_yield)}</td>
        <td class="num">${fmtPct(d.portfolio_cost_yield)}</td>
        <td class="num">${DASH}</td>
        <td class="num">${fmtMoney(d.total_dividend)}</td>
        <td class="num">${fmtSigned(d.portfolio_pnl_ratio)}</td>
        <td></td>
        <td></td>
      </tr></tfoot></table></div>
      ${d.fx_note ? `<div class="muted" style="font-size:12px;margin-top:8px">${esc(d.fx_note)}</div>` : ''}`;
  }

  function renderStability(d) {
    const s = d.stability || {};
    const buckets = Object.keys(s.payout_buckets || {}).map((k) => `
      <div class="bucket"><div class="n">${s.payout_buckets[k]}</div><div class="k">${esc(k)}</div></div>`).join('');
    const parts = [];
    parts.push(`<div class="bucket"><div class="n">${s.cr3 != null ? (s.cr3 * 100).toFixed(0) + '%' : '—'}</div>
      <div class="k">股息集中度 CR3${s.cr3_codes && s.cr3_codes.length ? '<br>' + esc(s.cr3_codes.join('、')) : ''}</div></div>`);
    if (s.stable_years_cover != null) {
      parts.push(`<div class="bucket"><div class="n">${(s.stable_years_cover * 100).toFixed(0)}%</div>
        <div class="k">连续分红≥5年<br>市值占比</div></div>`);
    }
    parts.push(`<div class="bucket"><div class="n">${esc(d.completeness)}</div>
      <div class="k">数据完整度</div></div>`);
    return `
      <div class="card">
        <div class="card-head"><h2>派息稳定性看板</h2>
          <span class="hint">描述性统计，不构成任何操作建议</span></div>
        <div class="buckets">${parts.join('')}</div>
        ${buckets ? `<div class="card-head" style="margin:18px 0 10px">
          <h2 style="font-size:13px">分红率分档（现金分红 ÷ 归母净利润）</h2></div><div class="buckets">${buckets}</div>` : ''}
        ${(s.warnings && s.warnings.length) ? `<ul class="notes" style="margin-top:16px">
          ${s.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
        ${(d.notes && d.notes.length) ? `<ul class="notes" style="margin-top:12px;color:var(--text-3)">
          ${d.notes.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : ''}
      </div>`;
  }

  /* ---------------- 分红质量卡 ---------------- */
  async function openQuality() {
    const panel = document.getElementById('quality-panel');
    if (!panel) return;
    if (!positions.length) {
      panel.innerHTML = '<div class="card"><div class="empty">先添加持仓再分析</div></div>';
      return;
    }
    panel.innerHTML = `<div class="card">
      <div class="card-head"><h2>分红质量分析</h2>
        <span class="hint">每票 1 次指标 + 每市场 1 次分红历史；约 10–30 秒，5 分钟缓存</span></div>
      ${Array(5).fill('<div class="skeleton" style="margin:9px 0"></div>').join('')}
    </div>`;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const d = await api('dividend-quality', {
        positions: positions.map(calendarPositionPayload),
      });
      renderQuality(panel, d);
    } catch (e) {
      panel.innerHTML = `<div class="card"><div class="error"><strong>分红质量取数失败：</strong>${esc(e.message)}</div></div>`;
    }
  }

  function abilityBand(score) {
    if (score == null) return { label: '—', cls: '' };
    if (score >= 80) return { label: '强', cls: 'ok' };
    if (score >= 60) return { label: '中', cls: 'ok' };
    if (score >= 40) return { label: '偏弱', cls: 'warn' };
    return { label: '弱', cls: 'warn' };
  }

  function confidenceLabel(c) {
    return { high: '高', medium: '中', low: '低' }[c] || c || '—';
  }

  function renderQuality(panel, d) {
    const s = d.summary || {};
    const skipped = (s.skipped || []).length;
    const kpis = [
      { label: '可评分标的', value: `${s.scored_count || 0} / ${s.eligible_count || 0}`,
        sub: skipped ? `另 ${skipped} 只暂不评分` : 'A 股非金融' },
      { label: '平均支付能力', value: s.avg_ability != null ? String(s.avg_ability) : '—',
        sub: s.avg_ability != null ? abilityBand(s.avg_ability).label : '—' },
      { label: '分红意愿', value: ['A', 'B', 'C', 'D'].map((g) =>
          `${g}:${s.willingness?.[g] || 0}`).join(' '),
        sub: '连续性 / 趋势 / 资本动作' },
      { label: '覆盖不足', value: String(s.coverage_thin || 0),
        sub: 'FCF 或 OCF 覆盖 < 1' },
      { label: '高股息陷阱', value: String(s.yield_trap || 0),
        sub: '股息率 ≥ 6% 且支付能力 < 50' },
      { label: '平均分红率(TTM)', value: fmtPct(s.avg_payout_ttm, 1),
        sub: `平均 OCF 覆盖 ${s.avg_ocf_cover != null ? s.avg_ocf_cover.toFixed(2) + 'x' : '—'}` },
    ];
    const rows = (d.rows || []).map((r, i) => {
      const band = abilityBand(r.ability_score);
      const flags = (r.flags || []).map((f) => `<span class="badge warn">${esc(f)}</span>`).join(' ');
      return `
      <tr class="quality-row" data-q-idx="${i}">
        <td><span class="chip-mkt mkt-${r.market || 'cn'}">${mktLabel(r.market)}</span> ${esc(r.code)}</td>
        <td>${esc(r.name)}${r.org_form ? ` <span class="currency-tag">${esc(r.org_form)}</span>` : ''}</td>
        <td class="num">${fmtPct(r.yield_ttm)}</td>
        <td class="num">${fmtPct(r.payout_ttm, 1)}</td>
        <td class="num">${fmtPct(r.payout_lyr, 1)}</td>
        <td class="num">${fmtPct(r.payout_3y_avg, 1)}</td>
        <td class="num">${esc(r.payout_trend == null ? '—'
          : { up: '↑', down: '↓', flat: '→' }[r.payout_trend] || r.payout_trend)}</td>
        <td class="num">${r.consecutive_years == null ? DASH : r.consecutive_years + ' 年'}</td>
        <td class="num">${r.ocf_cover == null ? (r.eligible ? DASH : 'N/A') : r.ocf_cover.toFixed(2) + 'x'}</td>
        <td class="num">${r.fcf_cover == null ? (r.org_type === 1 ? DASH : 'N/A') : r.fcf_cover.toFixed(2) + 'x'}</td>
        <td class="num">${fmtPct(r.tl_rate, 1)}</td>
        <td>${r.eligible
          ? `<span class="badge ${band.cls}">${band.label} ${r.ability_score}</span>`
          : `<span class="badge">暂不评分</span>`}</td>
        <td>${r.willingness_grade
          ? `<span class="badge ${r.willingness_grade === 'A' || r.willingness_grade === 'B' ? 'ok' : 'warn'}">${r.willingness_grade}</span>`
          : DASH}</td>
        <td>${r.eligible
          ? `<span class="muted">${confidenceLabel(r.confidence)}</span>${flags ? '<br>' + flags : ''}`
          : `<span class="muted">${esc(r.reason || '')}</span>`}
          <button class="btn-analyze" data-diagnose-code="${esc(r.code)}" title="分红持续性分析"><svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析</button></td>
      </tr>
      <tr class="quality-detail" data-qd-idx="${i}" style="display:none">
        <td colspan="14">${renderQualityDetail(r)}</td>
      </tr>`;
    }).join('');

    panel.innerHTML = `<div class="card">
      <div class="card-head"><h2>分红质量分析</h2>
        <span class="hint">只对 A 股非金融评分；点击行展开分项与近 5 年明细</span></div>
      <div class="kpis">${kpis.map((k) => `
        <div class="kpi"><div class="label">${esc(k.label)}</div>
          <div class="value">${k.value}</div>
          <div class="sub">${esc(k.sub)}</div></div>`).join('')}</div>
      <div class="table-scroll" style="margin-top:14px"><table class="quality-table">
        <thead><tr>
          <th>代码</th><th>名称</th><th class="num">股息率</th>
          <th class="num">分红率(TTM)</th><th class="num">分红率(财年)</th>
          <th class="num">3年均值</th><th class="num">趋势</th><th class="num">连续分红</th>
          <th class="num">OCF覆盖</th><th class="num">FCF覆盖</th><th class="num">资产负债率</th>
          <th>支付能力</th><th>分红意愿</th><th>说明</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      ${(d.notes || []).length ? `<ul class="notes" style="margin-top:12px">${d.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
    </div>`;
    panel.querySelectorAll('.quality-row').forEach((tr) => {
      tr.onclick = (e) => {
        if (e.target && e.target.getAttribute &&
            e.target.getAttribute('data-diagnose-code')) return;
        const i = tr.getAttribute('data-q-idx');
        const detail = panel.querySelector(`[data-qd-idx="${i}"]`);
        if (detail) detail.style.display = detail.style.display === 'none' ? '' : 'none';
      };
    });
    panel.querySelectorAll('[data-diagnose-code]').forEach((btn) => {
      btn.onclick = () => {
        openDiagnoseModal(btn.getAttribute('data-diagnose-code'));
      };
    });
  }

  function renderQualityDetail(r) {
    const bands = r.ability_bands || {};
    const bandLine = (key, label, weight) => {
      const b = bands[key] || {};
      const notes = [b.band, b.vs_industry, b.mix, b.note, b.cf_np_penalty,
        b.trend_penalty, b.ibd_penalty, b.quick_penalty, b.ocf_min,
        b.np_decline].filter(Boolean).join('；');
      return `<li><strong>${esc(label)}</strong>（${weight}）：${esc(notes || '—')}</li>`;
    };
    const recurring = (r.recurring_by_year || []).map((y) =>
      `<tr><td>${y.year}</td><td class="num">${fmtPrice(y.dps)}</td>
       <td class="num">${y.count}</td><td>${y.special ? '<span class="badge warn">含特别</span>' : '·'}</td></tr>`).join('');
    const specials = (r.specials || []).map((sp) =>
      `<span class="badge warn">${sp.year} ${esc(sp.kind || '特别')} ${fmtPrice(sp.dps)}</span>`).join(' ') || '—';
    const missing = (r.missing || []).map((m) => `<span class="badge warn">${esc(m)}</span>`).join(' ') || '无';
    return `<div class="quality-detail-body">
      <div class="quality-cols">
        <div>
          <h4>支付能力分项（权重公开可复现）</h4>
          <ul class="notes">
            ${bandLine('cash', '现金流覆盖', '35%')}
            ${bandLine('payout', '分红率纪律', '25%')}
            ${bandLine('debt', '资产负债', '20%')}
            ${bandLine('stability', '盈利稳定性', '20%')}
          </ul>
          <h4>覆盖计算</h4>
          <ul class="notes">
            <li>归母净利 TTM ${fmtMoney(r.npts_ttm)} · 经营现金流 ${fmtMoney(r.ncfo_ttm)} · FCF ${r.fcf_ttm == null ? 'N/A' : fmtMoney(r.fcf_ttm)}</li>
            <li>盈利覆盖 ${r.earnings_cover == null ? '—' : r.earnings_cover.toFixed(2) + 'x'} ·
                现金转化 OCF/NP ${r.cash_conversion == null ? '—' : r.cash_conversion.toFixed(2)} ·
                资本开支占比 ${r.capex_ratio == null ? '—' : fmtPct(r.capex_ratio, 0)}</li>
            <li>ROE ${fmtPct(r.roe, 1)} · ROIC ${fmtPct(r.roic, 1)} · 净利同比 ${fmtSigned(r.npts_yoy)}</li>
            <li>有息负债率 ${fmtPct(r.ibd_rate, 1)} · 速动 ${r.quick == null ? '—' : r.quick.toFixed(2)}</li>
          </ul>
        </div>
        <div>
          <h4>近 5 年经常性每股分红（特别分红另列）</h4>
          <table><thead><tr><th>年度</th><th class="num">每股(元)</th>
            <th class="num">笔数</th><th>口径</th></tr></thead>
          <tbody>${recurring || '<tr><td colspan="4" class="muted">无记录</td></tr>'}</tbody></table>
          <div style="margin-top:6px">特别分红：${specials}</div>
          <h4 style="margin-top:12px">股本结构（仅展示）</h4>
          <ul class="notes">
            <li>前十大流通股东合计 ${fmtPct(r.free_holder_sum, 1)} · 管理层持股 ${fmtPct(r.exec_hold, 1)}</li>
            <li>近 6 个月回购：${r.has_buyback == null ? '—' : (r.has_buyback ? '有' : '无')}</li>
            <li class="muted">实控人/机构/北向/质押：SDK 暂无稳定数据，未纳入</li>
          </ul>
          <h4 style="margin-top:12px">数据说明</h4>
          <div>${missing}</div>
        </div>
      </div>
    </div>`;
  }

  /* ---------------- 分红日历 / 收息驾驶舱 ---------------- */
  const calendarPositionPayload = (p) => ({
    code: p.code,
    market: marketOf(p),
    name: p.name,
    shares: p.shares,
    cost: p.cost,
    buy_date: p.buy_date || '',
    tax_rate: (p.tax_rate === '' || p.tax_rate == null) ? null : Number(p.tax_rate),
  });

  function setAutoNote(html) {
    const note = document.getElementById('auto-load-note');
    if (note) note.innerHTML = html;
  }

  function renderCalendarShell() {
    const panel = document.getElementById('calendar-panel');
    if (!panel) return;
    panel.innerHTML = `
      <div class="card calendar-card">
        <div class="card-head">
          <h2>分红日历</h2>
          <span class="hint">未来除权/到账与分红金额；预案单独标注。税后测算在「记账」</span>
          <span class="spacer"></span>
          <button class="ghost" id="calendar-refresh" style="padding:4px 10px;font-size:12.5px">刷新</button>
        </div>
        <div class="toolbar calendar-tabs" id="calendar-tabs">
          <button data-horizon="7">今天 / 本周</button>
          <button data-horizon="30" class="active">未来 30 天</button>
          <button data-horizon="90">未来 90 天</button>
          <button data-horizon="365">未来 12 个月</button>
          <span class="spacer"></span>
          <button class="ghost" data-pool="cn">高股息池 · A 股</button>
          <button class="ghost" data-pool="hk">高股息池 · 港股</button>
          <button class="ghost" id="calendar-back" style="display:none">回到我的持仓</button>
        </div>
        <div id="calendar-body"></div>
      </div>`;
    bindCalendarControls();
  }

  /* ---------------- 分红持续性分析（每票按钮 → 可视化弹层） ---------------- */
  function bindDiagnoseButtons(root) {
    (root || document).querySelectorAll('[data-diagnose-code]').forEach((btn) => {
      if (btn.dataset.diagBound) return;
      btn.dataset.diagBound = '1';
      btn.onclick = () => openDiagnoseModal(btn.getAttribute('data-diagnose-code'));
    });
  }

  let diagModalOpen = false;

  function openDiagnoseModal(code) {
    if (!code) return;
    let overlay = document.getElementById('diag-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'diag-overlay';
      overlay.className = 'diag-overlay';
      document.body.appendChild(overlay);
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeDiagnoseModal();
      });
    }
    diagModalOpen = true;
    overlay.innerHTML = `
      <div class="diag-modal card" role="dialog" aria-modal="true">
        <div class="card-head">
          <h2>分红持续性分析</h2>
          <span class="hint" id="diag-modal-sub">${esc(code)} · 取数中…</span>
          <span class="spacer"></span>
          <button class="ghost" id="diag-close" style="padding:4px 10px">关闭</button>
        </div>
        <div id="diag-modal-body">
          ${Array(5).fill('<div class="skeleton" style="margin:9px 0"></div>').join('')}
        </div>
      </div>`;
    document.getElementById('diag-close').onclick = closeDiagnoseModal;
    document.body.style.overflow = 'hidden';
    api('diagnose', { code }).then((d) => {
      if (!diagModalOpen) return;
      renderDiagnoseModal(d);
    }).catch((e) => {
      const body = document.getElementById('diag-modal-body');
      if (body && diagModalOpen) {
        body.innerHTML = `<div class="error"><strong>分析失败：</strong>${esc(e.message)}</div>`;
      }
    });
  }

  function closeDiagnoseModal() {
    diagModalOpen = false;
    document.body.style.overflow = '';
    const overlay = document.getElementById('diag-overlay');
    if (overlay) overlay.remove();
  }

  const ORG_TYPE_LABEL = { 1: '一般企业', 2: '银行', 3: '保险', 4: '证券' };

  function diagAbilityBars(r) {
    const bands = r.ability_bands || {};
    const items = [
      { key: 'cash', label: '现金流覆盖', weight: 35 },
      { key: 'payout', label: '分红率纪律', weight: 25 },
      { key: 'debt', label: '资产负债', weight: 20 },
      { key: 'stability', label: '盈利稳定性', weight: 20 },
    ];
    return `<div class="diag-bars">${items.map((it) => {
      const b = bands[it.key] || {};
      // 分项条按得分率填充（得分/权重），缺失时不填充
      const hasScore = b.score != null && b.weight;
      const pct = hasScore ? Math.max(0, Math.min(100, (b.score / b.weight) * 100)) : 0;
      const cls = !hasScore ? '' : (pct >= 70 ? 'good' : (pct >= 40 ? 'ok' : 'bad'));
      const notes = [b.band, b.vs_industry, b.mix, b.note, b.cf_np_penalty,
        b.trend_penalty, b.ibd_penalty, b.quick_penalty, b.ocf_min,
        b.np_decline].filter(Boolean).join('；');
      return `<div class="diag-bar-row">
        <div class="diag-bar-label">${esc(it.label)} <span class="muted">${it.weight}%</span></div>
        <div class="diag-bar-track">
          ${hasScore ? `<span class="diag-bar-fill ${cls}" style="width:${pct}%"></span>` : ''}
        </div>
        <div class="diag-bar-score">${hasScore ? `${b.score} / ${b.weight}` : '缺数据'}</div>
        <div class="diag-bar-note">${esc(notes || '—')}</div>
      </div>`;
    }).join('')}</div>`;
  }

  function diagPayoutChart(r) {
    const series = r.payout_series || [];
    const recurring = r.recurring_by_year || [];
    const dpsByYear = {};
    recurring.forEach((it) => { dpsByYear[it.year] = it.dps; });
    const years = [];
    const seen = new Set();
    series.forEach((p) => { if (!seen.has(p.year)) { seen.add(p.year); years.push(p.year); } });
    recurring.forEach((it) => { if (!seen.has(it.year)) { seen.add(it.year); years.push(it.year); } });
    years.sort((a, b) => a - b);
    const shown = years.slice(-6);
    if (!shown.length) return '';
    const maxPayout = Math.max(0.001, ...series.map((p) => p.payout || 0));
    const maxDps = Math.max(0.001, ...shown.map((y) => dpsByYear[y] || 0));
    const cols = shown.map((y) => {
      const payout = (series.find((p) => p.year === y) || {}).payout;
      const dps = dpsByYear[y];
      const ph = payout != null ? Math.max(4, (payout / maxPayout) * 100) : 0;
      const dh = dps != null ? Math.max(4, (dps / maxDps) * 100) : 0;
      return `<div class="diag-col">
        <div class="diag-col-bars">
          <div class="diag-col-bar payout" style="height:${ph}%">
            <span class="diag-col-val">${payout != null ? Math.round(payout * 100) + '%' : ''}</span></div>
          <div class="diag-col-bar dps" style="height:${dh}%">
            <span class="diag-col-val">${dps != null ? dps.toFixed(2) : ''}</span></div>
        </div>
        <div class="diag-col-year">${y}</div>
      </div>`;
    }).join('');
    return `<h4 class="diag-sec">近 5 年分红（蓝=分红率，绿=每股分红元）</h4>
      <div class="diag-chart">${cols}</div>
      ${(r.specials || []).length ? `<div class="muted" style="font-size:11.5px;margin-top:6px">
        特别分红（不计入经常性口径）：${r.specials.map((sp) =>
          `${sp.year} ${esc(sp.kind || '特别')} ${fmtPrice(sp.dps)}`).join('、')}</div>` : ''}`;
  }

  function diagCoverageBars(r) {
    const rows = [
      { label: 'OCF 覆盖', value: r.ocf_cover, hint: '经营现金流 ÷ 分红' },
      { label: 'FCF 覆盖', value: r.fcf_cover, hint: '自由现金流 ÷ 分红' },
    ];
    return `<h4 class="diag-sec">股息覆盖（1.0x = 分红刚好被现金流覆盖）</h4>
      <div class="diag-cov">${rows.map((it) => {
        if (it.value == null) {
          return `<div class="diag-cov-row">
            <div class="diag-bar-label">${esc(it.label)}</div>
            <div class="muted" style="font-size:12px">N/A${r.org_type !== 1 ? '（金融股不适用）' : ''}</div>
          </div>`;
        }
        const capped = Math.min(it.value, 2.5);
        const pct = (capped / 2.5) * 100;
        const mark = (1.0 / 2.5) * 100;
        const cls = it.value >= 1.5 ? 'good' : (it.value >= 1.0 ? 'ok' : 'bad');
        return `<div class="diag-cov-row">
          <div class="diag-bar-label">${esc(it.label)}</div>
          <div class="diag-cov-track">
            <span class="diag-cov-fill ${cls}" style="width:${pct}%"></span>
            <span class="diag-cov-mark" style="left:${mark}%"></span>
          </div>
          <div class="diag-cov-val ${it.value < 1 ? 'bad-text' : ''}">${it.value.toFixed(2)}x</div>
          <div class="muted" style="font-size:11px">${esc(it.hint)}</div>
        </div>`;
      }).join('')}</div>`;
  }

  function renderDiagnoseModal(d) {
    const body = document.getElementById('diag-modal-body');
    const sub = document.getElementById('diag-modal-sub');
    if (!body) return;
    const p = d.profile || {};
    const q = d.quote || {};
    const r = d.quality || {};
    const band = abilityBand(r.ability_score);
    if (sub) sub.textContent = `${d.code}${p.name ? ' · ' + p.name : ''}`;
    const orgForm = p.org_form
      || (d.market === 'hk' ? '—（港股暂无该标签）' : '—');

    const headHtml = `
      <div class="kpis">
        <div class="kpi"><div class="label">股票</div>
          <div class="value" style="font-size:16px">${esc(p.name || d.code)}
            <span class="chip-mkt mkt-${d.market}">${mktLabel(d.market)}</span></div>
          <div class="sub">${esc(d.code)} · 现价 ${fmtPriceCcy(q.price, q.currency)}</div></div>
        <div class="kpi"><div class="label">企业类型</div>
          <div class="value" style="font-size:16px">${esc(orgForm)}</div>
          <div class="sub">${p.industry ? esc(p.industry) + ' · ' : ''}${esc(ORG_TYPE_LABEL[p.org_type] || '')}</div></div>
        <div class="kpi"><div class="label">股息率 / 分红率(TTM)</div>
          <div class="value" style="font-size:16px">${fmtPct(q.yield_ttm)} / ${fmtPct(q.payout_ttm, 1)}
            ${d.market === 'hk' && q.payout_ttm != null ? '<span class="currency-tag">待核验</span>' : ''}</div>
          <div class="sub">上市 ${p.listing_date || '—'}</div></div>
        <div class="kpi"><div class="label">支付能力 / 分红意愿</div>
          <div class="value" style="font-size:16px">${r.eligible && r.ability_score != null
            ? `${r.ability_score} <span class="badge ${band.cls}">${band.label}</span>` : DASH}
            ${r.willingness_grade ? `<span class="badge ${r.willingness_grade === 'A' || r.willingness_grade === 'B' ? 'ok' : 'warn'}">${r.willingness_grade}</span>` : ''}</div>
          <div class="sub">连续分红 ${r.consecutive_years == null ? DASH : r.consecutive_years + ' 年'}</div></div>
      </div>`;

    const flags = r.flags || [];
    const flagsHtml = flags.length
      ? `<div style="margin:10px 0">${flags.map((f) =>
          `<span class="badge warn">${esc(f)}</span>`).join(' ')}</div>` : '';

    let analysisHtml;
    if (r.eligible) {
      analysisHtml = diagAbilityBars(r) + diagCoverageBars(r) + diagPayoutChart(r) + `
        <div class="muted" style="font-size:11.5px;margin-top:10px">
          资产负债率 ${fmtPct(r.tl_rate, 1)}${r.tl_ind_avg ? `（行业均值 ${fmtPct(r.tl_ind_avg, 1)}）` : ''} ·
          ROE ${fmtPct(r.roe, 1)} · 现金转化 ${r.cash_conversion == null ? DASH : r.cash_conversion.toFixed(2)} ·
          置信度 ${confidenceLabel(r.confidence)}</div>`;
    } else {
      analysisHtml = `<div class="muted" style="margin-top:10px;font-size:12.5px">
        暂不评分：${esc(r.reason || '')}
        ${r.payout_ttm != null ? `· 分红率(TTM) ${fmtPct(r.payout_ttm, 1)}` : ''}
        ${r.tl_rate != null ? `· 资产负债率 ${fmtPct(r.tl_rate, 1)}` : ''}
        ${r.roe != null ? `· ROE ${fmtPct(r.roe, 1)}` : ''}
      </div>`;
    }

    const ev = d.next_event;
    const eventHtml = ev ? `
      <h4 class="diag-sec">下一次分红（观察口径）</h4>
      <div class="event-list">${eventRow(ev, { noAction: true })}</div>` : '';

    const notes = (d.notes || []).map((n) => `<li>${esc(n)}</li>`).join('');
    body.innerHTML = headHtml + flagsHtml + analysisHtml + eventHtml +
      (notes ? `<ul class="notes" style="margin-top:12px">${notes}</ul>` : '');
  }

  function bindCalendarControls() {
    const refresh = document.getElementById('calendar-refresh');
    if (refresh) refresh.onclick = () => loadCalendar(calendarMode);
    document.querySelectorAll('#calendar-tabs [data-horizon]').forEach((btn) => {
      btn.onclick = () => {
        calendarHorizon = Number(btn.getAttribute('data-horizon'));
        document.querySelectorAll('#calendar-tabs [data-horizon]')
          .forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        if (calendarData) renderCalendarBody(calendarData);
      };
    });
    document.querySelectorAll('#calendar-tabs [data-pool]').forEach((btn) => {
      btn.onclick = () => {
        calendarMarket = btn.getAttribute('data-pool');
        loadCalendar('market');
      };
    });
    const back = document.getElementById('calendar-back');
    if (back) back.onclick = () => loadCalendar('positions');
  }

  async function autoLoadPositions() {
    try {
      const d = await api('positions-latest');
      if (positions.length) return;   // 用户已经手动加了股票，别覆盖
      const set = d && d.set;
      if (set && Array.isArray(set.positions) && set.positions.length) {
        positions.length = 0;
        set.positions.forEach((p) => positions.push(normalizePosition(p)));
        renderChips();
        renderHoldingsEditor();
        setAutoNote(`已自动载入「${esc(set.name)}」 · ${positions.length} 只 · 更新于 ${esc(set.updated_at || '')}
          <button class="link" id="auto-load-other">换一份</button>
          <button class="link" id="auto-load-edit">编辑持仓</button>`);
        const other = document.getElementById('auto-load-other');
        if (other) other.onclick = showLoad;
        const edit = document.getElementById('auto-load-edit');
        if (edit) edit.onclick = () => {
          const card = document.getElementById('positions-card');
          if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
          const details = document.getElementById('holdings-details');
          if (details) details.open = true;
        };
        loadCalendar('positions');
        return;
      }
      // 首次使用：注入示例持仓（仅内存，不落库），让驾驶舱开箱即有内容
      seedDemoPosition();
    } catch (_) {
      // 接口失败（如 demo 无档案）也走示例持仓
      if (!positions.length) seedDemoPosition();
    }
  }

  function seedDemoPosition() {
    positions.length = 0;
    positions.push(normalizePosition({
      code: '600036', market: 'cn', name: '招商银行', shares: 1000,
    }));
    renderChips();
    renderHoldingsEditor();
    setAutoNote(`示例持仓：招商银行 · 1,000 股（仅本次会话）
      <button class="link" id="auto-load-edit">编辑持仓</button>`);
    const edit = document.getElementById('auto-load-edit');
    if (edit) edit.onclick = () => {
      const card = document.getElementById('positions-card');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const details = document.getElementById('holdings-details');
      if (details) details.open = true;
    };
    loadCalendar('positions');
  }

  function renderCalendarEmpty() {
    calendarMode = 'positions';
    calendarData = null;
    const body = document.getElementById('calendar-body');
    if (!body) return;
    body.innerHTML = `
      <div class="calendar-empty">
        <div>还没有持仓。先添加股票，或看看高股息池里即将除权的票。</div>
        <div class="toolbar">
          <button class="ghost" data-pool="cn">高股息池 · A 股</button>
          <button class="ghost" data-pool="hk">高股息池 · 港股</button>
          <button class="ghost" id="calendar-import-group">从关注分组导入</button>
        </div>
        <div class="muted" style="font-size:11.5px;margin-top:8px">
          高股息池只展示已公告事件，不构成投资建议。
        </div>
      </div>`;
    const back = document.getElementById('calendar-back');
    if (back) back.style.display = 'none';
    bindCalendarBodyActions();
  }

  async function loadCalendar(mode) {
    const body = document.getElementById('calendar-body');
    if (!body) return;
    if (mode === 'positions' && !positions.length) {
      renderCalendarEmpty();
      return;
    }
    calendarMode = mode;
    // 市场池刚在持仓空态里加载过 → 直接复用，避免重复等选股接口
    if (mode === 'market' && marketCalendarCache
        && (marketCalendarCache.data.market || 'cn') === calendarMarket
        && Date.now() - marketCalendarCache.at < 300000) {
      const cached = marketCalendarCache.data;
      calendarMarket = cached.market || calendarMarket;
      calendarData = cached;
      renderCalendarBody(cached);
      const back = document.getElementById('calendar-back');
      if (back) back.style.display = positions.length ? '' : 'none';
      return;
    }
    if (mode === 'market' && marketPreviewPromise
        && marketPreviewMarket === calendarMarket) {
      body.innerHTML = '<div class="skeleton" style="margin:8px 0"></div>'.repeat(4);
      const d = await marketPreviewPromise.catch(() => null);
      if (d) {
        calendarMarket = d.market || calendarMarket;
        calendarData = d;
        renderCalendarBody(d);
        const back = document.getElementById('calendar-back');
        if (back) back.style.display = positions.length ? '' : 'none';
        return;
      }
    }
    body.innerHTML = '<div class="skeleton" style="margin:8px 0"></div>'.repeat(4);
    let payload;
    if (mode === 'market') {
      payload = { mode: 'market', market: calendarMarket, limit: 120,
                  tax: ledgerTaxPayload() };
    } else if (mode === 'codes') {
      payload = { mode: 'codes', codes: calendarWatchlist || [],
                  tax: ledgerTaxPayload() };
    } else {
      payload = { mode: 'positions',
                  positions: positions.map(calendarPositionPayload),
                  tax: ledgerTaxPayload() };
    }
    try {
      const d = await api('calendar', payload);
      if (mode === 'market') {
        calendarMarket = d.market || calendarMarket;
        marketCalendarCache = { at: Date.now(), data: d };
      }
      calendarData = d;
      renderCalendarBody(d);
      const back = document.getElementById('calendar-back');
      if (back) back.style.display = (mode !== 'positions' && positions.length) ? '' : 'none';
    } catch (e) {
      const back = document.getElementById('calendar-back');
      if (back) back.style.display = (mode !== 'positions' && positions.length) ? '' : 'none';
      body.innerHTML = `<div class="error"><strong>日历取数失败：</strong>${esc(e.message)}
        <div style="margin-top:8px">高股息池不可用时，可以先导入关注分组或添加持仓。</div>
        <div class="toolbar" style="margin-top:8px">
          <button class="ghost" data-pool="cn">高股息池 · A 股</button>
          <button class="ghost" data-pool="hk">高股息池 · 港股</button>
          <button class="ghost" id="calendar-import-group">从关注分组导入</button>
        </div></div>`;
      bindCalendarBodyActions();
    }
  }

  function scheduleCalendarRefresh() {
    if (calendarMode !== 'positions') return;
    clearTimeout(calendarTimer);
    calendarTimer = setTimeout(() => {
      if (!positions.length) {
        renderCalendarEmpty();
        return;
      }
      loadCalendar('positions');
    }, 500);
  }

  function renderCalendarBody(d) {
    const body = document.getElementById('calendar-body');
    if (!body) return;
    const futureStages = new Set(['待除权', '已除权待到账', '预案待定']);
    const hasFuture = (d.events || []).some(
      (e) => futureStages.has(e.stage) && eventInHorizon(e, calendarHorizon));
    const needPreview = d.mode === 'positions' && !hasFuture;
    const eventHtml = needPreview
      ? `<div class="muted" style="font-size:12.5px;margin:8px 0 0">
           你的持仓未来 ${calendarHorizon} 天没有已公告的分红事件；下面是市场高股息池的即将分红/预案。
         </div>`
      : renderCalendarEvents(d);
    const marketHint = d.mode !== 'positions'
      ? `<div class="muted" style="font-size:11.5px;margin-top:8px">
           市场视图来自平台高股息选股池（股息率 ≥ 3%），只展示其中已公告的分红事件，不是全市场逐票扫描。
         </div>`
      : '';
    body.innerHTML = marketHint + eventHtml +
      (needPreview ? '<div id="calendar-market-preview" class="market-preview"></div>' : '');
    bindCalendarBodyActions();
    if (needPreview) ensureMarketPreview();
  }

  function ensureMarketPreview() {
    const box = document.getElementById('calendar-market-preview');
    if (!box) return;
    const markets = new Set(positions.map((p) => marketOf(p)));
    const previewMarket = (markets.size === 1 && markets.has('hk')) ? 'hk' : 'cn';
    calendarMarket = previewMarket;
    marketPreviewMarket = previewMarket;
    if (marketCalendarCache
        && (marketCalendarCache.data.market || 'cn') === previewMarket) {
      renderMarketPreview(box, marketCalendarCache.data);
      return;
    }
    if (!marketPreviewPromise) {
      box.innerHTML = `<div class="skeleton" style="margin:8px 0"></div>
        <div class="skeleton" style="margin:8px 0"></div>
        <div class="muted" style="font-size:11.5px;margin-top:6px">
          正在查市场高股息池的即将分红/预案（首次约 10–25 秒，之后 10 分钟缓存）…
        </div>`;
      marketPreviewPromise = api('calendar', {
        mode: 'market', market: previewMarket, limit: 120,
        tax: ledgerTaxPayload(),
      }).then((d) => {
        marketCalendarCache = { at: Date.now(), data: d };
        return d;
      }).catch((e) => {
        const el = document.getElementById('calendar-market-preview');
        if (el) {
          el.innerHTML = `<div class="muted" style="font-size:12px">
            市场池加载失败：${esc(e.message)}
          </div>`;
        }
        return null;
      }).finally(() => { marketPreviewPromise = null; });
    }
    marketPreviewPromise.then((d) => {
      const el = document.getElementById('calendar-market-preview');
      if (d && el) renderMarketPreview(el, d);
    }).catch(() => {});
  }

  function renderMarketPreview(box, d) {
    const order = { '待除权': 0, '已除权待到账': 1, '预案待定': 2 };
    const events = (d.events || [])
      .filter((e) => order[e.stage] !== undefined)
      .sort((a, b) => {
        const byStage = order[a.stage] - order[b.stage];
        if (byStage) return byStage;
        return String(a.ex_date || '9999-12-31')
          .localeCompare(String(b.ex_date || '9999-12-31'));
      });
    const show = events.slice(0, 6);
    const s = d.summary || {};
    if (!show.length) {
      box.innerHTML = `<div class="market-preview-empty">
        高股息池里当前没有已公告的即将分红/预案。
        <button class="link" data-market-all>查看完整市场池</button>
      </div>`;
      const all = box.querySelector('[data-market-all]');
      if (all) all.onclick = () => loadCalendar('market');
      return;
    }
    box.innerHTML = `<div class="card-head" style="margin:16px 0 8px">
      <h3 style="font-size:13px;margin:0">市场高股息池 · ${d.market === 'hk' ? '港股' : 'A 股'} · 即将分红 / 预案</h3>
      <span class="hint">待除权 ${s.ex_count_30 || 0} · 预案待定 ${s.plan_count || 0}</span>
      <span class="spacer"></span>
      <button class="link" data-market-all>查看全部</button>
    </div>
    <div class="event-list">${show.map((e) => eventRow(e)).join('')}</div>
    <div class="muted" style="font-size:11.5px;margin-top:6px">
      来自高股息池（股息率 ≥ 3%），只列已公告事件，不是全市场逐票扫描。
    </div>`;
    const all = box.querySelector('[data-market-all]');
    if (all) all.onclick = () => loadCalendar('market');
    bindDiagnoseButtons(box);
  }

  function eventInHorizon(e, horizon) {
    if (e.is_plan) return true;
    if (e.days_to_ex != null && e.days_to_ex >= 0 && e.days_to_ex <= horizon) return true;
    if (e.days_to_pay != null && e.days_to_pay >= 0 && e.days_to_pay <= horizon) return true;
    if (e.stage === '已到账' && e.days_to_cash != null) {
      return e.days_to_cash >= -Math.min(30, horizon) && e.days_to_cash <= 0;
    }
    if (e.stage === '已除权待到账' && e.days_to_pay != null && e.days_to_pay >= 0) return true;
    return false;
  }

  function renderCalendarEvents(d) {
    const horizon = calendarHorizon;
    const events = (d.events || []).filter((e) => eventInHorizon(e, horizon));
    if (!events.length) {
      return `<div class="calendar-empty" style="margin-top:12px">
        未来 ${horizon} 天没有已公告的分红事件。
        ${d.mode === 'positions'
          ? `<div class="toolbar"><button class="ghost" data-pool="cn">看看高股息池 · A 股</button>
             <button class="ghost" data-pool="hk">高股息池 · 港股</button></div>
             <div class="muted" style="font-size:11.5px;margin-top:6px">
               你的持仓没有已公告事件；市场高股息池里还有正在预案/待除权的公司。
             </div>`
          : `<div class="muted" style="margin-top:6px">可切到「未来 12 个月」，或换 A/港股池。</div>`}
      </div>`;
    }
    const order = [
      ['待除权', '待除权'], ['预案待定', '预案待定'],
      ['已除权待到账', '已除权待到账'], ['已到账', '已到账'], ['待定', '待定'],
    ];
    let html = '<div class="event-groups">';
    order.forEach(([stage, title]) => {
      const group = events.filter((e) => e.stage === stage);
      if (!group.length) return;
      const rows = group.map((e) => eventRow(e)).join('');
      html += `<div class="event-group"><h3>${esc(title)} · ${group.length}</h3>
        <div class="event-list${group.length > 8 ? ' long' : ''}">${rows}</div></div>`;
    });
    html += '</div>';
    return html;
  }

  function eventRow(e, opts) {
    const noAction = opts && opts.noAction;
    const stageCls = e.stage === '已到账' ? 'paid'
      : (e.stage === '待除权' || e.stage === '预案待定' ? 'pending' : '');
    const stageBadge = `<span class="stage ${stageCls}">${esc(e.stage)}</span>`;
    const dateLabel = !e.ex_date && !e.pay_date
      ? '<div class="date">待定</div>'
      : (e.stage === '已到账' || e.stage === '已除权待到账')
        ? `<div class="date">${esc((e.pay_date || e.ex_date || '').slice(5))}</div><div class="meta">到账</div>`
        : `<div class="date">${esc((e.ex_date || e.pay_date || '').slice(5))}</div><div class="meta">除权</div>`;
    const meta = [e.code, e.status, e.kind, e.content].filter(Boolean).join(' · ');
    const timeline = `登记 ${e.record_date || '—'} · 除权 ${e.ex_date || '—'} · 到账 ${e.pay_date || '—'}`;
    let amount;
    if (e.shares > 0) {
      // 只展示事实金额：股数 × 每股股息（税前）；税后测算在「记账」里
      amount = `<div class="strong">${fmtMoneyCcy(e.gross, e.currency)}</div>
        <div class="meta">${fmtInt(e.shares)} 股 × ${fmtPriceCcy(e.dps, e.currency)}</div>`;
    } else {
      const extra = e.yield_ttm != null ? `${fmtPct(e.yield_ttm)} 股息率`
        : `${fmtPriceCcy(e.dps, e.currency)}/股`;
      amount = `<div class="strong">${fmtPriceCcy(e.dps, e.currency)}</div>
        <div class="meta">${extra}</div>`;
    }
    return `<div class="event-row">
      <div>${dateLabel}</div>
      <div>
        <div class="name">${esc(e.name)} <span class="chip-mkt mkt-${e.market || 'cn'}">${mktLabel(e.market)}</span></div>
        <div class="meta">${esc(meta)}</div>
      </div>
      <div>
        <div>${stageBadge}</div>
        <div class="meta">${esc(timeline)}</div>
      </div>
      <div class="amount">${amount}</div>
      ${noAction ? '' : `<div class="actions"><button class="btn-analyze" data-diagnose-code="${esc(e.code)}" title="分红持续性分析"><svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M1 8h3l2-5 3 10 2-5h4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>分析</button></div>`}
    </div>`;
  }

  function bindCalendarBodyActions() {
    const body = document.getElementById('calendar-body');
    if (!body) return;
    bindDiagnoseButtons(body);
    body.querySelectorAll('[data-pool]').forEach((btn) => {
      btn.onclick = () => {
        calendarMarket = btn.getAttribute('data-pool');
        loadCalendar('market');
      };
    });
    const importBtn = document.getElementById('calendar-import-group');
    if (importBtn) importBtn.onclick = showWatchlistImport;
  }

  async function showWatchlistImport() {
    const body = document.getElementById('calendar-body');
    if (!body) return;
    body.innerHTML = '<div class="skeleton" style="margin:8px 0"></div>'.repeat(3);
    try {
      const d = await api('watchlist-groups');
      const groups = d.groups || [];
      if (!groups.length) {
        body.innerHTML = '<div class="calendar-empty">没有读取到关注分组；先在 winmale 创建分组。</div>';
        return;
      }
      body.innerHTML = `<div class="card-head" style="margin:6px 0 10px">
        <h2 style="font-size:14px">选择关注分组作为观察池</h2>
        <span class="hint">不计算个人现金，只看即将除权/到账</span></div>` +
        groups.map((g) => `<div class="toolbar" style="margin:6px 0">
          <span class="strong">${esc(g.name)}</span>
          <span class="muted">${(g.symbols || []).length} 只</span>
          <button class="link" data-group="${esc(g.name)}">作为观察池</button>
        </div>`).join('');
      body.querySelectorAll('[data-group]').forEach((btn) => {
        btn.onclick = () => {
          const group = groups.find((g) => g.name === btn.getAttribute('data-group'));
          if (!group) return;
          calendarWatchlist = group.symbols || [];
          loadCalendar('codes');
        };
      });
    } catch (e) {
      body.innerHTML = `<div class="error">读取关注分组失败：${esc(e.message)}</div>`;
    }
  }

  async function run() {
    const result = document.getElementById('result');
    if (!positions.length) {
      result.innerHTML = `<div class="empty">请先添加持仓</div>`;
      return;
    }
    result.innerHTML = `<div class="card"><div class="card-head"><h2>正在取数…</h2></div>
      ${Array(6).fill('<div class="skeleton" style="margin:9px 0"></div>').join('')}</div>`;
    try {
      const resp = await fetch('/api/dividend-xray/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          positions: positions.map((p) => ({ ...p })),
          deep: document.getElementById('chk-deep').checked
        })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
      result.innerHTML =
        `<div style="margin:18px 0">${renderKpis(data)}</div>` +
        `<div class="card"><div class="card-head"><h2>持仓透视</h2>
           <span class="hint">生成于 ${esc(data.generated_at)}</span></div>
           ${renderTable(data)}</div>` +
        `<div class="toolbar" id="next-actions" style="margin:14px 0">
           <span class="muted" style="font-size:13px">接下来：</span>
           <button class="ghost" id="na-ledger">💰 算算这些年分到多少钱</button>
           <button class="ghost" id="na-quality">🛡 分红质量：现金流覆盖 / 分红率 / 连续性</button>
           <button class="ghost" id="na-export">⬇ 导出 Excel 表格</button>
         </div>` +
        `<div id="quality-panel"></div>` +
        renderStability(data);
      if (data.disclaimer) document.getElementById('disclaimer').textContent = data.disclaimer;
      const naLedger = document.getElementById('na-ledger');
      const naExport = document.getElementById('na-export');
      const naQuality = document.getElementById('na-quality');
      if (naLedger) naLedger.onclick = openLedger;
      if (naExport) naExport.onclick = exportCsv;
      if (naQuality) naQuality.onclick = openQuality;
      bindDiagnoseButtons(result);
      if (ledgerOpen) scheduleLedgerRefresh();
      scheduleCalendarRefresh();
    } catch (err) {
      const msg = String(err.message || err);
      const isRate = msg.includes('429') || msg.includes('限流') || msg.includes('limit');
      result.innerHTML = `<div class="error"><strong>取数失败：</strong>${esc(msg)}
        <div style="margin-top:8px;color:var(--text-2)">${
          isRate
            ? '共享体验 Key 的小时额度已用完。<button class="link" onclick="showKeyPanel()">🔑 立即配置自己的 Key</button>（两分钟，额度独立不再限流）；或等下一个整点自动恢复。'
            : '401/403 → <button class="link" onclick="showKeyPanel()">检查 Key 配置</button>。'
        }</div></div>`;
    }
    // 结果出来后，把后续能做的事亮出来（跟在结果旁，不藏进菜单）
    renderNextActions();
  }

  /* ---------------- 辅助面板 ---------------- */
  function aux(html) {
    document.getElementById('aux-panel').innerHTML =
      `<div class="aux-box">${html}</div>`;
  }
  function auxClose() { document.getElementById('aux-panel').innerHTML = ''; }

  async function api(path, body) {
    const resp = await fetch('/api/' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
    return data;
  }

  function showSave() {
    aux(`<div class="card-head"><h2>保存持仓档案</h2></div>
      <div class="toolbar">
        <input id="save-name" placeholder="档案名，如：主仓" style="max-width:240px">
        <button class="primary" id="do-save">保存</button>
        <button class="ghost" id="cancel-save">取消</button>
      </div>`);
    document.getElementById('cancel-save').onclick = auxClose;
    document.getElementById('do-save').onclick = async () => {
      const name = document.getElementById('save-name').value.trim();
      try {
        await api('positions-save', { name, positions });
        aux(`<span class="badge ok">已保存「${esc(name)}」（${positions.length} 只）</span>
             <button class="link" onclick="auxClose()">关闭</button>`);
      } catch (e) { aux(`<div class="error">${esc(e.message)}</div>`); }
    };
  }

  async function showLoad() {
    try {
      const data = await api('positions-list');
      const sets = data.sets || [];
      if (!sets.length) { aux('<span class="muted">还没有保存过档案。先「保存档案」。</span>'); return; }
      aux(`<div class="card-head"><h2>载入持仓档案</h2></div>` + sets.map((s) => `
        <div class="toolbar" style="margin:6px 0">
          <span class="strong">${esc(s.name)}</span>
          <span class="muted">${s.n} 只 · ${esc(s.updated_at)}</span>
          <button class="link" data-load="${esc(s.name)}">载入</button>
        </div>`).join(''));
      const panel = document.getElementById('aux-panel');
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
      document.querySelectorAll('[data-load]').forEach((el) => {
        el.onclick = async () => {
          const d = await api('positions-load', { name: el.getAttribute('data-load') });
          positions.length = 0;
          (d.positions || []).forEach((p) => {
            positions.push(normalizePosition(p));
          });
          renderChips();
          renderHoldingsEditor();
          auxClose();
          scheduleLedgerRefresh();
          loadCalendar('positions');
        };
      });
    } catch (e) { aux(`<div class="error">${esc(e.message)}</div>`); }
  }

  async function showHistory() {
    try {
      const data = await api('snapshots');
      const h = (data.history || []).filter((x) => x.mode === 'real');
      if (!h.length) { aux('<span class="muted">还没有快照。生成一次透视表后会自动存档。</span>'); return; }
      aux(`<div class="card-head"><h2>组合快照历史</h2>
        <span class="hint">每次生成自动存档</span></div>
        <table><thead><tr><th>时间</th><th class="num">标的</th>
          <th class="num">总市值</th><th class="num">总年息</th><th class="num">组合股息率</th></tr></thead>
        <tbody>${h.map((x) => `<tr>
          <td>${esc(x.taken_at)}</td>
          <td class="num">${x.n_positions}</td>
          <td class="num">${fmtMoney(x.total_market_value)}</td>
          <td class="num">${fmtMoney(x.total_dividend)}</td>
          <td class="num strong">${fmtPct(x.portfolio_yield)}</td>
        </tr>`).join('')}</tbody></table>`);
    } catch (e) { aux(`<div class="error">${esc(e.message)}</div>`); }
  }

  async function showSync() {
    if (!positions.length) { aux('<span class="muted">先添加持仓再同步。仅支持 A 股代码同步。</span>'); return; }
    const cnOnly = positions.filter((p) => (p.market || 'cn') === 'cn');
    if (!cnOnly.length) { aux('<span class="muted">winmale 分组同步暂只支持 A 股。</span>'); return; }
    aux(`<div class="card-head"><h2>同步到 winmale 关注分组</h2></div>
      <div class="toolbar">
        <input id="sync-group" value="持仓透视" style="max-width:200px" title="远端分组名">
        <button class="ghost" id="sync-diff">预览差异</button>
        <button class="primary" id="sync-push">推送</button>
        <span class="muted" style="font-size:12px">只增不删，远端多余标的不会被移除</span>
      </div><div id="sync-result" style="margin-top:10px"></div>`);
    const group = () => document.getElementById('sync-group').value.trim() || '持仓透视';
    document.getElementById('sync-diff').onclick = async () => {
      try {
        const d = await api('watchlist-diff', { group: group(), positions: cnOnly });
        document.getElementById('sync-result').innerHTML =
          `<span class="badge ${d.group_exists ? 'ok' : 'warn'}">${d.group_exists ? '分组已存在' : '将新建分组'}</span>
           <span style="margin-left:8px">将加入 <strong>${d.will_add.length}</strong> 只` +
          (d.already_in.length ? `；已在组内 ${d.already_in.length} 只` : '');
      } catch (e) {
        document.getElementById('sync-result').innerHTML = `<div class="error">${esc(e.message)}</div>`;
      }
    };
    document.getElementById('sync-push').onclick = async () => {
      const btn = document.getElementById('sync-push');
      btn.disabled = true; btn.textContent = '推送中…';
      try {
        const r = await api('watchlist-push', { group: group(), positions: cnOnly });
        document.getElementById('sync-result').innerHTML =
          `<span class="badge ok">已同步</span> 新加入 ${r.added.length} 只` +
          (r.already_in.length ? `，已在组内 ${r.already_in.length} 只` : '');
      } catch (e) {
        document.getElementById('sync-result').innerHTML = `<div class="error">${esc(e.message)}</div>`;
        btn.disabled = false; btn.textContent = '推送';
      }
    };
  }

  /* ---------------- Key 设置（页面内直接保存） ---------------- */
  async function showKey() {
    let status = {};
    try { status = await api('key-status'); } catch (_) { /* 忽略 */ }
    aux(`
      <div class="card-head"><h2>finpipe 数据 Key</h2>
        <span class="hint">${status.custom
          ? '✓ 正在使用你自己的 Key（额度独立）'
          : '当前使用共享体验 Key：可用但额度有限，高峰会 429 限流'}</span></div>
      <p class="muted" style="margin:0 0 10px;font-size:12.5px">
        到 <a href="https://open.winmale.com" target="_blank" rel="noopener">open.winmale.com</a>
        微信扫码登录 →「我的」→「开放平台」→「我的应用」→ 复制 client_id 与 api-key。
        保存后<strong>立即验证并热切换</strong>，无需重启（Key 只存本机
        ~/.finpipe/credentials.env，权限 600，不会回显）。</p>
      <div class="toolbar" style="flex-direction:column;align-items:stretch;gap:8px">
        <input id="key-id" placeholder="client_id" autocomplete="off" spellcheck="false">
        <input id="key-secret" type="password" placeholder="api-key（client_secret）" autocomplete="off">
        <div class="toolbar">
          <button class="primary" id="key-save">验证并保存</button>
          <button class="ghost" id="key-cancel">取消</button>
          <span class="muted" style="font-size:12px">非商业用途免费</span>
        </div>
      </div>
      <div id="key-result" style="margin-top:8px"></div>`);
    document.getElementById('key-cancel').onclick = auxClose;
    document.getElementById('key-save').onclick = async () => {
      const btn = document.getElementById('key-save');
      const cid = document.getElementById('key-id').value.trim();
      const sec = document.getElementById('key-secret').value.trim();
      btn.disabled = true; btn.textContent = '验证中…';
      try {
        const r = await api('key-save', { client_id: cid, client_secret: sec });
        document.getElementById('key-result').innerHTML =
          `<span class="badge ok">${esc(r.message)}</span>`;
        btn.textContent = '已生效 ✓';
      } catch (e) {
        document.getElementById('key-result').innerHTML = `<div class="error">${esc(e.message)}</div>`;
        btn.disabled = false; btn.textContent = '验证并保存';
      }
    };
  }

  /* ---------------- 分红记账（独立区域：年度汇总 + 折叠明细） ---------------- */
  const ledgerPositionPayload = (p) => ({
    code: p.code,
    market: marketOf(p),
    name: p.name,
    shares: p.shares,
    cost: p.cost,
    buy_date: p.buy_date || '',
    tax_rate: (p.tax_rate === '' || p.tax_rate == null) ? null : Number(p.tax_rate),
  });

  const ledgerTaxPayload = () => ({
    mode: ledgerTax.mode,
    flat_rate: ledgerTax.flat_rate,
    year_rates: ledgerTax.year_rates,
  });

  function closeLedger() {
    ledgerOpen = false;
    ledgerData = null;
    ledgerYearsKey = '';
    clearTimeout(ledgerTimer);
    const panel = document.getElementById('ledger-panel');
    if (panel) panel.innerHTML = '';
  }

  function openLedger() {
    const panel = document.getElementById('ledger-panel');
    if (!panel) return;
    if (!positions.length) {
      panel.innerHTML = '<div class="card"><div class="empty">先添加持仓再记账</div></div>';
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    ledgerOpen = true;
    ledgerData = null;
    ledgerYear = '';
    ledgerYearsKey = '';
    ledgerTax = { mode: 'auto', flat_rate: null, year_rates: {} };
    clearTimeout(ledgerTimer);
    panel.innerHTML = ledgerShell();
    bindLedgerControls();
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    fetchLedger();
  }

  function ledgerShell() {
    return `
      <div class="card ledger-card">
        <div class="card-head">
          <h2>分红记账</h2>
          <span class="hint">汇总按 CNY 折算；逐笔明细为原币。A 股按持有期，港股默认 20%（可改）</span>
          <span class="spacer"></span>
          <button class="ghost" id="ledger-close" style="padding:4px 10px;font-size:12.5px">收起</button>
        </div>
        <div class="ledger-controls">
          <div class="controls-row">
            <label>年份 <select id="ledger-year"><option value="">全部历史</option></select></label>
            <label>计税方式
              <select id="ledger-tax-mode">
                <option value="auto">自动（A 股按持有时长 / 港股 20%）</option>
                <option value="flat">统一税率</option>
                <option value="by_year">分年度税率</option>
              </select>
            </label>
            <span class="muted" style="font-size:11.5px">单票覆盖优先于全局设置</span>
          </div>
          <div id="ledger-tax-extra" class="tax-extra"></div>
        </div>
        <div id="ledger-kpis"></div>
        <div id="ledger-summary" style="margin-top:16px"></div>
        <details class="ledger-detail" id="ledger-detail">
          <summary>逐笔明细 <span class="muted" id="ledger-detail-count"></span></summary>
          <div id="ledger-detail-body" style="margin-top:10px"></div>
        </details>
        <div id="ledger-notes" class="ledger-notes"></div>
      </div>`;
  }

  function bindLedgerControls() {
    const close = document.getElementById('ledger-close');
    if (close) close.onclick = closeLedger;
    const yearSel = document.getElementById('ledger-year');
    if (yearSel) yearSel.onchange = (e) => { ledgerYear = e.target.value; fetchLedger(); };
    const modeSel = document.getElementById('ledger-tax-mode');
    if (modeSel) {
      modeSel.value = ledgerTax.mode;
      modeSel.onchange = (e) => {
        ledgerTax.mode = e.target.value;
        if (ledgerTax.mode === 'flat' && ledgerTax.flat_rate == null) {
          ledgerTax.flat_rate = 0.20;
        }
        renderTaxExtra();
        fetchLedger();
        scheduleCalendarRefresh();
      };
    }
    renderTaxExtra();
  }

  function renderTaxExtra() {
    const box = document.getElementById('ledger-tax-extra');
    if (!box) return;
    if (ledgerTax.mode === 'auto') { box.innerHTML = ''; return; }
    if (ledgerTax.mode === 'flat') {
      const pct = ledgerTax.flat_rate == null ? '' :
        String(Number((ledgerTax.flat_rate * 100).toFixed(4)));
      box.innerHTML = `
        <label>税率 <input id="ledger-flat-rate" type="number" min="0" max="100" step="0.1"
               value="${pct}" style="width:74px"> %</label>
        <button class="ghost" data-flat="20">20%</button>
        <button class="ghost" data-flat="10">10%</button>
        <button class="ghost" data-flat="0">0%</button>`;
      const input = document.getElementById('ledger-flat-rate');
      if (input) input.oninput = () => {
        const raw = input.value;
        ledgerTax.flat_rate = raw === '' ? null : Number(raw) / 100;
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      };
      box.querySelectorAll('[data-flat]').forEach((btn) => {
        btn.onclick = () => {
          ledgerTax.flat_rate = Number(btn.getAttribute('data-flat')) / 100;
          renderTaxExtra();
          fetchLedger();
          scheduleCalendarRefresh();
        };
      });
      return;
    }
    // by_year
    const years = (ledgerData && ledgerData.available_years) || [];
    const key = years.join(',');
    if (!years.length) {
      box.innerHTML = '<span class="muted" style="font-size:12px">取到分红历史后可设置年度税率</span>';
      ledgerYearsKey = '';
      return;
    }
    if (key === ledgerYearsKey && box.querySelector('[data-year-rate]')) return;
    ledgerYearsKey = key;
    const cells = years.map((y) => {
      const rate = ledgerTax.year_rates[y];
      const pct = rate == null ? '' : String(Number((rate * 100).toFixed(4)));
      return `<label class="tax-year-item">${y}
        <input type="number" data-year-rate="${y}" min="0" max="100" step="0.1"
               placeholder="自动" value="${pct}"></label>`;
    }).join('');
    box.innerHTML = `
      <label>批量 <input id="ledger-year-rate-all" type="number" min="0" max="100" step="0.1"
             placeholder="如 10" style="width:70px"> %</label>
      <button class="ghost" id="ledger-year-rate-apply">应用到所有年份</button>
      <div class="tax-year-grid">${cells}</div>`;
    box.querySelectorAll('[data-year-rate]').forEach((input) => {
      input.oninput = () => {
        const y = input.getAttribute('data-year-rate');
        if (input.value === '') delete ledgerTax.year_rates[y];
        else ledgerTax.year_rates[y] = Number(input.value) / 100;
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      };
    });
    const applyAll = document.getElementById('ledger-year-rate-apply');
    if (applyAll) applyAll.onclick = () => {
      const raw = document.getElementById('ledger-year-rate-all').value;
      if (raw === '') return;
      const rate = Number(raw) / 100;
      years.forEach((y) => { ledgerTax.year_rates[y] = rate; });
      renderTaxExtra();
      fetchLedger();
      scheduleCalendarRefresh();
    };
  }

  function populateLedgerYears(years) {
    const sel = document.getElementById('ledger-year');
    if (!sel) return false;
    const current = ledgerYear;
    sel.innerHTML = '<option value="">全部历史</option>' +
      (years || []).map((y) => `<option value="${y}">${y}</option>`).join('');
    if (current && (years || []).map(String).includes(String(current))) {
      sel.value = String(current);
      return false;
    }
    const reset = Boolean(current);
    sel.value = '';
    ledgerYear = '';
    return reset;
  }

  async function fetchLedger() {
    if (!ledgerOpen) return;
    const kpiBox = document.getElementById('ledger-kpis');
    if (!kpiBox) return;
    kpiBox.innerHTML = '<div class="skeleton" style="margin:8px 0"></div>'.repeat(2);
    try {
      const d = await api('ledger', {
        positions: positions.map(ledgerPositionPayload),
        year: ledgerYear || null,
        tax: ledgerTaxPayload(),
      });
      if (!ledgerOpen) return;
      ledgerData = d;
      // 持仓变化导致所选年份消失：重置为全部历史并再取一次
      if (populateLedgerYears(d.available_years || [])) {
        fetchLedger();
        return;
      }
      renderLedgerData(d);
      if (ledgerTax.mode === 'by_year') renderTaxExtra();
    } catch (e) {
      if (!ledgerOpen) return;
      kpiBox.innerHTML = `<div class="error"><strong>记账失败：</strong>${esc(e.message)}</div>`;
    }
  }

  function scheduleLedgerRefresh() {
    if (!ledgerOpen) return;
    clearTimeout(ledgerTimer);
    ledgerTimer = setTimeout(fetchLedger, 300);
  }

  function renderLedgerData(d) {
    const hasHk = (d.stocks || []).some((s) => s.currency === 'HKD');
    const effectiveRate = (d.total_gross != null && d.total_gross !== 0 && d.total_tax != null)
      ? d.total_tax / d.total_gross : null;
    const kpis = [
      { label: '税前股息', value: fmtMoney(d.total_gross), sub: hasHk ? 'CNY 折算' : 'CNY' },
      { label: '估算税额', value: fmtMoney(d.total_tax), sub: hasHk ? 'CNY 折算' : 'CNY' },
      { label: '税后净入', value: fmtMoney(d.total_net), cls: 'accent',
        sub: hasHk ? 'CNY 折算' : 'CNY' },
      { label: '实际税率', value: fmtPct(effectiveRate), sub: '税额 ÷ 税前股息' },
    ];
    const kpiBox = document.getElementById('ledger-kpis');
    if (kpiBox) {
      kpiBox.innerHTML = `<div class="kpis">` + kpis.map((k) => `
        <div class="kpi ${k.cls || ''}">
          <div class="label">${esc(k.label)}</div>
          <div class="value">${k.value}</div>
          ${k.sub ? `<div class="sub">${esc(k.sub)}</div>` : ''}
        </div>`).join('') + `</div>`;
    }

    const summary = document.getElementById('ledger-summary');
    if (summary) {
      const years = d.by_year || [];
      if (!years.length) {
        summary.innerHTML = '<div class="muted" style="font-size:13px">所选范围没有分红记录。</div>';
      } else {
        summary.innerHTML = `
          <div class="card-head" style="margin-bottom:8px">
            <h2 style="font-size:13px">年度汇总（${esc(d.total_currency || 'CNY')}）</h2>
            <span class="hint">默认只展示年度汇总，逐笔明细在下方折叠</span>
          </div>
          <div class="table-scroll"><table>
            <thead><tr><th>年份</th><th class="num">税前</th><th class="num">税</th>
              <th class="num">净入</th><th class="num">实际税率</th><th class="num">笔数</th></tr></thead>
            <tbody>${years.map((y) => `<tr>
              <td>${y.year}</td>
              <td class="num">${fmtMoney(y.gross)}</td>
              <td class="num">${fmtMoney(y.tax)}</td>
              <td class="num strong">${fmtMoney(y.net)}</td>
              <td class="num">${fmtPct(y.tax_ratio)}</td>
              <td class="num">${y.events}</td>
            </tr>`).join('')}</tbody>
          </table></div>`;
      }
    }

    const detailCount = document.getElementById('ledger-detail-count');
    const totalEvents = (d.stocks || []).reduce((n, s) => n + (s.events || []).length, 0);
    if (detailCount) detailCount.textContent = totalEvents ? `（${totalEvents} 笔）` : '';

    const detailBox = document.getElementById('ledger-detail-body');
    if (detailBox) {
      if (!totalEvents) {
        detailBox.innerHTML = '<div class="muted" style="font-size:13px">没有逐笔记录。</div>';
      } else {
        const rows = [];
        (d.stocks || []).forEach((s) => {
          (s.events || []).forEach((e) => {
            rows.push(`<tr>
              <td>${esc(s.name)} <span class="muted" style="font-size:11.5px">${esc(s.code)}</span></td>
              <td><span class="chip-mkt mkt-${s.market || 'cn'}">${mktLabel(s.market)}</span>
                <span class="currency-tag">${esc(e.currency || s.currency || 'CNY')}</span></td>
              <td class="num">${esc(e.ex_date)}</td>
              <td class="num">${fmtPriceCcy(e.dps, e.currency || s.currency)}</td>
              <td class="num">${fmtMoneyCcy(e.gross, e.currency || s.currency)}</td>
              <td class="num">${(e.tax_ratio * 100).toFixed(0)}%</td>
              <td class="num">${fmtMoneyCcy(e.tax, e.currency || s.currency)}</td>
              <td class="num strong">${fmtMoneyCcy(e.net, e.currency || s.currency)}</td>
              <td class="num">${e.holding_days == null ? DASH : e.holding_days}</td>
              <td><span class="badge">${esc(taxSourceLabel(e.tax_source))}</span>
                ${e.estimated ? '<span class="badge warn">估算</span>' : ''}</td>
            </tr>`);
          });
        });
        detailBox.innerHTML = `<div class="scroll-box"><table>
          <thead><tr><th>股票</th><th>市场</th><th class="num">除权日</th><th class="num">每股</th>
            <th class="num">税前</th><th class="num">税率</th><th class="num">税</th>
            <th class="num">净入</th><th class="num">持有天数</th><th>计税</th></tr></thead>
          <tbody>${rows.join('')}</tbody></table></div>`;
      }
    }

    const notes = document.getElementById('ledger-notes');
    if (notes) {
      const parts = String(d.note || '').split('。').map((s) => s.trim()).filter(Boolean);
      notes.innerHTML = parts.length
        ? `<ul class="notes">${parts.map((p) => `<li>${esc(p)}。</li>`).join('')}</ul>`
        : '';
    }
  }

  function exportCsv() {
    if (!positions.length) { aux('<span class="muted">先添加持仓再导出。</span>'); return; }
    const q = encodeURIComponent(JSON.stringify(positions));
    window.location.href = '/export/xray.csv?positions=' + q;
  }

  /* ---------------- 结果旁的后续操作 ---------------- */
  function renderNextActions() {
    const bar = document.getElementById('next-actions');
    if (!bar) return;
    bar.style.display = '';
  }

  /* ---------------- 挂载 ---------------- */
  function mount() {
    renderChips();
    renderHoldingsEditor();
    renderCalendarShell();
    autoLoadPositions();
    const input = document.getElementById('sym-search');

    // Key 状态徽章（右上角，一眼看清数据源）
    api('key-status').then((s) => {
      document.getElementById('key-badge').innerHTML = s.custom
        ? '<span class="badge ok">已用自己的 Key</span>'
        : '<span class="badge warn">共享体验 Key · 额度有限</span>';
    }).catch(() => {});

    // 「更多」折叠
    const moreBtn = document.getElementById('btn-more');
    const moreBody = document.getElementById('more-body');
    moreBtn.onclick = () => {
      const open = moreBody.style.display !== 'none';
      moreBody.style.display = open ? 'none' : '';
      moreBtn.textContent = open ? '▸ 更多：持仓单管理 · 生成记录 · 数据导出'
                                 : '▾ 收起';
    };

    // 市场切换
    document.querySelectorAll('.market-tab').forEach((tab) => {
      tab.onclick = () => {
        document.querySelectorAll('.market-tab').forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        currentMarket = tab.getAttribute('data-mkt');
        input.placeholder = currentMarket === 'hk'
          ? '搜索港股：代码 / 名称 / 拼音，如 00700、腾讯、txkg'
          : '搜索：代码 / 名称 / 拼音 / 缩写';
        input.focus();
      };
    });

    input.addEventListener('input', () => {
      const q = input.value.trim();
      clearTimeout(debounceTimer);
      if (!q) { closeDropdown(); return; }
      debounceTimer = setTimeout(() => query(q), 200);
    });
    input.addEventListener('keydown', (e) => {
      if (!dropdown) {
        if (e.key === 'Enter' && currentMarket === 'cn' && /^\d{6}$/.test(input.value.trim())) {
          e.preventDefault();
          addPosition({ code: input.value.trim(), name: input.value.trim(), market: 'cn' });
          input.value = '';
        }
        return;
      }
      const items = dropdown.querySelectorAll('.sym-item');
      let active = dropdown.querySelector('.sym-item.active');
      let idx = items.length ? Array.from(items).indexOf(active) : -1;
      if (e.key === 'ArrowDown' && items.length) {
        e.preventDefault();
        if (active) active.classList.remove('active');
        idx = (idx + 1) % items.length;
        items[idx].classList.add('active');
      } else if (e.key === 'ArrowUp' && items.length) {
        e.preventDefault();
        if (active) active.classList.remove('active');
        idx = (idx - 1 + items.length) % items.length;
        items[idx].classList.add('active');
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const i = idx >= 0 ? Number(items[idx].getAttribute('data-i')) : 0;
        fetch('/api/symbols?q=' + encodeURIComponent(input.value.trim())
              + '&market=' + currentMarket)
          .then((r) => r.json())
          .then((d) => {
            const results = d.results || [];
            if (results.length) pick(results[i] || results[0]);
          });
      } else if (e.key === 'Escape') {
        closeDropdown();
      }
    });
    document.addEventListener('click', (e) => {
      if (dropdown && !document.getElementById('search-box').contains(e.target)) closeDropdown();
    });

    document.getElementById('chips').addEventListener('click', (e) => {
      const del = e.target.getAttribute && e.target.getAttribute('data-del');
      if (del) {
        const i = positions.findIndex((x) => chipKey(x) === del);
        if (i >= 0) {
          positions.splice(i, 1);
          renderChips();
          renderHoldingsEditor();
          scheduleLedgerRefresh();
          scheduleCalendarRefresh();
        }
      }
    });
    document.getElementById('chips').addEventListener('input', (e) => {
      const key = e.target.getAttribute && e.target.getAttribute('data-shares');
      if (!key) return;
      const p = positions.find((x) => chipKey(x) === key);
      if (p) {
        p.shares = e.target.value;
        syncHoldingShares(positions.indexOf(p), e.target.value);
        updateHoldingsSummary();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      }
    });
    document.getElementById('chips').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') e.target.blur();
    });

    // 持仓明细：输入即时写回 positions，不重渲染（保持焦点）
    const holdings = document.getElementById('holdings-editor');
    if (holdings) {
      holdings.addEventListener('input', (e) => {
        const idx = Number(e.target.getAttribute('data-idx'));
        const field = e.target.getAttribute('data-field');
        if (!Number.isInteger(idx) || !field || !positions[idx]) return;
        const p = positions[idx];
        if (field === 'shares') {
          p.shares = e.target.value;
          syncChipShares(idx, e.target.value);
        } else if (field === 'cost') {
          p.cost = e.target.value;
        } else if (field === 'buy_date') {
          p.buy_date = e.target.value;
        } else if (field === 'tax_rate') {
          const n = Number(e.target.value);
          p.tax_rate = (e.target.value === '' || !isFinite(n)) ? '' : n / 100;
        }
        updateHoldingsSummary();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      });
      holdings.addEventListener('click', (e) => {
        const del = e.target.getAttribute && e.target.getAttribute('data-del-idx');
        if (del == null) return;
        positions.splice(Number(del), 1);
        renderChips();
        renderHoldingsEditor();
        scheduleLedgerRefresh();
        scheduleCalendarRefresh();
      });
    }

    document.getElementById('btn-run').onclick = run;
    document.getElementById('btn-save').onclick = showSave;
    document.getElementById('btn-load').onclick = showLoad;
    document.getElementById('btn-history').onclick = showHistory;
    document.getElementById('btn-export').onclick = exportCsv;
    document.getElementById('btn-key').onclick = showKey;
  }

  document.addEventListener('DOMContentLoaded', mount);

  // 内联 onclick 入口
  window.showKeyPanel = () => showKey();
  window.auxClose = auxClose;
})();
