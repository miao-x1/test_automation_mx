/**
 * API 接口管理 - 列表页
 *
 * 路由: /asset/endpoints
 *
 * 功能:
 *   1. 顶部统计卡片(总数 / 草稿 / 已发布 / 已弃用)
 *   2. 筛选条(关键词 / HTTP 方法 / 状态 / 模块)
 *   3. 接口列表表格(名称 / 方法 / 路径 / 状态 / 模块 / 版本 / 操作)
 *   4. 操作: 查看 / 编辑 / 发布 / 删除
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
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  ApiOutlined,
  EyeOutlined,
  EditOutlined,
  DeleteOutlined,
  CloudUploadOutlined,
  EllipsisOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  listEndpoints,
  getEndpointStats,
  deleteEndpoint,
  publishEndpoint,
  changeEndpointStatus,
  type ApiEndpointListItem,
  type ApiEndpointStats,
  type EndpointStatus,
  type HTTPMethod,
} from '@/services/apiEndpoint';

const { Title } = Typography;

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

export default function EndpointListPage() {
  const navigate = useNavigate();

  // 列表状态
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ApiEndpointListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // 筛选状态
  const [keyword, setKeyword] = useState('');
  const [methodFilter, setMethodFilter] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [moduleFilter, setModuleFilter] = useState<string | undefined>(undefined);

  // 统计
  const [stats, setStats] = useState<ApiEndpointStats>({
    total: 0,
    by_status: {},
    by_method: {},
    by_module: {},
  });

  // 拉取列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listEndpoints({
        keyword: keyword.trim() || undefined,
        method: methodFilter,
        status: statusFilter,
        module: moduleFilter,
        page,
        page_size: pageSize,
      });
      setData(res?.items || []);
      setTotal(res?.total || 0);
    } catch (e: any) {
      message.error(e?.message || '加载接口列表失败');
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [keyword, methodFilter, statusFilter, moduleFilter, page, pageSize]);

  // 拉取统计
  const fetchStats = useCallback(async () => {
    try {
      const s = await getEndpointStats();
      setStats(s || { total: 0, by_status: {}, by_method: {}, by_module: {} });
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
  const handleView = (id: number) => navigate(`/asset/endpoints/${id}`);

  // 操作: 编辑
  const handleEdit = (id: number) => navigate(`/asset/endpoints/${id}/edit`);

  // 操作: 发布
  const handlePublish = async (id: number) => {
    try {
      await publishEndpoint(id, '从列表页发布');
      message.success('发布成功');
      fetchData();
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '发布失败');
    }
  };

  // 操作: 状态变更
  const handleStatusChange = async (id: number, newStatus: EndpointStatus) => {
    try {
      await changeEndpointStatus(id, newStatus);
      message.success('状态已更新');
      fetchData();
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '状态变更失败');
    }
  };

  // 操作: 删除
  const handleDelete = async (id: number) => {
    try {
      await deleteEndpoint(id);
      message.success('删除成功');
      fetchData();
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  // 列表行操作下拉菜单
  const rowActions = (record: ApiEndpointListItem) => {
    // 使用 any[] 以容纳 menu item 与 divider 两种结构
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

    // 状态切换菜单
    items.push({ type: 'divider' as const });
    if (record.status !== 'deprecated') {
      items.push({
        key: 'deprecated',
        label: '标记为弃用',
        onClick: () => handleStatusChange(record.id, 'deprecated'),
      });
    }
    if (record.status !== 'archived') {
      items.push({
        key: 'archived',
        label: '归档',
        onClick: () => handleStatusChange(record.id, 'archived'),
      });
    }

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
      title: 'ID',
      dataIndex: 'id',
      width: 70,
    },
    {
      title: '接口名称',
      dataIndex: 'name',
      ellipsis: true,
      render: (text: string, record: ApiEndpointListItem) => (
        <a onClick={() => handleView(record.id)}>{text}</a>
      ),
    },
    {
      title: '方法',
      dataIndex: 'method',
      width: 90,
      render: (m: HTTPMethod) => (
        <Tag color={METHOD_COLOR[m] || 'default'} style={{ fontFamily: 'monospace', fontWeight: 600 }}>
          {m}
        </Tag>
      ),
    },
    {
      title: '路径',
      dataIndex: 'path',
      ellipsis: true,
      render: (p: string) => <span style={{ fontFamily: 'monospace', fontSize: 13 }}>{p}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: EndpointStatus) => {
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
      render: (v: number) => <span>v{v}</span>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 170,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right' as const,
      render: (_: unknown, record: ApiEndpointListItem) => (
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

  return (
    <div>
      {/* 顶部统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="接口总数"
              value={stats.total}
              prefix={<ApiOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="草稿"
              value={stats.by_status?.draft || 0}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已发布"
              value={stats.by_status?.active || 0}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已弃用"
              value={stats.by_status?.deprecated || 0}
              valueStyle={{ color: '#fa541c' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 列表卡片 */}
      <Card
        title={
          <Space>
            <Title level={4} style={{ margin: 0 }}>接口管理</Title>
            <Tag color="processing">{total}</Tag>
          </Space>
        }
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/asset/endpoints/new')}>
            新建接口
          </Button>
        }
      >
        {/* 筛选条 */}
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            placeholder="搜索接口名称 / 路径 / 摘要"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); fetchData(); }}
            style={{ width: 280 }}
            allowClear
          />
          <Select
            placeholder="HTTP 方法"
            value={methodFilter}
            onChange={(v) => { setMethodFilter(v); setPage(1); }}
            allowClear
            style={{ width: 130 }}
            options={[
              { value: 'GET', label: 'GET' },
              { value: 'POST', label: 'POST' },
              { value: 'PUT', label: 'PUT' },
              { value: 'DELETE', label: 'DELETE' },
              { value: 'PATCH', label: 'PATCH' },
              { value: 'HEAD', label: 'HEAD' },
              { value: 'OPTIONS', label: 'OPTIONS' },
            ]}
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
          <Input
            placeholder="模块"
            value={moduleFilter}
            onChange={(e) => setModuleFilter(e.target.value)}
            onPressEnter={() => { setPage(1); fetchData(); }}
            style={{ width: 160 }}
            allowClear
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
          scroll={{ x: 1100 }}
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
