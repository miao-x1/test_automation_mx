import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Empty, Input, Progress, Tag, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import {
  PROJECT_DESIGN_CHANGED,
  PROJECT_REQUIREMENT_CHANGED,
  apiError,
  confirmTestDesign,
  fetchRequirementAnalysis,
  fetchTestDesign,
  generateTestDesign,
  openProjectAgent,
  saveTestDesign,
  type RequirementDocument,
  type TestDesignDocument,
} from '@/services/projectExplorer';
import '../understand/understand.css';
import './shell.css';
import './designStudio.css';

const NAV = [
  { key: 'overview', label: '概览' },
  { key: 'scope', label: '测试范围' },
  { key: 'objects', label: '测试对象' },
  { key: 'dimensions', label: '测试维度' },
  { key: 'methods', label: '测试方法' },
  { key: 'scenarios', label: '测试场景' },
  { key: 'flows', label: '业务流程' },
  { key: 'states', label: '状态流转' },
  { key: 'roles', label: '角色权限' },
  { key: 'data', label: '测试数据' },
  { key: 'priority', label: '优先级' },
  { key: 'coverage', label: '覆盖分析' },
  { key: 'risks', label: '风险与缺口' },
  { key: 'plan', label: '设计方案' },
] as const;

const DIM: Record<string, string> = {
  normal: '正常',
  exception: '异常',
  boundary: '边界',
  rule: '业务规则',
  permission: '权限',
  state: '状态',
  data: '数据',
  interaction: '交互',
  dependency: '依赖异常',
  repeat: '重复操作',
  concurrency: '并发',
  regression: '回归影响',
};

type Section = (typeof NAV)[number]['key'];
type Selected = { kind: string; id: string; payload?: any };

function sectionOf(value?: string): Section {
  const hit = NAV.find((item) => item.key === value);
  if (hit) return hit.key;
  if (value === 'cases') return 'objects';
  return 'overview';
}

function Chip({ children }: { children: string }) {
  return <Tag>{children}</Tag>;
}

