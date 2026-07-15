/**
 * 测试用例中心页面
 *
 * 路由: /test-case
 *
 * 页面结构：
 *   顶部：需求来源（输入需求、上传文件）
 *   中间：AI生成过程（需求解析→测试点分析→RAG检索→生成用例→审核）
 *   底部：测试用例列表（编辑/删除/导出CSV）
 *   抽屉：思维导图
 */
import { useState } from 'react';
import {
  Card,
  Button,
  Input,
  Steps,
  Timeline,
  Table,
  Modal,
  Tag,
  Tooltip,
  Drawer,
  Tree,
  Tabs,
  Upload,
  message,
  Space,
  Statistic,
  Row,
  Col,
  Empty,
  Spin,
  Form,
  Select,
  Popconfirm,
  Typography,
} from 'antd';
import {
  RobotOutlined,
  FileTextOutlined,
  PictureOutlined,
  ExportOutlined,
  EditOutlined,
  DeleteOutlined,
  ApartmentOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  MessageOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import {
  generateTestCases,
  getTestCases,
  getMindMap,
  updateTestCase,
  deleteTestCase,
  regenerateTestCases,
  getAgentMessages,
  type GenerateRequest,
  type GenerateResponse,
  type TestCaseItem,
  type TestCaseResult,
  type MindMapNode,
  type AgentMessageItem,
} from '../../services/testcaseGeneration';
import AIContextTab from './AIContextTab';

const { TextArea } = Input;
const { Text } = Typography;

// AI生成步骤定义
const GENERATION_STEPS = [
  { title: '需求解析', description: '理解用户需求，提取业务模块和功能点' },
  { title: '测试点分析', description: '分析功能/异常/边界/权限/数据校验测试点' },
  { title: 'RAG检索', description: '检索历史用例和业务规则(TopK过滤)' },
  { title: '生成用例', description: '根据测试点+RAG上下文生成结构化用例' },
  { title: '用例审核', description: '审核步骤完整性、预期明确性、异常覆盖度' },
];

// 优先级颜色映射
const PRIORITY_COLORS: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'green',
};

// 用例类型名称
const TYPE_NAMES: Record<string, string> = {
  functional: '功能测试',
  error: '异常测试',
  boundary: '边界测试',
  permission: '权限测试',
  data_validation: '数据校验',
};

// 审核结果标签
const REVIEW_TAG = {
  pass: { color: 'green', text: '通过' },
  need_revision: { color: 'orange', text: '需修改' },
  reject: { color: 'red', text: '拒绝' },
};

