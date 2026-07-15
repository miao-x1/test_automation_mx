/**
 * API 测试 - 用例详情抽屉
 * 显示用例完整信息，支持编辑/复制/执行操作
 */
import { useState, useEffect } from 'react';
import { Drawer, Descriptions, Tag, Button, Space, Card, Typography, Spin, message, Divider } from 'antd';
import {
  EditOutlined, CopyOutlined, PlayCircleOutlined,
} from '@ant-design/icons';
import { getCase, ApiCase } from '../../services/apiCase';

const { Text, Paragraph } = Typography;

const PRIORITY_MAP: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高' },
  medium: { color: 'orange', text: '中' },
  low: { color: 'blue', text: '低' },
};

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  ready: { color: 'success', text: '就绪' },
  deprecated: { color: 'warning', text: '废弃' },
};

const METHOD_COLOR: Record<string, string> = {
  GET: '#61affe', POST: '#49cc90', PUT: '#fca130',
  DELETE: '#f93e3e', PATCH: '#50e3c2', HEAD: '#9012fe', OPTIONS: '#0d5aa7',
};

const ASSERTION_TYPE_LABELS: Record<string, string> = {
  equals: '等于',
  not_equals: '不等于',
  contains: '包含',
  not_contains: '不包含',
  not_empty: '非空',
  exists: '存在',
  is_type: '类型检查',
  greater_than: '大于',
  less_than: '小于',
  regex: '正则匹配',
};

interface ApiCaseDetailProps {
  visible: boolean;
  caseId: number | null;
  onClose: () => void;
  onEdit: (caseData: ApiCase) => void;
  onCopy: (id: number) => void;
  onRun: (id: number) => void;
}

export default function ApiCaseDetail({ visible, caseId, onClose, onEdit, onCopy, onRun }: ApiCaseDetailProps) {
  const [caseData, setCaseData] = useState<ApiCase | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (visible && caseId) {
      setLoading(true);
      getCase(caseId)
        .then((res: any) => {
          const data = res?.data || res;
          setCaseData(data);
        })
        .catch(() => {
          message.error('获取用例详情失败');
        })
        .finally(() => setLoading(false));
    } else {
      setCaseData(null);
    }
  }, [visible, caseId]);

  if (!caseData) {
    return (
      <Drawer open={visible} onClose={onClose} width={640} title="用例详情">
        {loading ? <Spin /> : <Text type="secondary">未选择用例</Text>}
      </Drawer>
    );
  }

  return (
    <Drawer
      open={visible}
      onClose={onClose}
      width={640}
      title={`用例详情 - ${caseData.title}`}
      extra={
        <Space>
          <Button icon={<EditOutlined />} onClick={() => onEdit(caseData)}>编辑</Button>
          <Button icon={<CopyOutlined />} onClick={() => onCopy(caseData.id)}>复制</Button>
          <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => onRun(caseData.id)}>执行</Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        {/* 基本信息 */}
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="ID">{caseData.id}</Descriptions.Item>
          <Descriptions.Item label="编号">{caseData.case_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="标题" span={2}>{caseData.title}</Descriptions.Item>
          <Descriptions.Item label="优先级">
            <Tag color={PRIORITY_MAP[caseData.priority]?.color}>
              {PRIORITY_MAP[caseData.priority]?.text || caseData.priority}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_MAP[caseData.status]?.color}>
              {STATUS_MAP[caseData.status]?.text || caseData.status}
            </Tag>
          </Descriptions.Item>
          {caseData.description && (
            <Descriptions.Item label="描述" span={2}>
              <Paragraph style={{ marginBottom: 0 }}>{caseData.description}</Paragraph>
            </Descriptions.Item>
          )}
          {caseData.precondition && (
            <Descriptions.Item label="前置条件" span={2}>
              <Paragraph style={{ marginBottom: 0 }}>{caseData.precondition}</Paragraph>
            </Descriptions.Item>
          )}
          {caseData.tags && (
            <Descriptions.Item label="标签" span={2}>
              {caseData.tags.split(',').map((tag, i) => (
                <Tag key={i}>{tag.trim()}</Tag>
              ))}
            </Descriptions.Item>
          )}
          <Descriptions.Item label="版本">{caseData.version}</Descriptions.Item>
          <Descriptions.Item label="执行次数">{caseData.run_count}</Descriptions.Item>
          <Descriptions.Item label="创建时间" span={2}>{caseData.created_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新时间" span={2}>{caseData.updated_at || '-'}</Descriptions.Item>
        </Descriptions>

        {/* 步骤 */}
        <Divider orientation="left">测试步骤 ({caseData.steps?.length || 0})</Divider>
        {(caseData.steps || []).map((step, i) => (
          <Card key={i} size="small" style={{ marginBottom: 8 }}>
            <Space>
              <Tag color={METHOD_COLOR[step.action] || '#999'}>{step.action}</Tag>
              <Text code>{step.url}</Text>
              {step.timeout && <Text type="secondary">超时: {step.timeout}s</Text>}
            </Space>
            {step.headers && Object.keys(step.headers).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">Headers:</Text>
                <Paragraph>
                  <pre style={{ fontSize: 12, margin: 0, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                    {JSON.stringify(step.headers, null, 2)}
                  </pre>
                </Paragraph>
              </div>
            )}
            {step.body && Object.keys(step.body).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">Body:</Text>
                <Paragraph>
                  <pre style={{ fontSize: 12, margin: 0, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                    {JSON.stringify(step.body, null, 2)}
                  </pre>
                </Paragraph>
              </div>
            )}
            {step.extract && step.extract.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">变量提取:</Text>
                <div style={{ marginTop: 4 }}>
                  {step.extract.map((ex, j) => (
                    <Tag key={j} color="blue" style={{ marginBottom: 4 }}>
                      {ex.key} ← {ex.path}
                    </Tag>
                  ))}
                </div>
              </div>
            )}
          </Card>
        ))}
        {(!caseData.steps || caseData.steps.length === 0) && (
          <Text type="secondary">暂无步骤</Text>
        )}

        {/* 断言 */}
        <Divider orientation="left">断言规则 ({caseData.assertions?.length || 0})</Divider>
        {(caseData.assertions || []).map((a, i) => (
          <Tag key={i} style={{ marginBottom: 4, padding: '4px 8px' }}>
            {ASSERTION_TYPE_LABELS[a.type] || a.type} | {a.path} | {String(a.expected ?? '-')}
          </Tag>
        ))}
        {(!caseData.assertions || caseData.assertions.length === 0) && (
          <Text type="secondary">暂无断言</Text>
        )}
      </Spin>
    </Drawer>
  );
}
