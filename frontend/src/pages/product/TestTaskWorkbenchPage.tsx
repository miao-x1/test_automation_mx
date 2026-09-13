import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography, message } from 'antd';
import { getCurrentProjectId } from './projectStore';
import { askProjectAgentFromAnywhere } from '@/services/projectExplorer';
import {
  createTaskCase,
  deleteTaskCase,
  exportTaskCases,
  fetchTestTask,
  operateTestTask,
  updateTaskCase,
  updateTestTask,
  type TestCaseRow,
  type TestTaskWorkspace,
} from '@/services/projectTestTask';
import './product.css';

const { Paragraph, Text } = Typography;

const AI_OPS = [
  { op: 'generate_cases', label: 'AI生成测试用例' },
  { op: 'supplement_exception', label: 'AI补充异常场景' },
  { op: 'supplement_boundary', label: 'AI补充边界场景' },
  { op: 'check_coverage', label: 'AI检查测试覆盖率' },
  { op: 'optimize_cases', label: 'AI优化测试用例' },
  { op: 'to_automation', label: '转自动化测试' },
];

function stepText(steps: TestCaseRow['steps']) {
  if (!steps) return '';
  if (typeof steps === 'string') return steps;
  return (steps as any[]).map((step) => (typeof step === 'string' ? step : `${step.no || ''}.${step.action || ''}`)).join(' / ');
}

