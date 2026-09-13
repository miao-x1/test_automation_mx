import { useCallback, useEffect, useState } from 'react';
import { Button, Drawer, Empty, Form, Input, Modal, Select, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from './projectStore';
import { createTestTask, fetchTestTask, listTestTasks, operateTestTask, type TestTaskWorkspace } from '@/services/projectTestTask';
import { PROJECT_DESIGN_CHANGED, fetchTestDesign, openProjectAgent, type TestDesignDocument } from '@/services/projectExplorer';
import { useNavigate } from 'react-router-dom';
import '../shell/shell.css';

function statusText(status?: string) {
  if (status === 'running' || status === '执行中') return '● 执行中';
  if (status === 'done' || status === 'completed' || status === '已完成') return '✓ 已完成';
  return '● 待执行';
}

export default function TestTaskListPage() {
  const navigate = useNavigate();
  const [design, setDesign] = useState<TestDesignDocument | null>(null);
  const [rows, setRows] = useState<TestTaskWorkspace[]>([]);
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState<string>();
  const [open, setOpen] = useState(false);
  const [pane, setPane] = useState<'list' | 'suites' | 'config'>('list');
  const [current, setCurrent] = useState<TestTaskWorkspace | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    try {
      setRows(await listTestTasks(projectId));
      setDesign(await fetchTestDesign(projectId).catch(() => null));
    } catch {
      message.error('加载测试任务失败');
    }
  }, []);

  useEffect(() => {
    void load();
    const reload = () => { void load(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    window.addEventListener(PROJECT_DESIGN_CHANGED, reload);
    return () => {
      window.removeEventListener(PROJECT_CHANGED, reload);
      window.removeEventListener(PROJECT_DESIGN_CHANGED, reload);
    };
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
          <h1>测试用例</h1>
          <p>把测试设计落成可执行的用例。下一阶段是测试准备，不是空口说「用例已完成」。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => navigate('/prepare')}>去测试准备</Button>
          <Button onClick={() => openProjectAgent('根据当前项目生成测试用例')}>✦ 生成测试用例</Button>
          <Button type="primary" onClick={() => {
            setOpen(true);
            if (design?.status === 'confirmed' && design.task_input) {
              form.setFieldsValue({ requirement_text: design.task_input });
            }
          }}>＋ 创建任务</Button>
        </div>
      </div>
      {design?.status === 'confirmed' ? (
        <div className="uw-panel">
          <p>已确认的测试设计可直接作为测试任务输入。对象 {design.counts?.objects ?? 0} · 场景 {design.counts?.scenarios ?? 0}。</p>
          <Button onClick={() => navigate('/design')}>查看测试设计</Button>
        </div>
      ) : null}
      <div className="sub-tabs">
        <button type="button" className={pane === 'list' ? 'is-on' : ''} onClick={() => setPane('list')}>任务列表</button>
        <button type="button" className={pane === 'suites' ? 'is-on' : ''} onClick={() => setPane('suites')}>测试套件</button>
        <button type="button" className={pane === 'config' ? 'is-on' : ''} onClick={() => setPane('config')}>任务配置</button>
      </div>
      <div className="pw-toolbar">
        <Input allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索任务……" style={{ maxWidth: 280, flex: '1 1 200px' }} />
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
      {pane === 'suites' ? (
        <Empty description="当前项目还没有独立的测试套件。任务列表里的任务就是这一次要跑的范围。" />
      ) : pane === 'config' ? (
        current ? (
          <div className="uw-panel">
            <p>任务：{current.name}</p>
            <p>范围：{current.focus || '-'}</p>
            <p>状态：{statusText(current.status)}</p>
            <p>关联用例：{current.case_count || (current.cases || []).length}</p>
            <p>{current.requirement_text || '还没有任务说明。'}</p>
          </div>
        ) : <Empty description="先在任务列表里打开一个任务，再看配置。" />
      ) : visible.map((row) => (
        <div key={row.id} className="task-row" onClick={() => void openTask(row)} style={{ cursor: 'pointer' }}>
          <div>
            <b>{row.name}</b>
            <div className="task-meta">
              范围 {row.focus || '未指定'}
              　关联用例 {row.case_count || (row.cases || []).length}
              　{statusText(row.status)}
              {(row.executions || []).length ? `　最近执行 ${(row.executions || [])[0]?.status || '#' + (row.executions || [])[0]?.id}` : ''}
            </div>
          </div>
          <Button type="primary" onClick={(event) => { event.stopPropagation(); void openTask(row); }}>
            打开
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
            <p>测试范围：{current.focus || '-'}</p>
            <p>执行方式：当前任务操作走已有测试任务接口，不另起执行引擎。</p>
            <p>关联用例：{current.case_count || (current.cases || []).length}</p>
            <p>状态：{statusText(current.status)}</p>
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
