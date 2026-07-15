/**
 * 定时任务页面
 *
 * 功能：列表、创建、编辑、运行历史、暂停/启用、手动触发
 */
import { useState, useCallback, useEffect } from 'react';
import {
  Card, Table, Button, Space, Tag, Modal, Form, Input, Select, InputNumber,
  Switch, message, Popconfirm, Tooltip, DatePicker, TimePicker, Radio,
} from 'antd';
import {
  ClockCircleOutlined, PlusOutlined, PlayCircleOutlined, PauseCircleOutlined,
  DeleteOutlined, HistoryOutlined, ReloadOutlined, ThunderboltOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SyncOutlined, EditOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import {
  listScheduleTasks, createScheduleTask, updateScheduleTask, deleteScheduleTask,
  pauseScheduleTask, resumeScheduleTask, triggerScheduleTask,
  getRunHistory,
} from '../services/schedule';
import type { ScheduleTaskItem, ScheduleRunLogItem, CreateScheduleTaskParams } from '../services/schedule';
import { PageHeader } from '../components/UI';

const { TextArea } = Input;
const { Option } = Select;

// ==================== 状态标签 ====================
const STATUS_MAP: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  active: { color: 'green', label: '启用', icon: <CheckCircleOutlined /> },
  paused: { color: 'orange', label: '暂停', icon: <PauseCircleOutlined /> },
  expired: { color: 'default', label: '已过期', icon: <ClockCircleOutlined /> },
  disabled: { color: 'red', label: '已禁用', icon: <CloseCircleOutlined /> },
};

const TYPE_MAP: Record<string, { color: string; label: string }> = {
  once: { color: 'blue', label: '一次性' },
  daily: { color: 'cyan', label: '每日' },
  cron: { color: 'purple', label: 'Cron' },
};

