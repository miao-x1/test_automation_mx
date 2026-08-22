/**
 * API 接口管理 - 详情页
 *
 * 路由: /asset/endpoints/:id
 *
 * 功能:
 *   1. 顶部: 接口基本信息(method 标签 / 名称 / 路径 / 状态 / 版本)
 *   2. 操作按钮: 编辑 / 发布 / 状态变更 / 回滚
 *   3. Tab 切换: 概览 / Headers / Params / Body / Response / Auth / 版本历史
 *   4. 版本历史: 列出所有版本,支持查看快照 / 回滚
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Button,
  Tag,
  Space,
  message,
  Typography,
  Descriptions,
  Tabs,
  Table,
  Empty,
  Modal,
  Input,
  Popconfirm,
  Tooltip,
  Spin,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  CloudUploadOutlined,
  RollbackOutlined,
  HistoryOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getEndpoint,
  publishEndpoint,
  listEndpointVersions,
  getEndpointVersion,
  rollbackEndpoint,
  type ApiEndpoint,
  type ApiEndpointVersionItem,
  type ApiEndpointVersionDetail,
  type HTTPMethod,
  type EndpointStatus,
} from '@/services/apiEndpoint';

const { Title, Paragraph, Text } = Typography;

// HTTP 方法对应的颜色
const METHOD_COLOR: Record<HTTPMethod, string> = {
  GET: 'blue',
  POST: 'green',
  PUT: 'orange',
  DELETE: 'red',
  PATCH: 'purple',
  HEAD: 'default',
  OPTIONS: 'default',
};

// 状态对应的颜色 / 文本
const STATUS_META: Record<EndpointStatus, { color: string; text: string }> = {
  draft: { color: 'orange', text: '草稿' },
  active: { color: 'green', text: '已发布' },
  deprecated: { color: 'volcano', text: '已弃用' },
  archived: { color: 'default', text: '已归档' },
};

// JSON 美化展示
function JsonBlock({ value }: { value: unknown }) {
  if (value == null) return <Empty description="无数据" />;
  return (
    <pre
      style={{
        background: '#f5f5f5',
        padding: 12,
        borderRadius: 4,
        fontSize: 13,
        fontFamily: 'monospace',
        overflow: 'auto',
        maxHeight: 400,
        margin: 0,
      }}
    >
      {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

export default function EndpointDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const endpointId = Number(id);

  const [loading, setLoading] = useState(true);
  const [endpoint, setEndpoint] = useState<ApiEndpoint | null>(null);

  // 版本列表
  const [versions, setVersions] = useState<ApiEndpointVersionItem[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);

  // 版本快照弹窗
  const [snapshotVisible, setSnapshotVisible] = useState(false);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshot, setSnapshot] = useState<ApiEndpointVersionDetail | null>(null);

  // 发布弹窗
  const [publishModalVisible, setPublishModalVisible] = useState(false);
  const [changeLog, setChangeLog] = useState('');
  const [publishing, setPublishing] = useState(false);

  // 拉取接口详情
  const fetchEndpoint = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getEndpoint(endpointId);
      setEndpoint(res);
    } catch (e: any) {
      message.error(e?.message || '加载接口详情失败');
      setEndpoint(null);
    } finally {
      setLoading(false);
    }
  }, [endpointId]);

  // 拉取版本列表
  const fetchVersions = useCallback(async () => {
    setVersionsLoading(true);
    try {
      const res = await listEndpointVersions(endpointId);
      setVersions(res || []);
    } catch (e: any) {
      message.error(e?.message || '加载版本列表失败');
      setVersions([]);
    } finally {
      setVersionsLoading(false);
    }
  }, [endpointId]);

  useEffect(() => {
    if (!Number.isFinite(endpointId) || endpointId <= 0) {
      message.error('接口 ID 无效');
      navigate('/asset/endpoints');
      return;
    }
    fetchEndpoint();
  }, [endpointId, fetchEndpoint, navigate]);

  // 查看 版本快照
  const handleViewSnapshot = async (version: number) => {
    setSnapshotVisible(true);
    setSnapshotLoading(true);
    try {
      const res = await getEndpointVersion(endpointId, version);
      setSnapshot(res);
    } catch (e: any) {
      message.error(e?.message || '加载版本快照失败');
    } finally {
      setSnapshotLoading(false);
    }
  };

  // 回滚到版本
  const handleRollback = async (version: number) => {
    try {
      await rollbackEndpoint(endpointId, version);
      message.success(`已回滚到 v${version}`);
      fetchEndpoint();
      fetchVersions();
    } catch (e: any) {
      message.error(e?.message || '回滚失败');
    }
  };

  // 发布
  const handlePublish = async () => {
    setPublishing(true);
    try {
      await publishEndpoint(endpointId, changeLog);
      message.success('发布成功');
      setPublishModalVisible(false);
      setChangeLog('');
      fetchEndpoint();
      fetchVersions();
    } catch (e: any) {
      message.error(e?.message || '发布失败');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!endpoint) {
    return (
      <Card>
        <Empty description="接口不存在或已被删除">
          <Button type="primary" onClick={() => navigate('/asset/endpoints')}>
            返回列表
          </Button>
        </Empty>
      </Card>
    );
  }

  // 版本列表表格列
  const versionColumns = [
    { title: '版本', dataIndex: 'version', width: 80, render: (v: number) => `v${v}` },
    {
      title: '当前',
      dataIndex: 'is_current',
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">当前</Tag> : '-'),
    },
    {
      title: '变更说明',
      dataIndex: 'change_log',
      ellipsis: true,
      render: (t: string | null) => t || '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: ApiEndpointVersionItem) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewSnapshot(record.version)}
          >
            查看快照
          </Button>
          {!record.is_current && (
            <Popconfirm
              title={`确定回滚到 v${record.version}?`}
              description="将创建新版本,当前字段会被覆盖"
              onConfirm={() => handleRollback(record.version)}
              okText="确定"
              cancelText="取消"
            >
              <Button type="link" size="small" icon={<RollbackOutlined />} danger>
                回滚
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ============================================================
  // 数据归一化: 优先使用子表数据 (api_headers / api_parameters / api_body),
  // 旧 JSON 字段 (headers / params / body) 作为回退以保持向后兼容
  // ============================================================

  // 请求头: 优先 api_headers (按 sort_order 排序),回退 headers
  const headers = endpoint.api_headers?.length
    ? endpoint.api_headers
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((h) => ({ key: h.key, value: h.value || '', required: h.required }))
    : endpoint.headers?.map((h) => ({ key: h.key, value: h.value, required: false })) || [];

  // 参数: 优先 api_parameters (按 sort_order 排序),回退 params
  const params = endpoint.api_parameters?.length
    ? endpoint.api_parameters
        .slice()
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((p) => ({
          name: p.name,
          location: p.location,
          type: p.type,
          required: p.required,
          default_value: p.default_value,
          description: p.description,
          example: p.example,
        }))
    : endpoint.params?.map((p) => ({
        name: p.name,
        location: p.location || '',
        type: p.type || '',
        required: p.required || false,
        default_value: p.default ?? null,
        description: p.desc ?? null,
        example: p.example ?? null,
      })) || [];

  // 请求体: 优先 api_body,回退 body
  const bodyData = endpoint.api_body
    ? {
        body_type: endpoint.api_body.body_type,
        schema_json: endpoint.api_body.schema_json,
        example_json: endpoint.api_body.example_json,
        raw_text: endpoint.api_body.raw_text,
      }
    : endpoint.body
      ? {
          body_type: endpoint.body.content_type || 'application/json',
          schema_json: (endpoint.body.json_schema as object) ?? null,
          example_json: (endpoint.body.example as object) ?? null,
          raw_text: endpoint.body.raw ?? null,
        }
      : null;

  // Tab 项
  const tabItems = [
    {
      key: 'overview',
      label: '概览',
      children: (
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="接口名称">{endpoint.name}</Descriptions.Item>
          <Descriptions.Item label="HTTP 方法">
            <Tag color={METHOD_COLOR[endpoint.method]} style={{ fontFamily: 'monospace', fontWeight: 600 }}>
              {endpoint.method}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="路径" span={2}>
            <Text code copyable style={{ fontFamily: 'monospace' }}>
              {endpoint.path}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_META[endpoint.status]?.color}>
              {STATUS_META[endpoint.status]?.text || endpoint.status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="当前版本">v{endpoint.version}</Descriptions.Item>
          <Descriptions.Item label="模块">{endpoint.module || '-'}</Descriptions.Item>
          <Descriptions.Item label="来源">{endpoint.source}</Descriptions.Item>
          <Descriptions.Item label="标签" span={2}>
            {endpoint.tags?.length ? (
              <Space size={4} wrap>
                {endpoint.tags.map((t, i) => <Tag key={i}>{t}</Tag>)}
              </Space>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="摘要" span={2}>
            {endpoint.summary || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="详细说明" span={2}>
            <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
              {endpoint.description || '-'}
            </Paragraph>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {endpoint.created_at ? new Date(endpoint.created_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {endpoint.updated_at ? new Date(endpoint.updated_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
        </Descriptions>
      ),
    },
    {
      key: 'headers',
      label: `请求头 (${headers.length})`,
      children: headers.length ? (
        <Table
          dataSource={headers}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={false}
          columns={[
            { title: 'Key', dataIndex: 'key', width: 240 },
            { title: 'Value', dataIndex: 'value', ellipsis: true },
            {
              title: '必填',
              dataIndex: 'required',
              width: 80,
              render: (v: boolean) => (v ? <Tag color="red">必填</Tag> : <Tag>否</Tag>),
            },
          ]}
        />
      ) : <Empty description="未配置请求头" />,
    },
    {
      key: 'params',
      label: `参数 (${params.length})`,
      children: params.length ? (
        <Table
          dataSource={params}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={false}
          columns={[
            { title: '参数名', dataIndex: 'name', width: 180 },
            { title: '位置', dataIndex: 'location', width: 90 },
            { title: '类型', dataIndex: 'type', width: 100 },
            {
              title: '必填',
              dataIndex: 'required',
              width: 70,
              render: (v: boolean) => (v ? <Tag color="red">必填</Tag> : '-'),
            },
            { title: '默认值', dataIndex: 'default_value', width: 120, render: (t: string | null) => t || '-' },
            { title: '示例', dataIndex: 'example', width: 140, render: (t: string | null) => t || '-' },
            { title: '说明', dataIndex: 'description', render: (t: string | null) => t || '-' },
          ]}
        />
      ) : <Empty description="未配置参数" />,
    },
    {
      key: 'body',
      label: '请求体',
      children: bodyData ? (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Text strong>Body Type</Text>
            <div style={{ marginTop: 8 }}>
              <Tag color="blue">{bodyData.body_type || 'raw'}</Tag>
            </div>
          </div>
          {bodyData.schema_json != null && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>Schema</Text>
              <div style={{ marginTop: 8 }}>
                <JsonBlock value={bodyData.schema_json} />
              </div>
            </div>
          )}
          {bodyData.example_json != null && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>示例</Text>
              <div style={{ marginTop: 8 }}>
                <JsonBlock value={bodyData.example_json} />
              </div>
            </div>
          )}
          {bodyData.raw_text && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>原始文本</Text>
              <div style={{ marginTop: 8 }}>
                <JsonBlock value={bodyData.raw_text} />
              </div>
            </div>
          )}
        </div>
      ) : <Empty description="无请求体" />,
    },
    {
      key: 'response',
      label: '响应',
      children: endpoint.response ? (
        <div>
          <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label="状态码">{endpoint.response.status_code || 200}</Descriptions.Item>
            {endpoint.response.desc && (
              <Descriptions.Item label="说明">{endpoint.response.desc}</Descriptions.Item>
            )}
          </Descriptions>
          {endpoint.response.headers && endpoint.response.headers.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>响应头</Text>
              <div style={{ marginTop: 8 }}>
                <Table
                  dataSource={endpoint.response.headers}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={false}
                  columns={[
                    { title: 'Key', dataIndex: 'key', width: 240 },
                    { title: 'Value', dataIndex: 'value', ellipsis: true },
                  ]}
                />
              </div>
            </div>
          )}
          {endpoint.response.body_schema && (
            <div style={{ marginBottom: 12 }}>
              <Text strong>响应体 Schema</Text>
              <div style={{ marginTop: 8 }}>
                <JsonBlock value={endpoint.response.body_schema} />
              </div>
            </div>
          )}
          {endpoint.response.example != null && (
            <div>
              <Text strong>响应示例</Text>
              <div style={{ marginTop: 8 }}>
                <JsonBlock value={endpoint.response.example} />
              </div>
            </div>
          )}
        </div>
      ) : <Empty description="未配置响应" />,
    },
    {
      key: 'auth',
      label: '认证',
      children: endpoint.auth ? (
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="认证类型">
            <Tag color={endpoint.auth.type === 'none' ? 'default' : 'blue'}>
              {endpoint.auth.type || 'none'}
            </Tag>
          </Descriptions.Item>
          {endpoint.auth.details && (
            <Descriptions.Item label="认证详情">
              <JsonBlock value={endpoint.auth.details} />
            </Descriptions.Item>
          )}
        </Descriptions>
      ) : <Empty description="无认证" />,
    },
    {
      key: 'versions',
      label: (
        <span>
          <HistoryOutlined /> 版本历史
        </span>
      ),
      children: (
        <Table
          dataSource={versions}
          rowKey="id"
          loading={versionsLoading}
          size="small"
          pagination={false}
          columns={versionColumns}
        />
      ),
    },
  ];

  return (
    <div>
      {/* 顶部信息卡 */}
      <Card style={{ marginBottom: 16 }}>
        <Space style={{ marginBottom: 12 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/asset/endpoints')}>返回</Button>
          <Button
            type="primary"
            icon={<EditOutlined />}
            onClick={() => navigate(`/asset/endpoints/${endpoint.id}/edit`)}
          >
            编辑
          </Button>
          {endpoint.status !== 'active' && (
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              onClick={() => setPublishModalVisible(true)}
              disabled={endpoint.status === 'archived'}
            >
              发布
            </Button>
          )}
          {endpoint.status === 'archived' && (
            <Tooltip title="已归档接口需先恢复为草稿才能发布">
              <Button disabled>已归档</Button>
            </Tooltip>
          )}
        </Space>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Tag color={METHOD_COLOR[endpoint.method]} style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 14, padding: '2px 10px' }}>
            {endpoint.method}
          </Tag>
          <Title level={4} style={{ margin: 0 }}>{endpoint.name}</Title>
          <Tag color={STATUS_META[endpoint.status]?.color}>
            {STATUS_META[endpoint.status]?.text || endpoint.status}
          </Tag>
          <Tag>v{endpoint.version}</Tag>
        </div>
        <div style={{ marginTop: 8 }}>
          <Text code copyable style={{ fontFamily: 'monospace', fontSize: 13 }}>
            {endpoint.path}
          </Text>
        </div>
        {endpoint.summary && (
          <Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
            {endpoint.summary}
          </Paragraph>
        )}
      </Card>

      {/* 详情 Tab */}
      <Card>
        <Tabs
          defaultActiveKey="overview"
          items={tabItems}
          onChange={(key) => { if (key === 'versions' && versions.length === 0) fetchVersions(); }}
        />
      </Card>

      {/* 版本快照弹窗 */}
      <Modal
        title={snapshot ? `版本快照 v${snapshot.version}` : '版本快照'}
        open={snapshotVisible}
        onCancel={() => { setSnapshotVisible(false); setSnapshot(null); }}
        footer={null}
        width={800}
      >
        {snapshotLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : snapshot ? (
          <div>
            {snapshot.change_log && (
              <Paragraph type="secondary">变更说明: {snapshot.change_log}</Paragraph>
            )}
            <JsonBlock value={snapshot.snapshot} />
          </div>
        ) : (
          <Empty />
        )}
      </Modal>

      {/* 发布弹窗 */}
      <Modal
        title="发布接口"
        open={publishModalVisible}
        onOk={handlePublish}
        onCancel={() => { setPublishModalVisible(false); setChangeLog(''); }}
        confirmLoading={publishing}
        okText="确认发布"
        cancelText="取消"
      >
        <Paragraph type="secondary">
          发布将生成一个版本快照,接口状态变更为「已发布」。后续修改可基于历史版本回滚。
        </Paragraph>
        <Input.TextArea
          placeholder="变更说明(可选,最多 500 字)"
          value={changeLog}
          onChange={(e) => setChangeLog(e.target.value)}
          maxLength={500}
          rows={3}
          showCount
        />
      </Modal>
    </div>
  );
}
