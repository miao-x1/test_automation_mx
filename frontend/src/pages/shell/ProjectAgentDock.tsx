import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button, Dropdown, Input, Popover, message } from 'antd';
import axios from 'axios';
import { getCurrentProjectId, getCurrentProjectName, PROJECT_CHANGED } from '@/pages/product/projectStore';
import {
  PROJECT_AGENT_ASK,
  PROJECT_AGENT_OPEN,
  PROJECT_MEMORY_CHANGED,
  PROJECT_REQUIREMENT_CHANGED,
  PROJECT_DESIGN_CHANGED,
  apiError,
  askProjectAgent,
  fetchProjectIndex,
  fetchProjectMemory,
  type AgentReply,
} from '@/services/projectExplorer';
import { PROJECT_PIPELINE_CHANGED } from '@/services/testPipeline';
import { PROJECT_CASES_CHANGED } from '@/services/testCases';
import { fetchLifecycleAssets } from '@/services/assetLifecycle';
import request from '@/services/request';
import { ProjectSwitcherMenu } from './ProjectHeaderBar';
import SimpleMarkdown from './agent/SimpleMarkdown';
import {
  CONTEXT_OPTIONS,
  SKILLS,
  cardsFromReply,
  composeQuestion,
  needsWriteConfirm,
  pageContextOf,
  pagePromptOf,
  statusLabel,
  stepsFromReply,
  workspaceFromChips,
  workspaceOf,
  type AgentMode,
  type ContextChip,
  type PanelStatus,
  type Turn,
} from './agent/workbench';

const MODE_KEY = 'agent_workbench_mode';
const MODEL_KEY = 'agent_workbench_model';
export const PROJECT_CREATE_OPEN = 'project-create-open';

function loadMode(): AgentMode {
  return sessionStorage.getItem(MODE_KEY) === 'chat' ? 'chat' : 'agent';
}

