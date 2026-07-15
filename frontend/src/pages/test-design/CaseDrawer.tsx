import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Drawer, Descriptions, Tag, Badge, Card, Button, Space, message, Table, Empty, Dropdown } from 'antd';
import {
  ApiOutlined, GlobalOutlined, AndroidOutlined, DesktopOutlined,
  CheckCircleOutlined, PlayCircleOutlined, ExportOutlined, DownOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { runCase } from './constants';

/** 推荐目标映射：根据 asset_type 自动识别 */
const importTargetMap: Record<string, { key: string; label: string; icon: React.ReactNode; path: string }[]> = {
  api: [
    { key: 'api-test', label: '接口测试', icon: <ApiOutlined />, path: '/api-test/cases' },
    { key: 'web', label: 'Web自动化', icon: <GlobalOutlined />, path: '/web/create' },
  ],
  web: [
    { key: 'web', label: 'Web自动化', icon: <GlobalOutlined />, path: '/web/create' },
    { key: 'api-test', label: '接口测试', icon: <ApiOutlined />, path: '/api-test/cases' },
  ],
  android: [
    { key: 'android', label: 'Android', icon: <AndroidOutlined />, path: '/android' },
    { key: 'api-test', label: '接口测试', icon: <ApiOutlined />, path: '/api-test/cases' },
  ],
  manual: [
    { key: 'api-test', label: '接口测试', icon: <ApiOutlined />, path: '/api-test/cases' },
    { key: 'web', label: 'Web自动化', icon: <GlobalOutlined />, path: '/web/create' },
  ],
};

const assetTypeConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  api: { color: 'blue', icon: <ApiOutlined />, label: 'API测试' },
  web: { color: 'green', icon: <GlobalOutlined />, label: 'Web测试' },
  android: { color: 'orange', icon: <AndroidOutlined />, label: 'Android测试' },
  manual: { color: 'purple', icon: <DesktopOutlined />, label: '通用用例' },
};

const statusConfig: Record<string, { color: string; label: string; badge: 'default' | 'processing' | 'success' | 'warning' | 'error' }> = {
  draft: { color: 'default', label: '草稿', badge: 'default' },
  reviewed: { color: 'purple', label: '已审查', badge: 'processing' },
  published: { color: 'success', label: '已发布', badge: 'success' },
  executed: { color: 'green', label: '已执行', badge: 'success' },
  failed: { color: 'error', label: '失败', badge: 'error' },
};

const sourceConfig: Record<string, { color: string; label: string }> = {
  ai: { color: 'purple', label: 'AI生成' },
  manual: { color: 'blue', label: '手动创建' },
  swagger: { color: 'cyan', label: 'Swagger' },
  import: { color: 'geekblue', label: '导入' },
  reused: { color: 'gold', label: '复用' },
};

interface Step {
  action?: string;
  url?: string;
  method?: string;
  headers?: Record<string, string>;
  body?: any;
  timeout?: number;
}

interface Assertion {
  path?: string;
  operator?: string;
  expected?: any;
}

interface Props {
  assetId: number | null;
  visible: boolean;
  onClose: () => void;
  onRefresh?: () => void;
}

