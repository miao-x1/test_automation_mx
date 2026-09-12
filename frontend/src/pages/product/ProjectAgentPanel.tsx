import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Input, Typography, message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from './projectStore';
import { PROJECT_AGENT_ASK, PROJECT_MEMORY_CHANGED, askProjectAgent, fetchProjectMemory, type AgentReply } from '@/services/projectExplorer';

const { Text, Paragraph } = Typography;

export default function ProjectAgentPanel({
  workspace,
  testTaskId,
}: {
  workspace: 'understand' | 'design' | 'execute';
  testTaskId?: number;
}) {
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [last, setLast] = useState<AgentReply | null>(null);

  const loadHistory = useCallback(async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const data = await fetchProjectMemory(projectId);
    const rows = (data?.messages || []).map((item: any) => ({
      role: item.role || 'assistant',
      content: item.content || item.title,
    }));
    setMessages(rows);
  }, []);

  useEffect(() => {
    loadHistory().catch(() => undefined);
    const reload = () => { void loadHistory(); };
    window.addEventListener(PROJECT_CHANGED, reload);
    return () => window.removeEventListener(PROJECT_CHANGED, reload);
  }, [loadHistory]);

  const openAction = (action: any) => {
    if (action?.path) {
      navigate(action.path);
      return;
    }
    if (action?.test_task_id) {
      navigate(`/test-tasks/${action.test_task_id}`);
    }
  };

  const submit = useCallback(async (text: string) => {
    const projectId = getCurrentProjectId();
    if (!projectId) {
      message.warning('请先选择项目');
      return;
    }
    const q = text.trim();
    if (!q) return;
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    try {
      const data = await askProjectAgent(projectId, q, workspace, false, testTaskId);
      setLast(data);
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer }]);
      setQuestion('');
      window.dispatchEvent(new CustomEvent(PROJECT_MEMORY_CHANGED));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || 'Agent 回答失败');
    } finally {
      setLoading(false);
    }
  }, [workspace, testTaskId]);

  useEffect(() => {
    const onAsk = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      if (detail.question) void submit(detail.question);
    };
    window.addEventListener(PROJECT_AGENT_ASK, onAsk);
    return () => window.removeEventListener(PROJECT_AGENT_ASK, onAsk);
  }, [submit]);

  return (
    <aside className="project-agent-panel">
      <div className="project-agent-panel__head">
        <Text strong>项目 Agent</Text>
        <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
          {getCurrentProjectName() || '当前项目'} · {workspace}
          {testTaskId ? ` · 任务 #${testTaskId}` : ''}
        </Paragraph>
        {last?.path ? <Text type="secondary">最短路径：{last.path}</Text> : null}
      </div>
      <div className="project-agent-panel__body">
        {messages.length === 0 && (
          <Paragraph type="secondary">
            普通用户可以说「帮我全面测试」。专业人员可以直接要用例、分析需求或定位代码。Agent 会选最短路径，并把产物写入测试任务。
          </Paragraph>
        )}
        {messages.map((item, index) => (
          <div key={`${item.role}-${index}`} className={`project-agent-msg is-${item.role}`}>
            <Text type="secondary">{item.role === 'user' ? '你' : 'Agent'}</Text>
            <pre>{item.content}</pre>
          </div>
        ))}
        {last?.locations?.length ? (
          <div className="project-agent-locs">
            {last.locations.slice(0, 6).map((item) => (
              <div key={`${item.path}-${item.name}-${item.line_start}`}>
                {item.path}:{item.line_start || 1} · {item.name}
              </div>
            ))}
          </div>
        ) : null}
        {last?.actions?.length ? (
          <div className="project-agent-actions">
            {last.actions.map((action, index) => (
              action.path || action.test_task_id ? (
                <Button key={`${action.type}-${index}`} size="small" type="link" onClick={() => openAction(action)}>
                  打开{action.path || `测试任务 #${action.test_task_id}`}
                </Button>
              ) : null
            ))}
          </div>
        ) : null}
      </div>
      <div className="project-agent-panel__foot">
        <Input.TextArea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={testTaskId ? '根据当前任务：生成用例、补边界、检查覆盖率…' : '帮我全面测试 / 给我登录用例 / 什么是冒烟测试'}
          autoSize={{ minRows: 2, maxRows: 4 }}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              void submit(question);
            }
          }}
        />
        <Button type="primary" block loading={loading} style={{ marginTop: 8 }} onClick={() => void submit(question)}>
          发送到项目 Agent
        </Button>
      </div>
    </aside>
  );
}