export default function TestCasePage() {
  // === 状态 ===
  const [requirement, setRequirement] = useState('');
  const [sourceType, setSourceType] = useState('text');
  const [loading, setLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [genStatus, setGenStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle');
  const [genResult, setGenResult] = useState<GenerateResponse | null>(null);
  const [testResult, setTestResult] = useState<TestCaseResult | null>(null);
  const [timelineLogs, setTimelineLogs] = useState<string[]>([]);
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingCase, setEditingCase] = useState<TestCaseItem | null>(null);
  const [mindmapVisible, setMindmapVisible] = useState(false);
  const [mindmapData, setMindmapData] = useState<MindMapNode | null>(null);
  const [mindmapLoading, setMindmapLoading] = useState(false);
  // 阶段四新增状态
  const [regenerating, setRegenerating] = useState(false);
  const [agentMessages, setAgentMessages] = useState<AgentMessageItem[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [savingCase, setSavingCase] = useState(false);
  const [imageData, setImageData] = useState<string>('');

  // === 生成测试用例 ===
  const handleGenerate = async () => {
    if (!requirement.trim()) {
      message.warning('请输入测试需求');
      return;
    }

    setLoading(true);
    setGenStatus('running');
    setCurrentStep(0);
    setTimelineLogs([]);

    try {
      const request: GenerateRequest = {
        requirement,
        source_type: sourceType,
        workflow_name: 'testcase_generation',
        image_data: imageData || undefined,
      };

      // 模拟步骤推进
      const stepTimer = setInterval(() => {
        setCurrentStep(prev => {
          if (prev < GENERATION_STEPS.length - 1) return prev + 1;
          return prev;
        });
      }, 2000);

      const result = await generateTestCases(request);
      clearInterval(stepTimer);
      setCurrentStep(GENERATION_STEPS.length);

      setGenResult(result);
      setTimelineLogs([
        `需求解析完成 | 模块: ${result.status === 'completed' ? '成功' : '失败'}`,
        `测试点分析完成 | 共 ${result.total_points} 个测试点`,
        `RAG检索完成 | TopK过滤`,
        `用例生成完成 | 共 ${result.total_cases} 条用例`,
        `用例审核完成 | 平均分: ${result.avg_score}`,
      ]);

      if (result.status === 'completed') {
        setGenStatus('done');
        message.success(`生成成功！${result.total_cases}条用例，平均分${result.avg_score}`);
        // 自动加载结果
        await fetchTestCases(result.task_id);
        // 自动加载Agent执行消息
        await fetchAgentMessages(result.task_id);
      } else {
        setGenStatus('error');
        message.error(`生成失败: ${result.error}`);
      }
    } catch (err: any) {
      setGenStatus('error');
      message.error(`请求失败: ${err.message || err}`);
    } finally {
      setLoading(false);
    }
  };

  // === 查询生成结果 ===
  const fetchTestCases = async (taskId: string) => {
    try {
      const result = await getTestCases(taskId);
      setTestResult(result);
    } catch (err: any) {
      message.error(`查询结果失败: ${err.message || err}`);
    }
  };

  // === 获取思维导图 ===
  const handleViewMindmap = async () => {
    if (!genResult?.task_id) {
      message.warning('请先生成测试用例');
      return;
    }
    setMindmapVisible(true);
    setMindmapLoading(true);
    try {
      const resp = await getMindMap(genResult.task_id);
      setMindmapData(resp.mindmap);
    } catch (err: any) {
      message.error(`获取思维导图失败: ${err.message || err}`);
    } finally {
      setMindmapLoading(false);
    }
  };

  // === 重新生成测试用例（阶段四新增） ===
  const handleRegenerate = async () => {
    if (!genResult?.task_id) {
      message.warning('请先生成测试用例');
      return;
    }
    setRegenerating(true);
    setGenStatus('running');
    setCurrentStep(0);
    try {
      const resp = await regenerateTestCases(genResult.task_id);
      if (resp.status === 'success') {
        message.success('重新生成完成');
        setGenStatus('done');
        // 重新加载结果
        await fetchTestCases(genResult.task_id);
        // 重新加载Agent消息
        await fetchAgentMessages(genResult.task_id);
      } else {
        setGenStatus('error');
        message.error(`重新生成失败: ${resp.message}`);
      }
    } catch (err: any) {
      setGenStatus('error');
      message.error(`重新生成失败: ${err.message || err}`);
    } finally {
      setRegenerating(false);
    }
  };

  // === 获取Agent执行消息日志（阶段四新增） ===
  const fetchAgentMessages = async (taskId: string) => {
    setMessagesLoading(true);
    try {
      const resp = await getAgentMessages(taskId);
      setAgentMessages(resp.messages);
    } catch (err: any) {
      // 静默失败，不影响主流程
      console.warn('获取Agent消息失败:', err);
    } finally {
      setMessagesLoading(false);
    }
  };

  // === 导出CSV ===
  const handleExport = () => {
    if (!testResult || testResult.test_cases.length === 0) {
      message.warning('暂无用例可导出');
      return;
    }
    // 生成CSV
    const headers = ['用例名称', '前置条件', '步骤', '预期结果', '优先级', '类型', '审核分数', '审核结果'];
    const rows = testResult.test_cases.map(c => [
      c.case_name,
      c.precondition,
      c.steps.map((s, i) => `${i + 1}. ${s.action} ${s.description} (预期: ${s.expected})`).join('\n'),
      c.expected_result,
      c.priority,
      TYPE_NAMES[c.type] || c.type,
      c.review_score.toString(),
      REVIEW_TAG[c.review_result as keyof typeof REVIEW_TAG]?.text || c.review_result,
    ]);
    const csv = [headers, ...rows].map(r => r.map(cell => `"${cell}"`).join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `test_cases_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    message.success('导出成功');
  };

  // === 编辑用例 ===
  const handleEdit = (record: TestCaseItem) => {
    setEditingCase({ ...record });
    setEditModalVisible(true);
  };

  // === 保存编辑（阶段四：调用PUT API持久化） ===
  const handleSaveEdit = async () => {
    if (!editingCase) return;
    setSavingCase(true);
    try {
      const resp = await updateTestCase(editingCase.id, {
        case_name: editingCase.case_name,
        precondition: editingCase.precondition,
        steps: editingCase.steps,
        expected_result: editingCase.expected_result,
        priority: editingCase.priority,
        type: editingCase.type,
        status: editingCase.status,
      });
      // 更新本地状态
      setTestResult(prev => prev ? {
        ...prev,
        test_cases: prev.test_cases.map(c =>
          c.id === editingCase.id ? editingCase : c
        ),
      } : null);
      message.success(`${resp.message}（版本 ${resp.version}）`);
      setEditModalVisible(false);
    } catch (err: any) {
      message.error(`保存失败: ${err.message || err}`);
    } finally {
      setSavingCase(false);
    }
  };

  // === 删除用例（阶段四：调用DELETE API持久化） ===
  const handleDelete = async (record: TestCaseItem) => {
    try {
      await deleteTestCase(record.id);
      setTestResult(prev => prev ? {
        ...prev,
        test_cases: prev.test_cases.filter(c => c.id !== record.id),
        total: prev.total - 1,
      } : null);
      message.success('已删除');
    } catch (err: any) {
      message.error(`删除失败: ${err.message || err}`);
    }
  };

  // === 转换思维导图数据为Tree格式 ===
  const mindmapToTreeData = (node: MindMapNode): any => ({
    title: (
      <span>
        {node.name}
        {node.priority && <Tag color={PRIORITY_COLORS[node.priority] || 'default'} style={{ marginLeft: 8 }}>{node.priority}</Tag>}
      </span>
    ),
    key: `${node.name}_${Math.random()}`,
    children: node.children?.map(mindmapToTreeData) || [],
  });

  // === 表格列定义 ===
  const columns: ColumnsType<TestCaseItem> = [
    {
      title: '用例名称',
      dataIndex: 'case_name',
      key: 'case_name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 70,
      render: (val: string) => <Tag color={PRIORITY_COLORS[val] || 'default'}>{val}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 90,
      render: (val: string) => TYPE_NAMES[val] || val,
    },
    {
      title: '前置条件',
      dataIndex: 'precondition',
      key: 'precondition',
      width: 150,
      ellipsis: true,
    },
    {
      title: '步骤数',
      key: 'step_count',
      width: 70,
      render: (_: any, record: TestCaseItem) => record.steps.length,
    },
    {
      title: '预期结果',
      dataIndex: 'expected_result',
      key: 'expected_result',
      width: 200,
      ellipsis: true,
    },
    {
      title: '审核',
      key: 'review',
      width: 100,
      render: (_: any, record: TestCaseItem) => {
        if (!record.review_result) return <Tag>未审核</Tag>;
        const tag = REVIEW_TAG[record.review_result as keyof typeof REVIEW_TAG];
        return (
          <Tooltip title={`分数: ${record.review_score}`}>
            <Tag color={tag?.color || 'default'}>{tag?.text || record.review_result}</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: TestCaseItem) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // === 渲染 ===
  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="generate"
        items={[
          {
            key: 'generate',
            label: <span><RobotOutlined /> 用例生成</span>,
            children: (
              <>
                {/* 顶部：需求来源 */}
                <Card title={<span><RobotOutlined /> 测试需求输入</span>} style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={4}>
            <Select
              value={sourceType}
              onChange={setSourceType}
              style={{ width: '100%' }}
              options={[
                { value: 'text', label: '自然语言' },
                { value: 'image', label: '图片截图' },
                { value: 'pdf', label: 'PDF文档' },
                { value: 'word', label: 'Word文档' },
                { value: 'api_doc', label: 'API文档' },
                { value: 'db_schema', label: '数据库Schema' },
              ]}
            />
          </Col>
          <Col span={16}>
            <TextArea
              value={requirement}
              onChange={e => setRequirement(e.target.value)}
              placeholder="请输入测试需求，例如：测试商城登录功能，包括账号密码登录、异常输入、边界条件等"
              rows={3}
              maxLength={2000}
              showCount
            />
          </Col>
          <Col span={4}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                type="primary"
                icon={<RobotOutlined />}
                onClick={handleGenerate}
                loading={loading}
                block
              >
                生成用例
              </Button>
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={(file) => {
                  // 读取文件为 base64 并保存到状态
                  const reader = new FileReader();
                  reader.onload = (e) => {
                    setImageData(e.target?.result as string);
                    message.success('图片已选择');
                  };
                  reader.onerror = () => {
                    message.error('图片读取失败');
                  };
                  reader.readAsDataURL(file);
                  return false; // 阻止自动上传
                }}
              >
                <Button icon={<PictureOutlined />} block>
                  {imageData ? '重新上传图片' : '上传图片'}
                </Button>
              </Upload>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 中间：AI生成过程 */}
      {(genStatus !== 'idle') && (
        <Card title={<span><ApartmentOutlined /> AI生成过程</span>} style={{ marginBottom: 16 }}>
          <Steps
            current={currentStep}
            size="small"
            items={GENERATION_STEPS.map((step, i) => ({
              title: step.title,
              description: step.description,
              status:
                genStatus === 'error' && i === currentStep ? 'error' :
                i < currentStep ? 'finish' :
                i === currentStep && genStatus === 'running' ? 'process' :
                i === currentStep && genStatus === 'done' ? 'finish' : 'wait',
            }))}
          />
          {genResult && (
            <Row gutter={16} style={{ marginTop: 16 }}>
              <Col span={6}>
                <Statistic title="测试点" value={genResult.total_points} />
              </Col>
              <Col span={6}>
                <Statistic title="测试用例" value={genResult.total_cases} />
              </Col>
              <Col span={6}>
                <Statistic title="平均审核分" value={genResult.avg_score} suffix="/100" />
              </Col>
              <Col span={6}>
                <Statistic title="耗时" value={genResult.duration.toFixed(1)} suffix="秒" />
              </Col>
            </Row>
          )}
          {timelineLogs.length > 0 && (
            <Timeline style={{ marginTop: 16 }} mode="left" items={timelineLogs.map(log => ({
              children: <Text type="secondary">{log}</Text>,
            }))} />
          )}
        </Card>
      )}

      {/* 底部：测试用例列表 */}
      <Card
        title={<span><FileTextOutlined /> 测试用例列表</span>}
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={handleRegenerate}
              loading={regenerating}
              disabled={!genResult?.task_id}
            >
              重新生成
            </Button>
            <Button
              icon={<MessageOutlined />}
              onClick={() => genResult?.task_id && fetchAgentMessages(genResult.task_id)}
              disabled={!genResult?.task_id}
            >
              Agent日志
            </Button>
            <Button icon={<ApartmentOutlined />} onClick={handleViewMindmap} disabled={!genResult?.task_id}>
              思维导图
            </Button>
            <Button icon={<ExportOutlined />} onClick={handleExport} disabled={!testResult?.test_cases.length}>
              导出CSV
            </Button>
          </Space>
        }
      >
        {testResult && testResult.test_cases.length > 0 ? (
          <>
            {/* 测试点统计 */}
            {testResult.test_points.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <Text strong>测试点 ({testResult.test_points.length}):</Text>
                <Space wrap style={{ marginLeft: 16 }}>
                  {testResult.test_points.map(p => (
                    <Tag key={p.id} color={PRIORITY_COLORS[p.priority] || 'default'}>
                      {p.name} ({TYPE_NAMES[p.type] || p.type})
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
            <Table
              columns={columns}
              dataSource={testResult.test_cases}
              rowKey="id"
              size="middle"
              pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 条` }}
              expandable={{
                expandedRowRender: (record: TestCaseItem) => (
                  <div style={{ padding: 8 }}>
                    <Text strong>测试步骤：</Text>
                    <ol style={{ margin: '8px 0' }}>
                      {record.steps.map((s, i) => (
                        <li key={i} style={{ marginBottom: 4 }}>
                          <Tag color="blue">{s.action || 'step'}</Tag>
                          {s.description}
                          {s.target && <Text type="secondary"> | 目标: {s.target}</Text>}
                          {s.value && <Text type="secondary"> | 值: {s.value}</Text>}
                          <Text type="secondary"> | 预期: {s.expected}</Text>
                        </li>
                      ))}
                    </ol>
                    {record.review_suggestions.length > 0 && (
                      <>
                        <Text strong>审核建议：</Text>
                        <ul style={{ margin: '8px 0' }}>
                          {record.review_suggestions.map((s, i) => (
                            <li key={i}><Text type="warning">{s}</Text></li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                ),
              }}
            />
          </>
        ) : (
          <Empty description="暂无测试用例，请先生成" />
        )}
      </Card>

      {/* Agent执行消息日志（阶段四新增） */}
      {agentMessages.length > 0 && (
        <Card
          title={<span><MessageOutlined /> Agent执行日志 ({agentMessages.length})</span>}
          style={{ marginBottom: 16 }}
          size="small"
        >
          <Spin spinning={messagesLoading}>
            <Timeline
              mode="left"
              items={agentMessages.map(msg => ({
                color: msg.status === 'success' ? 'green' : msg.status === 'failed' ? 'red' : 'blue',
                children: (
                  <div>
                    <Space>
                      <Tag icon={<RobotOutlined />} color="blue">{msg.sender}</Tag>
                      {msg.receiver && <Tag color="cyan">{msg.receiver}</Tag>}
                      <Tag>{msg.action || msg.message_type}</Tag>
                      <Tag color={msg.status === 'success' ? 'green' : msg.status === 'failed' ? 'red' : 'default'}>
                        {msg.status}
                      </Tag>
                      {msg.duration > 0 && (
                        <Text type="secondary"><ClockCircleOutlined /> {msg.duration.toFixed(1)}s</Text>
                      )}
                    </Space>
                    {msg.step && <div><Text type="secondary">步骤: {msg.step}</Text></div>}
                    {msg.error && <div><Text type="danger">{msg.error}</Text></div>}
                  </div>
                ),
              }))}
            />
          </Spin>
        </Card>
      )}

      {/* 编辑用例弹窗 */}
      <Modal
        title="编辑测试用例"
        open={editModalVisible}
        onCancel={() => setEditModalVisible(false)}
        onOk={handleSaveEdit}
        confirmLoading={savingCase}
        okText="保存"
        cancelText="取消"
        width={700}
      >
        {editingCase && (
          <Form layout="vertical">
            <Form.Item label="用例名称">
              <Input
                value={editingCase.case_name}
                onChange={e => setEditingCase({ ...editingCase, case_name: e.target.value })}
              />
            </Form.Item>
            <Form.Item label="前置条件">
              <TextArea
                value={editingCase.precondition}
                onChange={e => setEditingCase({ ...editingCase, precondition: e.target.value })}
                rows={2}
              />
            </Form.Item>
            {/* 测试步骤编辑（阶段四新增：支持人工修改步骤） */}
            <Form.Item label="测试步骤">
              <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, padding: 12 }}>
                {editingCase.steps.map((step, idx) => (
                  <Row key={idx} gutter={8} style={{ marginBottom: 8, alignItems: 'center' }}>
                    <Col span={1}><Text strong>{idx + 1}.</Text></Col>
                    <Col span={7}>
                      <Input
                        placeholder="操作"
                        value={step.action || ''}
                        onChange={e => {
                          const newSteps = [...editingCase.steps];
                          newSteps[idx] = { ...step, action: e.target.value };
                          setEditingCase({ ...editingCase, steps: newSteps });
                        }}
                      />
                    </Col>
                    <Col span={8}>
                      <Input
                        placeholder="描述"
                        value={step.description || ''}
                        onChange={e => {
                          const newSteps = [...editingCase.steps];
                          newSteps[idx] = { ...step, description: e.target.value };
                          setEditingCase({ ...editingCase, steps: newSteps });
                        }}
                      />
                    </Col>
                    <Col span={7}>
                      <Input
                        placeholder="预期结果"
                        value={step.expected || ''}
                        onChange={e => {
                          const newSteps = [...editingCase.steps];
                          newSteps[idx] = { ...step, expected: e.target.value };
                          setEditingCase({ ...editingCase, steps: newSteps });
                        }}
                      />
                    </Col>
                    <Col span={1}>
                      <Button
                        type="text"
                        danger
                        size="small"
                        icon={<DeleteOutlined />}
                        onClick={() => {
                          const newSteps = editingCase.steps.filter((_, i) => i !== idx);
                          setEditingCase({ ...editingCase, steps: newSteps });
                        }}
                      />
                    </Col>
                  </Row>
                ))}
                <Button
                  type="dashed"
                  size="small"
                  block
                  icon={<EditOutlined />}
                  onClick={() => {
                    setEditingCase({
                      ...editingCase,
                      steps: [...editingCase.steps, { step_no: editingCase.steps.length + 1, action: '', description: '', expected: '' }],
                    });
                  }}
                >
                  添加步骤
                </Button>
              </div>
            </Form.Item>
            <Form.Item label="预期结果">
              <TextArea
                value={editingCase.expected_result}
                onChange={e => setEditingCase({ ...editingCase, expected_result: e.target.value })}
                rows={2}
              />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="优先级">
                  <Select
                    value={editingCase.priority}
                    onChange={v => setEditingCase({ ...editingCase, priority: v })}
                    options={Object.keys(PRIORITY_COLORS).map(p => ({ value: p, label: p }))}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="类型">
                  <Select
                    value={editingCase.type}
                    onChange={v => setEditingCase({ ...editingCase, type: v })}
                    options={Object.entries(TYPE_NAMES).map(([v, l]) => ({ value: v, label: l }))}
                  />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        )}
      </Modal>

      {/* 思维导图抽屉（企业级思维导图展示） */}
      <Drawer
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span><ApartmentOutlined /> 测试用例思维导图</span>
            {mindmapData && (
              <Space size="small">
                <Tag color="red">P0</Tag>
                <Tag color="orange">P1</Tag>
                <Tag color="blue">P2</Tag>
                <Tag color="green">P3</Tag>
              </Space>
            )}
          </div>
        }
        open={mindmapVisible}
        onClose={() => setMindmapVisible(false)}
        width={720}
      >
        {mindmapLoading ? (
          <div style={{ textAlign: 'center', paddingTop: 50 }}>
            <Spin size="large" />
          </div>
        ) : mindmapData ? (
          <div style={{
            background: '#fafafa',
            padding: 16,
            borderRadius: 8,
            minHeight: 'calc(100vh - 120px)',
          }}>
            <Tree
              treeData={[mindmapToTreeData(mindmapData)]}
              defaultExpandAll
              showLine
              blockNode
              selectable={false}
            />
          </div>
        ) : (
          <Empty description="暂无思维导图数据" />
        )}
      </Drawer>
            </>
          ),
        },
        {
          key: 'ai-context',
          label: <span><DatabaseOutlined /> AI上下文</span>,
          children: <AIContextTab taskId={genResult?.task_id} />,
        },
      ]}
    />
    </div>
  );
}
