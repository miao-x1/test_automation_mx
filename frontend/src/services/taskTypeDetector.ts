/**
 * 任务类型自动推断器
 *
 * 从用户输入的自然语言需求中，自动推导测试任务的类型。
 * 严禁让用户选择类型，一切由系统自动判断。
 *
 * 判断依据：
 * - web：涉及页面操作/UI/浏览器/点击/输入/截图/登录/搜索
 * - api：涉及接口/请求/返回值/状态码/JSON/REST/HTTP
 * - performance：涉及压力/并发/响应时间/吞吐量/负载/QPS/TPS
 * - android：涉及移动端/app/手机/安卓/APP/iOS/原生应用
 */

export interface TaskTypeResult {
  task_type: string;
  test_scope: {
    web: boolean;
    api: boolean;
    performance: boolean;
    android: boolean;
  };
  confidence: number;
  reason: string;
}

// 关键词权重表
const KEYWORDS: Record<string, Record<string, number>> = {
  web: {
    '页面': 3, '网页': 3, '浏览器': 3, 'UI': 2, '界面': 2,
    '点击': 2, '输入': 2, '截图': 2, '登录': 1, '搜索': 1,
    '按钮': 2, '表单': 2, '下拉': 1, '弹窗': 2, '导航': 1,
    '滚动': 1, '拖拽': 1, '上传': 1, '下载': 1, '链接': 1,
    '前端': 2, '渲染': 2, '样式': 1, '布局': 1, '交互': 2,
    '购物车': 1, '注册': 1, '提交': 1, '选择': 1, '切换': 1,
    'URL': 2, '网址': 2, '网站': 2,
  },
  api: {
    '接口': 3, 'API': 3, '请求': 3, '返回值': 3, '响应': 2,
    '状态码': 3, 'JSON': 2, 'REST': 3, 'HTTP': 2, 'GET': 2,
    'POST': 2, 'PUT': 2, 'DELETE': 2, 'PATCH': 2,
    '端点': 3, 'endpoint': 3, '参数': 1, '鉴权': 2, 'token': 2,
    '回调': 2, 'webhook': 3, '幂等': 3, '序列化': 2,
    '微服务': 2, '后端': 1, '数据库': 1,
  },
  performance: {
    '性能': 3, '压力': 3, '并发': 3, '响应时间': 3, '吞吐量': 3,
    '负载': 3, 'QPS': 3, 'TPS': 3, '延迟': 2, '吞吐': 2,
    '容量': 2, '瓶颈': 2, '压测': 3, '基准': 2, 'benchmark': 3,
    '高并发': 3, '大流量': 2, '慢查询': 2, '超时率': 2,
    '稳定性': 1, '资源占用': 2, 'CPU': 1, '内存': 1,
  },
  android: {
    'android': 3, '安卓': 3, 'app': 2, 'APP': 2, '移动端': 3,
    '手机': 2, 'iOS': 2, '原生': 2, 'hybrid': 1, '混合开发': 1,
    '小程序': 2, 'H5': 1, '触摸': 2, '滑动': 1, '手势': 2,
    '推送': 2, '通知': 1, '权限': 1, '安装': 1, '卸载': 1,
    '机型': 2, '适配': 1, '扫码': 1,
  },
};

// 强制覆盖规则：某些关键词直接决定类型
const OVERRIDE_RULES: { keywords: string[]; forceType: string }[] = [
  { keywords: ['压力测试', '压测', '负载测试', '并发测试'], forceType: 'performance' },
  { keywords: ['接口测试', 'API测试', '接口自动化'], forceType: 'api' },
  { keywords: ['APP测试', '安卓测试', '移动端测试'], forceType: 'android' },
];

/**
 * 从需求文本自动推断任务类型
 */
export function detectTaskType(requirement: string, additionalInfo?: string): TaskTypeResult {
  const text = `${requirement} ${additionalInfo || ''}`.toLowerCase();
  const scores: Record<string, number> = { web: 0, api: 0, performance: 0, android: 0 };

  // 1. 关键词匹配计分
  for (const [type, keywords] of Object.entries(KEYWORDS)) {
    for (const [keyword, weight] of Object.entries(keywords)) {
      if (text.includes(keyword.toLowerCase())) {
        scores[type] += weight;
      }
    }
  }

  // 2. 强制覆盖规则
  for (const rule of OVERRIDE_RULES) {
    for (const keyword of rule.keywords) {
      if (text.includes(keyword.toLowerCase())) {
        scores[rule.forceType] += 10; // 高权重覆盖
      }
    }
  }

  // 3. 默认回退：如果所有分数都为0，默认为web
  if (Object.values(scores).every(s => s === 0)) {
    scores.web = 1;
  }

  // 4. 确定命中的类型
  const hitTypes = Object.entries(scores)
    .filter(([, score]) => score > 0)
    .map(([type]) => type);

  // 5. 确定主类型
  const maxScore = Math.max(...Object.values(scores));
  const primaryType = Object.entries(scores).find(([, s]) => s === maxScore)?.[0] || 'web';

  // 6. 如果多个类型命中，标记为 hybrid
  const isHybrid = hitTypes.length > 1;
  const taskType = isHybrid ? 'hybrid' : primaryType;

  // 7. 计算置信度
  const totalScore = Object.values(scores).reduce((a, b) => a + b, 0);
  const confidence = totalScore > 0
    ? Math.min(maxScore / totalScore + 0.3, 1.0)
    : 0.5;

  // 8. 生成原因
  const reasons: string[] = [];
  if (scores.web > 0) reasons.push(`Web(${scores.web}分)`);
  if (scores.api > 0) reasons.push(`API(${scores.api}分)`);
  if (scores.performance > 0) reasons.push(`性能(${scores.performance}分)`);
  if (scores.android > 0) reasons.push(`Android(${scores.android}分)`);

  const reason = isHybrid
    ? `混合类型，涉及: ${reasons.join('、')}，主类型: ${primaryType}`
    : `识别为${TYPE_LABELS[primaryType]}(${scores[primaryType]}分)`;

  return {
    task_type: taskType,
    test_scope: {
      web: scores.web > 0,
      api: scores.api > 0,
      performance: scores.performance > 0,
      android: scores.android > 0,
    },
    confidence: Math.round(confidence * 100) / 100,
    reason,
  };
}

export const TYPE_LABELS: Record<string, string> = {
  web: 'Web测试',
  api: '接口测试',
  performance: '性能测试',
  android: 'Android测试',
  hybrid: '混合类型',
};

export const TYPE_COLORS: Record<string, string> = {
  web: 'blue',
  api: 'purple',
  performance: 'orange',
  android: 'green',
  hybrid: 'cyan',
};

export const TYPE_ICONS: Record<string, string> = {
  web: '🌐',
  api: '🔌',
  performance: '⚡',
  android: '📱',
  hybrid: '🔄',
};
