/**
 * 接口测试用例管理页面
 * 左侧目录树 + 右侧用例列表 + 编辑/导入/详情弹窗
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Tag, Space, Input, Select,
  message, Empty, Popconfirm, Tooltip, Badge,
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  ReloadOutlined, ImportOutlined, EyeOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listCases, getCase, deleteCase, copyCase,
  ApiCase,
} from '../../services/apiCase';
import request from '../../services/request';

import ApiFolderTree from './ApiFolderTree';
import ApiCaseEditor from './ApiCaseEditor';
import ApiCaseImport from './ApiCaseImport';
import ApiCaseDetail from './ApiCaseDetail';

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

export default function ApiCasePage() {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selectedFolder, setSelectedFolder] = useState<number | undefined>();
  const [keyword, setKeyword] = useState('');
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  // 弹窗状态
  const [editingCase, setEditingCase] = useState<ApiCase | null>(null);
  const [editorVisible, setEditorVisible] = useState(false);
  const [importVisible, setImportVisible] = useState(false);
  const [detailCaseId, setDetailCaseId] = useState<number | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);

  const fetchCases = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await listCases({
        folder_id: selectedFolder,
        keyword: keyword || undefined,
        priority: priorityFilter,
        status: statusFilter,
        page,
        page_size: 20,
      });
      const data = res?.data || res;
      setCases(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('加载用例列表失败');
    }
    setLoading(false);
  }, [selectedFolder, keyword, priorityFilter, statusFilter, page]);

  useEffect(() => { fetchCases(); }, [fetchCases]);

  // 操作处理
  const handleNewCase = () => {
    setEditingCase(null);
    setEditorVisible(true);
  };

  const handleEdit = async (id: number) => {
    try {
      const res: any = await getCase(id);
      const data = res?.data || res;
      setEditingCase(data);
      setEditorVisible(true);
    } catch {
      message.error('获取用例详情失败');
    }
  };

  const handleEditFromDetail = (caseData: ApiCase) => {
    setDetailVisible(false);
    setEditingCase(caseData);
    setEditorVisible(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteCase(id);
      message.success('删除成功');
      fetchCases();
    } catch {
      message.error('删除失败');
    }
  };

  const handleCopy = async (id: number) => {
    try {
      await copyCase(id);
      message.success('用例已复制');
      fetchCases();
    } catch {
      message.error('复制失败');
    }
  };

  const handleViewDetail = (id: number) => {
    setDetailCaseId(id);
    setDetailVisible(true);
  };

  const handleRun = async (id: number) => {
    try {
      message.loading({ content: '正在提交执行...', key: 'exec' });
      const res: any = await request.post('/api-test/execution/run/json', {
        case_id: id,
      });
      if (res.code === 200 && res.data) {
        message.success({ content: `执行已提交 (ID: ${res.data.execution_id || id})`, key: 'exec' });
      } else {
        message.error({ content: res.message || '执行失败', key: 'exec' });
      }
    } catch {
      message.error({ content: '执行请求失败', key: 'exec' });
    }
  };

  // 表格列定义
  const columns: ColumnsType<ApiCase> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '编号', dataIndex: 'case_id', key: 'case_id', width: 80, render: (v: string) => v || '-' },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 70,
      render: (p: string) => <Tag color={PRIORITY_MAP[p]?.color}>{PRIORITY_MAP[p]?.text || p}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 70,
      render: (s: string) => <Tag color={STATUS_MAP[s]?.color}>{STATUS_MAP[s]?.text || s}</Tag>,
    },
    {
      title: '步骤', key: 'steps', width: 60,
      render: (_: unknown, r: ApiCase) => r.steps?.length || 0,
    },
    {
      title: '断言', key: 'assertions', width: 60,
      render: (_: unknown, r: ApiCase) => r.assertions?.length || 0,
    },
    {
      title: '最近执行', dataIndex: 'last_run_status', key: 'last_run_status', width: 90,
      render: (s: string) => {
        if (!s) return '-';
        const color = s === 'PASS' ? 'success' : s === 'FAIL' ? 'error' : 'warning';
        return <Badge status={color as any} text={s} />;
      },
    },
    {
      title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 160,
      render: (t: string) => t || '-',
    },
    {
      title: '操作', key: 'action', width: 180, fixed: 'right',
      render: (_: unknown, r: ApiCase) => (
        <Space size="small">
          <Tooltip title="详情">
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(r.id)} />
          </Tooltip>
          <Tooltip title="编辑">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(r.id)} />
          </Tooltip>
          <Tooltip title="复制">
            <Button type="link" size="small" icon={<CopyOutlined />} onClick={() => handleCopy(r.id)} />
          </Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(r.id)}>
            <Tooltip title="删除">
              <Button type="link" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 展开行 - 步骤摘要
  const expandedRowRender = (record: ApiCase) => {
    const steps = record.steps || [];
    if (steps.length === 0) return <Empty description="暂无步骤" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
    return (
      <div style={{ padding: '8px 16px' }}>
        {steps.map((step, i) => (
          <div key={i} style={{ marginBottom: 4 }}>
            <Tag color={METHOD_COLOR[step.action] || '#999'}>{step.action}</Tag>
            <span style={{ fontFamily: 'monospace' }}>{step.url}</span>
            {step.body && Object.keys(step.body).length > 0 && (
              <span style={{ color: '#999', marginLeft: 8, fontSize: 12 }}>
                Body: {JSON.stringify(step.body).slice(0, 100)}
                {JSON.stringify(step.body).length > 100 ? '...' : ''}
              </span>
            )}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', gap: 16 }}>
      {/* 左侧目录树 */}
      <ApiFolderTree
        selectedFolder={selectedFolder}
        onSelect={(folderId) => {
          setSelectedFolder(folderId);
          setPage(1);
        }}
      />

      {/* 右侧内容区 */}
      <Card style={{ flex: 1 }} size="small">
        {/* 搜索栏 */}
        <Space style={{ marginBottom: 12 }} wrap>
          <Input.Search
            placeholder="搜索用例"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); fetchCases(); }}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            placeholder="优先级"
            value={priorityFilter}
            onChange={v => { setPriorityFilter(v); setPage(1); }}
            style={{ width: 100 }}
            allowClear
            options={[
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]}
          />
          <Select
            placeholder="状态"
            value={statusFilter}
            onChange={v => { setStatusFilter(v); setPage(1); }}
            style={{ width: 100 }}
            allowClear
            options={[
              { value: 'draft', label: '草稿' },
              { value: 'ready', label: '就绪' },
              { value: 'deprecated', label: '废弃' },
            ]}
          />
          <Button icon={<PlusOutlined />} type="primary" onClick={handleNewCase}>新建用例</Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportVisible(true)}>导入</Button>
          <Button icon={<ReloadOutlined />} onClick={fetchCases}>刷新</Button>
        </Space>

        {/* 用例表格 */}
        <Table
          columns={columns}
          dataSource={cases}
          rowKey="id"
          loading={loading}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无用例" /> }}
          expandable={{
            expandedRowRender,
            rowExpandable: (r) => (r.steps?.length || 0) > 0,
          }}
          scroll={{ x: 1000 }}
        />
      </Card>

      {/* 用例编辑弹窗 */}
      <ApiCaseEditor
        visible={editorVisible}
        caseData={editingCase}
        folderId={selectedFolder}
        onClose={() => { setEditorVisible(false); setEditingCase(null); }}
        onSave={() => { setEditorVisible(false); setEditingCase(null); fetchCases(); }}
      />

      {/* 用例导入弹窗 */}
      <ApiCaseImport
        visible={importVisible}
        onClose={() => setImportVisible(false)}
        onImported={fetchCases}
      />

      {/* 用例详情抽屉 */}
      <ApiCaseDetail
        visible={detailVisible}
        caseId={detailCaseId}
        onClose={() => { setDetailVisible(false); setDetailCaseId(null); }}
        onEdit={handleEditFromDetail}
        onCopy={handleCopy}
        onRun={handleRun}
      />
    </div>
  );
}