export default function CaseDrawer({ assetId, visible, onClose, onRefresh }: Props) {
  const navigate = useNavigate();
  const [asset, setAsset] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);

  useEffect(() => {
    if (assetId && visible) {
      setLoading(true);
      fetch(`/api/assets/v2/${assetId}`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => setAsset(data))
        .catch(() => message.error('获取详情失败'))
        .finally(() => setLoading(false));
    } else {
      setAsset(null);
    }
  }, [assetId, visible]);

  const handlePublish = async () => {
    if (!assetId) return;
    try {
      const res = await fetch('/api/assets/v2/publish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ asset_ids: [assetId] }),
      });
      const data = await res.json();
      if (data.published) {
        message.success('发布成功');
        onRefresh?.();
        onClose();
      }
    } catch {
      message.error('发布失败');
    }
  };

  const handleExecute = async () => {
    if (!assetId) return;
    setExecuting(true);
    try {
      const result = await runCase(assetId);
      message.success(`执行已提交 (ID: ${result.execution_id})`);
      onRefresh?.();
    } catch (e: any) {
      message.error(e?.message || '执行失败');
    } finally {
      setExecuting(false);
    }
  };

  // 解析 content
  const content = asset?.content_json || asset?.draft_content || asset?.published_content;
  const parsedContent = typeof content === 'string' ? (() => { try { return JSON.parse(content); } catch { return null; } })() : content;
  const steps: Step[] = parsedContent?.steps || [];
  const assertions: Assertion[] = parsedContent?.assertions || [];
  const preconditions: string[] = parsedContent?.preconditions || [];
  const expectedResult: string = parsedContent?.expected_result || '';
  const isExecutable = asset?.executable || (steps.length > 0 && assertions.length > 0);

  const stepColumns: ColumnsType<Step> = [
    { title: '#', width: 40, render: (_: any, __: any, i: number) => i + 1 },
    { title: '操作', dataIndex: 'action', width: 120, ellipsis: true },
    { title: '方法', dataIndex: 'method', width: 70, render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-' },
    { title: 'URL', dataIndex: 'url', ellipsis: true },
  ];

  const assertionColumns: ColumnsType<Assertion> = [
    { title: '#', width: 40, render: (_: any, __: any, i: number) => i + 1 },
    { title: '路径', dataIndex: 'path', width: 150, ellipsis: true },
    { title: '操作符', dataIndex: 'operator', width: 80, render: (v: string) => <Tag>{v || 'eq'}</Tag> },
    { title: '预期值', dataIndex: 'expected', width: 120, render: (v: any) => String(v ?? '-') },
  ];

  return (
    <Drawer
      title={asset?.title || '用例详情'}
      placement="right"
      width={720}
      open={visible}
      onClose={onClose}
      loading={loading}
      extra={
        asset && (
          <Space>
            {asset.status === 'draft' && (
              <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={handlePublish}>
                发布
              </Button>
            )}
            {isExecutable && (
              <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={handleExecute} loading={executing}>
                立即执行
              </Button>
            )}
            {asset.status === 'published' && (
              <Dropdown menu={{
                items: (importTargetMap[asset.asset_type] || importTargetMap.manual).map(t => ({
                  key: t.key,
                  icon: t.icon,
                  label: t.label,
                  onClick: () => navigate(t.path),
                })),
              }}>
                <Button size="small" icon={<ExportOutlined />}>
                  导入到 <DownOutlined />
                </Button>
              </Dropdown>
            )}
          </Space>
        )
      }
    >
      {asset && (
        <div>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="ID">{asset.id}</Descriptions.Item>
            <Descriptions.Item label="标题">{asset.title}</Descriptions.Item>
            <Descriptions.Item label="类型">
              <Tag color={assetTypeConfig[asset.asset_type]?.color || 'blue'}>
                {assetTypeConfig[asset.asset_type]?.label || asset.asset_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge status={statusConfig[asset.status]?.badge || 'default'} text={statusConfig[asset.status]?.label || asset.status} />
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              <Tag color={sourceConfig[asset.source_type || asset.source]?.color || 'default'}>
                {sourceConfig[asset.source_type || asset.source]?.label || asset.source_type || asset.source}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="优先级">
              <Tag color={asset.priority === 'P0' ? 'red' : asset.priority === 'P1' ? 'orange' : 'blue'}>
                {asset.priority}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="可执行">
              <Tag color={isExecutable ? 'success' : 'error'}>{isExecutable ? '是' : '否'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="版本">{asset.version}</Descriptions.Item>
          </Descriptions>

          {/* 前置条件 */}
          {preconditions.length > 0 && (
            <Card title="前置条件" size="small" style={{ marginTop: 16 }}>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {preconditions.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </Card>
          )}

          {/* 步骤 */}
          <Card title={`步骤 (${steps.length})`} size="small" style={{ marginTop: 16 }}>
            {steps.length > 0 ? (
              <Table dataSource={steps} columns={stepColumns} rowKey={(_: any, i?: number) => String(i ?? 0)} pagination={false} size="small" />
            ) : (
              <Empty description="暂无步骤" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>

          {/* 断言 */}
          <Card title={`断言 (${assertions.length})`} size="small" style={{ marginTop: 16 }}>
            {assertions.length > 0 ? (
              <Table dataSource={assertions} columns={assertionColumns} rowKey={(_: any, i?: number) => String(i ?? 0)} pagination={false} size="small" />
            ) : (
              <Empty description="暂无断言" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>

          {/* 预期结果 */}
          {expectedResult && (
            <Card title="预期结果" size="small" style={{ marginTop: 16 }}>
              <p style={{ margin: 0 }}>{expectedResult}</p>
            </Card>
          )}

          {/* 执行状态 */}
          {asset.execution_state && (
            <Card title="执行状态" size="small" style={{ marginTop: 16 }}>
              <pre style={{ maxHeight: 200, overflow: 'auto', fontSize: 12, background: '#f5f5f5', padding: 8, borderRadius: 4 }}>
                {typeof asset.execution_state === 'string' ? asset.execution_state : JSON.stringify(asset.execution_state, null, 2)}
              </pre>
            </Card>
          )}
        </div>
      )}
    </Drawer>
  );
}
