/**
 * 接口测试套件页面
 * 套件列表 + 创建/编辑套件弹窗 + 套件详情(含执行历史Tab) + 执行按钮
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Tag, Space, Typography, Input, Select,
  Modal, message, Empty, Popconfirm, Divider, Tabs,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, PlayCircleOutlined,
  ReloadOutlined, EyeOutlined, EditOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  saveSuite, listSuites, getSuite, deleteSuite, runSuite, getSuiteExecutions,
  TestSuite, SuiteExecution,
} from '../../services/apiSuite';
import { listCases, ApiCase } from '../../services/apiCase';

const { Text } = Typography;

const PRIORITY_MAP: Record<string, { color: string; text: string }> = {
  high: { color: 'red', text: '高' },
  medium: { color: 'orange', text: '中' },
  low: { color: 'blue', text: '低' },
};

const SUITE_TYPE_MAP: Record<string, { color: string; text: string }> = {
  regression: { color: 'purple', text: '回归' },
  smoke: { color: 'orange', text: '冒烟' },
  custom: { color: 'blue', text: '自定义' },
};

const EXEC_STATUS_MAP: Record<string, { color: string; text: string }> = {
  waiting: { color: 'default', text: '排队中' },
  pending: { color: 'default', text: '待执行' },
  running: { color: 'processing', text: '执行中' },
  success: { color: 'success', text: '成功' },
  failed: { color: 'error', text: '失败' },
};

export default function ApiSuitePage() {
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [suiteType, setSuiteType] = useState<string | undefined>();
  const [createVisible, setCreateVisible] = useState(false);
  const [editSuite, setEditSuite] = useState<TestSuite | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [currentSuite, setCurrentSuite] = useState<TestSuite | null>(null);
  const [running, setRunning] = useState<number | null>(null);

  // 执行历史
  const [execHistory, setExecHistory] = useState<SuiteExecution[]>([]);
  const [execHistoryLoading, setExecHistoryLoading] = useState(false);
  const [detailActiveTab, setDetailActiveTab] = useState('info');

  const fetchSuites = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await listSuites({ suite_type: suiteType, page, page_size: 20 });
      const data = res?.data || res;
      setSuites(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('加载套件列表失败');
    }
    setLoading(false);
  }, [suiteType, page]);

  useEffect(() => { fetchSuites(); }, [fetchSuites]);

  const handleRun = async (id: number) => {
    setRunning(id);
    try {
      const res: any = await runSuite(id);
      const data = res?.data || res;
      message.success(`套件执行已提交 (execution_id: ${data.execution_id})`);
      fetchSuites();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '执行失败');
    }
    setRunning(null);
  };

  const handleViewDetail = async (id: number) => {
    try {
      const res: any = await getSuite(id);
      setCurrentSuite(res?.data || res);
      setDetailActiveTab('info');
      setDetailVisible(true);
      // 加载执行历史
      setExecHistoryLoading(true);
      try {
        const execRes: any = await getSuiteExecutions(id);
        const execData = execRes?.data || execRes;
        setExecHistory(execData?.items || []);
      } catch { setExecHistory([]); }
      setExecHistoryLoading(false);
    } catch { message.error('获取详情失败'); }
  };

  const handleEdit = (suite: TestSuite) => {
    setEditSuite(suite);
    setCreateVisible(true);
  };

  const handleCreateClose = () => {
    setCreateVisible(false);
    setEditSuite(null);
  };

  const handleCreateSave = () => {
    setCreateVisible(false);
    setEditSuite(null);
    fetchSuites();
  };

  const columns: ColumnsType<TestSuite> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
    {
      title: '类型', dataIndex: 'suite_type', key: 'suite_type', width: 80,
      render: (t: string) => <Tag color={SUITE_TYPE_MAP[t]?.color}>{SUITE_TYPE_MAP[t]?.text || t}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Tag color={s === 'running' ? 'processing' : 'default'}>{s}</Tag>,
    },
    { title: '用例数', dataIndex: 'case_count', key: 'case_count', width: 70 },
    { title: '环境', dataIndex: 'env', key: 'env', width: 80 },
    { title: '执行次数', dataIndex: 'run_count', key: 'run_count', width: 80 },
    {
      title: '操作', key: 'action', width: 240,
      render: (_: unknown, r: TestSuite) => (
        <Space>
          <Button type="primary" size="small" icon={<PlayCircleOutlined />}
            loading={running === r.id} onClick={() => handleRun(r.id)}>执行</Button>
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(r.id)}>详情</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteSuite(r.id); fetchSuites(); }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const execHistoryColumns: ColumnsType<SuiteExecution> = [
    { title: '执行ID', dataIndex: 'execution_id', key: 'execution_id', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => <Tag color={EXEC_STATUS_MAP[s]?.color || 'default'}>{EXEC_STATUS_MAP[s]?.text || s}</Tag>,
    },
    { title: '总数', dataIndex: 'total', key: 'total', width: 60 },
    {
      title: '通过', dataIndex: 'passed', key: 'passed', width: 60,
      render: (v: number) => <Text style={{ color: '#52c41a' }}>{v}</Text>,
    },
    {
      title: '失败', dataIndex: 'failed', key: 'failed', width: 60,
      render: (v: number) => <Text style={{ color: '#f5222d' }}>{v}</Text>,
    },
    {
      title: '耗时(s)', dataIndex: 'duration', key: 'duration', width: 80,
      render: (d: number | null) => d != null ? d.toFixed(1) : '-',
    },
    {
      title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (t: string) => t || '-',
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Select value={suiteType} onChange={v => { setSuiteType(v); setPage(1); }}
          style={{ width: 120 }} allowClear placeholder="套件类型"
          options={[{ value: undefined, label: '全部' }, { value: 'regression', label: '回归' }, { value: 'smoke', label: '冒烟' }, { value: 'custom', label: '自定义' }]}
        />
        <Button icon={<PlusOutlined />} type="primary" onClick={() => { setEditSuite(null); setCreateVisible(true); }}>新建套件</Button>
        <Button icon={<ReloadOutlined />} onClick={fetchSuites}>刷新</Button>
      </Space>

      <Table columns={columns} dataSource={suites} rowKey="id" loading={loading}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
        locale={{ emptyText: <Empty description="暂无套件" /> }}
      />

      <CreateSuiteModal
        visible={createVisible}
        suite={editSuite}
        onClose={handleCreateClose}
        onSave={handleCreateSave}
      />

      <Modal title={currentSuite ? `套件 - ${currentSuite.name}` : '套件详情'}
        open={detailVisible} onCancel={() => setDetailVisible(false)} footer={null} width={800}>
        {currentSuite && (
          <Tabs activeKey={detailActiveTab} onChange={setDetailActiveTab} items={[
            {
              key: 'info',
              label: '基本信息',
              children: (
                <div>
                  <p><Text strong>类型：</Text><Tag color={SUITE_TYPE_MAP[currentSuite.suite_type]?.color}>{SUITE_TYPE_MAP[currentSuite.suite_type]?.text}</Tag></p>
                  <p><Text strong>环境：</Text>{currentSuite.env} | <Text strong>Base URL：</Text>{currentSuite.base_url || '-'}</p>
                  <p><Text strong>并发数：</Text>{currentSuite.concurrency} | <Text strong>失败策略：</Text>{currentSuite.fail_strategy}</p>
                  <Divider>用例列表 ({currentSuite.cases?.length || 0})</Divider>
                  <Table size="small" dataSource={currentSuite.cases || []} rowKey="id" pagination={false}
                    columns={[
                      { title: 'ID', dataIndex: 'id', width: 60 },
                      { title: '标题', dataIndex: 'title', ellipsis: true },
                      { title: '优先级', dataIndex: 'priority', width: 70, render: (p: string) => <Tag color={PRIORITY_MAP[p]?.color}>{PRIORITY_MAP[p]?.text}</Tag> },
                      { title: '状态', dataIndex: 'last_run_status', width: 80, render: (s: string) => s || '-' },
                    ]}
                  />
                </div>
              ),
            },
            {
              key: 'history',
              label: '执行历史',
              children: (
                <Table
                  size="small"
                  dataSource={execHistory}
                  rowKey="id"
                  loading={execHistoryLoading}
                  pagination={false}
                  columns={execHistoryColumns}
                  locale={{ emptyText: <Empty description="暂无执行历史" /> }}
                />
              ),
            },
          ]} />
        )}
      </Modal>
    </div>
  );
}

// ========== 创建/编辑套件弹窗 ==========
function CreateSuiteModal({ visible, suite, onClose, onSave }: {
  visible: boolean;
  suite: TestSuite | null;
  onClose: () => void;
  onSave: () => void;
}) {
  const isEdit = suite !== null;
  const [form, setForm] = useState({
    name: '', description: '', suite_type: 'custom', env: 'test',
    base_url: '', concurrency: 1, fail_strategy: 'continue', retry_count: 0,
  });
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [allCases, setAllCases] = useState<ApiCase[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      // 加载所有用例
      listCases({ page_size: 200 }).then((res: any) => {
        const data = res?.data || res;
        setAllCases(data?.items || []);
      }).catch(() => {});

      // 编辑模式：填充表单
      if (suite) {
        setForm({
          name: suite.name || '',
          description: suite.description || '',
          suite_type: suite.suite_type || 'custom',
          env: suite.env || 'test',
          base_url: suite.base_url || '',
          concurrency: suite.concurrency || 1,
          fail_strategy: suite.fail_strategy || 'continue',
          retry_count: suite.retry_count || 0,
        });
        setSelectedCaseIds(suite.case_ids || []);
      } else {
        setForm({
          name: '', description: '', suite_type: 'custom', env: 'test',
          base_url: '', concurrency: 1, fail_strategy: 'continue', retry_count: 0,
        });
        setSelectedCaseIds([]);
      }
    }
  }, [visible, suite]);

  const handleSave = async () => {
    if (!form.name.trim()) { message.warning('名称不能为空'); return; }
    if (selectedCaseIds.length === 0) { message.warning('请选择用例'); return; }
    setSaving(true);
    try {
      await saveSuite({
        id: isEdit ? suite.id : undefined,
        name: form.name,
        description: form.description || undefined,
        suite_type: form.suite_type,
        case_ids: selectedCaseIds,
        env: form.env,
        base_url: form.base_url || undefined,
        concurrency: form.concurrency,
        fail_strategy: form.fail_strategy,
        retry_count: form.retry_count,
      });
      message.success(isEdit ? '套件更新成功' : '套件创建成功');
      onSave();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || (isEdit ? '更新失败' : '创建失败'));
    }
    setSaving(false);
  };

  return (
    <Modal title={isEdit ? '编辑测试套件' : '新建测试套件'} open={visible} onCancel={onClose} width={700}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="save" type="primary" loading={saving} onClick={handleSave}>{isEdit ? '保存' : '创建'}</Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Space wrap>
          <Space><Text>名称:</Text><Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={{ width: 200 }} /></Space>
          <Space><Text>类型:</Text><Select value={form.suite_type} onChange={v => setForm({ ...form, suite_type: v })} style={{ width: 100 }}
            options={[{ value: 'custom', label: '自定义' }, { value: 'regression', label: '回归' }, { value: 'smoke', label: '冒烟' }]} /></Space>
          <Space><Text>环境:</Text><Select value={form.env} onChange={v => setForm({ ...form, env: v })} style={{ width: 100 }}
            options={[{ value: 'test', label: '测试' }, { value: 'staging', label: '预发' }, { value: 'production', label: '生产' }]} /></Space>
        </Space>
        <Space><Text>Base URL:</Text><Input value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} style={{ width: 400 }} placeholder="http://localhost:8080" /></Space>

        <Divider>选择用例</Divider>
        <Table size="small" dataSource={allCases} rowKey="id" pagination={{ pageSize: 10 }}
          rowSelection={{
            selectedRowKeys: selectedCaseIds,
            onChange: (keys) => setSelectedCaseIds(keys as number[]),
          }}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '优先级', dataIndex: 'priority', width: 70, render: (p: string) => <Tag color={PRIORITY_MAP[p]?.color}>{PRIORITY_MAP[p]?.text}</Tag> },
          ]}
        />
        <Text type="secondary">已选择 {selectedCaseIds.length} 个用例</Text>
      </Space>
    </Modal>
  );
}
