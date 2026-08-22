/**
 * AI 接口调试系统设计文档 - 图表初始化
 *
 * 包含 3 个图表:
 *   1. chart-status-code    接口执行状态码分布 (柱状图)
 *   2. chart-duration-trend 接口响应耗时趋势 (折线图)
 *   3. chart-roadmap        三阶段里程碑时间线 (条形图)
 *
 * 所有颜色从 CSS 变量读取,保持与文档主题一致。
 */
(function () {
  'use strict';

  if (typeof window.echarts === 'undefined') {
    console.warn('[charts.js] ECharts 未加载,跳过图表初始化');
    return;
  }

  // ---------------------------------------------------------------
  // 读取 CSS 变量主题色
  // ---------------------------------------------------------------
  function readVar(name) {
    var raw = getComputedStyle(document.documentElement).getPropertyValue(name);
    return raw ? raw.trim() : '';
  }

  var THEME = {
    bg:       readVar('--bg')       || '#F8FAFC',
    bg2:      readVar('--bg2')      || '#FFFFFF',
    bg3:      readVar('--bg3')      || '#F1F5F9',
    ink:      readVar('--ink')      || '#1E293B',
    muted:    readVar('--muted')    || '#64748B',
    rule:     readVar('--rule')     || '#E2E8F0',
    accent:   readVar('--accent')   || '#2563EB',
    accent2:  readVar('--accent2')  || '#8B5CF6',
    accent3:  readVar('--accent3')  || '#F59E0B',
    success:  readVar('--success')  || '#10B981',
    danger:   readVar('--danger')   || '#EF4444'
  };

  var FONT = 'Inter, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
  var MONO = '"JetBrains Mono", Menlo, Consolas, monospace';

  // 通用 axis 样式
  function axisStyle(color) {
    return {
      axisLine: { lineStyle: { color: THEME.rule } },
      axisLabel: { color: color || THEME.muted, fontFamily: FONT, fontSize: 11 },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: THEME.rule, type: 'dashed' } }
    };
  }

  // 通用 tooltip 样式
  function tooltipStyle() {
    return {
      backgroundColor: THEME.ink,
      borderColor: THEME.ink,
      textStyle: { color: '#FFFFFF', fontFamily: FONT, fontSize: 12 }
    };
  }

  // ---------------------------------------------------------------
  // 1) 接口执行状态码分布 (柱状图)
  // ---------------------------------------------------------------
  function initStatusCode() {
    var el = document.getElementById('chart-status-code');
    if (!el) return;
    var chart = echarts.init(el, null, { renderer: 'svg' });

    var categories = ['2xx', '3xx', '4xx', '5xx', '0(无响应)'];
    var counts = [1250, 45, 280, 95, 30];
    var colors = [THEME.success, THEME.accent3, THEME.accent3, THEME.danger, THEME.muted];

    chart.setOption({
      animation: false,
      tooltip: Object.assign({}, tooltipStyle(), {
        trigger: 'axis',
        formatter: function (p) {
          return p[0].name + '<br/>执行数: <b>' + p[0].value + '</b> 次';
        }
      }),
      grid: { left: 60, right: 40, top: 40, bottom: 40, containLabel: false },
      xAxis: Object.assign({ type: 'category', data: categories }, axisStyle()),
      yAxis: Object.assign({ type: 'value', name: '执行次数' }, axisStyle()),
      series: [{
        type: 'bar',
        data: counts.map(function (v, i) {
          return { value: v, itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] } };
        }),
        barWidth: '48%',
        label: {
          show: true,
          position: 'top',
          color: THEME.ink,
          fontFamily: MONO,
          fontSize: 11,
          fontWeight: 600
        }
      }]
    });

    window.addEventListener('resize', function () { chart.resize(); });
  }

  // ---------------------------------------------------------------
  // 2) 接口响应耗时趋势 (折线图)
  // ---------------------------------------------------------------
  function initDurationTrend() {
    var el = document.getElementById('chart-duration-trend');
    if (!el) return;
    var chart = echarts.init(el, null, { renderer: 'svg' });

    var days = ['7/13', '7/14', '7/15', '7/16', '7/17', '7/18', '7/19'];
    var avgMs = [180, 220, 195, 350, 280, 240, 210];
    var p95Ms = [420, 480, 450, 820, 690, 580, 510];

    chart.setOption({
      animation: false,
      tooltip: Object.assign({}, tooltipStyle(), {
        trigger: 'axis',
        formatter: function (p) {
          var s = p[0].name + '<br/>';
          p.forEach(function (item) {
            s += item.marker + item.seriesName + ': <b>' + item.value + 'ms</b><br/>';
          });
          return s;
        }
      }),
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: THEME.muted, fontFamily: FONT, fontSize: 12 },
        itemWidth: 14,
        itemHeight: 8,
        itemGap: 16
      },
      grid: { left: 60, right: 40, top: 40, bottom: 40, containLabel: false },
      xAxis: Object.assign({ type: 'category', data: days, boundaryGap: false }, axisStyle()),
      yAxis: Object.assign({
        type: 'value',
        name: '耗时 (ms)',
        nameTextStyle: { color: THEME.muted, fontFamily: FONT, fontSize: 11 }
      }, axisStyle()),
      series: [
        {
          name: '平均耗时',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: avgMs,
          lineStyle: { color: THEME.accent, width: 2.5 },
          itemStyle: { color: THEME.accent },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(37, 99, 235, 0.25)' },
                { offset: 1, color: 'rgba(37, 99, 235, 0.02)' }
              ]
            }
          }
        },
        {
          name: 'P95 耗时',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          data: p95Ms,
          lineStyle: { color: THEME.accent2, width: 2.5, type: 'dashed' },
          itemStyle: { color: THEME.accent2 }
        }
      ]
    });

    window.addEventListener('resize', function () { chart.resize(); });
  }

  // ---------------------------------------------------------------
  // 3) 三阶段里程碑时间线 (条形图)
  // ---------------------------------------------------------------
  function initRoadmap() {
    var el = document.getElementById('chart-roadmap');
    if (!el) return;
    var chart = echarts.init(el, null, { renderer: 'svg' });

    var phases = [
      {
        name: 'Phase 1 · MVP',
        start: 0,
        duration: 2,
        color: THEME.accent,
        desc: 'Postman 基础 + 规则引擎'
      },
      {
        name: 'Phase 2 · AI 增强',
        start: 2,
        duration: 3,
        color: THEME.accent2,
        desc: 'ApiDebugAgent + SSE + 一键应用'
      },
      {
        name: 'Phase 3 · 协作',
        start: 5,
        duration: 4,
        color: THEME.accent3,
        desc: '团队共享 + 向量库 + Prompt 微调'
      }
    ];

    chart.setOption({
      animation: false,
      grid: { left: 140, right: 60, top: 20, bottom: 36, containLabel: false },
      xAxis: {
        type: 'value',
        name: '周 (Week)',
        nameLocation: 'middle',
        nameGap: 24,
        nameTextStyle: { color: THEME.muted, fontFamily: FONT, fontSize: 11 },
        min: 0,
        max: 10,
        interval: 1,
        axisLine: { lineStyle: { color: THEME.rule } },
        axisLabel: { color: THEME.muted, fontFamily: MONO, fontSize: 10 },
        splitLine: { lineStyle: { color: THEME.rule, type: 'dashed' } }
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: phases.map(function (p) { return p.name; }),
        axisLine: { lineStyle: { color: THEME.rule } },
        axisTick: { show: false },
        axisLabel: {
          color: THEME.ink,
          fontFamily: FONT,
          fontSize: 12,
          fontWeight: 600
        }
      },
      tooltip: Object.assign({}, tooltipStyle(), {
        trigger: 'item',
        formatter: function (p) {
          var ph = phases[p.dataIndex];
          var end = ph.start + ph.duration;
          return '<b>' + ph.name + '</b><br/>' +
                 '周期: 第 ' + (ph.start + 1) + ' - ' + end + ' 周 (' + ph.duration + ' 周)<br/>' +
                 '交付: ' + ph.desc;
        }
      }),
      series: [{
        type: 'bar',
        data: phases.map(function (p) {
          return {
            value: [p.start, p.start + p.duration],
            itemStyle: { color: p.color, borderRadius: 4 }
          };
        }),
        barWidth: 22,
        encode: { x: [0, 1], y: 0 },
        label: {
          show: true,
          position: 'right',
          formatter: function (p) {
            return phases[p.dataIndex].duration + ' 周';
          },
          color: THEME.muted,
          fontFamily: MONO,
          fontSize: 11,
          fontWeight: 600
        }
      }]
    });

    window.addEventListener('resize', function () { chart.resize(); });
  }

  // ---------------------------------------------------------------
  // 初始化入口
  // ---------------------------------------------------------------
  function initAll() {
    initStatusCode();
    initDurationTrend();
    initRoadmap();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
