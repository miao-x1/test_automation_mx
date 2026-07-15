/**
 * 上传任务全局 Store（zustand）
 *
 * 核心原则：
 *   - 上传 = Task，不是UI行为
 *   - 所有状态后端托管，store只做缓存
 *   - 页面切换不丢数据
 *   - 刷新页面可恢复（从后端重新加载）
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/** 单个上传任务的状态 */
export interface UploadTaskState {
  task_id: number;
  title: string;
  source_type: string;
  status: 'waiting' | 'parsing' | 'generating' | 'reviewing' | 'completed' | 'failed' | 'l1_designing' | 'l2_compiling';
  error_message?: string;
  compile_level: string;
  case_count: number;
  progress: number;         // 0-100
  progress_msg: string;
  current_step: number;     // 0-4
  created_at?: string;
  updated_at?: string;
}

/** Store状态 */
interface UploadStoreState {
  /** 当前活跃任务列表（从后端同步） */
  tasks: UploadTaskState[];
  /** 当前正在监听SSE的任务ID */
  activeTaskId: number | null;
  /** 加载状态 */
  loading: boolean;

  // ===== Actions =====
  /** 从后端加载任务列表 */
  fetchTasks: () => Promise<void>;
  /** 创建上传任务 */
  createTask: (params: {
    title?: string;
    source_type?: string;
    compile_level?: string;
    use_rag?: boolean;
    case_types?: string[];
    max_cases?: number;
    framework?: string;
    base_url?: string;
  }) => Promise<UploadTaskState>;
  /** 上传文件到任务 */
  uploadFile: (taskId: number, file: File) => Promise<void>;
  /** 启动任务处理 */
  startTask: (taskId: number, params?: { raw_text?: string; url?: string }) => Promise<void>;
  /** 监听任务SSE进度 */
  listenTaskProgress: (taskId: number) => void;
  /** 停止监听SSE */
  stopListening: () => void;
  /** 重试失败任务 */
  retryTask: (taskId: number) => Promise<void>;
  /** 更新单个任务状态（SSE回调） */
  updateTaskProgress: (taskId: number, update: Partial<UploadTaskState>) => void;
  /** 查询单个任务状态 */
  fetchTaskStatus: (taskId: number) => Promise<UploadTaskState>;
}

let eventSourceController: AbortController | null = null;