// ==================== 创建/编辑弹窗 ====================
function TaskFormModal({
  open, editTask, onClose, onSaved,
}: {
  open: boolean; editTask: ScheduleTaskItem | null; onClose: () => void; onSaved: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isEdit = !!editTask;
  const scheduleType = Form.useWatch('schedule_type', form);

  // 编辑时填充表单
  useEffect(() => {
    if (open && editTask) {
      let endTypeVal = 'forever';
      if (editTask.end_time) endTypeVal = 'date';

      form.setFieldsValue({
        name: editTask.name,
        description: editTask.description,
        schedule_type: editTask.schedule_type,
        cron_expression: editTask.cron_expression,
        execute_time: editTask.execute_time ? dayjs(editTask.execute_time, 'HH:mm') : undefined,
        execute_date: editTask.execute_date ? dayjs(editTask.execute_date, 'YYYY-MM-DD') : undefined,
        _start_type: editTask.start_time ? 'date' : 'today',
        start_date: editTask.start_time ? dayjs(editTask.start_time) : undefined,
        _end_type: endTypeVal,
        end_date: editTask.end_time ? dayjs(editTask.end_time) : undefined,
        timeout: editTask.timeout,
        max_retries: editTask.max_retries,
        retry_interval: editTask.retry_interval,
        notify_on_success: editTask.notify_on_success,
        notify_on_failure: editTask.notify_on_failure,
        requirement: editTask.task_config ? (typeof editTask.task_config === 'string' ? (JSON.parse(editTask.task_config) as any).requirement : (editTask.task_config as any).requirement) : undefined,
        target_url: editTask.task_config ? (typeof editTask.task_config === 'string' ? (JSON.parse(editTask.task_config) as any).target_url : (editTask.task_config as any).target_url) : undefined,
        script_format: editTask.task_config ? (typeof editTask.task_config === 'string' ? (JSON.parse(editTask.task_config) as any).script_format : (editTask.task_config as any).script_format) : 'playwright',
      });
    } else if (open) {
      form.resetFields();
    }
  }, [open, editTask, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      const startType = values._start_type || 'today';
      const endTypeVal = values._end_type || 'forever';

      const params: CreateScheduleTaskParams = {
        name: values.name,
        description: values.description,
        schedule_type: values.schedule_type,
        cron_expression: values.cron_expression,
        execute_time: values.execute_time?.format?.('HH:mm') || values.execute_time,
        execute_date: values.execute_date?.format?.('YYYY-MM-DD') || values.execute_date,
        start_time: startType === 'today' ? dayjs().format('YYYY-MM-DD') : values.start_date?.format('YYYY-MM-DD'),
        end_time: endTypeVal === 'forever' ? undefined : values.end_date?.format('YYYY-MM-DD'),
        timeout: values.timeout || 3600,
        max_retries: values.max_retries ?? 3,
        retry_interval: values.retry_interval ?? 60,
        notify_on_success: values.notify_on_success || false,
        notify_on_failure: values.notify_on_failure !== false,
        task_config: values.requirement ? {
          requirement: values.requirement,
          target_url: values.target_url,
          script_format: values.script_format || 'playwright',
        } : undefined,
      };

      if (isEdit) {
        await updateScheduleTask(editTask!.id, params);
        message.success('定时任务更新成功');
      } else {
        await createScheduleTask(params);
        message.success('定时任务创建成功');
      }
      form.resetFields();
      onSaved();
      onClose();
    } catch (e: any) {
      if (e?.response?.data?.detail) message.error(e.response.data.detail);
      else if (!e?.errorFields) message.error(isEdit ? '更新失败' : '创建失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={isEdit ? '编辑定时任务' : '创建定时任务'}
      open={open} onOk={handleSubmit} onCancel={onClose}
      confirmLoading={loading} width={640} destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          schedule_type: 'daily', timeout: 3600, max_retries: 3,
          retry_interval: 60, notify_on_failure: true, script_format: 'playwright',
          _start_type: 'today', _end_type: 'forever',
        }}
      >
        <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
          <Input placeholder="如：每日登录回归测试" />
        </Form.Item>
        <Form.Item name="description" label="描述（可选）">
          <TextArea rows={2} placeholder="可选描述" />
        </Form.Item>

        <Space style={{ width: '100%' }} size="middle" wrap>
          <Form.Item name="schedule_type" label="调度类型" rules={[{ required: true }]}>
            <Select style={{ width: 120 }}>
              <Option value="once">一次性</Option>
              <Option value="daily">每日</Option>
              <Option value="cron">Cron</Option>
            </Select>
          </Form.Item>
          {scheduleType === 'daily' && (
            <Form.Item name="execute_time" label="执行时间" rules={[{ required: true, message: '请选择执行时间' }]}>
              <TimePicker format="HH:mm" style={{ width: 120 }} />
            </Form.Item>
          )}
          {scheduleType === 'once' && (
            <>
              <Form.Item name="execute_date" label="执行日期" rules={[{ required: true, message: '请选择日期' }]}>
                <DatePicker style={{ width: 160 }} />
              </Form.Item>
              <Form.Item name="execute_time" label="执行时间（可选）">
                <TimePicker format="HH:mm" style={{ width: 120 }} />
              </Form.Item>
            </>
          )}
          {scheduleType === 'cron' && (
            <Form.Item name="cron_expression" label="Cron表达式" rules={[{ required: true, message: '请输入Cron表达式' }]}>
              <Input placeholder="0 8 * * 1-5" style={{ width: 160 }} />
            </Form.Item>
          )}
        </Space>

        {/* 有效期 */}
        <Space style={{ width: '100%' }} size="middle" wrap>
          <Form.Item name="_start_type" label="起始日期">
            <Radio.Group>
              <Radio value="today">今天</Radio>
              <Radio value="date">指定日期</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev._start_type !== cur._start_type}>
            {({ getFieldValue }) => getFieldValue('_start_type') === 'date' ? (
              <Form.Item name="start_date" label="起始日期" rules={[{ required: true, message: '请选择起始日期' }]}>
                <DatePicker style={{ width: 160 }} />
              </Form.Item>
            ) : <Form.Item label="起始日期"><Tag color="blue">今天 ({dayjs().format('YYYY-MM-DD')})</Tag></Form.Item>}
          </Form.Item>
        </Space>

        <Space style={{ width: '100%' }} size="middle" wrap>
          <Form.Item name="_end_type" label="终止日期">
            <Radio.Group>
              <Radio value="forever">永远执行</Radio>
              <Radio value="date">指定日期</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev._end_type !== cur._end_type}>
            {({ getFieldValue }) => getFieldValue('_end_type') === 'date' ? (
              <Form.Item name="end_date" label="终止日期" rules={[{ required: true, message: '请选择终止日期' }]}>
                <DatePicker style={{ width: 160 }} />
              </Form.Item>
            ) : <Form.Item label="终止日期"><Tag color="green">永远执行</Tag></Form.Item>}
          </Form.Item>
        </Space>

        <Form.Item name="requirement" label="测试需求" rules={[{ required: true, message: '请输入需求' }]}>
          <TextArea rows={3} placeholder="输入要自动执行的测试需求..." />
        </Form.Item>
        <Form.Item name="target_url" label="目标URL（可选）">
          <Input placeholder="https://..." />
        </Form.Item>

        <Space style={{ width: '100%' }} size="middle">
          <Form.Item name="timeout" label="超时(秒)（可选）">
            <InputNumber min={60} style={{ width: 100 }} />
          </Form.Item>
          <Form.Item name="max_retries" label="重试次数（可选）">
            <InputNumber min={0} max={10} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="retry_interval" label="重试间隔(秒)（可选）">
            <InputNumber min={10} style={{ width: 100 }} />
          </Form.Item>
        </Space>

        <Space>
          <Form.Item name="notify_on_success" valuePropName="checked" label="成功通知">
            <Switch size="small" />
          </Form.Item>
          <Form.Item name="notify_on_failure" valuePropName="checked" label="失败通知">
            <Switch size="small" />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}

