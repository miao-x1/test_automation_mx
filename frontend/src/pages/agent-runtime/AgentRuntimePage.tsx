/**
 * AI 执行过程页面
 *
 * 展示 Agent 执行过程：
 *   任务启动 → 需求分析Agent → RAG检索 → 用例生成 → 脚本生成 → 执行 → 结果分析
 *
 * 使用 SSE 实时推送 Agent 状态。
 */
import { useState, useEffect, useRef } from 'react';
import {
  Card, Row, Col, Input, Button, Steps, Tag, Timeline, Spin, message,
  Tabs, Table, Statistic, Progress, Empty, Typography, Space, Descriptions, Alert,
} from 'antd';
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, ClockCircleOutlined, RobotOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  runTaskSSE, getTaskLogs, listAgents, listWorkflows, getRuntimeStats,
  type AgentMeta, type WorkflowDef, type AgentExecutionLog,
} from '../../services/agentRuntime';
import AIClassifyCard from '../../components/AIClassifyCard';
import DegradationAlert, { type DegradationInfo } from '../../components/DegradationAlert';
import {
  classifyTestType,
  type ClassifyResult,
} from '../../services/testTypeClassifier';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

/** Agent 执行状态颜色映射 */
const STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  completed: 'success',
  failed: 'error',
  skipped: 'warning',
  retrying: 'processing',
};

/** Agent 执行状态图标 */
function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed':
      return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    case 'running':
      return <LoadingOutlined style={{ color: '#1677ff' }} />;
    default:
      return <ClockCircleOutlined style={{ color: '#bfbfbf' }} />;
  }
}

/** Agent 步骤状态 */
interface StepStatus {
  name: string;
  agent_name: string;
  status: string;
  message: string;
  progress: number;
  duration: number;
  input_data?: any;
  output_data?: any;
  error?: string;
}