export const useUploadStore = create<UploadStoreState>()(
  persist(
    (set, get) => ({
      tasks: [],
      activeTaskId: null,
      loading: false,

      fetchTasks: async () => {
        set({ loading: true });
        try {
          const res = await fetch('/api/upload/task/list?limit=50', { credentials: 'include' });
          const data = await res.json();
          const tasks: UploadTaskState[] = (data.items || []).map((t: any) => ({
            task_id: t.task_id,
            title: t.title,
            source_type: t.source_type,
            status: t.status,
            error_message: t.error_message,
            compile_level: t.compile_level || 'l2',
            case_count: t.case_count || 0,
            progress: t.status === 'completed' ? 100 : 0,
            progress_msg: '',
            current_step: t.status === 'completed' ? 4 : 0,
            created_at: t.created_at,
            updated_at: t.updated_at,
          }));
          set({ tasks, loading: false });
        } catch {
          set({ loading: false });
        }
      },

      createTask: async (params) => {
        const res = await fetch('/api/upload/task/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '创建任务失败');

        const task: UploadTaskState = {
          task_id: data.task_id,
          title: data.title || params.title || '',
          source_type: params.source_type || 'text',
          status: 'waiting',
          compile_level: params.compile_level || 'l2',
          case_count: 0,
          progress: 0,
          progress_msg: '任务已创建',
          current_step: 0,
          created_at: data.created_at,
        };

        set(state => ({ tasks: [task, ...state.tasks] }));
        return task;
      },

      uploadFile: async (taskId, file) => {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`/api/upload/task/${taskId}/upload`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '上传失败');

        get().updateTaskProgress(taskId, {
          source_type: data.source_type,
          progress_msg: '文件已上传',
        });
      },

      startTask: async (taskId, params) => {
        const res = await fetch(`/api/upload/task/${taskId}/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params || {}),
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '启动失败');

        get().updateTaskProgress(taskId, {
          status: 'parsing',
          progress: 5,
          progress_msg: '任务已启动',
          current_step: 1,
        });

        get().listenTaskProgress(taskId);
      },

      listenTaskProgress: (taskId) => {
        get().stopListening();
        set({ activeTaskId: taskId });

        eventSourceController = new AbortController();

        (async () => {
          try {
            const response = await fetch(`/api/upload/task/${taskId}/stream`, {
              credentials: 'include',
              signal: eventSourceController!.signal,
            });

            if (!response.ok) return;

            const reader = response.body?.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            if (!reader) return;

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split('\n');
              buffer = lines.pop() || '';

              for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                  const event = JSON.parse(line.slice(6));
                  const { type, payload } = event;

                  const update: Partial<UploadTaskState> = {};

                  switch (type) {
                    case 'parsing':
                      update.current_step = 1;
                      update.progress_msg = payload || '解析输入中...';
                      update.progress = 10;
                      update.status = 'parsing';
                      break;
                    case 'pdf_parsed':
                      update.progress_msg = payload || 'PDF解析完成';
                      update.progress = 15;
                      break;
                    case 'rag_ready':
                      update.progress_msg = payload || 'RAG检索完成';
                      update.progress = 20;
                      break;
                    case 'l1':
                      update.current_step = 2;
                      update.progress_msg = payload || '需求理解中...';
                      update.progress = 30;
                      update.status = 'l1_designing';
                      break;
                    case 'l1_done':
                      update.progress_msg = `设计完成，识别${payload?.feature_count || 0}个功能点`;
                      update.progress = 40;
                      break;
                    case 'l2':
                      update.current_step = 3;
                      update.progress_msg = '用例编译中...';
                      update.progress = 50;
                      update.status = 'l2_compiling';
                      break;
                    case 'case_generated':
                      const caseIdx = payload?.index || 0;
                      update.case_count = caseIdx;
                      update.progress_msg = `已生成第 ${caseIdx} 条用例: ${payload?.title || ''}`;
                      update.progress = 50 + Math.min(caseIdx * 3, 40);
                      break;
                    case 'completed':
                      update.current_step = 4;
                      update.progress = 100;
                      update.status = 'completed';
                      update.case_count = payload?.case_count || 0;
                      update.progress_msg = `完成！共生成 ${payload?.case_count || 0} 条草稿用例`;
                      break;
                    case 'error':
                      update.status = 'failed';
                      update.error_message = payload || '未知错误';
                      update.progress_msg = `失败: ${payload || ''}`;
                      break;
                    case 'heartbeat':
                      break;
                  }

                  if (Object.keys(update).length > 0) {
                    get().updateTaskProgress(taskId, update);
                  }
                } catch {
                  // 忽略解析错误
                }
              }
            }
          } catch (err: any) {
            if (err.name !== 'AbortError') {
              console.error('SSE监听异常:', err);
            }
          }
        })();
      },

      stopListening: () => {
        if (eventSourceController) {
          eventSourceController.abort();
          eventSourceController = null;
        }
        set({ activeTaskId: null });
      },

      retryTask: async (taskId) => {
        const res = await fetch(`/api/upload/task/${taskId}/retry`, {
          method: 'POST',
          credentials: 'include',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '重试失败');

        get().updateTaskProgress(taskId, {
          status: 'waiting',
          error_message: undefined,
          progress: 0,
          progress_msg: '任务已重置',
        });
      },

      updateTaskProgress: (taskId, update) => {
        set(state => ({
          tasks: state.tasks.map(t =>
            t.task_id === taskId ? { ...t, ...update } : t
          ),
        }));
      },

      fetchTaskStatus: async (taskId) => {
        const res = await fetch(`/api/upload/task/${taskId}`, { credentials: 'include' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '查询失败');

        const taskState: UploadTaskState = {
          task_id: data.task_id,
          title: data.title,
          source_type: data.source_type,
          status: data.status,
          error_message: data.error_message,
          compile_level: data.compile_level || 'l2',
          case_count: data.case_count || 0,
          progress: data.status === 'completed' ? 100 : 0,
          progress_msg: '',
          current_step: data.status === 'completed' ? 4 : 0,
          created_at: data.created_at,
          updated_at: data.updated_at,
        };

        get().updateTaskProgress(taskId, taskState);
        return taskState;
      },
    }),
    {
      name: 'upload-store',
      partialize: (state) => ({
        tasks: state.tasks.map(t => ({
          task_id: t.task_id,
          title: t.title,
          source_type: t.source_type,
          status: t.status,
          case_count: t.case_count,
          progress: t.progress,
          progress_msg: t.progress_msg,
          current_step: t.current_step,
          created_at: t.created_at,
        })),
        activeTaskId: state.activeTaskId,
      }),
    }
  )
);
