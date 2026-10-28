import { describe, expect, it } from 'vitest';
import {
  abilityBand, chipKey, fmtInt, fmtMoney, fmtMoneyCcy, fmtPct, fmtPrice,
  fmtSigned, marketFromCode, normalizePosition, signClass, taxSourceLabel,
} from '@/format';

describe('fmtMoney', () => {
  it('缺失显式返回 —，绝不填 0', () => {
    expect(fmtMoney(null)).toBe('—');
    expect(fmtMoney(undefined)).toBe('—');
    expect(fmtMoney(Number.NaN)).toBe('—');
  });
  it('万/亿换算（≥1e4 转万、≥1e8 转亿）', () => {
    expect(fmtMoney(2200)).toBe('2200.00');
    expect(fmtMoney(45600)).toBe('4.56 万');
    expect(fmtMoney(123456789)).toBe('1.23 亿');
  });
});

describe('fmtPct / fmtPrice / fmtInt / fmtSigned', () => {
  it('比率按百分数展示', () => {
    expect(fmtPct(0.0482)).toBe('4.82%');
    expect(fmtPct(0.352, 1)).toBe('35.2%');
    expect(fmtPct(null)).toBe('—');
  });
  it('价格两位小数', () => {
    expect(fmtPrice(45.6)).toBe('45.60');
    expect(fmtPrice(null)).toBe('—');
  });
  it('整数千分位', () => {
    expect(fmtInt(1000)).toBe('1,000');
    expect(fmtInt(null)).toBe('—');
  });
  it('带符号百分比（颜色交给 signClass）', () => {
    expect(fmtSigned(0.1234)).toBe('+12.34%');
    expect(fmtSigned(-0.05)).toBe('-5.00%');
    expect(signClass(0.1)).toBe('up');
    expect(signClass(-0.1)).toBe('down');
    expect(signClass(0)).toBe('');
  });
});

describe('币种前缀', () => {
  it('HKD 加 HK$，CNY 无前缀，缺失不拼', () => {
    expect(fmtMoneyCcy(1234.5, 'HKD')).toBe('HK$1234.50');
    expect(fmtMoneyCcy(1234.5, 'CNY')).toBe('1234.50');
    expect(fmtMoneyCcy(null, 'HKD')).toBe('—');
  });
});

describe('市场路由（与 tests/test_fetchers.py 的 CN/HK 语义一致）', () => {
  it('hk. 前缀与 5 位裸码 → hk，其余 → cn', () => {
    expect(marketFromCode('hk.00700')).toBe('hk');
    expect(marketFromCode('00700', 'cn')).toBe('hk');
    expect(marketFromCode('600036')).toBe('cn');
    expect(marketFromCode('600036', 'hk')).toBe('hk'); // 显式 hk 优先
    expect(marketFromCode('AAPL', 'us')).toBe('us');
  });
  it('chipKey 按市场+代码去重', () => {
    expect(chipKey({ code: '00700', market: 'hk' })).toBe('hk:00700');
    expect(chipKey({ code: '600036' })).toBe('cn:600036');
  });
});

describe('normalizePosition', () => {
  it('税率百分比/小数统一为小数，空串保留', () => {
    expect(normalizePosition({ code: '600036', shares: 1000, tax_rate: 20 }).tax_rate).toBe(0.2);
    expect(normalizePosition({ code: '600036', shares: 1000, tax_rate: 0.1 }).tax_rate).toBe(0.1);
    expect(normalizePosition({ code: '600036', shares: 1000, tax_rate: '' }).tax_rate).toBe('');
  });
  it('买入日缺省为今年 1 月 1 日', () => {
    const year = new Date().getFullYear();
    expect(normalizePosition({ code: '600036', shares: 1 }).buy_date).toBe(`${year}-01-01`);
  });
});

describe('展示辅助', () => {
  it('支付能力分档', () => {
    expect(abilityBand(85)).toEqual({ label: '强', cls: 'ok' });
    expect(abilityBand(65)).toEqual({ label: '中', cls: 'ok' });
    expect(abilityBand(45)).toEqual({ label: '偏弱', cls: 'warn' });
    expect(abilityBand(20)).toEqual({ label: '弱', cls: 'warn' });
    expect(abilityBand(null).label).toBe('—');
  });
  it('计税来源标签', () => {
    expect(taxSourceLabel('hk_default')).toBe('港股默认');
    expect(taxSourceLabel('fallback')).toBe('估算(缺买入日)');
    expect(taxSourceLabel(undefined)).toBe('自动');
  });
});
