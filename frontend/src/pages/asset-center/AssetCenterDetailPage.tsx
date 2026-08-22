/**
 * 测试资产中心 - 资产详情页
 *
 * 路由: /asset/center/:id
 *
 * 功能:
 *   1. Tabs 组织: 基本信息 / 版本历史 / 关系列表 / 影响面分析
 *   2. 顶部操作: 编辑 / 发布 / 状态变更 / 删除
 *   3. 发布弹窗(输入 change_log)
 *   4. 版本回滚(选择历史版本)
 *   5. 关系列表(出入边)
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Tabs,
  Button,
  Tag,
  Space,
  Descriptions,
  message,
  Typography,
  Modal,
  Input,
  Form,
  Select,
  Table,
  Popconfirm,
  Empty,
  Statistic,
  Row,
  Col,
  Divider,
  Tooltip,
  Alert,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  CloudUploadOutlined,
  RollbackOutlined,
  DeleteOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getAsset,
  listAssetVersions,
  getAssetVersion,
  rollbackAsset,
  publishAsset,
  changeAssetStatus,
  deleteAsset,
  markAssetUsed,
  listRelations,
  analyzeImpact,
  type Asset,
  type AssetVersionItem,
  type AssetVersionDetail,
  type AssetRelation,
  type AssetStatus,
  type ImpactResult,
} from '@/services/assetCenter';

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

// 状态对应的颜色 / 文本
const STATUS_META: Record<AssetStatus, { color: string; text: string }> = {
  draft: { color: 'orange', text: '草稿' },
  active: { color: 'green', text: '已发布' },
  deprecated: { color: 'volcano', text: '已弃用' },
  archived: { color: 'default', text: '已归档' },
};

// 资产类型中文名
const ASSET_TYPE_TEXT: Record<string, string> = {
  api_endpoint: 'API 接口',
  ui_element: 'UI 元素',
  test_case: '测试用例',
  test_asset: '测试资产',
  script: '测试脚本',
  test_data: '测试数据',
  test_report: '测试报告',
  requirement: '需求',
};

// 变更类型中文
const CHANGE_TYPE_TEXT: Record<string, string> = {
  create: '创建',
  update: '更新',
  rollback: '回滚',
  status_change: '状态变更',
};

export default function AssetCenterDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const assetId = Number(id);

  const [loading, setLoading] = useState(false);
  const [asset, setAsset] = useState<Asset | null>(null);

  // 版本
  const [versions, setVersions] = useState<AssetVersionItem[]>([]);
  const [versionsTotal, setVersionsTotal] = useState(0);
  const [versionModalOpen, setVersionModalOpen] = useState(false);
  const [versionDetail, setVersionDetail] = useState<AssetVersionDetail | null>(null);

  // 发布 Modal
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishForm] = Form.useForm();
  const [publishing, setPublishing] = useState(false);

  // 状态变更 Modal
  const [statusModalOpen, setStatusModalOpen] = useState(false);
  const [statusForm] = Form.useForm();

  // 关系列表
  const [relations, setRelations] = useState<AssetRelation[]>([]);
  const [relationsTotal, setRelationsTotal] = useState(0);
  const [relationsLoading, setRelationsLoading] = useState(false);

  // 影响面分析
  const [impact, setImpact] = useState<ImpactResult | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactDepth, setImpactDepth] = useState(2);

  // 拉取资产详情
  const fetchAsset = useCallback(async () => {
    if (!assetId) return;
    setLoading(true);
    try {
      const res = await getAsset(assetId);
      setAsset(res);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载资产详情失败');
    } finally {
      setLoading(false);
    }
  }, [assetId]);

  // 拉取版本列表
  const fetchVersions = useCallback(async () => {
    if (!assetId) return;
    try {
      const res = await listAssetVersions(assetId, { page: 1, page_size: 50 });
      setVersions(res?.items || []);
      setVersionsTotal(res?.total || 0);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载版本列表失败');
    }
  }, [assetId]);

  // 拉取关系列表
  const fetchRelations = useCallback(async () => {
    if (!assetId) return;
    setRelationsLoading(true);
    try {
      const res = await listRelations({ asset_id: assetId, page: 1, page_size: 50 });
      setRelations(res?.items || []);
      setRelationsTotal(res?.total || 0);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载关系列表失败');
    } finally {
      setRelationsLoading(false);
    }
  }, [assetId]);

  // 拉取影响面分析
  const fetchImpact = useCallback(async (depth: number = 2) => {
    if (!assetId) return;
    setImpactLoading(true);
    try {
      const res = await analyzeImpact(assetId, depth);
      setImpact(res);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '影响面分析失败');
    } finally {
      setImpactLoading(false);
    }
  }, [assetId]);

  useEffect(() => {
    fetchAsset();
    fetchVersions();
    fetchRelations();
  }, [fetchAsset, fetchVersions, fetchRelations]);

  // 操作: 发布
  const handlePublish = async () => {
    try {
      const values = await publishForm.validateFields();
      setPublishing(true);
      await publishAsset(assetId, {
        change_log: values.change_log || '',
        change_type: 'update',
      });
      message.success('发布成功');
      setPublishModalOpen(false);
      publishForm.resetFields();
      fetchAsset();
      fetchVersions();
    } catch (e: unknown) {
      if ((e as { errorFields?: unknown })?.errorFields) return;
      const err = e as { message?: string };
      message.error(err?.message || '发布失败');
    } finally {
      setPublishing(false);
    }
  };

  // 操作: 状态变更
  const handleStatusChange = async () => {
    try {
      const values = await statusForm.validateFields();
      await changeAssetStatus(assetId, {
        target_status: values.target_status,
        reason: values.reason,
      });
      message.success('状态已更新');
      setStatusModalOpen(false);
      statusForm.resetFields();
      fetchAsset();
      fetchVersions();
    } catch (e: unknown) {
      if ((e as { errorFields?: unknown })?.errorFields) return;
      const err = e as { message?: string };
      message.error(err?.message || '状态变更失败');
    }
  };

  // 操作: 标记使用
  const handleMarkUsed = async () => {
    try {
      await markAssetUsed(assetId);
      message.success('已标记为使用');
      fetchAsset();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '标记失败');
    }
  };

  // 操作: 回滚
  const handleRollback = async (version: number) => {
    try {
      await rollbackAsset(assetId, version);
      message.success(`已回滚到 v${version}`);
      fetchAsset();
      fetchVersions();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '回滚失败');
    }
  };

  // 操作: 查看版本详情
  const handleViewVersion = async (version: number) => {
    try {
      const res = await getAssetVersion(assetId, version);
      setVersionDetail(res);
      setVersionModalOpen(true);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载版本详情失败');
    }
  };

  // 操作: 删除
  const handleDelete = async () => {
    try {
      await deleteAsset(assetId);
      message.success('删除成功');
      navigate('/asset/center');
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '删除失败');
    }
  };

  if (loading && !asset) {
    return <Card loading={loading} />;
  }

  if (!asset) {
    return (
      <Card>
        <Empty description="资产不存在或已被删除" />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button onClick={() => navigate('/asset/center')} icon={<ArrowLeftOutlined />}>
            返回列表
          </Button>
        </div>
      </Card>
    );
  }

  const statusMeta = STATUS_META[asset.status as AssetStatus] || { color: 'default', text: asset.status };
  const canPublish = asset.status === 'draft' || asset.status === 'deprecated';

  // 版本表格列
  const versionColumns = [
    { title: '版本', dataIndex: 'version', width: 80, render: (v: number) => <span style={{ fontWeight: 600 }}>v{v}</span> },
    {
      title: '类型',
      dataIndex: 'change_type',
      width: 100,
      render: (t: string) => <Tag>{CHANGE_TYPE_TEXT[t] || t}</Tag>,
    },
    { title: '变更说明', dataIndex: 'change_log', ellipsis: true, render: (t: string | null) => t || '-' },
    {
      title: '当前版本',
      dataIndex: 'is_current',
      width: 100,
      render: (v: boolean) => v ? <Tag color="green">当前</Tag> : <span style={{ color: '#bfbfbf' }}>-</span>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: AssetVersionItem) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => handleViewVersion(record.version)}>
            查看快照
          </Button>
          {!record.is_current && (
            <Popconfirm
              title={`确认回滚到 v${record.version}?`}
              description="回滚会创建新版本,不可变字段不恢复"
              onConfirm={() => handleRollback(record.version)}
              okText="确认"
              cancelText="取消"
            >
              <Button type="link" size="small" danger icon={<RollbackOutlined />}>
                回滚
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // 关系表格列
  const relationColumns = [
    {
      title: '方向',
      key: 'direction',
      width: 80,
      render: (_: unknown, record: AssetRelation) => (
        <Tag color={record.source_id === assetId ? 'blue' : 'green'}>
          {record.source_id === assetId ? '出' : '入'}
        </Tag>
      ),
    },
    {
      title: '关系类型',
      dataIndex: 'relation_type',
      width: 130,
      render: (t: string) => <Tag color="purple">{t}</Tag>,
    },
    {
      title: '对端资产',
      key: 'peer',
      render: (_: unknown, record: AssetRelation) => {
        const peer = record.source_id === assetId ? record.target_asset : record.source_asset;
        return peer ? (
          <Tooltip title={`${peer.ref_type} #${peer.ref_id}`}>
            <a onClick={() => peer.asset_id && navigate(`/asset/center/${peer.asset_id}`)}>
              {peer.name || peer.asset_code || `资产 #${peer.asset_id || '?'}`}
            </a>
          </Tooltip>
        ) : <span style={{ color: '#bfbfbf' }}>-</span>;
      },
    },
    {
      title: '权重',
      dataIndex: 'weight',
      width: 80,
      align: 'center' as const,
      render: (w: number) => <span>{w?.toFixed(2)}</span>,
    },
    {
      title: 'Neo4j 同步',
      dataIndex: 'neo4j_synced',
      width: 110,
      render: (s: boolean) => s ? <Tag color="green">已同步</Tag> : <Tag color="orange">待同步</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
  ];

  // 影响面资产列表
  const impactColumns = [
    {
      title: '资产',
      key: 'asset',
      render: (_: unknown, record: ImpactResult['impacted'][number]) => {
        const a = record.asset;
        return (
          <a onClick={() => a.asset_id && navigate(`/asset/center/${a.asset_id}`)}>
            {a.name || a.asset_code || `资产 #${a.asset_id || '?'}`}
          </a>
        );
      },
    },
    {
      title: '类型',
      key: 'type',
      width: 110,
      render: (_: unknown, record: ImpactResult['impacted'][number]) => (
        <Tag>{ASSET_TYPE_TEXT[record.asset.ref_type] || record.asset.ref_type}</Tag>
      ),
    },
    {
      title: '深度',
      dataIndex: 'depth',
      width: 80,
      align: 'center' as const,
      render: (d: number) => <Tag color={d === 1 ? 'blue' : d === 2 ? 'orange' : 'red'}>{d}度</Tag>,
    },
    {
      title: '路径',
      key: 'path',
      render: (_: unknown, record: ImpactResult['impacted'][number]) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {record.path.map((p, i) => (
            <span key={i}>
              {i > 0 && ' → '}
              <Tag style={{ fontSize: 11 }}>{p.relation_type}</Tag>
            </span>
          ))}
        </Text>
      ),
    },
  ];

  return (
    <div>
      {/* 顶部操作栏 */}
      <Card
        size="small"
        style={{ marginBottom: 16 }}
        styles={{ body: { padding: '12px 24px' } }}
      >
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space>
            <Button onClick={() => navigate('/asset/center')} icon={<ArrowLeftOutlined />}>
              返回
            </Button>
            <Text strong>{asset.name}</Text>
            <Tag style={{ fontFamily: 'monospace', fontSize: 11, color: '#8c8c8c' }}>{asset.asset_code}</Tag>
            <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
            <Tag color="blue">v{asset.version}</Tag>
          </Space>
          <Space>
            <Button icon={<EditOutlined />} onClick={() => navigate(`/asset/center/${assetId}/edit`)}>
              编辑
            </Button>
            {canPublish && (
              <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setPublishModalOpen(true)}>
                发布
              </Button>
            )}
            <Button icon={<ApartmentOutlined />} onClick={() => setStatusModalOpen(true)}>
              状态变更
            </Button>
            <Button icon={<CheckCircleOutlined />} onClick={handleMarkUsed}>
              标记使用
            </Button>
            <Popconfirm
              title="确认删除该资产?"
              description="软删除, 历史版本与关系保留供审计"
              onConfirm={handleDelete}
              okText="确认"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          </Space>
        </Space>
      </Card>

      <Card loading={loading}>
        <Tabs
          defaultActiveKey="info"
          items={[
            {
              key: 'info',
              label: '基本信息',
              children: (
                <div>
                  <Descriptions bordered column={2} size="small">
                    <Descriptions.Item label="资产编码">
                      <Text code>{asset.asset_code}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="资产名称">{asset.name}</Descriptions.Item>
                    <Descriptions.Item label="资产类型">
                      <Tag color="blue">{ASSET_TYPE_TEXT[asset.asset_type] || asset.asset_type}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="状态">
                      <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="关联表">{asset.ref_type}</Descriptions.Item>
                    <Descriptions.Item label="关联 ID">{asset.ref_id}</Descriptions.Item>
                    <Descriptions.Item label="模块">{asset.module || '-'}</Descriptions.Item>
                    <Descriptions.Item label="来源">
                      <Tag>{asset.source}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="版本">v{asset.version}</Descriptions.Item>
                    <Descriptions.Item label="质量评分">
                      <span style={{ color: asset.quality_score >= 80 ? '#52c41a' : asset.quality_score >= 60 ? '#faad14' : '#ff4d4f', fontWeight: 600 }}>
                        {asset.quality_score.toFixed(1)}
                      </span>
                    </Descriptions.Item>
                    <Descriptions.Item label="复用次数">{asset.reuse_count}</Descriptions.Item>
                    <Descriptions.Item label="最后使用">
                      {asset.last_used_at ? new Date(asset.last_used_at).toLocaleString('zh-CN') : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="创建者">{asset.created_by ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="创建时间">
                      {new Date(asset.created_at).toLocaleString('zh-CN')}
                    </Descriptions.Item>
                    <Descriptions.Item label="更新时间">
                      {new Date(asset.updated_at).toLocaleString('zh-CN')}
                    </Descriptions.Item>
                  </Descriptions>

                  <Divider orientation="left">摘要</Divider>
                  <Paragraph>{asset.summary || <Text type="secondary">未填写</Text>}</Paragraph>

                  <Divider orientation="left">详细描述</Divider>
                  <Paragraph>
                    {asset.description ? (
                      <div style={{ whiteSpace: 'pre-wrap' }}>{asset.description}</div>
                    ) : (
                      <Text type="secondary">未填写</Text>
                    )}
                  </Paragraph>

                  <Divider orientation="left">标签</Divider>
                  <Space wrap>
                    {asset.tags && asset.tags.length > 0 ? (
                      asset.tags.map((t) => <Tag key={t}>{t}</Tag>)
                    ) : (
                      <Text type="secondary">无标签</Text>
                    )}
                  </Space>

                  {asset.extra_metadata && Object.keys(asset.extra_metadata).length > 0 && (
                    <>
                      <Divider orientation="left">扩展元数据</Divider>
                      <pre style={{
                        background: '#f5f5f5',
                        padding: 12,
                        borderRadius: 4,
                        fontSize: 12,
                        maxHeight: 400,
                        overflow: 'auto',
                      }}>
                        {JSON.stringify(asset.extra_metadata, null, 2)}
                      </pre>
                    </>
                  )}
                </div>
              ),
            },
            {
              key: 'versions',
              label: `版本历史 (${versionsTotal})`,
              children: (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <Button icon={<ReloadOutlined />} onClick={fetchVersions}>刷新</Button>
                  </div>
                  <Table
                    dataSource={versions}
                    rowKey="id"
                    size="small"
                    pagination={false}
                    columns={versionColumns}
                  />
                </div>
              ),
            },
            {
              key: 'relations',
              label: `关系 (${relationsTotal})`,
              children: (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <Button icon={<ReloadOutlined />} onClick={fetchRelations}>刷新</Button>
                  </div>
                  <Table
                    dataSource={relations}
                    rowKey="id"
                    size="small"
                    loading={relationsLoading}
                    pagination={false}
                    columns={relationColumns}
                  />
                </div>
              ),
            },
            {
              key: 'impact',
              label: '影响面分析',
              children: (
                <div>
                  <Space style={{ marginBottom: 12 }}>
                    <Text>搜索深度:</Text>
                    <Select
                      value={impactDepth}
                      onChange={(v) => setImpactDepth(v)}
                      style={{ width: 100 }}
                      options={[
                        { value: 1, label: '1 度 (直接)' },
                        { value: 2, label: '2 度 (二度)' },
                        { value: 3, label: '3 度 (三度)' },
                      ]}
                    />
                    <Button
                      type="primary"
                      icon={<ThunderboltOutlined />}
                      loading={impactLoading}
                      onClick={() => fetchImpact(impactDepth)}
                    >
                      分析
                    </Button>
                  </Space>
                  {impact ? (
                    <>
                      <Row gutter={16} style={{ marginBottom: 12 }}>
                        <Col span={6}>
                          <Card size="small">
                            <Statistic title="受影响资产" value={impact.total} prefix={<ApartmentOutlined />} />
                          </Card>
                        </Col>
                        <Col span={6}>
                          <Card size="small">
                            <Statistic title="1 度影响" value={impact.impacted.filter(i => i.depth === 1).length} />
                          </Card>
                        </Col>
                        <Col span={6}>
                          <Card size="small">
                            <Statistic title="2 度影响" value={impact.impacted.filter(i => i.depth === 2).length} />
                          </Card>
                        </Col>
                        <Col span={6}>
                          <Card size="small">
                            <Statistic title="3 度影响" value={impact.impacted.filter(i => i.depth === 3).length} />
                          </Card>
                        </Col>
                      </Row>
                      <Table
                        dataSource={impact.impacted}
                        rowKey={(r) => r.asset.asset_id ?? Math.random()}
                        size="small"
                        pagination={false}
                        columns={impactColumns}
                      />
                    </>
                  ) : (
                    <Alert
                      message="点击「分析」按钮查看该资产修改会影响哪些其他资产"
                      type="info"
                      showIcon
                    />
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* 发布 Modal */}
      <Modal
        title="发布资产(生成新版本)"
        open={publishModalOpen}
        onOk={handlePublish}
        onCancel={() => setPublishModalOpen(false)}
        confirmLoading={publishing}
        okText="确认发布"
        cancelText="取消"
      >
        <Form form={publishForm} layout="vertical">
          <Form.Item
            name="change_log"
            label="变更说明"
            tooltip="记录本次发布做了哪些变更,便于后续审计"
          >
            <TextArea rows={3} placeholder="例: 新增 headers 字段, 修复 path 校验问题" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 状态变更 Modal */}
      <Modal
        title="状态流转"
        open={statusModalOpen}
        onOk={handleStatusChange}
        onCancel={() => setStatusModalOpen(false)}
        okText="确认"
        cancelText="取消"
      >
        <Form form={statusForm} layout="vertical" initialValues={{ target_status: 'active' }}>
          <Form.Item
            name="target_status"
            label="目标状态"
            rules={[{ required: true, message: '请选择目标状态' }]}
          >
            <Select
              options={[
                { value: 'draft', label: '草稿 (恢复)' },
                { value: 'active', label: '已发布' },
                { value: 'deprecated', label: '已弃用' },
                { value: 'archived', label: '已归档' },
              ]}
            />
          </Form.Item>
          <Form.Item name="reason" label="流转原因">
            <TextArea rows={2} placeholder="例: 该资产已废弃, 改用新版" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 版本快照 Modal */}
      <Modal
        title={`版本快照 ${versionDetail ? 'v' + versionDetail.version : ''}`}
        open={versionModalOpen}
        onCancel={() => setVersionModalOpen(false)}
        footer={null}
        width={800}
      >
        {versionDetail && (
          <div>
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 12 }}>
              <Descriptions.Item label="版本">v{versionDetail.version}</Descriptions.Item>
              <Descriptions.Item label="类型">{CHANGE_TYPE_TEXT[versionDetail.change_type] || versionDetail.change_type}</Descriptions.Item>
              <Descriptions.Item label="变更说明" span={2}>{versionDetail.change_log || '-'}</Descriptions.Item>
            </Descriptions>
            {versionDetail.diff_summary && (
              <>
                <Text strong>差异摘要:</Text>
                <pre style={{ background: '#fff7e6', padding: 8, borderRadius: 4, fontSize: 12, margin: '8px 0' }}>
                  {JSON.stringify(versionDetail.diff_summary, null, 2)}
                </pre>
              </>
            )}
            <Text strong>完整快照:</Text>
            <pre style={{
              background: '#f5f5f5',
              padding: 12,
              borderRadius: 4,
              fontSize: 12,
              maxHeight: 500,
              overflow: 'auto',
            }}>
              {JSON.stringify(versionDetail.snapshot, null, 2)}
            </pre>
          </div>
        )}
      </Modal>
    </div>
  );
}
