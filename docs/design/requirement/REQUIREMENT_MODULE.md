# REQUIREMENT_MODULE.md — 需求模块重构

## 目录结构

```
requirement/
├── RequirementList.tsx       # 需求列表（入口）
├── RequirementCreate.tsx     # 新建需求（多模态输入）
├── RequirementDetail.tsx     # 需求详情（左需求+右分析结果）
├── RequirementAnalyze.tsx    # AI分析（独立页，兼容旧路由）
├── RequirementHistory.tsx    # 需求历史
├── RequirementDecompose.tsx  # 需求分解（兼容旧路由）
└── RequirementToTask.tsx     # 转测试任务（兼容旧路由）
```

## 页面说明

### RequirementList
- 展示所有需求记录
- "详情"按钮导航到 `/requirement/detail/:id`（非独立分析页）
- 支持搜索/删除

### RequirementCreate
- 多模态输入：文本/图片/URL/脚本
- 创建后导航到详情页

### RequirementDetail（核心新增）
- **左栏**：需求内容（ID/需求文本/状态/来源/时间）
- **右栏**：分析结果（AI分析流水线/用例/RAG/Graph）
- "开始AI分析"按钮触发SSE流式分析
- 分析完成后显示"转测试任务"按钮
- **禁止**独立分析页，分析必须进入详情

### RequirementHistory
- 所有需求处理历史记录
- 支持搜索/筛选/删除

## 上传能力

### 统一上传中心（/upload-tasks）

支持类型：
| 类型 | 扩展名 | 说明 |
|------|--------|------|
| PDF | .pdf | 文档解析 |
| Word | .doc/.docx | 文档解析 |
| Swagger | .json/.yaml/.yml | API规范 |
| 视频 | .mp4/.avi | 视频解析 |
| 图片 | .png/.jpg/.jpeg | 图片OCR |
| Schema | .json | 数据Schema |
| URL | - | 网页抓取 |
| 文本 | - | 直接输入 |

### 上传任务模型（upload_task）

```python
class UploadTask:
    id: int                    # 任务ID
    session_id: int            # 关联会话ID
    progress: int              # 进度 0-100
    status: str                # waiting/parsing/generating/completed/failed
    result: dict               # 处理结果
    source_type: str           # pdf/doc/swagger/video/image/schema/url/text
    title: str                 # 任务标题
    case_count: int            # 生成用例数
    error_message: str         # 错误信息
```

### 任务驱动流程

```
1. POST /upload/task/create   → 创建任务（返回task_id）
2. POST /upload/task/{id}/upload → 上传文件
3. POST /upload/task/{id}/start  → 启动处理（触发Pipeline）
4. GET  /upload/task/{id}/stream → SSE实时进度
5. GET  /upload/task/{id}        → 查询状态
6. GET  /upload/task/list        → 任务列表
7. POST /upload/task/{id}/retry  → 失败重试
```

## 前端状态管理

### zustand + persist

```typescript
// stores/uploadStore.ts
export const useUploadStore = create<UploadStoreState>()(
  persist(
    (set, get) => ({
      tasks: [],
      activeTaskId: null,
      loading: false,
      // ... actions
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
```

### 页面切换不丢数据

- zustand persist 自动持久化到 localStorage
- 页面切换时 store 保持
- 刷新页面后从 localStorage 恢复
- SSE监听在页面恢复后自动重连

## 路由

| 路由 | 页面 | 说明 |
|------|------|------|
| /requirement | RequirementList | 需求列表 |
| /requirement/create | RequirementCreate | 新建需求 |
| /requirement/detail/:id | RequirementDetail | 需求详情（左需求+右分析） |
| /requirement/analyze/:id | RequirementAnalyze | AI分析（兼容旧路由） |
| /requirement/history | RequirementHistory | 需求历史 |
| /upload-tasks | UploadTaskCenter | 上传中心 |
| /sessions | SessionCenter | 会话管理 |

## 文件变更

| 文件 | 变更 |
|------|------|
| pages/requirement/RequirementDetail.tsx | **新建** - 需求详情页（左需求+右分析） |
| pages/requirement/RequirementHistory.tsx | **新建** - 需求历史页 |
| pages/requirement/RequirementList.tsx | "分析"→"详情"，导航到detail |
| stores/uploadStore.ts | 添加 zustand persist 持久化 |
| App.tsx | 新增路由/detail/:id和/history，新增import |

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| RequirementAnalyze旧路由仍存在 | 低 | 保留兼容，新入口走Detail |
| localStorage容量限制 | 低 | partialize只存必要字段 |
| SSE重连后进度丢失 | 中 | 从后端fetchTaskStatus恢复 |