export default function TestTaskWorkbenchPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const taskId = Number(id);
  const [data, setData] = useState<TestTaskWorkspace | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<TestCaseRow | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !taskId) return;
    setLoading(true);
    try {
      setData(await fetchTestTask(projectId, taskId));
    } catch {
      message.error('加载测试任务失败');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { void load(); }, [load]);

  const runOp = async (op: string) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    try {
      const result = await operateTestTask(projectId, taskId, op);
      if (result?.workspace) setData(result.workspace);
      else await load();
      if (result?.coverage) message.info(`覆盖率 ${result.coverage.score}%：${result.coverage.advice}`);
      else message.success('已写入当前测试任务和项目资产');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败');
    } finally {
      setLoading(false);
    }
  };

  const saveRequirement = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !data) return;
    await updateTestTask(projectId, taskId, { requirement_text: data.requirement_text, name: data.name, focus: data.focus });
    message.success('需求已保存，Agent 会自动读取');
  };

  const saveCase = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !editing) return;
    const values = await form.validateFields();
    const payload = {
      ...values,
      tags: String(values.tags || '').split(/[,，]/).map((item: string) => item.trim()).filter(Boolean),
      steps: String(values.steps || '').split('\n').filter(Boolean).map((action: string, index: number) => ({ no: index + 1, action })),
    };
    if (editing.id) await updateTaskCase(projectId, taskId, editing.id, payload);
    else await createTaskCase(projectId, taskId, payload);
    setEditing(null);
    await load();
  };

  const removeCase = async (row: TestCaseRow) => {
    const projectId = getCurrentProjectId();
    if (!projectId || !row.id) return;
    await deleteTaskCase(projectId, taskId, row.id);
    await load();
  };

  const exportCsv = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const packed = await exportTaskCases(projectId, taskId);
    const blob = new Blob([packed.csv || ''], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = packed.filename || 'test-cases.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const cases = data?.cases || [];
  const analysis = data?.analysis || {};

  return (
    <div className="product-shell product-wide">
      <div className="product-hero">
        <Button type="link" onClick={() => navigate('/test-tasks')} style={{ paddingLeft: 0 }}>← 测试用例</Button>
        <h1>{data?.name || '测试任务工作台'}</h1>
        <p>当前任务上下文会自动带上项目知识、页面、API 和已有用例。右侧 Agent 与这里共用同一个 Testing Brain。</p>
      </div>

      <Tabs
        items={[
          {
            key: 'requirement',
            label: '需求',
            children: (
              <div className="product-card">
                <Input value={data?.name} onChange={(e) => setData((prev) => prev ? { ...prev, name: e.target.value } : prev)} style={{ marginBottom: 8 }} />
                <Input.TextArea
                  rows={8}
                  value={data?.requirement_text}
                  onChange={(e) => setData((prev) => prev ? { ...prev, requirement_text: e.target.value } : prev)}
                  placeholder="当前测试任务需求"
                />
                <Space style={{ marginTop: 12 }}>
                  <Button type="primary" onClick={() => void saveRequirement()}>保存需求</Button>
                  <Button onClick={() => askProjectAgentFromAnywhere('根据当前需求生成测试用例。')}>让 Agent 根据当前需求生成用例</Button>
                </Space>
              </div>
            ),
          },
          {
            key: 'analysis',
            label: '测试分析',
            children: (
              <div className="product-card">
                <Button onClick={() => void runOp('analyze')} loading={loading}>AI 分析当前需求</Button>
                <Paragraph style={{ marginTop: 16 }}>{(analysis.thinking || []).join(' ')}</Paragraph>
                <Text strong>必测</Text>
                <ul>{(analysis.must_test || []).map((item: string) => <li key={item}>{item}</li>)}</ul>
                <Text strong>按风险补充</Text>
                <ul>{(analysis.should_test || []).map((item: string) => <li key={item}>{item}</li>)}</ul>
              </div>
            ),
          },
          {
            key: 'cases',
            label: `测试用例（${cases.length}）`,
            children: (
              <div className="product-card">
                <div className="test-task-toolbar">
                  {AI_OPS.map((item) => (
                    <Button key={item.op} onClick={() => void runOp(item.op)} loading={loading}>{item.label}</Button>
                  ))}
                  <Button type="primary" onClick={() => { form.resetFields(); setEditing({ case_name: '', priority: 'P1', type: 'functional', status: 'draft' }); }}>新增</Button>
                  <Button onClick={() => void exportCsv()}>导出</Button>
                </div>
                <Table
                  rowKey={(row) => String(row.id || row.case_code)}
                  loading={loading}
                  dataSource={cases}
                  scroll={{ x: 1400 }}
                  pagination={false}
                  columns={[
                    { title: '用例ID', dataIndex: 'case_code', width: 120 },
                    { title: '模块', dataIndex: 'module', width: 90 },
                    { title: '测试场景', dataIndex: 'scenario', width: 180, render: (_: string, row) => row.scenario || row.case_name },
                    { title: '前置条件', dataIndex: 'precondition', width: 160, ellipsis: true },
                    { title: '操作步骤', dataIndex: 'steps', width: 220, ellipsis: true, render: stepText },
                    { title: '测试数据', dataIndex: 'test_data', width: 140, ellipsis: true },
                    { title: '预期结果', dataIndex: 'expected_result', width: 180, ellipsis: true },
                    { title: '优先级', dataIndex: 'priority', width: 80 },
                    { title: '类型', dataIndex: 'type', width: 100 },
                    { title: '标签', dataIndex: 'tags', width: 120, render: (tags: string[]) => (tags || []).map((tag) => <Tag key={tag}>{tag}</Tag>) },
                    { title: '状态', dataIndex: 'status', width: 80 },
                    {
                      title: '操作',
                      width: 140,
                      fixed: 'right',
                      render: (_: unknown, row) => (
                        <Space>
                          <Button type="link" onClick={() => { setEditing(row); form.setFieldsValue({ ...row, tags: (row.tags || []).join(','), steps: stepText(row.steps).replace(/ \/ /g, '\n') }); }}>编辑</Button>
                          <Button type="link" danger onClick={() => void removeCase(row)}>删除</Button>
                        </Space>
                      ),
                    },
                  ]}
                />
              </div>
            ),
          },
          {
            key: 'scripts',
            label: '自动化脚本',
            children: (
              <div className="product-card">
                <Button onClick={() => void runOp('to_automation')}>把当前用例转成 Playwright</Button>
                <ul>{(data?.scripts || []).map((item: any) => <li key={item.id}>{item.name}</li>)}</ul>
              </div>
            ),
          },
          {
            key: 'execution',
            label: '测试执行',
            children: (
              <div className="product-card">
                <Space>
                  <Button onClick={() => void runOp('execute')}>执行当前用例</Button>
                  <Button onClick={() => void runOp('analyze_failure')}>分析失败原因</Button>
                  <Button onClick={() => void runOp('create_bug')}>生成缺陷</Button>
                </Space>
                <ul>{(data?.executions || []).map((item: any) => <li key={item.id}>#{item.id} {item.status} {item.error || ''}</li>)}</ul>
              </div>
            ),
          },
          {
            key: 'defects',
            label: '缺陷',
            children: (
              <div className="product-card">
                <ul>{(data?.defects || []).map((item: any) => <li key={item.id}>{item.name}</li>)}</ul>
                {!(data?.defects || []).length && <Paragraph type="secondary">执行失败后生成的缺陷会回写到这里和项目资产。</Paragraph>}
              </div>
            ),
          },
          {
            key: 'report',
            label: '测试报告',
            children: (
              <div className="product-card">
                <Button onClick={() => void runOp('generate_report')}>生成测试报告</Button>
                <ul>{(data?.reports || []).map((item: any) => <li key={item.id}>{item.name}</li>)}</ul>
              </div>
            ),
          },
        ]}
      />

      <Modal title={editing?.id ? '编辑用例' : '新增用例'} open={!!editing} onOk={() => void saveCase()} onCancel={() => setEditing(null)} width={720}>
        <Form form={form} layout="vertical">
          <Form.Item name="case_code" label="用例ID"><Input /></Form.Item>
          <Form.Item name="module" label="模块"><Input /></Form.Item>
          <Form.Item name="scenario" label="测试场景" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="case_name" label="用例名称"><Input /></Form.Item>
          <Form.Item name="precondition" label="前置条件"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="steps" label="操作步骤（每行一步）"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="test_data" label="测试数据"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="expected_result" label="预期结果"><Input.TextArea rows={2} /></Form.Item>
          <Space>
            <Form.Item name="priority" label="优先级"><Select style={{ width: 100 }} options={['P0', 'P1', 'P2', 'P3'].map((v) => ({ value: v, label: v }))} /></Form.Item>
            <Form.Item name="type" label="类型"><Select style={{ width: 160 }} options={['functional', 'error', 'boundary', 'permission', 'data_validation'].map((v) => ({ value: v, label: v }))} /></Form.Item>
            <Form.Item name="status" label="状态"><Select style={{ width: 120 }} options={['draft', 'reviewed', 'published', 'archived'].map((v) => ({ value: v, label: v }))} /></Form.Item>
          </Space>
          <Form.Item name="tags" label="标签"><Input placeholder="逗号分隔" /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
