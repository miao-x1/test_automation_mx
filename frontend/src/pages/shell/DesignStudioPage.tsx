import { useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Empty, Form, Input, Modal, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { createTaskCase, createTestTask, listTaskCases, listTestTasks, type TestCaseRow } from '@/services/projectTestTask';
import { fetchProjectUnderstanding, openProjectAgent } from '@/services/projectExplorer';
import '../understand/understand.css';
import './shell.css';

export default function DesignStudioPage() {
  const [tab, setTab] = useState<'scenarios' | 'cases' | 'data'>('scenarios');
  const [keyword, setKeyword] = useState('');
  const [cases, setCases] = useState<Array<TestCaseRow & { task_id: number; task_name: string }>>([]);
  const [current, setCurrent] = useState<(TestCaseRow & { task_id: number; task_name: string }) | null>(null);
  const [createKind, setCreateKind] = useState<'scenario' | 'case' | null>(null);
  const [related, setRelated] = useState<any>(null);
  const [form] = Form.useForm();

  const load = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const rows = await listTestTasks(projectId);
    const packed = await Promise.all((rows || []).map(async (task) => {
      const items = await listTaskCases(projectId, task.id).catch(() => task.cases || []);
      return (items || []).map((item) => ({ ...item, task_id: task.id, task_name: task.name }));
    }));
    setCases(packed.flat());
  };

  useEffect(() => {
    load().catch(() => message.error('加载测试设计失败'));
    const reload = () => { void load(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, []);

  const filtered = cases.filter((item) => {
    const blob = `${item.case_code} ${item.case_name} ${item.scenario} ${item.module} ${item.test_data}`.toLowerCase();
    return !keyword.trim() || blob.includes(keyword.trim().toLowerCase());
  });
  const scenarios = useMemo(() => {
    const map = new Map<string, typeof filtered>();
    filtered.forEach((item) => {
      const key = item.scenario || item.module || item.task_name || '未分组';
      map.set(key, [...(map.get(key) || []), item]);
    });
    return [...map.entries()];
  }, [filtered]);

  const create = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const values = await form.validateFields();
    if (createKind === 'scenario') {
      await createTestTask(projectId, values.name, values.requirement_text, values.focus);
      message.success('已创建测试场景');
    } else {
      const tasks = await listTestTasks(projectId);
      const task = tasks[0] || await createTestTask(projectId, values.name || '未命名任务', values.requirement_text, values.focus);
      await createTaskCase(projectId, task.id, {
        case_name: values.name,
        scenario: values.focus,
        precondition: values.requirement_text,
      });
      message.success('已创建测试用例');
    }
    setCreateKind(null);
    form.resetFields();
    await load();
  };

  const showRelated = async (item: TestCaseRow & { task_id: number; task_name: string }) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const data = await fetchProjectUnderstanding(projectId).catch(() => null);
    const hit = (data?.features || []).find((row: any) => `${item.case_name} ${item.scenario} ${item.module}`.includes(row.name));
    setRelated({
      page: hit?.entry_page || '-',
      feature: hit?.name || '-',
      api: hit?.apis?.[0] || '-',
      file: hit?.files?.[0] || '-',
    });
  };

  return (
    <div className="pw-page">
      <div className="pw-head">
        <div>
          <h1>测试设计</h1>
          <p>场景、用例和测试数据都来自当前项目的测试任务。</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => setCreateKind('scenario')}>＋ 新建测试场景</Button>
          <Button type="primary" onClick={() => setCreateKind('case')}>＋ 新建测试用例</Button>
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 16 }}>
        <Input allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索测试用例……" style={{ maxWidth: 360 }} />
        <Button onClick={() => openProjectAgent('分析当前项目的测试缺口')}>AI 分析测试缺口</Button>
      </div>
      <div className="ds-tabs">
        {[
          { key: 'scenarios', label: '测试场景' },
          { key: 'cases', label: '测试用例' },
          { key: 'data', label: '测试数据' },
        ].map((item) => (
          <button key={item.key} type="button" className={tab === item.key ? 'is-on' : ''} onClick={() => setTab(item.key as typeof tab)}>{item.label}</button>
        ))}
      </div>
      {cases.length === 0 ? (
        <Empty description="还没有测试用例。先创建一个测试场景或用例。" />
      ) : tab === 'scenarios' ? (
        scenarios.map(([name, rows]) => (
          <div key={name} className="uw-panel" style={{ marginBottom: 16 }}>
            <h3>{name}</h3>
            {rows.map((item) => (
              <div key={`${item.task_id}-${item.id || item.case_code}`} className="ds-row" onClick={() => { setCurrent(item); setRelated(null); }}>
                <span>{item.case_code || 'TC'} {item.case_name || item.scenario}</span>
                <span className={item.status === 'draft' ? 'uw-tone-warn' : 'uw-tone-ok'}>{item.status === 'draft' ? '⚠ 待完善' : '✓ 已设计'}</span>
              </div>
            ))}
          </div>
        ))
      ) : tab === 'data' ? (
        filtered.filter((item) => item.test_data).length === 0 ? (
          <Empty description="这些用例还没有单独的测试数据字段。" />
        ) : filtered.filter((item) => item.test_data).map((item) => (
          <div key={`${item.task_id}-${item.id || item.case_code}`} className="ds-row" onClick={() => { setCurrent(item); setRelated(null); }}>
            <span>{item.case_code} {item.case_name}</span>
            <span className="uw-tone-empty">{item.test_data}</span>
          </div>
        ))
      ) : (
        filtered.map((item) => (
          <div key={`${item.task_id}-${item.id || item.case_code}`} className="ds-row" onClick={() => { setCurrent(item); setRelated(null); }}>
            <span>{item.case_code || 'TC'} {item.case_name || item.scenario}</span>
            <span className={item.status === 'draft' ? 'uw-tone-warn' : 'uw-tone-ok'}>{item.status === 'draft' ? '⚠ 待完善' : '✓ 已设计'}</span>
          </div>
        ))
      )}

      <Drawer
        title={current ? `测试设计 / ${current.case_code || '用例'}` : '用例详情'}
        open={!!current}
        onClose={() => { setCurrent(null); setRelated(null); }}
        width={520}
      >
        {current ? (
          <div>
            <h3 style={{ marginTop: 0 }}>{current.case_name}</h3>
            <p>任务：{current.task_name}</p>
            <p>模块：{current.module || '-'}</p>
            <p>场景：{current.scenario || '-'}</p>
            <p>前置条件：{current.precondition || '-'}</p>
            <p>测试数据：{current.test_data || '-'}</p>
            <p>预期：{current.expected_result || '-'}</p>
            <Button style={{ marginTop: 12 }} onClick={() => void showRelated(current)}>项目关联</Button>
            {related ? (
              <div style={{ marginTop: 16 }}>
                <p>页面：{related.page}</p>
                <p>功能：{related.feature}</p>
                <p>API：{related.api}</p>
                <p>文件：{related.file}</p>
              </div>
            ) : null}
          </div>
        ) : null}
      </Drawer>

      <Modal
        title={createKind === 'scenario' ? '新建测试场景' : '新建测试用例'}
        open={!!createKind}
        onOk={() => void create()}
        onCancel={() => setCreateKind(null)}
        okText="创建"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={createKind === 'scenario' ? '场景名称' : '用例名称'} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="focus" label="模块 / 场景">
            <Input />
          </Form.Item>
          <Form.Item name="requirement_text" label="说明">
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
