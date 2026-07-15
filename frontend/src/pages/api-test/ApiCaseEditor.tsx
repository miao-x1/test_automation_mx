/**
 * API 测试 - 用例编辑器弹窗
 * 支持新建/编辑模式，包含基本信息、步骤编辑、断言编辑
 */
import { useState, useEffect } from 'react';
import {
  Modal, Card, Button, Space, Typography, Input, Select,
  InputNumber, Empty, message,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, SaveOutlined,
} from '@ant-design/icons';
import { saveCase, ApiCase, Step, Assertion } from '../../services/apiCase';

const { Text } = Typography;
const { TextArea } = Input;

const ASSERTION_TYPES = [
  { value: 'equals', label: '等于' },
  { value: 'not_equals', label: '不等于' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
  { value: 'not_empty', label: '非空' },
  { value: 'exists', label: '存在' },
  { value: 'is_type', label: '类型检查' },
  { value: 'greater_than', label: '大于' },
  { value: 'less_than', label: '小于' },
  { value: 'regex', label: '正则匹配' },
];

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];

const METHOD_COLOR: Record<string, string> = {
  GET: '#61affe', POST: '#49cc90', PUT: '#fca130',
  DELETE: '#f93e3e', PATCH: '#50e3c2', HEAD: '#9012fe', OPTIONS: '#0d5aa7',
};

interface ApiCaseEditorProps {
  visible: boolean;
  caseData: ApiCase | null;
  folderId?: number;
  onClose: () => void;
  onSave: () => void;
}

