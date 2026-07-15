import request from './request';

// ============ 知识库管理 ============

// 元素库
export const getElements = (params: any) => request.get('/kb/elements', { params });
export const getElement = (id: number) => request.get(`/kb/elements/${id}`);
export const updateElement = (id: number, data: any) => request.put(`/kb/elements/${id}`, data);
export const deleteElement = (id: number) => request.delete(`/kb/elements/${id}`);
export const batchDeleteElements = (ids: number[]) => request.post('/kb/elements/batch-delete', { ids });
export const reindexElement = (id: number) => request.post(`/kb/elements/${id}/reindex`);
export const approveElement = (id: number) => request.post(`/kb/elements/${id}/approve`);
export const rejectElement = (id: number) => request.post(`/kb/elements/${id}/reject`);

// 用例库
export const getCases = (params: any) => request.get('/kb/cases', { params });
export const getCase = (id: number) => request.get(`/kb/cases/${id}`);
export const updateCase = (id: number, data: any) => request.put(`/kb/cases/${id}`, data);
export const deleteCase = (id: number) => request.delete(`/kb/cases/${id}`);
export const batchDeleteCases = (ids: number[]) => request.post('/kb/cases/batch-delete', { ids });
export const reindexCase = (id: number) => request.post(`/kb/cases/${id}/reindex`);
export const approveCase = (id: number) => request.post(`/kb/cases/${id}/approve`);
export const rejectCase = (id: number) => request.post(`/kb/cases/${id}/reject`);

// 脚本库
export const getScripts = (params: any) => request.get('/kb/scripts', { params });
export const getScript = (id: number) => request.get(`/kb/scripts/${id}`);
export const updateScript = (id: number, data: any) => request.put(`/kb/scripts/${id}`, data);
export const deleteScript = (id: number) => request.delete(`/kb/scripts/${id}`);
export const batchDeleteScripts = (ids: number[]) => request.post('/kb/scripts/batch-delete', { ids });
export const reindexScript = (id: number) => request.post(`/kb/scripts/${id}/reindex`);
export const approveScript = (id: number) => request.post(`/kb/scripts/${id}/approve`);
export const rejectScript = (id: number) => request.post(`/kb/scripts/${id}/reject`);

// 统计
export const getKBStatistics = () => request.get('/kb/statistics');

// 去重
export const detectDuplicates = () => request.post('/kb/detect-duplicates');
export const deduplicate = () => request.post('/kb/deduplicate');
