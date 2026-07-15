import request from './request';

/** 分析执行失败原因 */
export function analyzeExecution(executionId: number) {
  return request.post(`/executions/${executionId}/analyze`);
}

/** 获取失败分析结果 */
export function getExecutionAnalysis(executionId: number) {
  return request.get(`/executions/${executionId}/analysis`);
}

/** 获取所有失败执行记录（含分析结果） */
export function listFailedExecutions(skip = 0, limit = 20) {
  return request.get('/executions/analysis/list', { params: { skip, limit } });
}

/** 删除单条失败执行记录 */
export function deleteExecution(executionId: number) {
  return request.delete(`/executions/analysis/${executionId}`);
}

/** 批量删除失败执行记录 */
export function batchDeleteExecutions(ids: number[]) {
  return request.delete('/executions/analysis/batch', { data: { ids } });
}