export default function AgentRuntimePage() {
  // 任务输入
  const [requirement, setRequirement] = useState('');
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState('');

  // AI智能识别状态
  const [classifyResult, setClassifyResult] = useState<ClassifyResult | null>(null);
  const [classifyLoading, setClassifyLoading] = useState(false);
  const [classifyError, setClassifyError] = useState<string | null>(null);
  // 降级信息（脚本生成降级时展示警告）
  const [degradationInfo, setDegradationInfo] = useState<DegradationInfo | null>(null);
  // 复用信息
  const [reuseInfo, setReuseInfo] = useState<{ reused: boolean; similarity: number; scriptName: string } | null>(null);
  // 用户手动修改后的类型（覆盖AI识别结果）
  const [overrideType, setOverrideType] = useState<string | null>(null);
  const [overrideFramework, setOverrideFramework] = useState<string | null>(null);
  const [overridePlatform, setOverridePlatform] = useState<string | null>(null);
  const classifyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 执行状态
  const [steps, setSteps] = useState<StepStatus[]>([]);
  const [taskStatus, setTaskStatus] = useState('');
  const [totalSteps, setTotalSteps] = useState(0);
  const [completedSteps, setCompletedSteps] = useState(0);

  // 日志
  const [logs, setLogs] = useState<AgentExecutionLog[]>([]);

  // 后脚本步骤结果
  const [reportResult, setReportResult] = useState<any>(null);
  const [defectResult, setDefectResult] = useState<any>(null);

  // 管理面板
  const [agents, setAgents] = useState<AgentMeta[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([]);
  const [stats, setStats] = useState<any>(null);

  // 当前 Tab
  const [activeTab, setActiveTab] = useState('execution');

  // SSE 引用
  const sseRef = useRef(false);

  // 加载管理数据
  useEffect(() => {
    loadAgents();
    loadWorkflows();
    loadStats();
  }, []);

  // 需求文本变化时，自动触发AI识别（防抖）
  useEffect(() => {
    if (classifyTimerRef.current) {
      clearTimeout(classifyTimerRef.current);
    }

    if (!requirement.trim() || requirement.trim().length < 5) {
      setClassifyResult(null);
      setClassifyError(null);
      setOverrideType(null);
      setOverrideFramework(null);
      setOverridePlatform(null);
      return;
    }

    classifyTimerRef.current = setTimeout(async () => {
      await doClassify(requirement.trim());
    }, 800);

    return () => {
      if (classifyTimerRef.current) {
        clearTimeout(classifyTimerRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requirement]);

  /** 执行AI识别 */
  const doClassify = async (text: string) => {
    setClassifyLoading(true);
    setClassifyError(null);
    setOverrideType(null);
    setOverrideFramework(null);
    setOverridePlatform(null);
    try {
      const result = await classifyTestType({ requirement: text, use_llm: false });
      setClassifyResult(result);
    } catch (e: any) {
      setClassifyError(e?.message || 'AI识别请求失败');
      setClassifyResult(null);
    } finally {
      setClassifyLoading(false);
    }
  };

  const loadAgents = async () => {
    try {
      const res = await listAgents();
      setAgents(res.agents);
    } catch (e) { /* ignore */ }
  };

  const loadWorkflows = async () => {
    try {
      const res = await listWorkflows();
      setWorkflows(res.workflows);
    } catch (e) { /* ignore */ }
  };

  const loadStats = async () => {
    try {
      const res = await getRuntimeStats();
      setStats(res);
    } catch (e) { /* ignore */ }
  };

  const loadLogs = async (sid: string) => {
    try {
      const res = await getTaskLogs(sid);
      setLogs(res.logs);
    } catch (e) { /* ignore */ }
  };

  /** 提交任务（SSE 流式） */
  const handleSubmit = async () => {
    if (!requirement.trim()) {
      message.warning('请输入测试需求');
      return;
    }

    // 获取最终测试类型（优先用户修改，其次AI识别）
    const finalType = overrideType || classifyResult?.test_type || '';
    const finalFramework = overrideFramework || classifyResult?.framework || '';
    const finalPlatform = overridePlatform || classifyResult?.platform || '';
    const finalConfidence = overrideType ? 1.0 : (classifyResult?.confidence || undefined);

    setRunning(true);
    setSteps([]);
    setTaskStatus('running');
    setCompletedSteps(0);
    setLogs([]);
    sseRef.current = true;

    await runTaskSSE(
      {
        requirement: requirement.trim(),
        task_type: finalType,
        framework: finalFramework,
        platform: finalPlatform,
        confidence: finalConfidence,
        auto_classify: false, // 前端已经识别过了
        timeout: 600,
      },
      // onEvent
      (event: any) => {
        // reuse_hit — 命中脚本复用（快速预检 or 精确检索）
        if (event.event === 'reuse_hit' || event.event_type === 'reuse_hit') {
          const data = event.data || event;
          const checkType = data.check_type || 'unknown';
          setReuseInfo({
            reused: true,
            similarity: data.similarity || 0,
            scriptName: data.script_name || '',
          });
          if (data.degradation_info) {
            setDegradationInfo(data.degradation_info);
          }
          const checkLabel = checkType === 'quick' ? '快速预检' : '精确检索';
          message.success(`${checkLabel}命中脚本复用！相似度: ${data.similarity || 0}`);
          return;
        }

        // reuse_missed — 未命中复用（快速预检 or 精确检索）
        if (event.event === 'reuse_missed' || event.event_type === 'reuse_missed') {
          const data = event.data || event;
          const checkType = data.check_type || 'unknown';
          setReuseInfo({
            reused: false,
            similarity: data.similarity || 0,
            scriptName: '',
          });
          // 只在精确检索未命中时显示提示（快速预检未命中是常态，不需要提示）
          if (checkType === 'precise') {
            message.info('未找到可复用脚本，开始生成新脚本');
          }
          return;
        }

        // ===== 管道级 SSE 事件 (execute_pipeline_sse 格式) =====

        // pipeline_start — 管道开始
        if (event.event === 'pipeline_start') {
          const data = event.data || {};
          setSessionId(data.session_id || '');
          setTotalSteps(data.total_steps || 0);
          return;
        }

        // step_start — 步骤开始
        if (event.event === 'step_start') {
          const data = event.data || {};
          const stepIdx = data.step ?? 0;
          setSteps(prev => {
            const stepName = `${stepIdx + 1}. ${data.agent_type}`;
            const exists = prev.find(s => s.name === stepName);
            if (exists) {
              return prev.map(s => s.name === stepName ? {
                ...s, status: 'running', message: `执行: ${data.action || ''}`,
              } : s);
            }
            return [...prev, {
              name: stepName,
              agent_name: data.agent_type,
              status: 'running',
              message: `执行: ${data.action || ''}`,
              progress: 0,
              duration: 0,
            }];
          });
          return;
        }

        // step_progress — 步骤进度
        if (event.event === 'step_progress') {
          // 进度更新可选处理，暂不特殊展示
          return;
        }

        // step_completed — 步骤完成
        if (event.event === 'step_completed') {
          const data = event.data || {};
          const stepIdx = data.step ?? 0;
          setSteps(prev => prev.map((s, idx) => {
            // 按名称匹配或索引匹配
            const stepName = `${stepIdx + 1}. `;
            if (s.name?.startsWith(stepName) || idx === stepIdx) {
              return {
                ...s, status: 'completed',
                duration: data.duration || 0,
                output_data: data.data,
              };
            }
            return s;
          }));
          setCompletedSteps(prev => prev + 1);

          // 提取特定步骤结果用于展示组件
          const stepData = data.data;
          if (stepData) {
            const agentType = stepData.agent_type || '';
            // 根据步骤索引或 agent 类型判断
            if (stepIdx === 9 || agentType === 'report_agent') {
              setReportResult(stepData);
            }
            if (stepIdx === 10 || agentType === 'defect_agent') {
              setDefectResult(stepData);
            }
          }
          return;
        }

        // step_failed — 步骤失败
        if (event.event === 'step_failed') {
          const data = event.data || {};
          const stepIdx = data.step ?? 0;
          const errorStr = typeof data.error === 'string' ? data.error : JSON.stringify(data.error || '');
          setSteps(prev => prev.map((s, idx) => {
            const stepName = `${stepIdx + 1}. `;
            if (s.name?.startsWith(stepName) || idx === stepIdx) {
              return {
                ...s, status: 'failed',
                error: errorStr,
                message: '步骤失败',
              };
            }
            return s;
          }));
          return;
        }

        // pipeline_completed — 管道完成
        if (event.event === 'pipeline_completed') {
          const data = event.data || {};
          setTaskStatus('completed');
          if (data.session_id) {
            setSessionId(data.session_id);
            loadLogs(data.session_id);
          }
          // 从管道上下文中提取特定步骤结果
          const ctx = data.context || {};
          if (ctx.report_result) setReportResult(ctx.report_result);
          if (ctx.defect_result) setDefectResult(ctx.defect_result);
          return;
        }

        // done — 结束（兼容 event 和 event_type 两种格式）
        if (event.event === 'done' || event.event_type === 'done') {
          setRunning(false);
          sseRef.current = false;
          if (event.status === 'completed' || taskStatus === 'completed') {
            message.success('任务执行完成');
          } else if (event.status === 'failed' || taskStatus === 'failed') {
            message.error('任务执行失败');
          }
          return;
        }

        // ===== 旧版 SSE 事件 (event_type 格式) =====

        // task_started
        if (event.event_type === 'task_started' || event.task_status) {
          setSessionId(event.session_id || '');
          setTotalSteps(event.total_steps || 0);
          return;
        }

        // agent_started
        if (event.event_type === 'agent_started') {
          setSteps(prev => {
            const exists = prev.find(s => s.name === event.step);
            if (exists) {
              return prev.map(s => s.name === event.step ? {
                ...s, status: 'running', message: event.message,
              } : s);
            }
            return [...prev, {
              name: event.step || event.agent_name,
              agent_name: event.agent_name,
              status: 'running',
              message: event.message,
              progress: event.progress,
              duration: 0,
            }];
          });
          return;
        }

        // agent_completed
        if (event.event_type === 'agent_completed') {
          setSteps(prev => prev.map(s =>
            s.name === (event.step || event.agent_name) ? {
              ...s, status: 'completed', message: event.message,
              duration: event.duration,
              output_data: event.output_data,
            } : s
          ));
          setCompletedSteps(prev => prev + 1);
          return;
        }

        // agent_failed
        if (event.event_type === 'agent_failed') {
          setSteps(prev => prev.map(s =>
            s.name === (event.step || event.agent_name) ? {
              ...s, status: 'failed', message: event.message,
              error: event.error, duration: event.duration,
            } : s
          ));
          return;
        }

        // task_completed
        if (event.task_status === 'completed' || event.task_status === 'failed') {
          setTaskStatus(event.task_status);
          if (event.session_id) {
            setSessionId(event.session_id);
            loadLogs(event.session_id);
          }
          return;
        }

        // done
        if (event.event_type === 'done') {
          setRunning(false);
          sseRef.current = false;
          if (event.status === 'completed') {
            message.success('任务执行完成');
          } else if (event.status === 'failed') {
            message.error('任务执行失败');
          }
        }
      },
      // onError
      (error: any) => {
        message.error(`SSE 连接错误: ${error}`);
        setRunning(false);
        setTaskStatus('failed');
        sseRef.current = false;
      },
      // onComplete
      () => {
        setRunning(false);
        sseRef.current = false;
        // 从最终步骤结果中提取降级信息
        setSteps((prevSteps) => {
          const scriptStep = prevSteps.find(
            (s) => s.agent_name === 'script_generator' || s.name?.includes('脚本生成')
          );
          if (scriptStep?.output_data?.degradation_info) {
            setDegradationInfo(scriptStep.output_data.degradation_info);
          }
          return prevSteps;
        });
      },
    );
  };

  /** 重置 */
  const handleReset = () => {
    setRequirement('');
    setSteps([]);
    setTaskStatus('');
    setSessionId('');
    setLogs([]);
    setCompletedSteps(0);
    setTotalSteps(0);
    setClassifyResult(null);
    setClassifyError(null);
    setOverrideType(null);
    setOverrideFramework(null);
    setOverridePlatform(null);
    setReportResult(null);
    setDefectResult(null);
  };

  /** 用户修改AI识别结果 */
  const handleClassifyChange = (testType: string, framework: string, platform: string) => {
    setOverrideType(testType);
    setOverrideFramework(framework);
    setOverridePlatform(platform);
    message.success(`已修改为: ${testType} / ${framework}`);
  };

  /** 重新识别 */
  const handleReclassify = () => {
    if (requirement.trim()) {
      doClassify(requirement.trim());
    }
  };

  // Steps 列
  const stepColumns: ColumnsType<StepStatus> = [
    {
      title: '步骤',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      render: (text: string, record: StepStatus) => (
        <Space>
          <StatusIcon status={record.status} />
          <Text strong>{text}</Text>
        </Space>
      ),
    },
    {
      title: 'Agent',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 150,
      render: (text: string) => <Tag icon={<RobotOutlined />}>{text}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => <Tag color={STATUS_COLORS[status] || 'default'}>{status}</Tag>,
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
    },
    {
      title: '耗时',
      dataIndex: 'duration',
      key: 'duration',
      width: 100,
      render: (d: number) => d > 0 ? `${d.toFixed(2)}s` : '-',
    },
  ];

  // 日志列
  const logColumns: ColumnsType<AgentExecutionLog> = [
    { title: '步骤', dataIndex: 'step', key: 'step', width: 150 },
    { title: 'Agent', dataIndex: 'agent_name', key: 'agent_name', width: 120 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Tag color={STATUS_COLORS[s] || 'default'}>{s}</Tag>,
    },
    {
      title: '耗时', dataIndex: 'duration', key: 'duration', width: 80,
      render: (d: number) => d ? `${d.toFixed(2)}s` : '-',
    },
    {
      title: '错误', dataIndex: 'error', key: 'error', ellipsis: true,
      render: (e: string) => e ? <Text type="danger" ellipsis>{e}</Text> : '-',
    },
  ];

  // Agent 列
  const agentColumns: ColumnsType<AgentMeta> = [
    { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name', width: 150 },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    {
      title: '模型', dataIndex: 'model_config', key: 'model',
      width: 150, render: (m: any) => m?.model_name || <Tag>无</Tag>,
    },
    {
      title: '能力', dataIndex: 'capabilities', key: 'capabilities',
      render: (caps: string[]) => caps?.map(c => <Tag key={c}>{c}</Tag>) || null,
    },
    {
      title: '分类', dataIndex: 'category', key: 'category', width: 80,
      render: (c: string) => <Tag>{c}</Tag>,
    },
    {
      title: '状态', dataIndex: 'enabled', key: 'enabled', width: 80,
      render: (e: boolean) => <Tag color={e ? 'success' : 'default'}>{e ? '启用' : '禁用'}</Tag>,
    },
  ];

  return (
    <div style={{ padding: '0px' }}>
      <Card
        title={
          <Space>
            <RobotOutlined />
            <span>AI Agent 执行过程</span>
          </Space>
        }
        extra={
          <Space>
            <Button onClick={loadStats} icon={<ReloadOutlined />}>刷新</Button>
          </Space>
        }
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'execution',
            label: '任务执行',
            children: (
              <Row gutter={16}>
                {/* 左侧：任务输入 */}
                <Col span={8}>
                  <Card title="任务输入" size="small" style={{ marginBottom: 16 }}>
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <div>
                        <Text type="secondary">测试需求</Text>
                        <TextArea
                          value={requirement}
                          onChange={e => setRequirement(e.target.value)}
                          placeholder="例如：测试商城登录流程，包括正确密码、错误密码、空密码等场景"
                          rows={6}
                          style={{ marginTop: 4 }}
                        />
                      </div>

                      {/* AI智能识别结果卡片 */}
                      <AIClassifyCard
                        result={classifyResult}
                        loading={classifyLoading}
                        error={classifyError}
                        onChange={handleClassifyChange}
                        onReclassify={handleReclassify}
                      />

                      <Space>
                        <Button
                          type="primary"
                          icon={<PlayCircleOutlined />}
                          onClick={handleSubmit}
                          loading={running}
                          disabled={!requirement.trim()}
                        >
                          执行任务
                        </Button>
                        <Button onClick={handleReset} disabled={running}>重置</Button>
                      </Space>
                    </Space>
                  </Card>

                  {/* 任务状态卡片 */}
                  {sessionId && (
                    <Card title="任务状态" size="small">
                      <Descriptions column={1} size="small">
                        <Descriptions.Item label="Session">
                          <Text copyable style={{ fontSize: 12 }}>{sessionId}</Text>
                        </Descriptions.Item>
                        <Descriptions.Item label="状态">
                          <Tag color={STATUS_COLORS[taskStatus] || 'default'}>
                            {taskStatus || 'idle'}
                          </Tag>
                        </Descriptions.Item>
                        <Descriptions.Item label="进度">
                          {totalSteps > 0 ? `${completedSteps}/${totalSteps}` : '-'}
                        </Descriptions.Item>
                      </Descriptions>
                      {totalSteps > 0 && (
                        <Progress
                          percent={Math.round((completedSteps / totalSteps) * 100)}
                          status={taskStatus === 'failed' ? 'exception' : 'active'}
                        />
                      )}
                    </Card>
                  )}

                  {/* 脚本降级警告 */}
                  {degradationInfo && (
                    <DegradationAlert
                      info={degradationInfo}
                      onEdit={() => {
                        // 如果有脚本ID，可以跳转到脚本编辑页面
                        message.info('请查看下方脚本内容并进行审查');
                      }}
                    />
                  )}

                  {/* 脚本复用信息 */}
                  {reuseInfo?.reused && (
                    <Alert
                      type="success"
                      showIcon
                      message={`已复用历史脚本：${reuseInfo.scriptName || '未命名'}`}
                      description={`相似度: ${(reuseInfo.similarity * 100).toFixed(1)}% — 跳过了用例生成和脚本生成步骤`}
                      style={{ marginBottom: 16 }}
                    />
                  )}

                  {/* 运行时统计 */}
                  {stats && (
                    <Card title="运行时统计" size="small" style={{ marginTop: 16 }}>
                      <Row gutter={8}>
                        <Col span={12}>
                          <Statistic title="注册Agent" value={stats.registered_agents || 0} />
                        </Col>
                        <Col span={12}>
                          <Statistic title="活跃会话" value={stats.active_sessions || 0} />
                        </Col>
                      </Row>
                    </Card>
                  )}
                </Col>

                {/* 右侧：执行过程 */}
                <Col span={16}>
                  {running || steps.length > 0 ? (
                    <>
                      {/* 时间线视图 */}
                      <Card title="执行时间线" size="small" style={{ marginBottom: 16 }}>
                        {steps.length === 0 && running ? (
                          <div style={{ textAlign: 'center', padding: 40 }}>
                            <Spin tip="等待 Agent 启动..." />
                          </div>
                        ) : (
                          <Timeline
                            items={steps.map((step, idx) => ({
                              key: idx,
                              dot: <StatusIcon status={step.status} />,
                              color: STATUS_COLORS[step.status] || 'gray',
                              children: (
                                <div>
                                  <Space>
                                    <Text strong>{step.name}</Text>
                                    <Tag icon={<RobotOutlined />}>{step.agent_name}</Tag>
                                    <Tag color={STATUS_COLORS[step.status] || 'default'}>
                                      {step.status}
                                    </Tag>
                                    {step.duration > 0 && (
                                      <Text type="secondary">{step.duration.toFixed(2)}s</Text>
                                    )}
                                  </Space>
                                  <div style={{ marginTop: 4 }}>
                                    <Text type="secondary">{step.message}</Text>
                                  </div>
                                  {step.error && (
                                    <Alert
                                      message={step.error}
                                      type="error"
                                      style={{ marginTop: 8 }}
                                      closable
                                    />
                                  )}
                                </div>
                              ),
                            }))}
                          />
                        )}
                      </Card>

                      {/* 表格视图 */}
                      <Card title="步骤详情" size="small">
                        <Table
                          columns={stepColumns}
                          dataSource={steps}
                          rowKey="name"
                          pagination={false}
                          size="small"
                        />
                      </Card>

                      {/* 测试报告卡片 */}
                      {reportResult && (
                        <Card title="测试报告" size="small" style={{ marginTop: 16 }}>
                          {reportResult.summary ? (
                            <>
                              <Row gutter={16}>
                                <Col span={6}>
                                  <Statistic title="总计" value={reportResult.summary.total || 0} />
                                </Col>
                                <Col span={6}>
                                  <Statistic title="通过" value={reportResult.summary.passed || 0}
                                    valueStyle={{ color: '#52c41a' }} />
                                </Col>
                                <Col span={6}>
                                  <Statistic title="失败" value={reportResult.summary.failed || 0}
                                    valueStyle={{ color: '#ff4d4f' }} />
                                </Col>
                                <Col span={6}>
                                  <Statistic title="跳过" value={reportResult.summary.skipped || 0} />
                                </Col>
                              </Row>
                              {reportResult.summary.total > 0 && (
                                <Progress
                                  percent={reportResult.summary.pass_rate || 0}
                                  status={reportResult.summary.failed > 0 ? 'exception' : 'success'}
                                  format={(p) => `${p}%`}
                                  style={{ marginTop: 12 }}
                                />
                              )}
                            </>
                          ) : (
                            <Text type="secondary">{JSON.stringify(reportResult).slice(0, 200)}</Text>
                          )}
                        </Card>
                      )}

                      {/* 缺陷分析表格 */}
                      {defectResult && defectResult.defects && defectResult.defects.length > 0 && (
                        <Card title={`缺陷分析 (${defectResult.total_defects || defectResult.defects.length} 个)`} size="small" style={{ marginTop: 16 }}>
                          <Table
                            columns={[
                              { title: '缺陷ID', dataIndex: 'defect_id', key: 'defect_id', width: 100 },
                              { title: '测试名称', dataIndex: 'test_name', key: 'test_name', ellipsis: true },
                              {
                                title: '错误类型', dataIndex: 'error_type', key: 'error_type', width: 120,
                                render: (t: string) => {
                                  const colorMap: Record<string, string> = {
                                    assertion: 'red', timeout: 'orange', element_not_found: 'red',
                                    connection: 'volcano', syntax: 'magenta', unknown: 'default',
                                  };
                                  return <Tag color={colorMap[t] || 'default'}>{t}</Tag>;
                                },
                              },
                              {
                                title: '严重程度', dataIndex: 'severity', key: 'severity', width: 80,
                                render: (s: string) => {
                                  const colorMap: Record<string, string> = {
                                    critical: 'red', high: 'volcano', medium: 'orange', low: 'blue',
                                  };
                                  return <Tag color={colorMap[s] || 'default'}>{s}</Tag>;
                                },
                              },
                              {
                                title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true,
                                render: (e: string) => <Text type="danger" ellipsis>{e}</Text>,
                              },
                            ]}
                            dataSource={defectResult.defects}
                            rowKey="defect_id"
                            pagination={false}
                            size="small"
                          />
                        </Card>
                      )}
                    </>
                  ) : (
                    <Card>
                      <Empty
                        description="暂无执行记录，请输入测试需求并点击执行"
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                      />
                    </Card>
                  )}

                  {/* 执行日志 */}
                  {logs.length > 0 && (
                    <Card title="执行日志（数据库记录）" size="small" style={{ marginTop: 16 }}>
                      <Table
                        columns={logColumns}
                        dataSource={logs}
                        rowKey="id"
                        pagination={{ pageSize: 10 }}
                        size="small"
                        expandable={{
                          expandedRowRender: (record) => (
                            <Descriptions column={1} size="small" bordered>
                              <Descriptions.Item label="输入">
                                <pre style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                  {JSON.stringify(record.input_data, null, 2)}
                                </pre>
                              </Descriptions.Item>
                              <Descriptions.Item label="输出">
                                <pre style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                  {JSON.stringify(record.output_data, null, 2)}
                                </pre>
                              </Descriptions.Item>
                            </Descriptions>
                          ),
                        }}
                      />
                    </Card>
                  )}
                </Col>
              </Row>
            ),
          },
          {
            key: 'agents',
            label: 'Agent 列表',
            children: (
              <Table
                columns={agentColumns}
                dataSource={agents}
                rowKey="name"
                pagination={{ pageSize: 15 }}
                size="small"
              />
            ),
          },
          {
            key: 'workflows',
            label: '工作流',
            children: (
              <Row gutter={16}>
                {workflows.map(wf => (
                  <Col span={12} key={wf.name}>
                    <Card
                      title={wf.display_name}
                      size="small"
                      style={{ marginBottom: 16 }}
                      extra={<Tag>{wf.task_type}</Tag>}
                    >
                      <Paragraph type="secondary">{wf.description}</Paragraph>
                      <Steps
                        size="small"
                        current={wf.total_steps}
                        items={wf.steps.map((s) => ({
                          title: s.name,
                          description: s.agent_name,
                        }))}
                      />
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
        ]} />
      </Card>
    </div>
  );
}
