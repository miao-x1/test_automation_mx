/**
 * ApiDataGeneratorAgent 设计文档 - 图表初始化
 *
 * 包含 3 个图表:
 *   1. chart-source-dist  数据生成来源占比 (饼图)
 *   2. chart-type-dist    四种数据类型生成量分布 (饼图)
 *   3. chart-roadmap      三阶段里程碑时间线 (条形图)
 *
 * 所有颜色从 CSS 变量读取,保持与文档主题一致。
 */
(function () {
  'use strict';

  // 兜底: 若 ECharts 未加载则直接退出
  if (typeof window.echarts === 'undefined') {
    console.warn('[charts.js] ECharts 未加载,跳过图表初始化');
    return;
  }

  // ---------------------------------------------------------------
  // 从 CSS 变量读取主题色
  // ---------------------------------------------------------------
  function readVar(name) {
    var raw = getComputedStyle(document.documentElement).getPropertyValue(name);
    return raw ? raw.trim() : '';
  }

  var THEME = {
    bg:       readVar('--bg')       || '#F8FAFC',
    bg2:      readVar('--bg2')      || '#FFFFFF',
    ink:      readVar('--ink')      || '#1E293B',
    muted:    readVar('--muted')    || '#64748B',
    rule:     readVar('--rule')     || '#E2E8F0',
    accent:   readVar('--accent')   || '#2563EB',
    accent2:  readVar('--accent2')  || '#8B5CF6',
    accent3:  readVar('--accent3')  || '#F59E0B',
    success:  readVar('--success')  || '#10B981',
    danger:   readVar('--danger')   || '#EF4444'
  };

  // 通用文字样式
  var FONT_FAMILY = 'Inter, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';
  var MONO_FAMILY = '"JetBrains Mono", Menlo, Consolas, monospace';

  // ---------------------------------------------------------------
  // 1) 数据生成来源占比 (饼图)
  // ---------------------------------------------------------------
  function initSourceDist() {
    var el = document.getElementById('chart-source-dist');
    if (!el) return;

    var chart = echarts.init(el, null, { renderer: 'svg' });

    var data = [
      { name: 'Faker (语义化随机)',       value: 40, itemStyle: { color: THEME.accent  } },
      { name: '规则引擎 (Schema 驱动)',   value: 35, itemStyle: { color: THEME.accent2 } },
      { name: 'LLM (复杂语义推理)',       value: 15, itemStyle: { color: THEME.accent3 } },
      { name: 'DB 字段分析 (历史样本)',   value:  7, itemStyle: { color: THEME.success } },
      { name: 'Runtime 关联取值',         value:  3, itemStyle: { color: THEME.danger  } }
    ];

    chart.setOption({
      animation: false,
      tooltip: {
        trigger: 'item',
        formatter: '{b}<br/>占比: <b>{c}%</b> ({d}%)',
        backgroundColor: THEME.ink,
        borderColor: THEME.ink,
        textStyle: { color: '#FFFFFF', fontFamily: FONT_FAMILY, fontSize: 12 }
      },
      legend: {
        orient: 'horizontal',
        bottom: 0,
        textStyle: { color: THEME.muted, fontFamily: FONT_FAMILY, fontSize: 12 },
        itemWidth: 12,
        itemHeight: 12,
        itemGap: 16
      },
      series: [{
        name: '生成来源',
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: THEME.bg2,
          borderWidth: 3
        },
        label: {
          show: true,
          formatter: '{b|{b}}\n{c|{c}%}',
          rich: {
            b: { color: THEME.ink, fontSize: 12, fontFamily: FONT_FAMILY, lineHeight: 18 },
            c: { color: THEME.muted, fontSize: 11, fontFamily: MONO_FAMILY, fontWeight: 600 }
          }
        },
        labelLine: {
          length: 12,
          length2: 14,
          lineStyle: { color: THEME.rule }
        },
        data: data
      }]
    });

    window.addEventListener('resize', function () { chart.resize(); });
  }

  // ---------------------------------------------------------------
  // 2) 四种数据类型生成量分布 (饼图)
  // ---------------------------------------------------------------
  function initTypeDist() {
    var el = document.getElementById('chart-type-dist');
    if (!el) return;

    var chart = echarts.init(el, null, { renderer: 'svg' });

    // 以 POST /register 接口为例的单接口数据生成量
    var data = [
      { name: '正常数据 (Normal)',     value: 40, itemStyle: { color: THEME.success } },
      { name: '异常数据 (Abnormal)',   value: 25, itemStyle: { color: THEME.danger  } },
      { name: '边界数据 (Boundary)',   value: 25, itemStyle: { color: THEME.accent3 } },
      { name: '关联数据 (Dependent)',  value: 10, itemStyle: { color: THEME.accent  } }
    ];

    chart.setOption({
      animation: false,
      tooltip: {
        trigger: 'item',
        formatter: '{b}<br/>生成量: <b>{c} 条</b> ({d}%)',
        backgroundColor: THEME.ink,
        borderColor: THEME.ink,
        textStyle: { color: '#FFFFFF', fontFamily: FONT_FAMILY, fontSize: 12 }
      },
      legend: {
        orient: 'horizontal',
        bottom: 0,
        textStyle: { color: THEME.muted, fontFamily: FONT_FAMILY, fontSize: 12 },
        itemWidth: 12,
        itemHeight: 12,
        itemGap: 16
      },
      series: [{
        name: '数据类型',
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: THEME.bg2,
          borderWidth: 3
        },
        label: {
          show: true,
          formatter: '{b|{b}}\n{c|{c} 条}',
          rich: {
            b: { color: THEME.ink, fontSize: 12, fontFamily: FONT_FAMILY, lineHeight: 18 },
            c: { color: THEME.muted, fontSize: 11, fontFamily: MONO_FAMILY, fontWeight: 600 }
          }
        },
        labelLine: {
          length: 12,
          length2: 14,
          lineStyle: { color: THEME.rule }
        },
        data: data
      }]
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

    // 阶段数据: 开始周, 持续周数, 阶段名, 关键交付物
    var phases = [
      {
        name: 'Phase 1 · MVP',
        start: 0,
        duration: 2,
        color: THEME.accent,
        desc: '规则引擎 + Faker + Schema 解析'
      },
      {
        name: 'Phase 2 · LLM + DB',
        start: 2,
        duration: 3,
        color: THEME.accent2,
        desc: 'LLM 接入 + 数据库字段分析 + 模板复用'
      },
      {
        name: 'Phase 3 · 高级',
        start: 5,
        duration: 4,
        color: THEME.accent3,
        desc: '关联数据生成 + 异常场景库 + 自适应优化'
      }
    ];

    chart.setOption({
      animation: false,
      grid: {
        left: 140,
        right: 60,
        top: 20,
        bottom: 36,
        containLabel: false
      },
      xAxis: {
        type: 'value',
        name: '周 (Week)',
        nameLocation: 'middle',
        nameGap: 24,
        nameTextStyle: { color: THEME.muted, fontFamily: FONT_FAMILY, fontSize: 11 },
        min: 0,
        max: 10,
        interval: 1,
        axisLine: { lineStyle: { color: THEME.rule } },
        axisLabel: { color: THEME.muted, fontFamily: MONO_FAMILY, fontSize: 10 },
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
          fontFamily: FONT_FAMILY,
          fontSize: 12,
          fontWeight: 600
        }
      },
      tooltip: {
        trigger: 'item',
        formatter: function (p) {
          var idx = p.dataIndex;
          var ph = phases[idx];
          var end = ph.start + ph.duration;
          return '<b>' + ph.name + '</b><br/>' +
                 '周期: 第 ' + (ph.start + 1) + ' - ' + end + ' 周 (' + ph.duration + ' 周)<br/>' +
                 '交付: ' + ph.desc;
        },
        backgroundColor: THEME.ink,
        borderColor: THEME.ink,
        textStyle: { color: '#FFFFFF', fontFamily: FONT_FAMILY, fontSize: 12 }
      },
      series: [{
        type: 'bar',
        data: phases.map(function (p) {
          return {
            value: [p.start, p.start + p.duration],
            itemStyle: {
              color: p.color,
              borderRadius: 4
            }
          };
        }),
        barWidth: 22,
        coordinateSystem: 'cartesian2d',
        encode: {
          x: [0, 1],
          y: 0
        },
        label: {
          show: true,
          position: 'right',
          formatter: function (p) {
            var ph = phases[p.dataIndex];
            return ph.duration + ' 周';
          },
          color: THEME.muted,
          fontFamily: MONO_FAMILY,
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
    initSourceDist();
    initTypeDist();
    initRoadmap();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
