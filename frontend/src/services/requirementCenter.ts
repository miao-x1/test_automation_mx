import request from './request';

// ============ RequirementCenter 需求中心 ============

export interface RequirementSession {
  id: number;
  title: string;
  status: string;
  current_step: string;
  input_text: string;
  input_urls: string;
  task_id: number | null;
  final_requirement: string;
  finalized: boolean;
  created_at: string;
}

export interface RequirementFileItem {
  id: number;
  file_name: string;
  file_path: string;
  file_type: string;
  category: string;
  file_ext: string;
  file_size: number;
  mime_type: string;
  parse_status: string;
  sort_order: number;
  created_at: string;
}

export interface RequirementContextData {
  system_name: string;
  business_background: string;
  test_scope: string;
  credentials: any;
  notes: string;
  special_requirements: string;
}

export interface RequirementAnalysisItem {
  id: number;
  agent_name: string;
  agent_display_name: string;
  intent_type: string;
  status: string;
  duration: number;
  input_summary: string;
  output: any;
  error_message: string | null;
  created_at: string;
}

export interface RequirementReviewItem {
  id: number;
  review_round: number;
  status: string;
  completeness_score: number;
  missing_items: string[];
  conflicts: string[];
  suggestions: string[];
  review_summary: string;
  needs_user_input: boolean;
  created_at: string;
}

export interface RequirementSummaryData {
  requirement_text: string;
  page_description: any;
  page_elements: any[];
  business_flows: any[];
  test_goals: any[];
  risk_points: any[];
  recommended_test_types: string[];
  related_pages: string[];
  recommended_strategy: any;
  confidence: number;
  source_agents: string[];
  analysis_count: number;
}

export interface RequirementQuestionItem {
  id: number;
  question_text: string;
  question_type: string;
  category: string;
  options: string[];
  default_answer: string | null;
  required: boolean;
  answer: string | null;
  answered: boolean;
  answered_at: string | null;
}

export interface FullSessionData {
  session: RequirementSession;
  files: RequirementFileItem[];
  context: RequirementContextData | null;
  analyses: RequirementAnalysisItem[];
  reviews: RequirementReviewItem[];
  summary: RequirementSummaryData | null;
  questions: RequirementQuestionItem[];
  steps: any[];
}

// 创建需求会话
export function createSession(data: {
  title?: string;
  input_text?: string;
  input_urls?: string;
  system_name?: string;
  business_background?: string;
  test_scope?: string;
  credentials?: string;
  notes?: string;
  special_requirements?: string;
}) {
  return request.post('/requirement-center/session', data);
}

// 获取会话列表
export function listSessions(limit: number = 20) {
  return request.get('/requirement-center/sessions', { params: { limit } });
}

// 删除会话
export function deleteSession(sessionId: number) {
  return request.delete(`/requirement-center/session/${sessionId}`);
}

// 上传文件
export function uploadFiles(sessionId: number, files: File[]) {
  const formData = new FormData();
  formData.append('session_id', String(sessionId));
  files.forEach((file) => {
    formData.append('files', file);
  });
  return request.post('/requirement-center/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

// 删除文件
export function deleteFile(fileId: number) {
  return request.delete(`/requirement-center/file/${fileId}`);
}

// 保存附加上下文
export function saveContext(sessionId: number, data: {
  system_name: string;
  business_background: string;
  test_scope: string;
  credentials: string;
  notes: string;
  special_requirements: string;
}) {
  const formData = new FormData();
  formData.append('session_id', String(sessionId));
  Object.entries(data).forEach(([key, value]) => {
    formData.append(key, value || '');
  });
  return request.post('/requirement-center/context', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
}

// 开始AI分析（SSE）
export function analyzeRequirement(sessionId: number): EventSource {
  // SSE需要直接使用EventSource，不能用axios
  const url = `/api/requirement-center/analyze`;
  // 由于POST无法直接用EventSource，我们用fetch + ReadableStream
  // 返回一个伪EventSource替代
  return new EventSource(url + `?session_id=${sessionId}`) as any;
}

// 使用fetch处理SSE
export async function* analyzeStream(sessionId: number): AsyncGenerator<any> {
  const response = await fetch('/api/requirement-center/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data:')) {
        try {
          const jsonStr = line.slice(5).trim();
          if (jsonStr) {
            yield JSON.parse(jsonStr);
          }
        } catch (e) {
          // skip invalid JSON
        }
      }
    }
  }
}

// 提交评审回答
export function submitReview(sessionId: number, answers: { question_id: number; answer: string }[]) {
  return request.post('/requirement-center/review', { session_id: sessionId, answers });
}

// 最终化需求
export function finalizeRequirement(sessionId: number, finalRequirement: string) {
  return request.post('/requirement-center/finalize', {
    session_id: sessionId,
    final_requirement: finalRequirement,
  });
}

// 获取完整会话信息
export function getFullSession(sessionId: number) {
  return request.get(`/requirement-center/session/${sessionId}`);
}

// 获取需求详情
export function getRequirement(id: number) {
  return request.get(`/requirement-center/${id}`);
}
