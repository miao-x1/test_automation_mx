import { useCallback, useEffect, useState } from 'react';
import { Button, Drawer, Input, message } from 'antd';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import {
  PROJECT_AGENT_ASK,
  PROJECT_AGENT_OPEN,
  PROJECT_MEMORY_CHANGED,
  apiError,
  askProjectAgent,
  fetchProjectFile,
  previewGeneratedCases,
  type AgentReply,
} from '@/services/projectExplorer';

const CAPS = [
  { label: '理解项目', q: '这个项目是做什么的？核心模块和测试风险是什么？' },
  { label: '查找功能', q: '核心功能在哪里？入口页面、函数和 API 是什么？' },
  { label: '分析代码', q: '解释项目里最核心的代码文件，以及它和页面、接口的关系。' },
  { label: '分析调用链', q: '把核心功能的完整调用链列出来。' },
  { label: '设计测试', q: '根据当前项目理解，登录相关测试应该怎么设计？' },
  { label: '分析测试缺口', q: '当前项目测试缺口和风险是什么？' },
  { label: '分析执行失败', q: '最近一次失败执行的原因是什么？' },
];

function workspaceOf(pathname: string): 'understand' | 'design' | 'execute' {
  if (pathname.startsWith('/execute') || pathname.startsWith('/execution') || pathname.startsWith('/report')) return 'execute';
  if (pathname.startsWith('/design') || pathname.startsWith('/test-tasks') || pathname.startsWith('/task')) return 'design';
  return 'understand';
}

export default function ProjectAgentDock() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState('');
  const [last, setLast] = useState<AgentReply | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<any[]>([]);
  const [preview, setPreview] = useState<{ path: string; text: string } | null>(null);

  const submit = useCallback(async (text: string) => {
    const projectId = getCurrentProjectId();
    const q = text.trim();
    if (!projectId || !q) return;
    setQuestion(q);
    setOpen(true);
    setLoading(true);
    setDrafts([]);
    setPreview(null);
    setSteps(['识别目标对象', '搜索项目知识', '定位页面 / 功能 / 代码 / API / 测试']);
    try {
      if (/生成/.test(q) && /用例|测试/.test(q)) {
        const preview = await previewGeneratedCases(projectId, q);
        setDrafts(preview?.cases || []);
        setLast({
          answer: `已预览 ${preview?.cases?.length || 0} 条用例，未写入测试资产。`,
          workspace: 'design',
          project_id: projectId,
          locations: [],
          memory_used: [],
          actions: [],
        });
      } else {
        const reply = await askProjectAgent(projectId, q, workspaceOf(window.location.pathname));
        setLast(reply);
        window.dispatchEvent(new CustomEvent(PROJECT_MEMORY_CHANGED));
      }
    } catch (err: any) {
      message.error(apiError(err, '分析失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const onOpen = (event: Event) => {
      const q = (event as CustomEvent).detail?.question || '';
      setOpen(true);
      if (q) void submit(q);
    };
    const onAsk = (event: Event) => {
      const q = (event as CustomEvent).detail?.question || '';
      if (q) void submit(q);
    };
    window.addEventListener(PROJECT_AGENT_OPEN, onOpen);
    window.addEventListener(PROJECT_AGENT_ASK, onAsk);
    const reset = () => { setLast(null); setDrafts([]); setQuestion(''); setPreview(null); };
    window.addEventListener(PROJECT_CHANGED, reset);
    return () => {
      window.removeEventListener(PROJECT_AGENT_OPEN, onOpen);
      window.removeEventListener(PROJECT_AGENT_ASK, onAsk);
      window.removeEventListener(PROJECT_CHANGED, reset);
    };
  }, [submit]);

  return (
    <Drawer
      title="agent助手"
      extra={<span style={{ color: '#656d76' }}>{getCurrentProjectName() || '当前项目'}</span>}
      open={open}
      onClose={() => setOpen(false)}
      width={380}
    >
        <div className="agent-dock">
          <div>AI 能帮你：</div>
          <div className="agent-dock-caps">
            {CAPS.map((item) => (
              <button key={item.label} type="button" className={active === item.label ? 'is-on' : ''} onClick={() => { setActive(item.label); void submit(item.q); }}>
                {item.label}
              </button>
            ))}
          </div>
          <div className="agent-dock-log">
            {!last && !loading ? (
              <div className="agent-dock-msg">
                <p>你好，我可以帮助你理解当前项目。</p>
                <p>例如：</p>
                <p>“登录功能在哪里？”</p>
                <p>“这个 API 被谁调用？”</p>
                <p>“登录测试还缺什么？”</p>
              </div>
            ) : null}
            {loading || last ? (
              <div className="agent-dock-result">
                <b>{loading ? '正在分析' : '分析完成'}</b>
                {steps.map((item) => <div key={item}>{loading ? '●' : '✓'} {item}</div>)}
              </div>
            ) : null}
            {last ? (
              <div className="agent-dock-result">
                <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{last.answer}</pre>
                {(last.locations || []).map((item) => (
                  <button
                    key={`${item.path}-${item.name}`}
                    type="button"
                    style={{ display: 'block', width: '100%', textAlign: 'left', background: 'none', border: 0, padding: 0, cursor: item.path ? 'pointer' : 'default' }}
                    onClick={async () => {
                      if (!item.path) return;
                      const projectId = getCurrentProjectId();
                      if (!projectId) return;
                      try {
                        const file = await fetchProjectFile(projectId, item.path);
                        setPreview({
                          path: item.path,
                          text: file?.content || file?.text || file?.source || file?.snippet || item.snippet || '',
                        });
                      } catch {
                        setPreview({ path: item.path, text: item.snippet || `读不到 ${item.path}` });
                      }
                    }}
                  >
                    {item.path}:{item.line_start || 1} · {item.name}
                    {item.snippet ? <pre style={{ whiteSpace: 'pre-wrap' }}>{item.snippet}</pre> : null}
                  </button>
                ))}
                {preview ? (
                  <div>
                    <b>{preview.path}</b>
                    <pre style={{ whiteSpace: 'pre-wrap' }}>{preview.text || '文件是空的'}</pre>
                  </div>
                ) : null}
              </div>
            ) : null}
            {drafts.map((item, index) => (
              <div className="agent-dock-result" key={item.case_code || item.name || index}>
                <b>{item.case_code} {item.name}</b>
                <p>{item.precondition}</p>
                <p>{item.expected || item.expected_result}</p>
              </div>
            ))}
          </div>
          <div className="agent-dock-foot">
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="问问当前项目……"
              onPressEnter={() => void submit(question)}
            />
            <Button type="primary" loading={loading} onClick={() => void submit(question)}>发送</Button>
          </div>
        </div>
    </Drawer>
  );
}
