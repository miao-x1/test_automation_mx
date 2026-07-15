/**
 * 用户反馈相关API
 */
import request from './request';

/** 提交反馈 */
export const submitFeedback = (data: {
  requirement_id: number;
  score: number;
  comment?: string;
  accepted?: boolean;
}) => request.post('/feedback/submit', data);

/** 基于反馈重新生成 */
export const regenerateFromFeedback = (feedbackId: number) =>
  request.post(`/feedback/${feedbackId}/regenerate`);

/** 获取需求的反馈列表 */
export const getRequirementFeedbacks = (requirementId: number) =>
  request.get(`/feedback/requirement/${requirementId}`);

/** 获取脚本通过率统计 */
export const getFeedbackStats = () =>
  request.get('/feedback/stats');
