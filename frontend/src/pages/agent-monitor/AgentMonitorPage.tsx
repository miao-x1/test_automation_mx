/**
 * Agent 监控页面
 *
 * 功能模块：
 *   1. 任务搜索 - 输入 Task ID 查询 Agent 执行链
 *   2. 执行时间线 - 垂直 Timeline 展示 Agent 执行流程
 *   3. Agent 日志详情 - Drawer 展示输入/输出数据
 *   4. 汇总统计 - 展示总步骤数、成功数、失败数、总耗时
 *   5. Agent 注册表 - 表格展示已注册 Agent，支持启用/禁用
 */
import { useState, useCallback } from 'react';
import {
  Card, Row, Col, Input, Button, Tabs, Timeline, Drawer, Table, Tag,
  Statistic, Switch, message, Space, Typography, Spin, Empty, Tooltip,
  Descriptions, Alert, Divider,
} from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  ClockCircleOutlined, SearchOutlined, RobotOutlined, ReloadOutlined,
  ArrowDownOutlined, FireOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getTaskWorkflow, getTaskAgentLog, getAgentRegistry, toggleAgent,
  type WorkflowStepInfo, type TaskWorkflow, type AgentLogDetail,
  type AgentRegistryItem,
} from '../../services/agentMonitor';

const { Text, Paragraph } = Typography;

/* ===================== 常量定义 ===================== */

/** Agent 执行状态颜色映射 */
const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  completed: 'green',
  error: 'red',
  failed: 'red',
  running: 'blue',
  skipped: 'gray',
  pending: 'gray',
};

/** Agent 执行状态中文标签 */
const STATUS_LABELS: Record<string, string> = {
  success: '成功',
  completed: '完成',
  error: '错误',
  failed: '失败',
  running: '执行中',
  skipped: '已跳过',
  pending: '等待中',
};

/* ===================== 辅助组件 ===================== */

/** 状态图标组件 */
function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'success':
    case 'completed':
      return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 18 }} />;
    case 'error':
    case 'failed':
      return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 18 }} />;
    case 'running':
      return <LoadingOutlined style={{ color: '#1677ff', fontSize: 18 }} />;
    case 'skipped':
      return <ClockCircleOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />;
    default:
      return <ClockCircleOutlined style={{ color: '#bfbfbf', fontSize: 18 }} />;
  }
}

/** 格式化耗时 */
function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '-';
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  return `${seconds.toFixed(1)}s`;
}

/** 格式化 Token 数 */
function formatTokens(tokens: number): string {
  if (!tokens || tokens <= 0) return '-';
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return String(tokens);
}

/**
 * JSON 语法高亮渲染
 * 将 JSON 字符串转换为带颜色的 HTML
 */
function syntaxHighlight(json: any): string {
  let jsonStr: string;
  if (typeof json === 'string') {
    jsonStr = json;
  } else {
    try {
      jsonStr = JSON.stringify(json, null, 2);
    } catch {
      jsonStr = String(json);
    }
  }
  // 转义 HTML 特殊字符
  jsonStr = jsonStr
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  // 语法高亮：key、string、number、boolean、null
  return jsonStr.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+\.?\d*([eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'json-number'; // 数字
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'json-key'; // 键名
        } else {
          cls = 'json-string'; // 字符串
        }
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean'; // 布尔值
      } else if (/null/.test(match)) {
        cls = 'json-null'; // null
      }
      return `<span class="${cls}">${match}</span>`;
    }
  );
}

/** JSON 查看器组件 */
function JsonViewer({ data }: { data: any }) {
  if (data === null || data === undefined) {
    return <Text type="secondary">无数据</Text>;
  }
  return (
    <pre
      style={{
        background: '#f5f5f5',
        padding: 12,
        borderRadius: 6,
        maxHeight: 400,
        overflow: 'auto',
        fontSize: 13,
        lineHeight: 1.6,
        margin: 0,
      }}
      dangerouslySetInnerHTML={{ __html: syntaxHighlight(data) }}
    />
  );
}

/* ===================== 主组件 ===================== */

