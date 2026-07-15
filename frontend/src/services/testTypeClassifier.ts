/**
 * 测试类型智能识别服务
 *
 * 对接后端 POST /api/v1/classify 接口，
 * 根据用户需求自动判断测试类型、平台、框架。
 */

import request from './request';

const BASE = '/api/v1';

/** 分类请求参数 */
export interface ClassifyRequest {
  requirement: string;
  urls?: string[];
  script_content?: string;
  script_language?: string;
  images?: string[];
  swagger_content?: string;
  db_schema?: string;
  page_info?: string;
  use_llm?: boolean;
}

/** 分类响应结果 */
export interface ClassifyResult {
  test_type: 'web' | 'api' | 'android' | 'performance';
  platform: 'browser' | 'mobile' | 'server';
  framework: 'playwright' | 'appium' | 'pytest' | 'jmeter';
  confidence: number;
  reason: string;
  scores: Record<string, number>;
  detected_signals: string[];
}

/** 测试类型标签 */
export const TEST_TYPE_LABELS: Record<string, string> = {
  web: 'Web自动化测试',
  api: 'API接口测试',
  android: 'Android移动端测试',
  performance: '性能测试',
};

/** 测试类型颜色 */
export const TEST_TYPE_COLORS: Record<string, string> = {
  web: 'blue',
  api: 'purple',
  android: 'green',
  performance: 'orange',
};

/** 测试类型图标 */
export const TEST_TYPE_ICONS: Record<string, string> = {
  web: '🌐',
  api: '🔌',
  android: '📱',
  performance: '⚡',
};

/** 平台标签 */
export const PLATFORM_LABELS: Record<string, string> = {
  browser: '浏览器',
  mobile: '移动端',
  server: '服务端',
};

/** 框架标签 */
export const FRAMEWORK_LABELS: Record<string, string> = {
  playwright: 'Playwright',
  appium: 'Appium',
  pytest: 'Pytest',
  jmeter: 'JMeter',
};

/**
 * 调用后端AI智能识别测试类型
 */
export async function classifyTestType(req: ClassifyRequest): Promise<ClassifyResult> {
  const res = await request.post(`${BASE}/classify`, req);
  return res.data;
}

/**
 * 生成中文展示文本
 * 例如: "AI判断该需求为Web自动化测试，准确率96%"
 */
export function formatClassificationText(result: ClassifyResult): string {
  const typeLabel = TEST_TYPE_LABELS[result.test_type] || result.test_type;
  const confidencePercent = Math.round(result.confidence * 100);
  return `AI判断该需求为${typeLabel}，准确率${confidencePercent}%`;
}
