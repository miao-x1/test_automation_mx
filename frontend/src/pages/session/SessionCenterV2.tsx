/**
 * SessionCenter - 会话管理中心
 *
 * 功能：
 * 1. 左侧：会话列表（搜索/筛选/创建）
 * 2. 右侧：会话详情（恢复整个 AI 执行历史）
 *    - 需求 | 上传文件 | Agent消息 | 测试点 | 用例 | 脚本 | 日志 | 思维导图 | 导出
 * 3. 支持新建会话、执行 GraphFlow、恢复历史
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Button, Input, List, Tag, Tabs, Spin, Empty, message,
  Card, Row, Col, Statistic, Modal, Form, Tooltip, Space, Typography
} from 'antd';
import {
  PlusOutlined, SearchOutlined, PlayCircleOutlined,
  DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons';
import type { SessionInfo, SessionState, ArtifactInfo } from '../../services/session';
import * as sessionService from '../../services/session';

const { TextArea } = Input;
const { Text } = Typography;

const STATUS_COLORS: Record<string, string> = {
  active: 'processing',
  paused: 'warning',
  completed: 'success',
  archived: 'default',
};

const STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  paused: '已暂停',
  completed: '已完成',
  archived: '已归档',
};

export default function SessionCenter() {
  // ===== 状态 =====
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [runLoading, setRunLoading] = useState(false);
  const [createForm] = Form.useForm();

  // ===== 加载会话列表 =====
  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const data = await sessionService.listSessions({
        status: statusFilter || undefined,
        limit: 50,
      });
      // 搜索过滤
      const filtered = searchKeyword
        ? data.filter(s =>
            s.session_name.toLowerCase().includes(searchKeyword.toLowerCase()) ||
            (s.requirement_summary || '').toLowerCase().includes(searchKeyword.toLowerCase())
          )
        : data;
      setSessions(filtered);
    } catch (err) {
      console.error('加载会话列表失败:', err);
    } finally {
      setLoading(false);
    }
  }, [searchKeyword, statusFilter]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // ===== 恢复会话 =====
  const restoreSession = useCallback(async (sessionId: number) => {
    setRestoring(true);
    setSelectedSessionId(sessionId);
    try {
      const state = await sessionService.restoreSession(sessionId);
      setSessionState(state);
    } catch (err) {
      console.error('恢复会话失败:', err);
      message.error('恢复会话失败');
    } finally {
      setRestoring(false);
    }
  }, []);

  // ===== 创建会话 =====
  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields();
      const session = await sessionService.createSession({
        requirement: values.requirement || '',
        input_mode: values.input_mode || 'text',
        session_name: values.session_name || '',
      });
      message.success('会话创建成功');
      setCreateModalVisible(false);
      createForm.resetFields();
      await loadSessions();
      // 自动选中新会话
      await restoreSession(session.id);
    } catch (err) {
      console.error('创建会话失败:', err);
    }
  };

  // ===== 执行 GraphFlow =====
  const handleRunGraphflow = async () => {
    if (!selectedSessionId) return;
    setRunLoading(true);
    try {
      const result = await sessionService.runGraphflow(selectedSessionId, {});
      if ((result as Record<string, unknown>).status === 'completed') {
        message.success('工作流执行完成');
      } else {
        message.warning(`工作流状态: ${(result as Record<string, unknown>).status}`);
      }
      // 重新恢复会话
      await restoreSession(selectedSessionId);
      await loadSessions();
    } catch (err) {
      console.error('执行失败:', err);
      message.error('工作流执行失败');
    } finally {
      setRunLoading(false);
    }
  };

  // ===== 删除会话 =====
  const handleDelete = async (sessionId: number) => {
    Modal.confirm({
      title: '确认删除',
      content: '删除后无法恢复，确定删除此会话？',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await sessionService.deleteSession(sessionId);
          message.success('删除成功');
          if (selectedSessionId === sessionId) {
            setSelectedSessionId(null);
            setSessionState(null);
          }
          await loadSessions();
        } catch (err) {
          message.error('删除失败');
        }
      },
    });
  };

  // ===== 渲染制品列表 =====
  const renderArtifacts = (artifactType: string) => {
    if (!sessionState) return null;
    const artifacts = sessionState.artifacts[artifactType] || [];
    if (artifacts.length === 0) {
      return <Empty description="暂无内容" />;
    }
    return (
      <List
        dataSource={artifacts}
        renderItem={(item: ArtifactInfo, index) => (
          <List.Item key={index}>
            <List.Item.Meta
              title={
                <Space>
                  <Text strong>{item.name}</Text>
                  {item.source_agent && <Tag color="blue">{item.source_agent}</Tag>}
                  {item.step && <Tag>{item.step}</Tag>}
                </Space>
              }
              description={
                <div>
                  {item.created_at && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {new Date(item.created_at).toLocaleString()}
                    </Text>
                  )}
                  {item.content && (
                    <pre style={{
                      marginTop: 8, maxHeight: 200, overflow: 'auto',
                      background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12,
                    }}>
                      {JSON.stringify(item.content, null, 2)}
                    </pre>
                  )}
                </div>
              }
            />
          </List.Item>
        )}
      />
    );
  };

  // ===== 渲染 Agent 事件 =====
  const renderAgentEvents = () => {
    if (!sessionState || sessionState.agent_events.length === 0) {
      return <Empty description="暂无 Agent 事件" />;
    }
    return (
      <List
        dataSource={sessionState.agent_events}
        renderItem={(event, index) => (
          <List.Item key={index}>
            <List.Item.Meta
              title={
                <Space>
                  <Tag color={
                    event.status === 'error' ? 'red' :
                    event.status === 'success' ? 'green' :
                    event.status === 'warning' ? 'orange' : 'blue'
                  }>
                    {event.event_type}
                  </Tag>
                  <Text strong>{event.agent_name}</Text>
                  {event.step && <Tag>{event.step}</Tag>}
                  {event.is_retry && <Tag color="orange">重试</Tag>}
                  {event.is_final && <Tag color="gold">最终</Tag>}
                </Space>
              }
              description={
                <div>
                  {event.model_name && <Tag color="purple">{event.model_name}</Tag>}
                  {event.total_tokens > 0 && <Tag>tokens: {event.total_tokens}</Tag>}
                  {event.duration > 0 && <Tag>耗时: {event.duration.toFixed(3)}s</Tag>}
                  {event.message && <div style={{ marginTop: 4 }}>{event.message}</div>}
                  {event.error_message && (
                    <div style={{ color: 'red', marginTop: 4 }}>{event.error_message}</div>
                  )}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {event.created_at && new Date(event.created_at).toLocaleString()}
                  </Text>
                </div>
              }
            />
          </List.Item>
        )}
      />
    );
  };

  // ===== 渲染 Flow 结果 =====
  const renderFlowResults = () => {
    if (!sessionState || sessionState.flow_results.length === 0) {
      return <Empty description="暂无流程结果" />;
    }
    return (
      <List
        dataSource={sessionState.flow_results}
        renderItem={(item, index) => (
          <List.Item key={index}>
            <List.Item.Meta
              title={
                <Space>
                  <Tag color={item.status === 'success' ? 'green' : 'red'}>{item.step}</Tag>
                  <Text strong>{item.agent_name}</Text>
                  <Tag>{item.status}</Tag>
                  {item.duration > 0 && <Tag>{item.duration.toFixed(3)}s</Tag>}
                </Space>
              }
              description={
                <div>
                  {item.output && (
                    <pre style={{
                      marginTop: 8, maxHeight: 150, overflow: 'auto',
                      background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12,
                    }}>
                      {item.output}
                    </pre>
                  )}
                  {item.error && <div style={{ color: 'red' }}>{item.error}</div>}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.created_at && new Date(item.created_at).toLocaleString()}
                  </Text>
                </div>
              }
            />
          </List.Item>
        )}
      />
    );
  };

  // ===== Tab 项 =====
  const tabItems = sessionState ? [
    { key: 'requirement', label: '需求', children: renderArtifacts('requirement') },
    { key: 'file', label: '上传文件', children: renderArtifacts('file') },
    { key: 'agent_message', label: 'Agent消息', children: renderArtifacts('agent_message') },
    { key: 'test_point', label: '测试点', children: renderArtifacts('test_point') },
    { key: 'case', label: '生成用例', children: renderArtifacts('case') },
    { key: 'script', label: '脚本', children: renderArtifacts('script') },
    { key: 'log', label: '日志', children: renderArtifacts('log') },
    { key: 'mindmap', label: '思维导图', children: renderArtifacts('mindmap') },
    { key: 'export', label: '导出文件', children: renderArtifacts('export') },
    { key: 'review', label: '评审', children: renderArtifacts('review') },
    { key: 'events', label: 'Agent事件时间线', children: renderAgentEvents() },
    { key: 'flow', label: '流程结果', children: renderFlowResults() },
  ] : [];

  return (
    <div style={{ height: 'calc(100vh - 64px)', display: 'flex' }}>
      {/* ===== 左侧：会话列表 ===== */}
      <div style={{ width: 360, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0' }}>
          <Space style={{ width: '100%', marginBottom: 8 }}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateModalVisible(true)}
            >
              新建会话
            </Button>
            <Button icon={<ReloadOutlined />} onClick={loadSessions}>刷新</Button>
          </Space>
          <Input
            placeholder="搜索会话..."
            prefix={<SearchOutlined />}
            value={searchKeyword}
            onChange={e => setSearchKeyword(e.target.value)}
            style={{ marginBottom: 8 }}
          />
          <Space>
            {['', 'active', 'completed', 'paused', 'archived'].map(s => (
              <Tag
                key={s}
                color={statusFilter === s ? 'blue' : 'default'}
                style={{ cursor: 'pointer' }}
                onClick={() => setStatusFilter(s)}
              >
                {s === '' ? '全部' : STATUS_LABELS[s] || s}
              </Tag>
            ))}
          </Space>
        </div>

        <div style={{ flex: 1, overflow: 'auto' }}>
          <Spin spinning={loading}>
            <List
              dataSource={sessions}
              locale={{ emptyText: <Empty description="暂无会话" /> }}
              renderItem={(session) => (
                <List.Item
                  key={session.id}
                  onClick={() => restoreSession(session.id)}
                  style={{
                    cursor: 'pointer',
                    padding: '12px 16px',
                    background: selectedSessionId === session.id ? '#e6f7ff' : 'transparent',
                    borderLeft: selectedSessionId === session.id ? '3px solid #1890ff' : '3px solid transparent',
                  }}
                >
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong ellipsis style={{ maxWidth: 200 }}>
                        {session.session_name}
                      </Text>
                      <Tag color={STATUS_COLORS[session.status] || 'default'}>
                        {STATUS_LABELS[session.status] || session.status}
                      </Tag>
                    </div>
                    {session.requirement_summary && (
                      <Text type="secondary" ellipsis style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                        {session.requirement_summary}
                      </Text>
                    )}
                    <div style={{ marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {session.artifact_count > 0 && (
                        <Tag style={{ fontSize: 11 }}>制品: {session.artifact_count}</Tag>
                      )}
                      {session.total_tokens > 0 && (
                        <Tag style={{ fontSize: 11 }}>tokens: {session.total_tokens}</Tag>
                      )}
                      {session.error_count > 0 && (
                        <Tag color="red" style={{ fontSize: 11 }}>错误: {session.error_count}</Tag>
                      )}
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {session.created_at && new Date(session.created_at).toLocaleString()}
                      </Text>
                    </div>
                  </div>
                </List.Item>
              )}
            />
          </Spin>
        </div>
      </div>

      {/* ===== 右侧：会话详情 ===== */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {restoring ? (
          <div style={{ textAlign: 'center', paddingTop: 100 }}>
            <Spin size="large" tip="恢复会话中..." />
          </div>
        ) : !sessionState ? (
          <div style={{ textAlign: 'center', paddingTop: 100 }}>
            <Empty description="选择左侧会话查看详情" />
          </div>
        ) : (
          <>
            {/* 会话头部 */}
            <Card size="small" style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                <Col span={6}>
                  <Statistic title="状态" value={STATUS_LABELS[sessionState.session.status] || sessionState.session.status} />
                </Col>
                <Col span={6}>
                  <Statistic title="制品数" value={sessionState.stats.total_artifacts} />
                </Col>
                <Col span={6}>
                  <Statistic title="事件数" value={sessionState.stats.total_events} />
                </Col>
                <Col span={6}>
                  <Statistic title="总耗时" value={`${(sessionState.session.total_duration || 0).toFixed(1)}s`} />
                </Col>
              </Row>
              <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
                <Space>
                  <Text strong>{sessionState.session.session_name}</Text>
                  <Tag>{sessionState.session.input_mode}</Tag>
                  {sessionState.session.graphflow_task_id && (
                    <Tag color="blue">GraphFlow: {sessionState.session.graphflow_task_id}</Tag>
                  )}
                </Space>
                <Space>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={runLoading}
                    onClick={handleRunGraphflow}
                  >
                    执行 GraphFlow
                  </Button>
                  <Tooltip title="删除会话">
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDelete(sessionState.session.id)}
                    />
                  </Tooltip>
                </Space>
              </div>
              {sessionState.session.requirement_text && (
                <div style={{ marginTop: 12 }}>
                  <Text type="secondary">需求: </Text>
                  <Text>{sessionState.session.requirement_text}</Text>
                </div>
              )}
            </Card>

            {/* Tab 内容 */}
            <Tabs
              items={tabItems}
              defaultActiveKey="requirement"
              type="card"
              style={{ minHeight: 400 }}
            />
          </>
        )}
      </div>

      {/* ===== 创建会话 Modal ===== */}
      <Modal
        title="新建会话"
        open={createModalVisible}
        onOk={handleCreate}
        onCancel={() => setCreateModalVisible(false)}
        okText="创建"
        cancelText="取消"
        width={600}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item name="session_name" label="会话名称">
            <Input placeholder="留空则自动生成" />
          </Form.Item>
          <Form.Item name="requirement" label="需求描述">
            <TextArea
              rows={4}
              placeholder="请描述测试需求，例如：测试登录功能..."
            />
          </Form.Item>
          <Form.Item name="input_mode" label="输入模式" initialValue="text">
            <select style={{ width: '100%', padding: '4px 11px', border: '1px solid #d9d9d9', borderRadius: 6 }}>
              <option value="text">文本输入</option>
              <option value="image">图片输入</option>
              <option value="file">文件上传</option>
              <option value="url">URL输入</option>
            </select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