// ==================== 运行历史弹窗 ====================
function RunHistoryModal({ task, open, onClose }: { task: ScheduleTaskItem | null; open: boolean; onClose: () => void }) {
  const [runs, setRuns] = useState<ScheduleRunLogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  const fetchRuns = useCallback(async () => {
    if (!task) return;
    setLoading(true);
    try {
      const data = await getRunHistory(task.id, { page, page_size: 20 });
      setRuns(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('加载运行历史失败');
    }
    setLoading(false);
  }, [task, page]);

  useEffect(() => { if (open) fetchRuns(); }, [open, fetchRuns]);

  const runColumns: ColumnsType<ScheduleRunLogItem> = [
    { title: '#', dataIndex: 'run_number', width: 50 },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (s: string) => {
        const map: Record<string, { color: string; icon: React.ReactNode }> = {
          running: { color: 'blue', icon: <SyncOutlined spin /> },
          success: { color: 'green', icon: <CheckCircleOutlined /> },
          failed: { color: 'red', icon: <CloseCircleOutlined /> },
          timeout: { color: 'orange', icon: <ClockCircleOutlined /> },
          retrying: { color: 'gold', icon: <ReloadOutlined /> },
        };
        const cfg = map[s] || { color: 'default', icon: null };
        return <Tag color={cfg.color} icon={cfg.icon}>{s}</Tag>;
      },
    },
    { title: '开始时间', dataIndex: 'started_at', width: 160, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '耗时(秒)', dataIndex: 'duration', width: 80 },
    { title: '重试', dataIndex: 'retry_count', width: 50 },
    { title: '结果', dataIndex: 'result_summary', ellipsis: true },
    { title: '错误', dataIndex: 'error_message', ellipsis: true, render: (v: string) => v ? <Tooltip title={v}><span style={{ color: 'red' }}>{v.slice(0, 50)}</span></Tooltip> : '-' },
  ];

  return (
    <Modal title={`运行历史 - ${task?.name || ''}`} open={open} onCancel={onClose} footer={null} width={900}>
      <Table
        columns={runColumns}
        dataSource={runs}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ current: page, total, pageSize: 20, onChange: setPage, size: 'small' }}
      />
    </Modal>
  );
}

