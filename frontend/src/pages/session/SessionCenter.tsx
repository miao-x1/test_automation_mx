/**
 * 会话中心 - 事件驱动架构核心页面
 *
 * 布局：左侧会话列表 | 右侧详情Tabs
 * 支持实时工作流监控、Agent状态追踪、恢复/重跑
 */
import { useState, useEffect, useCallback } from 'react';
import { Layout, List, Card, Tabs, Tag, Badge, Button, Space, Descriptions, Timeline, Empty, Spin, message, Input, Select } from 'antd';
import { PlayCircleOutlined, RedoOutlined, CheckCircleOutlined, CloseCircleOutlined, SyncOutlined, ClockCircleOutlined, FileTextOutlined, ApiOutlined, BugOutlined } from '@ant-design/icons';
import { useWorkflowMonitor } from '../../hooks/useWorkflowMonitor';
import type { WorkflowEventItem, AgentResultItem } from '../../hooks/useWorkflowMonitor';

const { Sider, Content } = Layout;

/* ── 常量映射 ── */
const statusConfig: Record<string, { color: string; label: string }> = {
  active: { color: 'processing', label: '进行中' },
  paused: { color: 'warning', label: '已暂停' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
  archived: { color: 'default', label: '已归档' },
};

const agentStatusIcon: Record<string, React.ReactNode> = {
  pending: <ClockCircleOutlined style={{ color: '#faad14' }} />,
  running: <SyncOutlined spin style={{ color: '#1890ff' }} />,
  completed: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
};

const agentLabel: Record<string, string> = {
  APIExtraction: 'API提取',
  RAG: 'RAG上下文',
  CaseGenerate: '用例生成',
  RequirementParser: '需求解析',
  TestPoint: '测试点',
};

/* ── Agent结果获取 ── */
async function fetchAgentResult(sessionId: string, agent: string): Promise<any> {
  const res = await fetch(`/api/workflow/result?session_id=${sessionId}&agent=${agent}`, { credentials: 'include' });
  if (!res.ok) throw new Error('获取结果失败');
  const data = await res.json();
  return data.result || data.items || data;
}

/* ── 状态Badge组件 ── */
function AgentBadge({ status }: { status: string }) {
  const cfg: Record<string, { color: string; text: string }> = {
    pending: { color: 'default', text: '等待中' },
    running: { color: 'processing', text: '运行中' },
    completed: { color: 'success', text: '已完成' },
    failed: { color: 'error', text: '失败' },
  };
  const c = cfg[status] || { color: 'default', text: status };
  return <Badge status={c.color as any} text={c.text} />;
}

/* ── 主组件 ── */
export default function SessionCenter() {
  // 会话列表
  const [sessions, setSessions] = useState<any[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [searchText, setSearchText] = useState('');

  // 选中会话
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedSession = sessions.find(s => String(s.session_id) === selectedId) || null;

  // 工作流监控
  const { events, agents, loading: wfLoading, error: wfError, isRunning, refetch } = useWorkflowMonitor(selectedId);

  // Agent结果
  const [apiResult, setApiResult] = useState<any>(null);
  const [ragResult, setRagResult] = useState<any>(null);
  const [caseResult, setCaseResult] = useState<any>(null);
  const [resultLoading, setResultLoading] = useState(false);

  /* ── 获取会话列表 ── */
  const fetchSessions = useCallback(async () => {
    setListLoading(true);
    try {
      const res = await fetch('/api/session/v2/list', { credentials: 'include' });
      const data = await res.json();
      setSessions(data.items || data || []);
    } catch {
      message.error('获取会话列表失败');
    }
    setListLoading(false);
  }, []);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  /* ── 选中会话后获取Agent结果 ── */
  useEffect(() => {
    if (!selectedId) return;
    setResultLoading(true);
    Promise.all([
      fetchAgentResult(selectedId, 'APIExtraction').catch(() => null),
      fetchAgentResult(selectedId, 'RAG').catch(() => null),
      fetchAgentResult(selectedId, 'CaseGenerate').catch(() => null),
    ]).then(([api, rag, cs]) => {
      setApiResult(api);
      setRagResult(rag);
      setCaseResult(cs);
      setResultLoading(false);
    });
  }, [selectedId, isRunning]); // isRunning变化时刷新结果

  /* ── 操作：恢复 ── */
  const handleResume = async () => {
    if (!selectedId) return;
    try {
      const res = await fetch(`/api/workflow/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: selectedId }),
        credentials: 'include',
      });
      if (!res.ok) throw new Error('恢复失败');
      message.success('工作流已恢复');
      refetch();
      fetchSessions();
    } catch (err: any) {
      message.error(err.message || '恢复失败');
    }
  };

  /* ── 操作：重跑 ── */
  const handleRerun = async () => {
    if (!selectedId) return;
    try {
      const res = await fetch(`/api/workflow/rerun`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: selectedId }),
        credentials: 'include',
      });
      if (!res.ok) throw new Error('重跑失败');
      message.success('工作流已重新启动');
      refetch();
      fetchSessions();
    } catch (err: any) {
      message.error(err.message || '重跑失败');
    }
  };

  /* ── 过滤会话 ── */
  const filteredSessions = sessions.filter(s => {
    if (statusFilter && s.status !== statusFilter) return false;
    if (searchText && !s.session_name?.toLowerCase().includes(searchText.toLowerCase())) return false;
    return true;
  });

  /* ── 渲染JSON结果 ── */
  const renderResult = (data: any, emptyText: string) => {
    if (!data) return <Empty description={emptyText} />;
    if (Array.isArray(data)) {
      return (
        <List size="small" dataSource={data} renderItem={(item: any) => (
          <List.Item>
            <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', width: '100%' }}>
              {JSON.stringify(item, null, 2)}
            </pre>
          </List.Item>
        )} />
      );
    }
    return <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{JSON.stringify(data, null, 2)}</pre>;
  };

  /* ── 右侧Tabs ── */
  const tabItems = [
    {
      key: 'requirement',
      label: <span><FileTextOutlined /> 需求</span>,
      children: (
        <Card size="small">
          {selectedSession?.requirement_summary ? (
            <Descriptions column={1} size="small">
              <Descriptions.Item label="需求摘要">{selectedSession.requirement_summary}</Descriptions.Item>
              {selectedSession.compile_level && (
                <Descriptions.Item label="编译级别">{selectedSession.compile_level}</Descriptions.Item>
              )}
            </Descriptions>
          ) : (
            <Empty description="暂无需求信息" />
          )}
        </Card>
      ),
    },
    {
      key: 'api',
      label: <span><ApiOutlined /> API提取</span>,
      children: resultLoading ? <Spin /> : renderResult(apiResult, '暂无API提取结果'),
    },
    {
      key: 'rag',
      label: <span><BugOutlined /> RAG上下文</span>,
      children: resultLoading ? <Spin /> : renderResult(ragResult, '暂无RAG结果'),
    },
    {
      key: 'case',
      label: <span><FileTextOutlined /> 用例</span>,
      children: resultLoading ? <Spin /> : renderResult(caseResult, '暂无用例生成结果'),
    },
    {
      key: 'log',
      label: <span><ClockCircleOutlined /> 日志</span>,
      children: (
        <Card size="small">
          {wfError && (
            <div style={{ color: '#ff4d4f', marginBottom: 12 }}>
              <CloseCircleOutlined /> {wfError}
            </div>
          )}
          {events.length === 0 ? (
            <Empty description="暂无工作流事件" />
          ) : (
            <Timeline
              items={events.map((ev: WorkflowEventItem) => ({
                color: ev.status === 'failed' ? 'red' : ev.status === 'running' ? 'blue' : ev.status === 'completed' ? 'green' : 'gray',
                children: (
                  <div>
                    <Space>
                      <Tag>{agentLabel[ev.agent] || ev.agent}</Tag>
                      <AgentBadge status={ev.status} />
                      <span style={{ fontSize: 12, color: '#999' }}>
                        {ev.timestamp ? new Date(ev.timestamp).toLocaleString() : ''}
                      </span>
                    </Space>
                    <div style={{ marginTop: 4 }}>{ev.message}</div>
                    {ev.error_detail && (
                      <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>
                        错误详情: {ev.error_detail}
                      </div>
                    )}
                  </div>
                ),
              }))}
            />
          )}
        </Card>
      ),
    },
    {
      key: 'exec',
      label: <span><PlayCircleOutlined /> 执行</span>,
      children: (
        <Card size="small">
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {/* Agent状态概览 */}
            <div>
              <div style={{ fontWeight: 500, marginBottom: 8 }}>Agent 状态</div>
              {agents.length === 0 ? (
                <Empty description="暂无Agent信息" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <Space wrap>
                  {agents.map((a: AgentResultItem) => (
                    <Tag key={a.agent} icon={agentStatusIcon[a.status]}>
                      {agentLabel[a.agent] || a.agent}: {a.status}
                    </Tag>
                  ))}
                </Space>
              )}
            </div>

            {/* 错误展示 */}
            {agents.some(a => a.status === 'failed') && (
              <div style={{ background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 6, padding: 12 }}>
                <div style={{ color: '#ff4d4f', fontWeight: 500, marginBottom: 4 }}>
                  <CloseCircleOutlined /> 执行错误
                </div>
                {agents.filter(a => a.status === 'failed' && a.error).map(a => (
                  <div key={a.agent} style={{ fontSize: 12, marginTop: 4 }}>
                    <strong>{agentLabel[a.agent] || a.agent}:</strong> {a.error}
                  </div>
                ))}
              </div>
            )}

            {/* 操作按钮 */}
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleResume}
                disabled={!selectedSession || selectedSession.status === 'active'}
              >
                恢复执行
              </Button>
              <Button
                icon={<RedoOutlined />}
                onClick={handleRerun}
                disabled={!selectedSession}
              >
                重新执行
              </Button>
            </Space>

            {/* 运行状态 */}
            {wfLoading && (
              <div><SyncOutlined spin /> 正在监控工作流...</div>
            )}
          </Space>
        </Card>
      ),
    },
  ];

  return (
    <Layout style={{ height: '100%', background: '#fff' }}>
      {/* ── 左侧：会话列表 ── */}
      <Sider width={360} style={{ background: '#fafafa', borderRight: '1px solid #f0f0f0', padding: 12 }}>
        <div style={{ marginBottom: 12 }}>
          <Input.Search
            placeholder="搜索会话名称"
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ marginBottom: 8 }}
            allowClear
          />
          <Select
            placeholder="按状态筛选"
            value={statusFilter}
            onChange={setStatusFilter}
            allowClear
            style={{ width: '100%' }}
            options={Object.entries(statusConfig).map(([k, v]) => ({ value: k, label: v.label }))}
          />
        </div>

        <List
          loading={listLoading}
          dataSource={filteredSessions}
          rowKey="session_id"
          renderItem={(session: any) => {
            const isSelected = String(session.session_id) === selectedId;
            const sc = statusConfig[session.status] || { color: 'default', label: session.status };
            return (
              <List.Item
                onClick={() => setSelectedId(String(session.session_id))}
                style={{
                  cursor: 'pointer',
                  background: isSelected ? '#e6f7ff' : '#fff',
                  border: isSelected ? '1px solid #1890ff' : '1px solid #f0f0f0',
                  borderRadius: 6,
                  padding: '8px 12px',
                  marginBottom: 4,
                }}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <span style={{ fontSize: 14 }}>{session.session_name || `会话 #${session.session_id}`}</span>
                      <Tag color={sc.color} style={{ marginLeft: 4 }}>{sc.label}</Tag>
                    </Space>
                  }
                  description={
                    <div style={{ fontSize: 12, color: '#999' }}>
                      <div>步骤: {session.current_step || '-'} | {session.created_at ? new Date(session.created_at).toLocaleString() : '-'}</div>
                    </div>
                  }
                />
              </List.Item>
            );
          }}
          locale={{ emptyText: <Empty description="暂无会话" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
        />
      </Sider>

      {/* ── 右侧：详情 ── */}
      <Content style={{ padding: 16, overflow: 'auto' }}>
        {!selectedSession ? (
          <Empty description="请从左侧选择一个会话" style={{ marginTop: 120 }} />
        ) : (
          <div>
            <div style={{ marginBottom: 16 }}>
              <Space>
                <span style={{ fontSize: 18, fontWeight: 600 }}>
                  {selectedSession.session_name || `会话 #${selectedSession.session_id}`}
                </span>
                <Tag color={statusConfig[selectedSession.status]?.color}>
                  {statusConfig[selectedSession.status]?.label || selectedSession.status}
                </Tag>
                {isRunning && <Badge status="processing" text="监控中" />}
              </Space>
            </div>
            <Tabs items={tabItems} defaultActiveKey="requirement" />
          </div>
        )}
      </Content>
    </Layout>
  );
}
