/**
 * API 测试 - 用例导入弹窗
 * 支持 AI 导入和 Swagger 导入
 */
import { useState } from 'react';
import { Modal, Tabs, Input, Button, message, Typography, Space, Alert } from 'antd';
import { ImportOutlined, RobotOutlined, ApiOutlined } from '@ant-design/icons';
import { importFromAI, importFromSwagger } from '../../services/apiCase';

const { TextArea } = Input;
const { Text } = Typography;

interface ApiCaseImportProps {
  visible: boolean;
  onClose: () => void;
  onImported: () => void;
}

export default function ApiCaseImport({ visible, onClose, onImported }: ApiCaseImportProps) {
  const [activeTab, setActiveTab] = useState('ai');
  const [importing, setImporting] = useState(false);

  // AI 导入
  const [taskId, setTaskId] = useState<number | null>(null);

  // Swagger 导入
  const [swaggerContent, setSwaggerContent] = useState('');
  const [baseUrl, setBaseUrl] = useState('');

  const handleAIImport = async () => {
    if (!taskId) { message.warning('请输入 Task ID'); return; }
    setImporting(true);
    try {
      const res = await importFromAI(taskId);
      message.success(`导入成功: ${res.title} (${res.steps_count} 步骤, ${res.assertions_count} 断言)`);
      resetForm();
      onImported();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'AI 导入失败');
    }
    setImporting(false);
  };

  const handleSwaggerImport = async () => {
    if (!swaggerContent.trim()) { message.warning('请粘贴 Swagger/OpenAPI JSON'); return; }
    try {
      JSON.parse(swaggerContent);
    } catch {
      message.warning('JSON 格式不正确，请检查');
      return;
    }
    setImporting(true);
    try {
      const res = await importFromSwagger({ content: swaggerContent, base_url: baseUrl || undefined });
      message.success(`导入成功: 共 ${res.imported} 个用例`);
      resetForm();
      onImported();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'Swagger 导入失败');
    }
    setImporting(false);
  };

  const resetForm = () => {
    setTaskId(null);
    setSwaggerContent('');
    setBaseUrl('');
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  return (
    <Modal
      title={<span><ImportOutlined /> 导入用例</span>}
      open={visible}
      onCancel={handleClose}
      width={700}
      footer={null}
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        {
          key: 'ai',
          label: <span><RobotOutlined /> AI 导入</span>,
          children: (
            <div>
              <Alert
                type="info"
                message="从 AI 生成结果导入测试用例"
                description="输入 AI 任务的 Task ID，系统将从 AI 生成结果中提取并导入测试用例。"
                style={{ marginBottom: 16 }}
                showIcon
              />
              <Space direction="vertical" style={{ width: '100%' }}>
                <div>
                  <Text>Task ID:</Text>
                  <Input
                    type="number"
                    placeholder="请输入 Task ID"
                    value={taskId ?? ''}
                    onChange={e => setTaskId(e.target.value ? Number(e.target.value) : null)}
                    style={{ width: 300, marginTop: 4 }}
                  />
                </div>
                <Button
                  type="primary"
                  icon={<RobotOutlined />}
                  loading={importing}
                  onClick={handleAIImport}
                >
                  开始导入
                </Button>
              </Space>
            </div>
          ),
        },
        {
          key: 'swagger',
          label: <span><ApiOutlined /> Swagger 导入</span>,
          children: (
            <div>
              <Alert
                type="info"
                message="从 Swagger/OpenAPI 规范导入测试用例"
                description="粘贴 Swagger 或 OpenAPI JSON 内容，系统将自动解析接口定义并生成测试用例。"
                style={{ marginBottom: 16 }}
                showIcon
              />
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                <div style={{ width: '100%' }}>
                  <Text>Base URL:</Text>
                  <Input
                    placeholder="https://api.example.com"
                    value={baseUrl}
                    onChange={e => setBaseUrl(e.target.value)}
                    style={{ marginTop: 4 }}
                  />
                </div>
                <div style={{ width: '100%' }}>
                  <Text>Swagger/OpenAPI JSON:</Text>
                  <TextArea
                    rows={12}
                    value={swaggerContent}
                    onChange={e => setSwaggerContent(e.target.value)}
                    placeholder='{"openapi": "3.0.0", ...}'
                    style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 4 }}
                  />
                </div>
                <Button
                  type="primary"
                  icon={<ApiOutlined />}
                  loading={importing}
                  onClick={handleSwaggerImport}
                >
                  开始导入
                </Button>
              </Space>
            </div>
          ),
        },
      ]} />
    </Modal>
  );
}