export default function ApiCaseEditor({ visible, caseData, folderId, onClose, onSave }: ApiCaseEditorProps) {
  const [form, setForm] = useState({
    title: '',
    case_id: '',
    description: '',
    priority: 'medium',
    status: 'draft',
    precondition: '',
    tags: '',
  });
  const [steps, setSteps] = useState<Step[]>([]);
  const [assertions, setAssertions] = useState<Assertion[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      if (caseData) {
        setForm({
          title: caseData.title || '',
          case_id: caseData.case_id || '',
          description: caseData.description || '',
          priority: caseData.priority || 'medium',
          status: caseData.status || 'draft',
          precondition: caseData.precondition || '',
          tags: caseData.tags || '',
        });
        setSteps(caseData.steps || []);
        setAssertions(caseData.assertions || []);
      } else {
        setForm({ title: '', case_id: '', description: '', priority: 'medium', status: 'draft', precondition: '', tags: '' });
        setSteps([{ action: 'GET', url: '', headers: {}, body: {} }]);
        setAssertions([]);
      }
    }
  }, [caseData, visible]);

  const handleSave = async () => {
    if (!form.title.trim()) { message.warning('标题不能为空'); return; }
    if (steps.length === 0) { message.warning('至少需要一个步骤'); return; }

    setSaving(true);
    try {
      await saveCase({
        id: caseData?.id,
        title: form.title,
        case_id: form.case_id || undefined,
        description: form.description || undefined,
        folder_id: folderId,
        priority: form.priority,
        status: form.status,
        tags: form.tags || undefined,
        precondition: form.precondition || undefined,
        steps,
        assertions,
      });
      message.success(caseData ? '更新成功' : '创建成功');
      onSave();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败');
    }
    setSaving(false);
  };

  const addStep = () => setSteps([...steps, { action: 'GET', url: '', headers: {}, body: {} }]);
  const removeStep = (i: number) => setSteps(steps.filter((_, idx) => idx !== i));
  const updateStep = (i: number, field: string, value: unknown) => {
    const newSteps = [...steps];
    newSteps[i] = { ...newSteps[i], [field]: value };
    setSteps(newSteps);
  };

  const addAssertion = () => setAssertions([...assertions, { type: 'equals', path: '', expected: '' }]);
  const removeAssertion = (i: number) => setAssertions(assertions.filter((_, idx) => idx !== i));
  const updateAssertion = (i: number, field: string, value: unknown) => {
    const newAssertions = [...assertions];
    newAssertions[i] = { ...newAssertions[i], [field]: value };
    setAssertions(newAssertions);
  };

  return (
    <Modal
      title={caseData ? `编辑用例 - ${caseData.title}` : '新建用例'}
      open={visible}
      onCancel={onClose}
      width={900}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="save" type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
          保存
        </Button>,
      ]}
    >
      {/* 基本信息 */}
      <Card size="small" title="基本信息" style={{ marginBottom: 12 }}>
        <Space wrap style={{ width: '100%' }}>
          <Space><Text>标题:</Text><Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} style={{ width: 300 }} /></Space>
          <Space><Text>编号:</Text><Input value={form.case_id} onChange={e => setForm({ ...form, case_id: e.target.value })} style={{ width: 120 }} placeholder="C001" /></Space>
          <Space><Text>优先级:</Text><Select value={form.priority} onChange={v => setForm({ ...form, priority: v })} style={{ width: 80 }} options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} /></Space>
          <Space><Text>状态:</Text><Select value={form.status} onChange={v => setForm({ ...form, status: v })} style={{ width: 100 }} options={[{ value: 'draft', label: '草稿' }, { value: 'ready', label: '就绪' }, { value: 'deprecated', label: '废弃' }]} /></Space>
        </Space>
        <div style={{ marginTop: 8 }}>
          <Text>前置条件:</Text>
          <TextArea rows={1} value={form.precondition} onChange={e => setForm({ ...form, precondition: e.target.value })} style={{ marginTop: 4 }} />
        </div>
        <div style={{ marginTop: 8 }}>
          <Text>标签:</Text>
          <Input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} style={{ marginTop: 4, width: 300 }} placeholder="多个标签用逗号分隔" />
        </div>
      </Card>

      {/* 步骤编辑 */}
      <Card size="small" title={`测试步骤 (${steps.length})`} style={{ marginBottom: 12 }} extra={
        <Button size="small" icon={<PlusOutlined />} onClick={addStep}>添加步骤</Button>
      }>
        {steps.map((step, i) => (
          <Card key={i} size="small" style={{ marginBottom: 8, background: '#fafafa' }}>
            <Space wrap style={{ width: '100%' }}>
              <Text>步骤{i + 1}</Text>
              <Select value={step.action} onChange={v => updateStep(i, 'action', v)} style={{ width: 100 }}
                options={HTTP_METHODS.map(m => ({ value: m, label: <span style={{ color: METHOD_COLOR[m] }}>{m}</span> }))} />
              <Input value={step.url} onChange={e => updateStep(i, 'url', e.target.value)}
                style={{ width: 320 }} placeholder="/api/xxx" />
              <InputNumber value={step.timeout} onChange={v => updateStep(i, 'timeout', v ?? undefined)}
                style={{ width: 90 }} placeholder="超时(s)" min={1} max={120} />
              <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeStep(i)} />
            </Space>
            {/* Headers */}
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">Headers (JSON):</Text>
              <TextArea rows={2} value={JSON.stringify(step.headers || {}, null, 2)}
                onChange={e => {
                  try { updateStep(i, 'headers', JSON.parse(e.target.value)); } catch { /* ignore */ }
                }} style={{ fontFamily: 'monospace', fontSize: 12 }} />
            </div>
            {/* Body */}
            {['POST', 'PUT', 'PATCH'].includes(step.action) && (
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">Body (JSON):</Text>
                <TextArea rows={3} value={JSON.stringify(step.body || {}, null, 2)}
                  onChange={e => {
                    try { updateStep(i, 'body', JSON.parse(e.target.value)); } catch { /* ignore */ }
                  }} style={{ fontFamily: 'monospace', fontSize: 12 }} />
              </div>
            )}
            {/* 变量提取 */}
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">变量提取 (JSON):</Text>
              <TextArea rows={2} value={JSON.stringify(step.extract || [], null, 2)}
                onChange={e => {
                  try { updateStep(i, 'extract', JSON.parse(e.target.value)); } catch { /* ignore */ }
                }} style={{ fontFamily: 'monospace', fontSize: 12 }} placeholder='[{"key":"token","path":"data.token"}]' />
            </div>
          </Card>
        ))}
        {steps.length === 0 && <Empty description="暂无步骤" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      {/* 断言编辑 */}
      <Card size="small" title={`断言规则 (${assertions.length})`} extra={
        <Button size="small" icon={<PlusOutlined />} onClick={addAssertion}>添加断言</Button>
      }>
        {assertions.map((a, i) => (
          <Space key={i} style={{ marginBottom: 4, display: 'flex' }} wrap>
            <Select value={a.type} onChange={v => updateAssertion(i, 'type', v)} style={{ width: 110 }}
              options={ASSERTION_TYPES} />
            <Input value={a.path} onChange={e => updateAssertion(i, 'path', e.target.value)}
              style={{ width: 200 }} placeholder="data.code" />
            <Input value={String(a.expected ?? '')} onChange={e => updateAssertion(i, 'expected', e.target.value)}
              style={{ width: 150 }} placeholder="期望值" />
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => removeAssertion(i)} />
          </Space>
        ))}
        {assertions.length === 0 && <Empty description="暂无断言" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>
    </Modal>
  );
}
