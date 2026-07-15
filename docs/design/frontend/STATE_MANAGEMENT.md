# STATE_MANAGEMENT.md — 前端状态治理

## 删除

- 页面state存业务数据（改用zustand store）

## 新增 stores/

| Store | 用途 | 持久化 |
|-------|------|--------|
| assetStore | 测试用例状态 | 是 |
| uploadStore | 上传任务状态 | 是 |
| executionStore | 执行状态 | 是 |
| sessionStore | 会话状态 | 否 |

## 使用：zustand + persist

```typescript
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useAssetStore = create<AssetStoreState>()(
  persist(
    (set, get) => ({
      assets: [],
      filters: {},
      loading: false,
      // actions...
    }),
    {
      name: 'asset-store',
      partialize: (state) => ({
        assets: state.assets,
        filters: state.filters,
      }),
    }
  )
);
```

## 刷新恢复

```
1. 页面加载 → zustand从localStorage恢复
2. 后台异步fetch最新数据
3. 合并本地缓存和服务器数据
4. 页面切换不丢数据
```

## 各Store定义

### assetStore
```typescript
interface AssetStoreState {
  assets: AssetItem[];
  filters: { status?: string; type?: string; keyword?: string };
  loading: boolean;
  fetchAssets: (filters?) => Promise<void>;
  updateAsset: (id: number, update: Partial<AssetItem>) => void;
}
```

### uploadStore（已完成）
```typescript
interface UploadStoreState {
  tasks: UploadTaskState[];
  activeTaskId: number | null;
  loading: boolean;
  fetchTasks: () => Promise<void>;
  createTask: (params) => Promise<UploadTaskState>;
  // ...
}
```

### executionStore
```typescript
interface ExecutionStoreState {
  executions: ExecutionRecord[];
  activeExecutionId: number | null;
  loading: boolean;
  fetchExecutions: () => Promise<void>;
  updateExecution: (id: number, update: Partial<ExecutionRecord>) => void;
}
```

### sessionStore
```typescript
interface SessionStoreState {
  sessions: SessionItem[];
  activeSessionId: number | null;
  loading: boolean;
  fetchSessions: () => Promise<void>;
}
```

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| localStorage容量 | 低 | partialize只存必要字段 |
| 数据不一致 | 中 | 后台异步fetch覆盖 |
| persist序列化失败 | 低 | 使用JSON兼容类型 |