export default function AgentMonitorPage() {
  /* ---- 任务搜索 ---- */
  const [taskIdInput, setTaskIdInput] = useState('');
  const [currentTaskId, setCurrentTaskId] = useState<number | null>(null);
  const [searching, setSearching] = useState(false);

  /* ---- 工作流数据 ---- */
  const [workflow, setWorkflow] = useState<TaskWorkflow | null>(null);

  /* ---- Agent 日志 Drawer ---- */
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<WorkflowStepInfo | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLogDetail[]>([]);

  /* ---- Agent 注册表 ---- */
  const [registry, setRegistry] = useState<AgentRegistryItem[]>([]);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null);

  /* ---- Tab 切换 ---- */
  const [activeTab, setActiveTab] = useState('monitor');

  /* ===================== 数据加载方法 ===================== */

  /** 搜索任务工作流 */
  const handleSearch = useCallback(async () => {
    const id = Number(taskIdInput.trim());
    if (!id || isNaN(id)) {
      message.warning('请输入有效的 Task ID');
      return;
    }

    setSearching(true);
    setWorkflow(null);
    setCurrentTaskId(id);

    try {
      const data = await getTaskWorkflow(id);
      setWorkflow(data);
      if (data.steps.length === 0) {
        message.info('该任务暂无工作流执行记录');
      } else {
        message.success(`查询到 ${data.steps.length} 个执行步骤`);
      }
    } catch (error: any) {
      message.error(`查询失败: ${error?.message || '未知错误'}`);
    } finally {
      setSearching(false);
    }
  }, [taskIdInput]);

  /** 点击时间线项 - 打开日志 Drawer */
  const handleTimelineItemClick = useCallback(
    async (step: WorkflowStepInfo) => {
      if (!currentTaskId) return;

      setSelectedAgent(step);
      setDrawerVisible(true);
      setDrawerLoading(true);
      setAgentLogs([]);

      try {
        const res = await getTaskAgentLog(currentTaskId, {
          agent_name: step.agent_name,
          limit: 50,
        });
        setAgentLogs(res.logs || []);
      } catch (error: any) {
        message.error(`获取日志失败: ${error?.message || '未知错误'}`);
      } finally {
        setDrawerLoading(false);
      }
    },
    [currentTaskId]
  );

  /** 加载 Agent 注册表 */
  const loadRegistry = useCallback(async () => {
    setRegistryLoading(true);
    try {
      const res = await getAgentRegistry();
      setRegistry(res.agents || []);
    } catch (error: any) {
      message.error(`加载注册表失败: ${error?.message || '未知错误'}`);
    } finally {
      setRegistryLoading(false);
    }
  }, []);

  /** 切换 Agent 启用状态 */
  const handleToggleAgent = useCallback(async (agentName: string, enabled: boolean) => {
    setTogglingAgent(agentName);
    try {
      await toggleAgent(agentName, enabled);
      // 更新本地状态
      setRegistry(prev =>
        prev.map(item =>
          item.agent_name === agentName ? { ...item, enabled } : item
        )
      );
      message.success(`Agent「${agentName}」已${enabled ? '启用' : '禁用'}`);
    } catch (error: any) {
      message.error(`操作失败: ${error?.message || '未知错误'}`);
      // 回滚状态
      setRegistry(prev =>
        prev.map(item =>
          item.agent_name === agentName ? { ...item, enabled: !enabled } : item
        )
      );
    } finally {
      setTogglingAgent(null);
    }
  }, []);

  /** Tab 切换时按需加载数据 */
  const handleTabChange = useCallback(
    (key: string) => {
      setActiveTab(key);
      if (key === 'registry' && registry.length === 0) {
        loadRegistry();
      }
    },
    [registry.length, loadRegistry]
  );

  /* ===================== 汇总统计计算 ===================== */

  const stats = workflow
    ? {
        totalSteps: workflow.total_steps || workflow.steps.length,
        successCount: workflow.steps.filter(s => s.status === 'success' || s.status === 'completed').length,
        failedCount: workflow.steps.filter(s => s.status === 'error' || s.status === 'failed').length,
        totalDuration: workflow.total_duration || workflow.steps.reduce((sum, s) => sum + (s.duration || 0), 0),
        totalTokens: workflow.steps.reduce((sum, s) => sum + (s.tokens_used || 0), 0),
      }
    : { totalSteps: 0, successCount: 0, failedCount: 0, totalDuration: 0, totalTokens: 0 };

  /* ===================== 表格列定义 ===================== */

  /** Agent 注册表列定义 */
  const registryColumns: ColumnsType<AgentRegistryItem> = [
    {
      title: 'Agent 名称',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 180,
      render: (text: string) => (
        <Space>
          <RobotOutlined style={{ color: '#1677ff' }} />
          <Text strong>{text}</Text>
        </Space>
      ),
    },
    {
      title: '显示名称',
      dataIndex: 'display_name',
      key: 'display_name',
      width: 140,
    },
    {
      title: '类型',
      dataIndex: 'agent_type',
      key: 'agent_type',
      width: 120,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
      width: 140,
      render: (text: string) => text ? <Tag icon={<ThunderboltOutlined />}>{text}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] || 'default'}>
          {STATUS_LABELS[status] || status}
        </Tag>
      ),
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
      render: (v: string) => <Text code>v{v}</Text>,
    },
    {
      title: '启用/禁用',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled: boolean, record: AgentRegistryItem) => (
        <Switch
          checked={enabled}
          loading={togglingAgent === record.agent_name}
          onChange={(checked) => handleToggleAgent(record.agent_name, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
  ];

  /* ===================== 渲染 ===================== */

  return (
    <div style={{ padding: 0 }}>
      <Card
        title={
          <Space>
            <RobotOutlined style={{ fontSize: 20, color: '#1677ff' }} />
            <span>Agent 监控面板</span>
          </Space>
        }
        extra={
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                if (currentTaskId) handleSearch();
                if (activeTab === 'registry') loadRegistry();
              }}
            >
              刷新
            </Button>
          </Space>
        }
      >
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={[
            {
              key: 'monitor',
              label: (
                <span>
                  <FireOutlined />
                  执行监控
                </span>
              ),
              children: (
                <div>
                  {/* ========== 1. 任务搜索区 ========== */}
                  <Card size="small" style={{ marginBottom: 16 }}>
                    <Row gutter={16} align="middle">
                      <Col xs={24} sm={12} md={8} lg={6}>
                        <Input
                          placeholder="请输入 Task ID"
                          value={taskIdInput}
                          onChange={e => setTaskIdInput(e.target.value)}
                          onPressEnter={handleSearch}
                          prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
                          size="large"
                          allowClear
                        />
                      </Col>
                      <Col>
                        <Button
                          type="primary"
                          size="large"
                          icon={<SearchOutlined />}
                          onClick={handleSearch}
                          loading={searching}
                        >
                          搜索
                        </Button>
                      </Col>
                      {currentTaskId && (
                        <Col>
                          <Text type="secondary">
                            当前任务 ID: <Text strong>{currentTaskId}</Text>
                          </Text>
                        </Col>
                      )}
                    </Row>
                  </Card>

                  {/* 搜索加载中 */}
                  {searching && (
                    <div style={{ textAlign: 'center', padding: 60 }}>
                      <Spin tip="正在查询工作流..." size="large" />
                    </div>
                  )}

                  {/* 空状态 */}
                  {!searching && !workflow && (
                    <Card>
                      <Empty
                        description="请输入 Task ID 查询 Agent 执行链"
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                      />
                    </Card>
                  )}

                  {/* ========== 工作流展示 ========== */}
                  {!searching && workflow && (
                    <>
                      {/* ========== 4. 汇总统计卡片 ========== */}
                      <Row gutter={16} style={{ marginBottom: 16 }}>
                        <Col xs={12} sm={12} md={6}>
                          <Card>
                            <Statistic
                              title="总步骤数"
                              value={stats.totalSteps}
                              prefix={<ClockCircleOutlined />}
                              valueStyle={{ color: '#1677ff' }}
                            />
                          </Card>
                        </Col>
                        <Col xs={12} sm={12} md={6}>
                          <Card>
                            <Statistic
                              title="成功"
                              value={stats.successCount}
                              prefix={<CheckCircleOutlined />}
                              valueStyle={{ color: '#52c41a' }}
                              suffix={`/ ${stats.totalSteps}`}
                            />
                          </Card>
                        </Col>
                        <Col xs={12} sm={12} md={6}>
                          <Card>
                            <Statistic
                              title="失败"
                              value={stats.failedCount}
                              prefix={<CloseCircleOutlined />}
                              valueStyle={{ color: '#ff4d4f' }}
                              suffix={`/ ${stats.totalSteps}`}
                            />
                          </Card>
                        </Col>
                        <Col xs={12} sm={12} md={6}>
                          <Card>
                            <Statistic
                              title="总耗时"
                              value={formatDuration(stats.totalDuration)}
                              prefix={<ThunderboltOutlined />}
                              valueStyle={{ color: '#722ed1' }}
                            />
                          </Card>
                        </Col>
                      </Row>

                      {/* ========== 2. Agent 执行时间线 ========== */}
                      <Card
                        title={
                          <Space>
                            <ArrowDownOutlined />
                            <span>Agent 执行时间线</span>
                            {stats.totalTokens > 0 && (
                              <Tag icon={<ThunderboltOutlined />} color="purple">
                                总 Token: {formatTokens(stats.totalTokens)}
                              </Tag>
                            )}
                          </Space>
                        }
                        size="small"
                      >
                        <Timeline
                          mode="left"
                          items={workflow.steps.map((step, idx) => ({
                            key: idx,
                            dot: <StatusIcon status={step.status} />,
                            color: STATUS_COLORS[step.status] || 'gray',
                            children: (
                              <div
                                style={{
                                  cursor: 'pointer',
                                  padding: '8px 12px',
                                  borderRadius: 6,
                                  transition: 'background-color 0.2s',
                                  border: '1px solid #f0f0f0',
                                  marginBottom: 4,
                                }}
                                onClick={() => handleTimelineItemClick(step)}
                                onMouseEnter={e => {
                                  (e.currentTarget as HTMLElement).style.backgroundColor = '#f5f5f5';
                                }}
                                onMouseLeave={e => {
                                  (e.currentTarget as HTMLElement).style.backgroundColor = 'transparent';
                                }}
                              >
                                {/* 第一行：Agent 名称 + 状态 */}
                                <Row align="middle" gutter={8}>
                                  <Col flex="auto">
                                    <Space wrap>
                                      <Text strong style={{ fontSize: 15 }}>
                                        <RobotOutlined style={{ marginRight: 6, color: '#1677ff' }} />
                                        {step.display_name || step.agent_name}
                                      </Text>
                                      <Tag
                                        color={STATUS_COLORS[step.status] || 'default'}
                                      >
                                        {STATUS_LABELS[step.status] || step.status}
                                      </Tag>
                                      {/* 步骤序号 */}
                                      <Tag color="default">步骤 {idx + 1}</Tag>
                                    </Space>
                                  </Col>
                                </Row>

                                {/* 第二行：详细信息 */}
                                <Row gutter={16} style={{ marginTop: 8 }}>
                                  <Col>
                                    <Tooltip title="耗时">
                                      <Text type="secondary">
                                        <ClockCircleOutlined style={{ marginRight: 4 }} />
                                        {formatDuration(step.duration)}
                                      </Text>
                                    </Tooltip>
                                  </Col>
                                  {step.model_name && (
                                    <Col>
                                      <Tooltip title="使用模型">
                                        <Text type="secondary">
                                          <ThunderboltOutlined style={{ marginRight: 4 }} />
                                          {step.model_name}
                                        </Text>
                                      </Tooltip>
                                    </Col>
                                  )}
                                  {step.tokens_used > 0 && (
                                    <Col>
                                      <Tooltip title="Token 使用量">
                                        <Text type="secondary">
                                          <FireOutlined style={{ marginRight: 4 }} />
                                          {formatTokens(step.tokens_used)} tokens
                                        </Text>
                                      </Tooltip>
                                    </Col>
                                  )}
                                  {step.start_time && (
                                    <Col>
                                      <Text type="secondary" style={{ fontSize: 12 }}>
                                        {step.start_time}
                                      </Text>
                                    </Col>
                                  )}
                                </Row>

                                {/* 错误信息 */}
                                {step.error && (
                                  <Alert
                                    message={step.error}
                                    type="error"
                                    style={{ marginTop: 8 }}
                                    showIcon
                                    closable
                                  />
                                )}

                                {/* 提示：点击查看详情 */}
                                <div style={{ marginTop: 6 }}>
                                  <Text type="secondary" style={{ fontSize: 12 }}>
                                    点击查看详情 →
                                  </Text>
                                </div>
                              </div>
                            ),
                          }))}
                        />

                        {/* 空步骤提示 */}
                        {workflow.steps.length === 0 && (
                          <Empty description="暂无执行步骤" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                        )}
                      </Card>
                    </>
                  )}
                </div>
              ),
            },
            {
              key: 'registry',
              label: (
                <span>
                  <RobotOutlined />
                  Agent 注册表
                </span>
              ),
              children: (
                <div>
                  <Row gutter={16} style={{ marginBottom: 16 }}>
                    <Col>
                      <Statistic title="已注册 Agent" value={registry.length} />
                    </Col>
                    <Col>
                      <Statistic
                        title="已启用"
                        value={registry.filter(a => a.enabled).length}
                        valueStyle={{ color: '#52c41a' }}
                      />
                    </Col>
                    <Col>
                      <Statistic
                        title="已禁用"
                        value={registry.filter(a => !a.enabled).length}
                        valueStyle={{ color: '#ff4d4f' }}
                      />
                    </Col>
                  </Row>
                  <Table
                    columns={registryColumns}
                    dataSource={registry}
                    rowKey="agent_name"
                    loading={registryLoading}
                    pagination={{ pageSize: 15, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
                    size="middle"
                    scroll={{ x: 1000 }}
                  />
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* ========== 3. Agent 日志详情 Drawer ========== */}
      <Drawer
        title={
          selectedAgent ? (
            <Space>
              <RobotOutlined style={{ color: '#1677ff' }} />
              <span>{selectedAgent.display_name || selectedAgent.agent_name}</span>
              <Tag color={STATUS_COLORS[selectedAgent.status] || 'default'}>
                {STATUS_LABELS[selectedAgent.status] || selectedAgent.status}
              </Tag>
            </Space>
          ) : (
            'Agent 详情'
          )
        }
        open={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        width={720}
      >
        {drawerLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin tip="正在加载日志..." size="large" />
          </div>
        ) : (
          selectedAgent && (
            <div>
              {/* Agent 基本信息 */}
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="Agent 名称" span={1}>
                  {selectedAgent.agent_name}
                </Descriptions.Item>
                <Descriptions.Item label="显示名称" span={1}>
                  {selectedAgent.display_name || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="状态" span={1}>
                  <Tag color={STATUS_COLORS[selectedAgent.status] || 'default'}>
                    {STATUS_LABELS[selectedAgent.status] || selectedAgent.status}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="耗时" span={1}>
                  {formatDuration(selectedAgent.duration)}
                </Descriptions.Item>
                <Descriptions.Item label="模型" span={1}>
                  {selectedAgent.model_name ? (
                    <Tag icon={<ThunderboltOutlined />}>{selectedAgent.model_name}</Tag>
                  ) : (
                    <Text type="secondary">-</Text>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="Token 使用" span={1}>
                  {formatTokens(selectedAgent.tokens_used)}
                </Descriptions.Item>
                <Descriptions.Item label="开始时间" span={1}>
                  {selectedAgent.start_time || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="结束时间" span={1}>
                  {selectedAgent.end_time || '-'}
                </Descriptions.Item>
              </Descriptions>

              {/* 错误信息 */}
              {selectedAgent.error && (
                <Alert
                  message="错误信息"
                  description={selectedAgent.error}
                  type="error"
                  style={{ marginTop: 16 }}
                  showIcon
                />
              )}

              <Divider orientation="left">输入数据 (Input)</Divider>
              <JsonViewer data={selectedAgent.input_data} />

              <Divider orientation="left">输出数据 (Output)</Divider>
              <JsonViewer data={selectedAgent.output_data} />

              {/* 历史执行日志 */}
              {agentLogs.length > 0 && (
                <>
                  <Divider orientation="left">历史执行日志 ({agentLogs.length} 条)</Divider>
                  {agentLogs.map((log, idx) => (
                    <Card
                      key={log.id}
                      size="small"
                      style={{ marginBottom: 8 }}
                      title={
                        <Space>
                          <Text type="secondary">#{idx + 1}</Text>
                          <Tag color={STATUS_COLORS[log.status] || 'default'}>
                            {STATUS_LABELS[log.status] || log.status}
                          </Tag>
                          <Text type="secondary">{formatDuration(log.duration)}</Text>
                          {log.model_name && (
                            <Tag icon={<ThunderboltOutlined />}>{log.model_name}</Tag>
                          )}
                          {log.tokens_used > 0 && (
                            <Text type="secondary">{formatTokens(log.tokens_used)} tokens</Text>
                          )}
                        </Space>
                      }
                    >
                      {log.error && (
                        <Alert
                          message={log.error}
                          type="error"
                          style={{ marginBottom: 8 }}
                          showIcon
                          closable
                        />
                      )}
                      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 4 }}>
                        输入:
                      </Paragraph>
                      <JsonViewer data={log.input_data} />
                      <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 4, marginTop: 8 }}>
                        输出:
                      </Paragraph>
                      <JsonViewer data={log.output_data} />
                    </Card>
                  ))}
                </>
              )}
            </div>
          )
        )}
      </Drawer>
    </div>
  );
}