export default function DesignStudioPage() {
  const navigate = useNavigate();
  const params = useParams();
  const section = sectionOf(params.section);
  const [doc, setDoc] = useState<TestDesignDocument | null>(null);
  const [requirement, setRequirement] = useState<RequirementDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Selected | null>(null);

  const hasResult = Boolean(doc && doc.status !== 'empty' && (doc.objects?.length || doc.scenarios?.length));
  const confirmed = doc?.status === 'confirmed';
  const counts = doc?.counts || {};
  const brief = doc?.requirement_brief;
  const plan = doc?.plan;
  const hasRequirement = Boolean(brief?.available || (requirement && requirement.status !== 'empty' && (requirement.requirements?.length || requirement.functions?.length)));
  const reqName = brief?.name || plan?.name || '当前需求';

  const load = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const [design, analysis] = await Promise.all([
      fetchTestDesign(projectId).catch(() => null),
      fetchRequirementAnalysis(projectId).catch(() => null),
    ]);
    setDoc(design);
    setRequirement(analysis);
    setNotes(design?.user_notes || '');
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载测试设计失败')));
    const reload = () => { void load().catch(() => undefined); };
    window.addEventListener(PROJECT_CHANGED, reload);
    window.addEventListener(PROJECT_REQUIREMENT_CHANGED, reload);
    window.addEventListener(PROJECT_DESIGN_CHANGED, reload);
    return () => {
      window.removeEventListener(PROJECT_CHANGED, reload);
      window.removeEventListener(PROJECT_REQUIREMENT_CHANGED, reload);
      window.removeEventListener(PROJECT_DESIGN_CHANGED, reload);
    };
  }, []);

  const go = (key: Section) => navigate(key === 'overview' ? '/design' : `/design/${key}`);

  const pick = (kind: string, id: string, payload?: any) => setSelected({ kind, id, payload });

  const design = async (withAnswers = false) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    if (!hasRequirement) {
      message.info('请先完成需求分析。测试设计不会重新理解需求。');
      return;
    }
    setLoading(true);
    try {
      const packed = withAnswers
        ? Object.entries(answers).filter(([, value]) => value.trim()).map(([id, answer]) => ({ id, answer }))
        : undefined;
      const data = await generateTestDesign(projectId, packed);
      setDoc(data);
      window.dispatchEvent(new CustomEvent(PROJECT_DESIGN_CHANGED));
      message.success(data.interaction?.summary || '测试设计已完成');
    } catch (err: any) {
      message.error(apiError(err, '测试设计失败'));
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !hasResult) return;
    setSaving(true);
    try {
      const data = await saveTestDesign(projectId, { user_notes: notes });
      setDoc(data);
      message.success('已保存修改');
    } catch (err: any) {
      message.error(apiError(err, '保存失败'));
    } finally {
      setSaving(false);
    }
  };

  const confirm = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setSaving(true);
    try {
      if (hasResult) await saveTestDesign(projectId, { user_notes: notes });
      const data = await confirmTestDesign(projectId);
      setDoc(data);
      window.dispatchEvent(new CustomEvent(PROJECT_DESIGN_CHANGED));
      message.success('测试设计已确认，可作为测试用例输入');
    } catch (err: any) {
      message.error(apiError(err, '确认失败'));
    } finally {
      setSaving(false);
    }
  };

  const goCases = () => {
    navigate('/test-tasks');
  };

  const grouped = useMemo(() => {
    const map = new Map<string, any[]>();
    (doc?.scenarios || []).forEach((item) => {
      const key = item.td_id || '未关联';
      map.set(key, [...(map.get(key) || []), item]);
    });
    return map;
  }, [doc]);

  const dimensions = useMemo(() => {
    const keys = new Set<string>();
    (doc?.objects || []).forEach((item) => (item.applicable || []).forEach((dim: string) => keys.add(dim)));
    (doc?.scenarios || []).forEach((item) => item.dimension && keys.add(item.dimension));
    return [...keys];
  }, [doc]);

  const navCount = (key: Section) => {
    if (key === 'objects') return counts.objects || 0;
    if (key === 'scenarios') return counts.scenarios || 0;
    if (key === 'methods') return counts.methods || 0;
    if (key === 'data') return counts.data || 0;
    if (key === 'flows') return doc?.flows?.length || 0;
    if (key === 'states') return doc?.states?.length || 0;
    if (key === 'roles') return doc?.permissions?.length || 0;
    if (key === 'coverage') return doc?.coverage?.length || 0;
    if (key === 'risks') return (doc?.risks?.length || 0) + (doc?.gaps?.length || 0);
    return 0;
  };

  const sourcesOf = (ids?: string[]) => (ids || []).map((id) => doc?.source_index?.[id] || { id, title: id, text: '', kind: 'requirement' });

  const questions = doc?.interaction?.questions || [];
  const currentSources = sourcesOf(selected?.payload?.req_ids || selected?.payload?.fn_ids || (selected?.kind === 'req' ? [selected.id] : []));

  return (
    <div className="tdw">
      <div className="tdw-head">
        <div>
          <h1>测试设计 · {hasRequirement ? reqName : '未承接需求'}</h1>
          <p>{plan?.headline || '读取已完成的需求分析，设计应该怎么测。本阶段不生成完整测试用例。'}</p>
        </div>
        <div className="tdw-head-actions">
          <Button onClick={() => navigate('/understand/requirements')}>查看需求分析</Button>
          <Button onClick={() => openProjectAgent('根据已有需求分析做测试设计')}>✦ Agent 设计</Button>
          <Button type="primary" loading={loading} onClick={() => void design()} disabled={!hasRequirement}>生成设计</Button>
          <Button onClick={() => void confirm()} loading={saving} disabled={!hasResult || confirmed}>确认设计</Button>
          <Button onClick={() => goCases()}>进入测试用例</Button>
        </div>
      </div>

      <div className="tdw-body">
        <nav className="tdw-nav">
          <div className="tdw-nav-label">设计导航</div>
          {NAV.map((item) => (
            <button key={item.key} type="button" className={section === item.key ? 'is-on' : ''} onClick={() => go(item.key)}>
              <span>{item.label}</span>
              {navCount(item.key) ? <em>{navCount(item.key)}</em> : null}
            </button>
          ))}
        </nav>

        <main className="tdw-main">
          {!hasRequirement ? (
            <Empty description="还没有需求分析结果。测试设计必须承接第一阶段，不会重新让你描述需求。">
              <Button type="primary" onClick={() => navigate('/understand/requirements')}>去完成需求分析</Button>
            </Empty>
          ) : null}

          {hasRequirement && section === 'overview' ? (
            <>
              <div className="tdw-banner">
                <span className="tdw-kicker">已自动承接需求分析</span>
                <h2>{plan?.headline}</h2>
                <p>
                  需求 {brief?.requirements?.length || 0} 条 · 功能 {brief?.functions?.length || 0} · 规则 {brief?.rules?.length || 0} ·
                  角色 {brief?.roles?.length || 0} · 状态 {requirement?.status === 'confirmed' || brief?.status === 'confirmed' ? '已确认' : '草稿'}。
                  不需要重新上传或描述需求。
                </p>
                {hasResult ? <Progress percent={doc?.completeness ?? 0} showInfo format={(p) => `设计完成度 ${p}%`} /> : null}
                {doc?.llm_error ? <p className="uw-tone-warn">模型未能完整设计：{doc.llm_error}。下面是基于需求分析的诚实拆解，没有扩大范围。</p> : null}
              </div>
              <div className="tdw-stats">
                <div className="tdw-stat"><b>{plan?.objects || 0}</b><span>测试对象</span></div>
                <div className="tdw-stat"><b>{plan?.scenarios || 0}</b><span>测试场景</span></div>
                <div className="tdw-stat"><b>{plan?.methods?.length || 0}</b><span>测试方法</span></div>
                <div className="tdw-stat"><b>{plan?.data_fields || 0}</b><span>数据要求</span></div>
              </div>
              {hasResult ? (
                <div className="tdw-cards">
                  <div className="tdw-card">
                    <b>准备从这些方面测试</b>
                    <p>{(plan?.aspects || []).join('、') || '尚未形成维度'}</p>
                  </div>
                  <div className="tdw-card">
                    <b>采用的测试方法</b>
                    <p>{(plan?.methods || []).join('、') || '尚未说明方法'}</p>
                  </div>
                  <div className="tdw-card">
                    <b>边界 / 角色 / 状态 / 数据</b>
                    <p>
                      边界 {(plan?.boundaries || []).length} · 角色 {(plan?.roles || []).length} ·
                      状态 {(plan?.states || []).length} · 数据字段 {plan?.data_fields || 0}
                    </p>
                  </div>
                  <div className="tdw-card">
                    <b>优先级</b>
                    <p>P0 {plan?.priorities?.P0 || 0} · P1 {plan?.priorities?.P1 || 0} · P2 {plan?.priorities?.P2 || 0} · P3 {plan?.priorities?.P3 || 0}</p>
                  </div>
                </div>
              ) : (
                <Empty description="需求已读入。点「生成设计」即可，不必再贴一份 PRD。">
                  <Button type="primary" loading={loading} onClick={() => void design()}>基于当前需求生成测试设计</Button>
                </Empty>
              )}
              {questions.length ? (
                <div className="tdw-banner" style={{ marginTop: 12 }}>
                  <h2>关键问题（可跳过）</h2>
                  {questions.map((item) => (
                    <div key={item.id || item.question} className="ra-question">
                      <p>{item.question}</p>
                      <Input.TextArea
                        rows={2}
                        value={answers[item.id || item.question] || ''}
                        onChange={(e) => setAnswers((prev) => ({ ...prev, [item.id || item.question]: e.target.value }))}
                        placeholder="补充后可重新设计；也可以跳过"
                      />
                    </div>
                  ))}
                  <Button onClick={() => void design(true)} loading={loading}>根据补充重新设计</Button>
                </div>
              ) : null}
            </>
          ) : null}

          {hasResult && section === 'scope' ? (
            <div className="tdw-cards">
              {(['core', 'related', 'regression', 'out_of_scope'] as const).map((key) => (
                <div key={key}>
                  <h3>{{ core: '核心测试范围', related: '关联影响', regression: '建议回归', out_of_scope: '明确不在范围' }[key]}</h3>
                  {(doc?.scope?.[key] || []).length ? (doc?.scope?.[key] || []).map((item, index) => (
                    <button key={`${key}-${index}`} type="button" className={`tdw-card ${selected?.id === `${key}-${index}` ? 'is-on' : ''}`} onClick={() => pick('scope', `${key}-${index}`, item)}>
                      <b>{item.item}</b>
                      <p>{item.reason || '—'}</p>
                      <div className="tdw-card-meta">{(item.req_ids || []).map((id) => <Chip key={id}>{id}</Chip>)}</div>
                    </button>
                  )) : <p className="uw-tone-empty">无</p>}
                </div>
              ))}
            </div>
          ) : null}

          {hasResult && section === 'objects' ? (
            <div className="tdw-cards">
              {(doc?.objects || []).map((item) => (
                <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('object', item.id, item)}>
                  <b>{item.id} {item.module ? `${item.module} / ` : ''}{item.name}</b>
                  <p>适用：{(item.applicable || []).map((d: string) => DIM[d] || d).join('、') || '正常'}</p>
                  <div className="tdw-card-meta">
                    <Chip>{item.priority}</Chip>
                    {(item.req_ids || []).map((id: string) => <Chip key={id}>{id}</Chip>)}
                    <Chip>{(grouped.get(item.id) || []).length} 个场景</Chip>
                  </div>
                </button>
              ))}
            </div>
          ) : null}

          {hasResult && section === 'dimensions' ? (
            <div className="tdw-cards">
              {dimensions.length ? dimensions.map((dim) => {
                const used = (doc?.objects || []).filter((item) => (item.applicable || []).includes(dim));
                const skipped = (doc?.objects || []).filter((item) => (item.not_applicable || []).some((row: any) => row.dimension === dim));
                const scenes = (doc?.scenarios || []).filter((item) => item.dimension === dim);
                return (
                  <div key={dim} className="tdw-card">
                    <b>{DIM[dim] || dim}</b>
                    <p>对象 {used.length} · 场景 {scenes.length} · 明确不适用 {skipped.length}</p>
                    {skipped.length ? <p>不适用：{skipped.map((item) => `${item.id}（${(item.not_applicable || []).find((row: any) => row.dimension === dim)?.reason || '需求未涉及'}）`).join('；')}</p> : null}
                  </div>
                );
              }) : <Empty description="还没有测试维度。" />}
            </div>
          ) : null}

          {hasResult && section === 'methods' ? (
            (doc?.methods || []).length ? (
              <div className="tdw-cards">
                {(doc?.methods || []).map((item) => (
                  <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('method', item.id, item)}>
                    <b>{item.id} {item.name}</b>
                    <p>为什么用：{item.why || '未说明'}</p>
                    <div className="tdw-card-meta">{(item.applied_to || []).map((id: string) => <Chip key={id}>{id}</Chip>)}</div>
                  </button>
                ))}
              </div>
            ) : <Empty description="没有单独说明测试方法。不会为了展示而堆砌方法。" />
          ) : null}

          {hasResult && section === 'scenarios' ? (
            (doc?.objects || []).map((td) => (
              <div key={td.id} style={{ marginBottom: 16 }}>
                <h3>{td.id} {td.name}</h3>
                <div className="tdw-cards">
                  {(grouped.get(td.id) || []).map((item) => (
                    <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('scenario', item.id, item)}>
                      <b>{item.id} {item.name}</b>
                      <p>{item.expected || '需求未定义，待确认'}</p>
                      <div className="tdw-card-meta">
                        <Chip>{DIM[item.dimension] || item.dimension}</Chip>
                        <Chip>{item.priority}</Chip>
                        {(item.req_ids || []).map((id: string) => <Chip key={id}>{id}</Chip>)}
                      </div>
                    </button>
                  ))}
                  {(grouped.get(td.id) || []).length === 0 ? <p className="uw-tone-empty">这个对象还没有场景。</p> : null}
                </div>
              </div>
            ))
          ) : null}

          {hasResult && section === 'flows' ? (
            (doc?.flows || []).length ? (
              <div className="tdw-cards">
                {(doc?.flows || []).map((item) => (
                  <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('flow', item.id, item)}>
                    <b>{item.id} {item.name}</b>
                    <p>{(item.steps || []).join(' → ') || '需求缺失'}</p>
                  </button>
                ))}
              </div>
            ) : <Empty description="需求分析未给出可测流程，不编造业务流程。" />
          ) : null}

          {hasResult && section === 'states' ? (
            (doc?.states || []).length ? (
              <div className="tdw-cards">
                {(doc?.states || []).map((item) => (
                  <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('state', item.id, item)}>
                    <b>{item.id}</b>
                    <p>合法：{(item.legal || []).map((row: any) => `${row.from} → ${row.to}`).join('；') || '需求缺失'}</p>
                    <p>非法：{(item.illegal || []).map((row: any) => `${row.from} → ${row.to}`).join('；') || '需求缺失'}</p>
                  </button>
                ))}
              </div>
            ) : <Empty description="需求分析未定义状态机，不编造状态流转。" />
          ) : null}

          {hasResult && section === 'roles' ? (
            (doc?.permissions || []).length ? (
              <div className="tdw-cards">
                {(doc?.permissions || []).map((item) => (
                  <button key={item.role} type="button" className={`tdw-card ${selected?.id === item.role ? 'is-on' : ''}`} onClick={() => pick('role', item.role, item)}>
                    <b>{item.role}</b>
                    <p>查看 {item.view ? '✓' : '×'} · 新增 {item.create ? '✓' : '×'} · 修改 {item.update ? '✓' : '×'} · 删除 {item.delete ? '✓' : '×'}</p>
                    <p>数据范围：{item.data_scope || '需求缺失'}</p>
                  </button>
                ))}
              </div>
            ) : <Empty description="需求分析未说明角色权限。" />
          ) : null}

          {hasResult && section === 'data' ? (
            (doc?.data || []).length ? (
              <div className="tdw-cards">
                {(doc?.data || []).map((item) => (
                  <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('data', item.id, item)}>
                    <b>{item.id} {item.object}.{item.field}</b>
                    <p>正常 {item.normal} · 边界 {item.boundary} · 空 {item.empty}</p>
                    <div className="tdw-card-meta">{(item.req_ids || []).map((id: string) => <Chip key={id}>{id}</Chip>)}</div>
                  </button>
                ))}
              </div>
            ) : <Empty description="需求未给出可设计的测试数据，不会编造具体值。" />
          ) : null}

          {hasResult && section === 'priority' ? (
            <div className="tdw-cards">
              {(doc?.objects || []).map((item) => {
                const reason = (doc?.priorities || []).find((row) => row.td_id === item.id);
                return (
                  <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('object', item.id, item)}>
                    <b>{item.priority} {item.id} {item.name}</b>
                    <p>{reason?.reason || '按对象优先级排列，未另写理由'}</p>
                  </button>
                );
              })}
            </div>
          ) : null}

          {hasResult && section === 'coverage' ? (
            <div className="tdw-cards">
              {(doc?.coverage || []).map((item) => (
                <button key={item.req_id} type="button" className={`tdw-card ${selected?.id === item.req_id ? 'is-on' : ''}`} onClick={() => pick('coverage', item.req_id, { ...item, req_ids: [item.req_id] })}>
                  <b>{item.req_id} {item.covered ? '已覆盖' : '未覆盖'}</b>
                  <p>对象 {(item.td_ids || []).join('、') || '无'} · 场景 {(item.ts_ids || []).join('、') || '无'}</p>
                  {item.gap ? <p>{item.gap}</p> : null}
                </button>
              ))}
            </div>
          ) : null}

          {hasResult && section === 'risks' ? (
            <div className="tdw-cards">
              {(doc?.risks || []).map((item) => (
                <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('risk', item.id, item)}>
                  <b>{item.point}</b>
                  <p>关注：{item.focus || '—'}</p>
                  <div className="tdw-card-meta"><Chip>{item.level}</Chip></div>
                </button>
              ))}
              {(doc?.gaps || []).map((item) => (
                <button key={item.id} type="button" className={`tdw-card ${selected?.id === item.id ? 'is-on' : ''}`} onClick={() => pick('gap', item.id, item)}>
                  <b>{item.problem}</b>
                  <p>需要确认：{item.need_confirm || '—'}</p>
                </button>
              ))}
              {!(doc?.risks || []).length && !(doc?.gaps || []).length ? <Empty description="没有单独的风险或缺口。" /> : null}
            </div>
          ) : null}

          {hasResult && section === 'plan' ? (
            <div className="tdw-banner">
              <span className="tdw-kicker">下一阶段输入</span>
              <h2>测试设计方案</h2>
              <p>{plan?.next}</p>
              <ul className="tdw-list">
                <li>对象 {(doc?.case_input?.objects || []).length} 个，均可追溯 REQ / FN</li>
                <li>场景 {(doc?.case_input?.scenarios || []).length} 个，含维度、数据、预期</li>
                <li>数据要求 {(doc?.case_input?.data || []).length} 条</li>
                <li>待确认 {(doc?.case_input?.gaps || []).length} 项，不会被写成确定规则</li>
              </ul>
              <Input.TextArea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="补充范围裁剪或确认备注" disabled={confirmed} />
              <div className="ra-actions">
                <Button onClick={() => void save()} loading={saving} disabled={confirmed}>保存修改</Button>
                <Button type="primary" onClick={() => void confirm()} loading={saving} disabled={confirmed}>确认测试设计</Button>
                <Button onClick={() => goCases()}>进入测试用例</Button>
                {confirmed ? <span className="uw-tone-ok">已确认，可作为测试用例的输入来源</span> : <span className="uw-tone-empty">未确认也可以直接去测试用例工作，本页结果只是输入之一</span>}
              </div>
            </div>
          ) : null}

          {hasRequirement && !hasResult && section !== 'overview' ? (
            <Empty description="已承接需求分析，但还没有测试设计。">
              <Button type="primary" loading={loading} onClick={() => void design()}>生成设计</Button>
            </Empty>
          ) : null}
        </main>

        <aside className="tdw-side">
          <h3>设计详情</h3>
          {!selected ? (
            <p className="uw-tone-empty">点击任意设计项，查看细节和来源需求。</p>
          ) : (
            <SelectedDetail selected={selected} dim={DIM} />
          )}
          <h4>来源需求</h4>
          {currentSources.length ? currentSources.map((item) => (
            <div key={item.id} className="tdw-src">
              <b>{item.id}</b>
              <span>{item.title && item.title !== item.id ? `${item.title}：` : ''}{item.text || '需求分析中未给出更多原文'}</span>
            </div>
          )) : (
            <p className="uw-tone-empty">{selected ? '这项没有挂上来源需求。' : '选择设计项后显示 REQ / FN / BR。'}</p>
          )}
          {hasRequirement ? (
            <>
              <h4>已承接的需求条目</h4>
              {(brief?.requirements || []).slice(0, 8).map((item) => (
                <button key={item.id} type="button" className="tdw-src" style={{ width: '100%', background: 'none', border: 0, cursor: 'pointer' }} onClick={() => pick('req', item.id, { req_ids: [item.id], name: item.id, text: item.text })}>
                  <b>{item.id}</b>
                  <span>{item.text}</span>
                </button>
              ))}
            </>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function SelectedDetail({ selected, dim }: { selected: Selected; dim: Record<string, string> }) {
  const item = selected.payload || {};
  if (selected.kind === 'req') {
    return (
      <>
        <p className="tdw-kicker">来源需求</p>
        <h3>{selected.id}</h3>
        <p>{item.text}</p>
      </>
    );
  }
  if (selected.kind === 'object') {
    return (
      <>
        <p className="tdw-kicker">测试对象</p>
        <h3>{item.id} {item.name}</h3>
        <p>模块 {item.module || '未分组'} · 优先级 {item.priority}</p>
        <p>适用维度：{(item.applicable || []).map((d: string) => dim[d] || d).join('、')}</p>
        {(item.not_applicable || []).length ? <p>不适用：{(item.not_applicable || []).map((row: any) => `${dim[row.dimension] || row.dimension}（${row.reason}）`).join('；')}</p> : null}
      </>
    );
  }
  if (selected.kind === 'scenario') {
    return (
      <>
        <p className="tdw-kicker">测试场景</p>
        <h3>{item.id} {item.name}</h3>
        <p>对象 {item.td_id} · {dim[item.dimension] || item.dimension} · {item.method || '未指定方法'}</p>
        <p>前置：{item.precondition || '需求缺失'}</p>
        <p>步骤：{(item.steps || []).join(' → ') || '需求缺失'}</p>
        <p>数据：{item.data || '需求缺失'}</p>
        <p>预期：{item.expected || '需求未定义，待确认'}</p>
      </>
    );
  }
  if (selected.kind === 'data') {
    return (
      <>
        <p className="tdw-kicker">测试数据要求</p>
        <h3>{item.object}.{item.field}</h3>
        {['normal', 'invalid', 'boundary', 'empty', 'duplicate', 'illegal', 'min', 'max', 'special'].map((key) => (
          <p key={key}>{key}：{item[key] || '需求缺失'}</p>
        ))}
      </>
    );
  }
  return (
    <>
      <p className="tdw-kicker">设计项</p>
      <h3>{item.id || item.role || item.item || selected.id}</h3>
      <p>{item.why || item.reason || item.problem || item.gap || item.focus || item.name || '已选中该项。'}</p>
    </>
  );
}
