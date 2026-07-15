import request from './request';

export interface PageElement {
  id: number;
  tag_name: string;
  element_text: string | null;
  element_id: string | null;
  element_class: string | null;
  element_name: string | null;
  placeholder: string | null;
  href: string | null;
  aria_label: string | null;
  role: string | null;
  xpath: string | null;
  css_selector: string | null;
}

// 创建页面抓取任务
export function createCrawlTask(url: string, task_name?: string) {
  return request.post('/page/crawl', { url, task_name });
}

// 获取页面元素列表
export function getPageElements(taskId: number) {
  return request.get(`/page/${taskId}/elements`);
}