export default function ProjectAgentDock() {
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [projectId, setProjectId] = useState(getCurrentProjectId);
  const [projectName, setProjectName] = useState(getCurrentProjectName);
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [mode, setMode] = useState<AgentMode>(loadMode);
  const [model, setModel] = useState(sessionStorage.getItem(MODEL_KEY) || 'Auto');
  const [models, setModels] = useState<string[]>(['Auto']);
  const [chips, setChips] = useState<ContextChip[]>([]);
  const [openStep, setOpenStep] = useState<string | null>(null);
  const [picker, setPicker] = useState<{ title: string; items: Array<{ label: string; chip: ContextChip }> } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const sync = () => {
      setProjectId(getCurrentProjectId());
      setProjectName(getCurrentProjectName() || '当前项目');
      setTurns([]);
      setQuestion('');
      setChips(pageContextOf(window.location.pathname));
      setPicker(null);
      setStatus('idle');
      abortRef.current?.abort();
      abortRef.current = null;
      setLoading(false);
    };
    sync();
    window.addEventListener(PROJECT_CHANGED, sync);
    return () => window.removeEventListener(PROJECT_CHANGED, sync);
  }, []);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, loading, open, status]);

  useEffect(() => {
    setChips((prev) => {
      const page = pageContextOf(location.pathname);
      const extras = prev.filter((item) => item.kind !== 'context');
      return [...page, ...extras];
    });
  }, [location.pathname, projectId]);

  useEffect(() => {
    let cancelled = false;
    request.get('/llm-gateway/providers').then((res: any) => {
      const providers = res?.providers || res?.data?.providers || [];
      const names = providers.flatMap((item: any) => {
        const provider = item?.name || item?.provider || '';
        const list = item?.models || item?.model_names || [];
        if (Array.isArray(list) && list.length) {
          return list.map((modelName: any) => (typeof modelName === 'string' ? modelName : modelName?.name)).filter(Boolean);
        }
        return provider ? [provider] : [];
      });
      if (!cancelled && names.length) setModels(['Auto', ...Array.from(new Set(names as string[]))]);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const addChip = (chip: ContextChip) => {
    setChips((prev) => (prev.some((item) => item.id === chip.id) ? prev : [...prev, chip]));
    setPicker(null);
  };

  const runAsk = useCallback(async (text: string) => {
    const currentId = getCurrentProjectId();
    const currentName = getCurrentProjectName() || '当前项目';
    const q = text.trim();
    if (!q || !currentId) return;
    setProjectId(currentId);
    setProjectName(currentName);
    setOpen(true);
    setQuestion('');
    setTurns((prev) => [...prev.filter((item) => item.role !== 'confirm'), { role: 'user', text: q }]);
    setStatus('thinking');
    setLoading(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const packed = composeQuestion(q, chips);
    const workspace = workspaceFromChips(chips, workspaceOf(window.location.pathname));
    window.setTimeout(() => {
      if (abortRef.current === ctrl) setStatus((prev) => (prev === 'thinking' ? 'running' : prev));
    }, 400);
    try {
      const reply = await askProjectAgent(currentId, packed, workspace, false, undefined, { signal: ctrl.signal }) as AgentReply;
      if (reply?.project_id && Number(reply.project_id) !== Number(currentId)) {
        throw new Error('回答不是当前选中项目的结果');
      }
      const answer = (reply?.answer || '').trim() || '没有得到回答。';
      setTurns((prev) => [...prev, {
        role: 'assistant',
        text: answer,
        steps: stepsFromReply(reply),
        cards: mode === 'agent' ? cardsFromReply(reply) : [],
      }]);
      setStatus('completed');
      window.dispatchEvent(new CustomEvent(PROJECT_MEMORY_CHANGED));
      if ((reply?.actions || []).some((item) => item?.type === 'requirement_analysis')) {
        window.dispatchEvent(new CustomEvent(PROJECT_REQUIREMENT_CHANGED));
      }
      if ((reply?.actions || []).some((item) => item?.type === 'design_test')) {
        window.dispatchEvent(new CustomEvent(PROJECT_DESIGN_CHANGED));
      }
      if ((reply?.actions || []).some((item) => item?.type === 'pipeline')) {
        window.dispatchEvent(new CustomEvent(PROJECT_PIPELINE_CHANGED));
      }
      if ((reply?.actions || []).some((item) => ['generate_cases', 'generated_cases', 'supplement_exception', 'supplement_boundary'].includes(item?.type || ''))) {
        window.dispatchEvent(new CustomEvent(PROJECT_CASES_CHANGED));
      }
    } catch (err: any) {
      if (axios.isCancel(err) || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
        setTurns((prev) => [...prev, { role: 'assistant', text: '已停止。' }]);
        setStatus('cancelled');
        return;
      }
      const textError = apiError(err, '回答失败');
      setTurns((prev) => [...prev, { role: 'assistant', text: textError, failed: true }]);
      setStatus('error');
      message.error(textError);
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      setLoading(false);
    }
  }, [chips, mode]);

  const submit = useCallback(async (text: string) => {
    const currentId = getCurrentProjectId();
    const q = text.trim();
    if (!q) return;
    if (!currentId) {
      message.info('请先选择一个项目');
      return;
    }
    setOpen(true);
    if (mode === 'chat' && needsWriteConfirm(q, 'agent')) {
      message.info('Chat 模式只做问答，不会执行或改资产。请切换到 Agent。');
      return;
    }
    if (needsWriteConfirm(q, mode)) {
      setTurns((prev) => [...prev.filter((item) => item.role !== 'confirm'), {
        role: 'confirm',
        text: q,
        pendingQuestion: q,
      }]);
      setQuestion('');
      setStatus('waiting');
      return;
    }
    await runAsk(q);
  }, [mode, runAsk]);

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
    return () => {
      window.removeEventListener(PROJECT_AGENT_OPEN, onOpen);
      window.removeEventListener(PROJECT_AGENT_ASK, onAsk);
    };
  }, [submit]);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLoading(false);
    setStatus('cancelled');
  };

  const loadHistory = async () => {
    const currentId = getCurrentProjectId();
    if (!currentId) {
      message.info('请先选择一个项目');
      return;
    }
    try {
      const data = await fetchProjectMemory(currentId);
      const rows = (data?.messages || []).map((item: any) => ({
        role: item.role === 'user' ? 'user' : 'assistant',
        text: item.content || item.title || '',
      })) as Turn[];
      if (!rows.length) {
        message.info('当前项目还没有历史对话');
        return;
      }
      setTurns(rows);
      setStatus('idle');
    } catch (err: any) {
      message.error(apiError(err, '历史对话加载失败'));
    }
  };

  const openAssetPicker = async () => {
    const currentId = getCurrentProjectId();
    if (!currentId) return message.info('请先选择一个项目');
    try {
      const data = await fetchLifecycleAssets({ project_id: currentId, page: 1, page_size: 20 });
      const items = (data?.items || []).map((item: any) => ({
        label: item.name || item.asset_code || `#${item.id}`,
        chip: { id: `asset-${item.id}`, kind: 'asset' as const, label: item.name || `资产 #${item.id}` },
      }));
      setPicker({ title: items.length ? '选择测试资产' : '当前项目还没有测试资产', items });
    } catch (err: any) {
      message.error(apiError(err, '资产列表加载失败'));
    }
  };

  const openIndexPicker = async (kind: 'api' | 'page', title: string) => {
    const currentId = getCurrentProjectId();
    if (!currentId) return message.info('请先选择一个项目');
    try {
      const rows = await fetchProjectIndex(currentId, { kind, limit: 20 });
      const items = (Array.isArray(rows) ? rows : []).map((item: any) => ({
        label: item.name || item.path,
        chip: {
          id: `${kind}-${item.id || item.name || item.path}`,
          kind,
          label: item.name || item.path,
          workspace: 'understand' as const,
        },
      }));
      setPicker({ title: items.length ? title : `当前项目还没有${kind === 'api' ? '接口' : '页面'}`, items });
    } catch (err: any) {
      message.error(apiError(err, '索引加载失败'));
    }
  };

  const openResultPicker = async () => {
    const currentId = getCurrentProjectId();
    if (!currentId) return message.info('请先选择一个项目');
    try {
      const data: any = await request.get('/executions/list', { params: { page: 1, page_size: 12, project_id: currentId } });
      const rows = data?.items || data?.data?.items || [];
      const items = rows.map((item: any) => ({
        label: `#${item.execution_id || item.id} ${item.status || ''}`.trim(),
        chip: {
          id: `result-${item.execution_id || item.id}`,
          kind: 'result' as const,
          label: `执行 #${item.execution_id || item.id}`,
          workspace: 'execute' as const,
        },
      }));
      setPicker({ title: items.length ? '选择测试结果' : '当前项目还没有测试结果', items });
    } catch (err: any) {
      message.error(apiError(err, '执行记录加载失败'));
    }
  };

  const attachFiles = (files: FileList | null, kind: 'file' | 'asset') => {
    if (!files?.length) return;
    Array.from(files).forEach((file) => {
      addChip({ id: `${kind}-${file.name}-${file.size}`, kind: 'file', label: file.name });
    });
  };

  const headerStatus = loading ? (status === 'thinking' ? 'thinking' : 'running') : status;

  return (
    <div className={`agent-wb-root ${open ? 'is-open' : ''}`}>
      <aside className={`agent-wb ${open ? 'is-open' : ''}`}>
        <header className="agent-wb-top">
          <div className="agent-wb-brand">
            <span>✦</span>
            <b>AI 测试助手</b>
          </div>
          <span className={`agent-wb-live is-${headerStatus}`}>
            <i />
            {statusLabel(headerStatus)}
          </span>
          <Dropdown
            menu={{
              items: [
                { key: 'new', label: '新建对话', onClick: () => { setTurns([]); setStatus('idle'); setChips(pageContextOf(location.pathname)); } },
                { key: 'history', label: '历史对话', onClick: () => void loadHistory() },
                { key: 'clear', label: '清空当前对话', onClick: () => { setTurns([]); setStatus('idle'); } },
              ],
            }}
          >
            <button type="button" className="agent-wb-more" aria-label="更多">⋯</button>
          </Dropdown>
          <button type="button" className="agent-wb-more" onClick={() => setOpen(false)} aria-label="关闭">×</button>
        </header>

        <div className="agent-wb-project">
          <span>当前项目</span>
          <Popover trigger="click" placement="bottomLeft" content={<ProjectSwitcherMenu onCreate={() => window.dispatchEvent(new CustomEvent(PROJECT_CREATE_OPEN))} />}>
            <button type="button" className="agent-wb-switch">
              <b>{projectName || '未选择项目'}</b>
              <span>▾</span>
            </button>
          </Popover>
        </div>

        <div className="agent-wb-list" ref={listRef}>
          {turns.length === 0 && !loading ? (
            <div className="agent-wb-empty">
              针对「{projectName || '当前项目'}」下达测试任务。Agent 只使用当前项目的理解、资产和执行数据。
              {pagePromptOf(location.pathname) ? (
                <div style={{ marginTop: 12 }}>
                  <button type="button" className="agent-chip" onClick={() => void submit(pagePromptOf(location.pathname) || '')}>
                    ✦ {pagePromptOf(location.pathname)}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          {turns.map((item, index) => {
            if (item.role === 'confirm') {
              return (
                <div key={`confirm-${index}`} className="agent-card agent-card-warn">
                  <div className="agent-card-kicker">即将执行操作</div>
                  <b>{item.text}</b>
                  <p>会按当前项目「{projectName}」调用现有 Agent 能力。创建、修改和执行类操作将写入该项目。</p>
                  <div className="agent-card-actions">
                    <button type="button" onClick={() => { setTurns((prev) => prev.filter((row) => row.role !== 'confirm')); setStatus('cancelled'); }}>取消</button>
                    <button type="button" className="is-primary" onClick={() => void runAsk(item.pendingQuestion || item.text)}>确认执行</button>
                  </div>
                </div>
              );
            }
            return (
              <div key={`${item.role}-${index}`} className={`agent-wb-row is-${item.role}`}>
                <div className="agent-wb-who">{item.role === 'user' ? '我' : '✦ Agent'}</div>
                {item.role === 'assistant' && item.steps?.length ? (
                  <div className="agent-steps">
                    {item.steps.map((step) => (
                      <div key={step.key} className="agent-step">
                        <button type="button" className="agent-step-head" onClick={() => setOpenStep((prev) => (prev === `${index}-${step.key}` ? null : `${index}-${step.key}`))}>
                          <span>{step.status === 'done' ? '✓' : step.status === 'bad' ? '×' : '→'}</span>
                          {step.label}
                        </button>
                        {openStep === `${index}-${step.key}` && step.detail?.length ? (
                          <div className="agent-step-body">
                            {step.detail.map((block) => (
                              <div key={block.title}>
                                <em>{block.title}</em>
                                {block.lines.map((line) => <p key={line}>{line}</p>)}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {item.text ? (
                  item.role === 'assistant'
                    ? <div className="agent-wb-bubble"><SimpleMarkdown text={item.text} /></div>
                    : <div className="agent-wb-bubble">{item.text}</div>
                ) : null}
                {item.failed ? (
                  <div className="agent-card-actions">
                    <button type="button" onClick={() => {
                      const lastUser = [...turns].reverse().find((row) => row.role === 'user');
                      if (lastUser?.text) void runAsk(lastUser.text);
                    }}>重试</button>
                  </div>
                ) : null}
                {item.cards?.map((card) => (
                  <div key={card.title} className="agent-card">
                    <div className="agent-card-kicker">{card.title}</div>
                    {card.stats.length ? (
                      <div className="agent-card-stats">
                        {card.stats.map((stat) => (
                          <span key={stat.label}><b>{stat.value}</b>{stat.label}</span>
                        ))}
                      </div>
                    ) : null}
                    {card.buttons.length ? (
                      <div className="agent-card-actions">
                        {card.buttons.map((btn) => (
                          <button key={btn.path + btn.label} type="button" onClick={() => navigate(btn.path)}>{btn.label}</button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            );
          })}

          {loading ? (
            <div className="agent-wb-row is-assistant">
              <div className="agent-wb-who">✦ Agent</div>
              <div className="agent-steps">
                <div className="agent-step">
                  <div className="agent-step-head">
                    <span className="is-run">→</span>
                    {status === 'thinking' ? '正在分析…' : '正在执行…'}
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {picker ? (
            <div className="agent-picker">
              <div className="agent-picker-title">{picker.title}</div>
              {picker.items.map((item) => (
                <button key={item.chip.id} type="button" onClick={() => addChip(item.chip)}>{item.label}</button>
              ))}
              <button type="button" className="is-ghost" onClick={() => setPicker(null)}>关闭</button>
            </div>
          ) : null}
        </div>

        <footer className="agent-wb-foot">
          {chips.length ? (
            <div className="agent-chips">
              {chips.map((chip) => (
                <button key={chip.id} type="button" className="agent-chip" onClick={() => {
                  if (chip.id === 'ctx-project') return;
                  setChips((prev) => prev.filter((item) => item.id !== chip.id));
                }}>
                  {chip.kind === 'file' ? '📎' : '@'}{chip.label} ×
                </button>
              ))}
            </div>
          ) : null}

          <div className="agent-wb-tools">
            <Dropdown
              menu={{
                items: [
                  { key: 'upload', label: '上传文件', onClick: () => fileRef.current?.click() },
                  { key: 'asset', label: '添加测试资产', onClick: () => void openAssetPicker() },
                  { key: 'api', label: '添加 API 文档', onClick: () => void openIndexPicker('api', '选择接口') },
                  { key: 'result', label: '添加测试结果', onClick: () => void openResultPicker() },
                  { key: 'shot', label: '添加截图', onClick: () => imageRef.current?.click() },
                ],
              }}
            >
              <button type="button">＋</button>
            </Dropdown>
            <Dropdown
              menu={{
                items: CONTEXT_OPTIONS.map((item) => ({
                  key: item.key,
                  label: item.label,
                  onClick: () => addChip({
                    id: `ctx-${item.key}`,
                    kind: 'context',
                    label: item.label,
                    workspace: item.workspace,
                  }),
                })),
              }}
            >
              <button type="button">@ 上下文</button>
            </Dropdown>
            <Dropdown
              menu={{
                items: SKILLS.map((item) => ({
                  key: item.key,
                  label: item.label,
                  onClick: () => {
                    if (mode === 'chat' && item.write) {
                      message.info('Chat 模式不会执行写入。已放入输入框，可改成 Agent 后再发送。');
                    }
                    setQuestion((prev) => prev.trim() || item.draft);
                  },
                })),
              }}
            >
              <button type="button">Skill</button>
            </Dropdown>
          </div>

          <div className="agent-wb-input">
            <Input.TextArea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="输入你想完成的测试任务…"
              autoSize={{ minRows: 2, maxRows: 6 }}
              disabled={!projectId}
              onPressEnter={(e) => {
                if (e.shiftKey) return;
                e.preventDefault();
                if (!loading && question.trim()) void submit(question);
              }}
            />
            {loading ? (
              <Button onClick={stop}>■ 停止</Button>
            ) : (
              <Button type="primary" disabled={!question.trim() || !projectId} onClick={() => void submit(question)}>↑</Button>
            )}
          </div>

          <div className="agent-wb-meta">
            <Dropdown
              menu={{
                items: [
                  { key: 'agent', label: 'Agent', onClick: () => { setMode('agent'); sessionStorage.setItem(MODE_KEY, 'agent'); } },
                  { key: 'chat', label: 'Chat', onClick: () => { setMode('chat'); sessionStorage.setItem(MODE_KEY, 'chat'); } },
                ],
              }}
            >
              <button type="button">{mode === 'chat' ? 'Chat' : 'Agent'} ▾</button>
            </Dropdown>
            <Dropdown
              menu={{
                items: models.map((item) => ({
                  key: item,
                  label: item,
                  onClick: () => { setModel(item); sessionStorage.setItem(MODEL_KEY, item); },
                })),
              }}
            >
              <button type="button">{model} ▾</button>
            </Dropdown>
          </div>
        </footer>

        <input ref={fileRef} type="file" hidden multiple onChange={(e) => { attachFiles(e.target.files, 'file'); e.target.value = ''; }} />
        <input ref={imageRef} type="file" hidden accept="image/*" onChange={(e) => { attachFiles(e.target.files, 'file'); e.target.value = ''; }} />
      </aside>
    </div>
  );
}