// ==================== 主页面 ====================
export default function SchedulePage() {
  const [tasks, setTasks] = useState<ScheduleTaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [formOpen, setFormOpen] = useState(false);
  const [editTask, setEditTask] = useState<ScheduleTaskItem | null>(null);
  const [historyTask, setHistoryTask] = useState<ScheduleTaskItem | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listScheduleTasks({ status: statusFilter, page, page_size: 20 });
      setTasks(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('加载任务列表失败');
    }
    setLoading(false);
  }, [statusFilter, page]);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  const handleDelete = async (id: number) => {
    try { await deleteScheduleTask(id); message.success('已删除'); fetchTasks(); }
    catch { message.error('删除失败'); }
  };

  const handlePause = async (id: number) => {
    try { await pauseScheduleTask(id); message.success('已暂停'); fetchTasks(); }
    catch { message.error('操作失败'); }
  };

  const handleResume = async (id: number) => {
    try { await resumeScheduleTask(id); message.success('已启用'); fetchTasks(); }
    catch { message.error('操作失败'); }
  };

  const handleTrigger = async (id: number) => {
    try { await triggerScheduleTask(id); message.success('已触发执行'); fetchTasks(); }
    catch { message.error('触发失败'); }
  };

  const handleEdit = (task: ScheduleTaskItem) => {
    setEditTask(task);
    setFormOpen(true);
  };

  const handleCreate = () => {
    setEditTask(null);
    setFormOpen(true);
  };

  const handleFormClose = () => {
    setFormOpen(false);
    setEditTask(null);
  };

  const columns: ColumnsType<ScheduleTaskItem> = [
    { title: 'ID', dataIndex: 'id', width: 50 },
    { title: '名称', dataIndex: 'name', width: 180, ellipsis: true },
    {
      title: '调度', dataIndex: 'schedule_type', width: 120,
      render: (type: string, r: ScheduleTaskItem) => {
        const cfg = TYPE_MAP[type] || { color: 'default', label: type };
        let detail = '';
        if (type === 'daily') detail = r.execute_time || '';
        if (type === 'cron') detail = r.cron_expression || '';
        if (type === 'once') detail = r.execute_date || '';
        return <Tooltip title={detail}><Tag color={cfg.color}>{cfg.label} {detail}</Tag></Tooltip>;
      },
    },
    {
      title: '有效期', width: 160,
      render: (_: unknown, r: ScheduleTaskItem) => {
        const start = r.start_time || '-';
        const end = r.end_time || '永远';
        return <span style={{ fontSize: 12 }}>{start} ~ {end}</span>;
      },
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (s: string) => { const cfg = STATUS_MAP[s] || { color: 'default', label: s, icon: null }; return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>; },
    },
    { title: '执行', dataIndex: 'run_count', width: 80, render: (v: number, r: ScheduleTaskItem) => <span>{v} <span style={{ color: r.fail_count > 0 ? '#ff4d4f' : undefined }}>({r.fail_count}失败)</span></span> },
    {
      title: '上次执行', width: 140,
      render: (_: unknown, r: ScheduleTaskItem) => r.last_run_at
        ? <span>{new Date(r.last_run_at).toLocaleString('zh-CN')} <Tag color={r.last_run_status === 'success' ? 'green' : 'red'} style={{ fontSize: 10 }}>{r.last_run_status}</Tag></span>
        : '-',
    },
    {
      title: '下次执行', dataIndex: 'next_run_at', width: 140,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', width: 220, fixed: 'right',
      render: (_: unknown, r: ScheduleTaskItem) => (
        <Space size="small">
          <Tooltip title="编辑"><Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} /></Tooltip>
          {r.status === 'active' && (
            <Tooltip title="暂停"><Button size="small" icon={<PauseCircleOutlined />} onClick={() => handlePause(r.id)} /></Tooltip>
          )}
          {r.status === 'paused' && (
            <Tooltip title="启用"><Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => handleResume(r.id)} /></Tooltip>
          )}
          <Tooltip title="手动触发"><Button size="small" icon={<ThunderboltOutlined />} onClick={() => handleTrigger(r.id)} /></Tooltip>
          <Tooltip title="运行历史"><Button size="small" icon={<HistoryOutlined />} onClick={() => setHistoryTask(r)} /></Tooltip>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="定时任务"
        icon={<ClockCircleOutlined />}
        subtitle="支持每日/一次性/Cron调度，自动运行测试任务"
      />

      <Card extra={
        <Space>
          <Select placeholder="状态筛选" allowClear style={{ width: 120 }} value={statusFilter} onChange={v => { setStatusFilter(v); setPage(1); }}>
            <Option value="active">启用</Option>
            <Option value="paused">暂停</Option>
            <Option value="expired">已过期</Option>
          </Select>
          <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>创建定时任务</Button>
        </Space>
      }>
        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ current: page, total, pageSize: 20, onChange: setPage, showTotal: t => `共 ${t} 条` }}
          scroll={{ x: 1000 }}
        />
      </Card>

      <TaskFormModal open={formOpen} editTask={editTask} onClose={handleFormClose} onSaved={fetchTasks} />
      <RunHistoryModal task={historyTask} open={!!historyTask} onClose={() => setHistoryTask(null)} />
    </div>
  );
}
