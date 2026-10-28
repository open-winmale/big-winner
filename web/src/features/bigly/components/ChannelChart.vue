<script setup lang="ts">
/* 估值通道主图：均值 ± Nσ 通道 + 均值/中位轨线 + 当前点。
   轨线必须带时间坐标（两点式），纯数值会把时间轴拉到 1970。 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as echarts from 'echarts';
import type { BiglyChannel } from '@/api/types';

const props = defineProps<{
  series: [number, number][];
  channel: BiglyChannel;
  metric: string;
}>();

const el = ref<HTMLDivElement | null>(null);
let chart: echarts.ECharts | null = null;

function render(): void {
  if (!el.value) return;
  const pts = props.series.map((p) => [p[0] * 1000, p[1]] as [number, number]);
  if (!pts.length) return;
  const t0 = pts[0][0];
  const t1 = pts[pts.length - 1][0];
  const mainName = (props.metric || 'pe').toUpperCase();
  const c = props.channel;
  const rule = (v: number, name: string, color: string, dash: boolean, width = 1.5) => ({
    type: 'line' as const, data: [[t0, v], [t1, v]], name,
    symbol: 'none' as const, silent: true,
    lineStyle: { color, width, type: dash ? 'dashed' as const : 'solid' as const },
  });
  chart = chart || echarts.init(el.value);
  chart.setOption({
    animation: false,
    grid: { left: 52, right: 70, top: 16, bottom: 46 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const arr = Array.isArray(params) ? params : [params];
        const list = arr as { seriesName: string; axisValue?: number; value: [number, number]; marker: string }[];
        const m = list.find((p) => p.seriesName === mainName) || list[0];
        if (!m) return '';
        const tv = m.axisValue != null ? m.axisValue : m.value[0];
        const d = new Date(tv);
        const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        return `${ds}<br/>${m.marker}${m.seriesName} ${Number(m.value[1]).toFixed(2)}`;
      },
    },
    xAxis: { type: 'time' },
    yAxis: { type: 'value', scale: true, axisLabel: { formatter: (v: number) => v.toFixed(2) } },
    dataZoom: [
      { type: 'slider', height: 16, bottom: 10 },
      { type: 'inside' },
    ],
    series: [
      { type: 'line', name: mainName, data: pts, symbol: 'none',
        lineStyle: { color: '#2563eb', width: 1.6 }, z: 5,
        /* σ 色带：±1σ 一档、±1σ~±2σ 一档，横向铺满（与平台「看估值通道」同风格） */
        markArea: {
          silent: true,
          data: [
            [{ yAxis: c.upper1, itemStyle: { color: 'rgba(220,38,38,.07)' } },
             { yAxis: c.upper2 }],
            [{ yAxis: c.lower2, itemStyle: { color: 'rgba(22,163,74,.07)' } },
             { yAxis: c.lower1 }],
            [{ yAxis: c.lower1, itemStyle: { color: 'rgba(148,163,184,.16)' } },
             { yAxis: c.upper1 }],
          ],
        } },
      { type: 'line', name: '低估线', data: [[t0, c.lower2], [t1, c.lower2]], symbol: 'none',
        lineStyle: { color: '#16a34a', width: 1.6, type: 'dashed' }, silent: true,
        endLabel: { show: true, formatter: '低估线', color: '#16a34a' } },
      { type: 'line', name: '高估线', data: [[t0, c.upper2], [t1, c.upper2]], symbol: 'none',
        lineStyle: { color: '#dc2626', width: 1.6, type: 'dashed' }, silent: true,
        endLabel: { show: true, formatter: '高估线', color: '#dc2626' } },
      rule(c.lower1, '−1σ', '#94a3b8', true),
      rule(c.upper1, '+1σ', '#94a3b8', true),
      rule(c.avg, '均值', '#f59e0b', true),
      ...(c.median != null ? [rule(c.median, '中位', '#6366f1', true, 1)] : []),
      { type: 'scatter', name: '当前', data: [[t1, c.current]],
        symbolSize: 9, itemStyle: { color: '#dc2626' }, z: 10,
        label: { show: true, formatter: () => c.current.toFixed(2), position: 'right', color: '#dc2626' } },
    ],
  });
  // 自动加载早于首帧布局时 init 会拿到 0 宽画布，强制按容器尺寸重排
  chart.resize();
}

function onResize(): void { chart?.resize(); }

onMounted(() => {
  render();
  window.addEventListener('resize', onResize);
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  chart?.dispose();
  chart = null;
});
watch(() => [props.series, props.channel, props.metric], render);
</script>

<template>
  <div ref="el" class="chart-box"></div>
</template>

<style scoped>
.chart-box { height: 300px; }
</style>
