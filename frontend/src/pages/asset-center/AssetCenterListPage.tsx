/**
 * 测试资产中心 - 资产列表页
 *
 * 路由: /asset/center
 *
 * 功能:
 *   1. 顶部统计卡片(总数 / 草稿 / 已发布 / 已弃用 / 关系数)
 *   2. 筛选条(关键词 / 资产类型 / 状态 / 模块 / 来源 / 最低质量分)
 *   3. 资产列表表格(编码 / 名称 / 类型 / 状态 / 模块 / 版本 / 质量分 / 复用次数 / 更新时间 / 操作)
 *   4. 操作: 查看 / 编辑 / 发布 / 标记使用 / 删除
 *   5. 顶部 "AI 分析需求" 按钮跳转到 Agent 业务流入口
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Button,
  Input,
  Select,
  Tag,
  Space,
  message,
  Typography,
  Row,
  Col,
  Statistic,
  Dropdown,
  Tooltip,
  InputNumber,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  DatabaseOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
  CloudUploadOutlined,
  EllipsisOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  listAssets,
  getAssetStats,
  deleteAsset,
  publishAsset,
  markAssetUsed,
  type AssetListItem,
  type AssetStats,
  type AssetStatus,
} from '@/services/assetCenter';

const { Title } = Typography;

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

// 状态对应的颜色 / 文本
const STATUS_META: Record<AssetStatus, { color: string; text: string }> = {
  draft: { color: 'orange', text: '草稿' },
  active: { color: 'green', text: '已发布' },
  deprecated: { color: 'volcano', text: '已弃用' },
  archived: { color: 'default', text: '已归档' },
};

// 资产类型颜色
const ASSET_TYPE_COLOR: Record<string, string> = {
  api_endpoint: 'blue',
  ui_element: 'cyan',
  test_case: 'purple',
  test_asset: 'geekblue',
  script: 'magenta',
  test_data: 'gold',
  test_report: 'lime',
  requirement: 'volcano',
};

export default function AssetCenterListPage() {
  const navigate = useNavigate();

  // 列表状态
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<AssetListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // 筛选状态
  const [keyword, setKeyword] = useState('');
  const [assetTypeFilter, setAssetTypeFilter] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [moduleFilter, setModuleFilter] = useState<string | undefined>(undefined);
  const [sourceFilter, setSourceFilter] = useState<string | undefined>(undefined);
  const [minQuality, setMinQuality] = useState<number | undefined>(undefined);

  // 统计
  const [stats, setStats] = useState<AssetStats>({
    total: 0,
    by_type: {},
    by_status: {},
    by_module: {},
    by_source: {},
    avg_quality_score: 0,
    total_relations: 0,
    pending_neo4j_sync: 0,
  });

  // 拉取列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAssets({
        keyword: keyword.trim() || undefined,
        asset_type: assetTypeFilter,
        status: statusFilter,
        module: moduleFilter,
        source: sourceFilter,
        min_quality: minQuality,
        page,
        page_size: pageSize,
      });
      setData(res?.items || []);
      setTotal(res?.total || 0);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载资产列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [keyword, assetTypeFilter, statusFilter, moduleFilter, sourceFilter, minQuality, page, pageSize]);

  // 拉取统计
  const fetchStats = useCallback(async () => {
    try {
      const s = await getAssetStats();
      setStats(s || {
        total: 0, by_type: {}, by_status: {}, by_module: {}, by_source: {},
        avg_quality_score: 0, total_relations: 0, pending_neo4j_sync: 0,
      });
    } catch {
      // 静默失败,统计不是关键路径
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // 操作: 查看
  const handleView = (id: number) => navigate(`/asset/center/${id}`);

  // 操作: 编辑
  const handleEdit = (id: number) => navigate(`/asset/center/${id}/edit`);

  // 操作: 发布
  const handlePublish = async (id: number) => {
    try {
      await publishAsset(id, { change_log: '从列表页发布', change_type: 'update' });
      message.success('发布成功');
      fetchData();
      fetchStats();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '发布失败');
    }
  };

  // 操作: 标记使用
  const handleMarkUsed = async (id: number) => {
    try {
      await markAssetUsed(id);
      message.success('已标记为使用');
      fetchData();
      fetchStats();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '标记失败');
    }
  };

  // 操作: 删除
  const handleDelete = async (id: number) => {
    try {
      await deleteAsset(id);
      message.success('删除成功');
      fetchData();
      fetchStats();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '删除失败');
    }
  };

  // 列表行操作下拉菜单
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rowActions = (record: AssetListItem) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const items: any[] = [
      { key: 'view', label: '查看', icon: <EyeOutlined />, onClick: () => handleView(record.id) },
      { key: 'edit', label: '编辑', icon: <EditOutlined />, onClick: () => handleEdit(record.id) },
    ];

    // 发布按钮仅在非 active 状态显示
    if (record.status !== 'active') {
      items.push({
        key: 'publish',
        label: '发布',
        icon: <CloudUploadOutlined />,
        onClick: () => handlePublish(record.id),
      });
    }

    // 标记使用
    items.push({
      key: 'mark-used',
      label: '标记使用',
      icon: <CheckCircleOutlined />,
      onClick: () => handleMarkUsed(record.id),
    });

    // 删除
    items.push({ type: 'divider' as const });
    items.push({
      key: 'delete',
      label: '删除',
      icon: <DeleteOutlined />,
      danger: true,
      onClick: () => handleDelete(record.id),
    });

    return (
      <Dropdown menu={{ items: items as any }} trigger={['click']}>
        <Button type="text" size="small" icon={<EllipsisOutlined />} />
      </Dropdown>
    );
  };

  // 表格列
  const columns = [
    {
      title: '资产编码',
      dataIndex: 'asset_code',
      width: 150,
      ellipsis: true,
      render: (code: string) => (
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#8c8c8c' }}>{code}</span>
      ),
    },
    {
      title: '资产名称',
      dataIndex: 'name',
      ellipsis: true,
      render: (text: string, record: AssetListItem) => (
        <a onClick={() => handleView(record.id)}>{text}</a>
      ),
    },
    {
      title: '类型',
      dataIndex: 'asset_type',
      width: 110,
      render: (t: string) => (
        <Tag color={ASSET_TYPE_COLOR[t] || 'default'}>
          {ASSET_TYPE_TEXT[t] || t}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: AssetStatus) => {
        const meta = STATUS_META[s] || { color: 'default', text: s };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '模块',
      dataIndex: 'module',
      width: 120,
      ellipsis: true,
      render: (m: string | null) => m || '-',
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 70,
      align: 'center' as const,
      render: (v: number) => <span>v{v}</span>,
    },
    {
      title: '质量分',
      dataIndex: 'quality_score',
      width: 90,
      align: 'center' as const,
      sorter: (a: AssetListItem, b: AssetListItem) => a.quality_score - b.quality_score,
      render: (q: number) => {
        const color = q >= 80 ? '#52c41a' : q >= 60 ? '#faad14' : '#ff4d4f';
        return <span style={{ color, fontWeight: 600 }}>{q.toFixed(1)}</span>;
      },
    },
    {
      title: '复用次数',
      dataIndex: 'reuse_count',
      width: 90,
      align: 'center' as const,
      render: (n: number) => (n > 0 ? <Tag color="blue">{n}</Tag> : <span style={{ color: '#bfbfbf' }}>0</span>),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      width: 150,
      ellipsis: true,
      render: (tags: string[]) => (
        <Space size={4} wrap>
          {(tags || []).slice(0, 3).map((t) => (
            <Tag key={t} style={{ fontSize: 11 }}>{t}</Tag>
          ))}
          {tags && tags.length > 3 && (
            <Tooltip title={tags.slice(3).join(', ')}>
              <Tag style={{ fontSize: 11 }}>+{tags.length - 3}</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 160,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right' as const,
      render: (_: unknown, record: AssetListItem) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleView(record.id)}>
            查看
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record.id)}>
            编辑
          </Button>
          {rowActions(record)}
        </Space>
      ),
    },
  ];

  // 资产类型选项
  const assetTypeOptions = Object.entries(ASSET_TYPE_TEXT).map(([value, label]) => ({
    value,
    label,
  }));

  return (
    <div>
      {/* 顶部统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card>
            <Statistic
              title="资产总数"
              value={stats.total}
              prefix={<DatabaseOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="草稿"
              value={stats.by_status?.draft || 0}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="已发布"
              value={stats.by_status?.active || 0}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="已弃用"
              value={stats.by_status?.deprecated || 0}
              valueStyle={{ color: '#fa541c' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="关系总数"
              value={stats.total_relations || 0}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="平均质量分"
              value={stats.avg_quality_score || 0}
              precision={1}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 列表卡片 */}
      <Card
        title={
          <Space>
            <Title level={4} style={{ margin: 0 }}>测试资产中心</Title>
            <Tag color="processing">{total}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button
              type="primary"
              ghost
              icon={<ThunderboltOutlined />}
              onClick={() => navigate('/asset/center/analyze')}
            >
              AI 分析需求
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/asset/center/new')}>
              新建资产
            </Button>
          </Space>
        }
      >
        {/* 筛选条 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            placeholder="搜索资产名称 / 编码 / 摘要"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); fetchData(); }}
            style={{ width: 280 }}
            allowClear
          />
          <Select
            placeholder="资产类型"
            value={assetTypeFilter}
            onChange={(v) => { setAssetTypeFilter(v); setPage(1); }}
            allowClear
            style={{ width: 140 }}
            options={assetTypeOptions}
          />
          <Select
            placeholder="状态"
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            allowClear
            style={{ width: 130 }}
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'active', label: '已发布' },
              { value: 'deprecated', label: '已弃用' },
              { value: 'archived', label: '已归档' },
            ]}
          />
          <Select
            placeholder="来源"
            value={sourceFilter}
            onChange={(v) => { setSourceFilter(v); setPage(1); }}
            allowClear
            style={{ width: 130 }}
            options={[
              { value: 'manual', label: '手工' },
              { value: 'swagger', label: 'Swagger' },
              { value: 'postman', label: 'Postman' },
              { value: 'har', label: 'HAR' },
              { value: 'import', label: '导入' },
              { value: 'ai', label: 'AI 生成' },
            ]}
          />
          <Input
            placeholder="模块"
            value={moduleFilter}
            onChange={(e) => setModuleFilter(e.target.value)}
            onPressEnter={() => { setPage(1); fetchData(); }}
            style={{ width: 140 }}
            allowClear
          />
          <InputNumber
            placeholder="最低质量分"
            min={0}
            max={100}
            value={minQuality}
            onChange={(v) => { setMinQuality(v ?? undefined); setPage(1); }}
            style={{ width: 130 }}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => { fetchData(); fetchStats(); }}
          >
            刷新
          </Button>
        </Space>

        <Table
          dataSource={data}
          rowKey="id"
          loading={loading}
          size="middle"
          scroll={{ x: 1400 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          columns={columns}
        />
      </Card>
    </div>
  );
}
