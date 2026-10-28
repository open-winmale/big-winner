import { defineConfig, presetAttributify, presetUno } from 'unocss';

// 设计体系沿用 base.css 移植版（src/styles/main.css 的 CSS 变量与组件类），
// UnoCSS 只负责模板里的一次性布局原子类。
export default defineConfig({
  presets: [presetUno(), presetAttributify()],
  safelist: [
    'bg-red-50', 'text-red-600', 'border-red-200',
    'bg-amber-50', 'text-amber-600', 'border-amber-200',
    'bg-blue-50', 'text-blue-600', 'border-blue-200',
    'bg-emerald-50', 'text-emerald-600', 'border-emerald-200',
  ],
});
