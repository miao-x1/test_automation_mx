import { useCallback, useEffect, useState } from 'react';
import { Button, Drawer, Form, Input, Modal, Select, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from './projectStore';
import { createTestTask, fetchTestTask, listTestTasks, operateTestTask, type TestTaskWorkspace } from '@/services/projectTestTask';
import '../shell/shell.css';

function statusText(status?: string) {
  if (status === 'running' || status === '执行中') return '● 执行中';
  if (status === 'done' || status === 'completed' || status === '已完成') return '✓ 已完成';
  return '● 待执行';
}

export default function TestTaskListPage() {
  const [rows, setRows] = useState<TestTaskWorkspace[]>([]);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<string>();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<TestTaskWorkspace | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    try {
      setRows(await listTestTasks(projectId));
    } catch {
      message.error('加载测试任务失败');
    }
  }, []);

  useEffect(() => {
    void load();
    const reload = () => { void load(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [load]);

  const openTask = async (row: TestTaskWorkspace) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    try {
      setCurrent(await fetchTestTask(projectId, row.id));
    } catch {
      setCurrent(row);
    }
  };

  const create = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const values = await form.validateFields();
    const created = await createTestTask(projectId, values.name, values.requirement_text, values.focus);
    setOpen(false);
    form.resetFields();
    await load();
    setCurrent(created);
  };

  const run = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !current) return;
    try {
      const result = await operateTestTask(projectId, current.id, 'check_coverage');
      if (result?.workspace) setCurrent(result.workspace);
      message.success('已在当前任务上执行操作');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败');
    }
  };

  const visible = rows.filter((item) => {
    const hit = !keyword.trim() || `${item.name} ${item.focus}`.toLowerCase().includes(keyword.trim().toLowerCase());
    return hit && (!status || item.status === status);
  });

  return (
    <div className="pw-page">
      <div className="pw-head">
        <div>
          <h1>测试任务</h1>
          <p>每个任务是当前项目里的独立工作区。</p>
        </div>
        <Button type="primary" onClick={() => setOpen(true)}>＋ 创建任务</Button>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Input allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索任务……" style={{ maxWidth: 280 }} />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 140 }}
          value={status}
          onChange={setStatus}
          options={[
            { value: 'draft', label: '待执行' },
            { value: 'running', label: '执行中' },
            { value: 'done', label: '已完成' },
          ]}
        />
      </div>
      {visible.map((row) => (
        <div key={row.id} className="task-row" onClick={() => void openTask(row)} style={{ cursor: 'pointer' }}>
          <div>
            <b>{row.name}</b>
            <div className="task-meta">{row.case_count || 0} 个用例　　{statusText(row.status)}</div>
          </div>
          <Button type="primary" onClick={(event) => { event.stopPropagation(); void openTask(row); }}>
            详情
          </Button>
        </div>
      ))}
      <Modal title="创建任务" open={open} onOk={() => void create()} onCancel={() => setOpen(false)} okText="创建">
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '例如：回归测试-2026-09-12' }]}>
            <Input placeholder="回归测试-2026-09-12" />
          </Form.Item>
          <Form.Item name="focus" label="模块">
            <Input placeholder="登录" />
          </Form.Item>
          <Form.Item name="requirement_text" label="当前需求">
            <Input.TextArea rows={4} placeholder="粘贴当前任务需求。" />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer title={current?.name || '测试任务'} open={!!current} onClose={() => setCurrent(null)} width={520}>
        {current ? (
          <div>
            <p>状态：{statusText(current.status)}</p>
            <p>模块：{current.focus || '-'}</p>
            <p>用例：{current.case_count || (current.cases || []).length}</p>
            <p>{current.requirement_text || ''}</p>
            {(current.cases || []).map((item: any) => (
              <p key={item.id || item.case_code}>{item.case_code} {item.case_name || item.name}</p>
            ))}
            <Button type="primary" style={{ marginTop: 12 }} onClick={() => void run()}>检查覆盖</Button>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
