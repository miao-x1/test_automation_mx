/**
 * 需求模块 - 需求创建
 *
 * 多模态输入（文本/图片/URL/脚本），创建需求任务
 * 输入层：只创建，不执行
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import request from '../../services/request';
import { detectTaskType, TYPE_LABELS } from '../../services/taskTypeDetector';
import { PageHeader } from '../../components/UI';
import { RequirementInput } from '../../components/RequirementInput';

export default function RequirementCreate() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  const handleMultiModalSubmit = useCallback(async (data: {
    text?: string;
    images?: string[];
    urls?: string[];
    script_content?: string;
    script_language?: string;
  }) => {
    const isTextOnly = !!data.text?.trim() && !data.images?.length && !data.urls?.length && !data.script_content?.trim();

    setLoading(true);
    try {
      if (isTextOnly) {
        const typeResult = detectTaskType(data.text!.trim(), '');
        const res: any = await request.post('/requirement/create', {
          requirement: data.text!.trim(),
          image_paths: undefined,
          script_format: 'playwright',
          task_type: typeResult.task_type,
          test_scope: typeResult.test_scope,
        });
        if (res.code === 200 && res.data?.id) {
          message.success(`需求创建成功（AI识别为${TYPE_LABELS[typeResult.task_type]}），跳转到分析页...`);
          navigate(`/requirement/analyze/${res.data.id}`);
        } else {
          message.error(res.message || '创建失败');
        }
      } else {
        // 多模态：直接跳转到分析页，通过SSE处理
        message.success('多模态需求已提交，跳转到分析页...');
        navigate('/requirement/analyze/new', { state: { multimodalData: data } });
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  return (
    <div>
      <PageHeader title="需求创建" subtitle="输入测试需求（文本/图片/URL/脚本），AI自动分析生成测试" icon={<PlusOutlined />} />
      <Card>
        <RequirementInput onSubmit={handleMultiModalSubmit} loading={loading} />
      </Card>
    </div>
  );
}
