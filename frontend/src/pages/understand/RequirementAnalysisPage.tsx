import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Empty, Input, Progress, Tag, Upload, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import {
  PROJECT_REQUIREMENT_CHANGED,
  analyzeRequirementText,
  analyzeRequirementUpload,
  apiError,
  confirmRequirementAnalysis,
  fetchRequirementAnalysis,
  openProjectAgent,
  saveRequirementAnalysis,
  type EvidenceField,
  type RequirementDocument,
} from '@/services/projectExplorer';
import './understand.css';
import '../shell/shell.css';

const SECTIONS = [
  { key: 'overview', label: '需求概览' },
  { key: 'functions', label: '功能分析' },
  { key: 'rules', label: '业务规则' },
  { key: 'roles', label: '角色权限' },
  { key: 'flows', label: '业务流程' },
  { key: 'data', label: '数据分析' },
  { key: 'exceptions', label: '异常与边界' },
  { key: 'gaps', label: '需求缺失' },
  { key: 'risks', label: '风险分析' },
] as const;

const EVIDENCE_LABEL: Record<string, string> = {
  explicit: '原文明确',
  inferred: '合理推断',
  missing: '需求缺失/歧义',
};

const EVIDENCE_TONE: Record<string, string> = {
  explicit: 'uw-tone-ok',
  inferred: 'uw-tone-warn',
  missing: 'uw-tone-bad',
};

function kindOf(value?: EvidenceField | string) {
  if (typeof value === 'object' && value?.evidence_kind) return value.evidence_kind;
  return '';
}

function textOf(value?: EvidenceField | string) {
  if (typeof value === 'object') return value?.text || '';
  return value || '';
}

function Evidence({ value, sources }: { value?: EvidenceField | string; sources?: string[] }) {
  const kind = kindOf(value);
  const refs = sources || (typeof value === 'object' ? value?.sources : undefined) || [];
  if (!kind && !refs.length) return null;
  return (
    <span className="ra-evidence">
      {kind ? <span className={EVIDENCE_TONE[kind] || 'uw-tone-empty'}>{EVIDENCE_LABEL[kind] || kind}</span> : null}
      {refs.length ? <span className="uw-tone-empty">{refs.join(' · ')}</span> : null}
    </span>
  );
}

function Field({ label, value }: { label: string; value?: EvidenceField | string }) {
  const text = textOf(value) || '需求缺失';
  return (
    <div className="ra-field">
      <dt>{label}</dt>
      <dd>
        <p>{text}</p>
        <Evidence value={value} />
      </dd>
    </div>
  );
}

export default function RequirementAnalysisPage() {
  const navigate = useNavigate();
  const [doc, setDoc] = useState<RequirementDocument | null>(null);
  const [source, setSource] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [section, setSection] = useState<(typeof SECTIONS)[number]['key']>('overview');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState('');
  const [overview, setOverview] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const hasResult = Boolean(doc && doc.status !== 'empty' && (doc.requirements?.length || doc.functions?.length));
  const confirmed = doc?.status === 'confirmed';
  const counts = doc?.counts || {};

  const load = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const data = await fetchRequirementAnalysis(projectId);
    setDoc(data);
    if (data.source_text) setSource(data.source_text);
    setNotes(data.user_notes || '');
    const next: Record<string, string> = {};
    Object.entries(data.overview || {}).forEach(([key, value]) => {
      next[key] = textOf(value);
    });
    setOverview(next);
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载需求分析失败')));
    const reload = () => { void load().catch(() => undefined); };
    window.addEventListener(PROJECT_CHANGED, reload);
    window.addEventListener(PROJECT_REQUIREMENT_CHANGED, reload);
    return () => {
      window.removeEventListener(PROJECT_CHANGED, reload);
      window.removeEventListener(PROJECT_REQUIREMENT_CHANGED, reload);
    };
  }, []);

  const analyze = async (withAnswers = false) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    if (!source.trim() && !files.length && !doc?.source_text) {
      message.info('请先粘贴需求材料或上传文档');
      return;
    }
    setLoading(true);
    try {
      const packedAnswers = withAnswers
        ? Object.entries(answers).filter(([, value]) => value.trim()).map(([id, answer]) => ({ id, answer }))
        : undefined;
      const data = files.length
        ? await analyzeRequirementUpload(projectId, source, files)
        : await analyzeRequirementText(projectId, source || doc?.source_text || '', packedAnswers);
      setDoc(data);
      setFiles([]);
      if (data.source_text) setSource(data.source_text);
      const next: Record<string, string> = {};
      Object.entries(data.overview || {}).forEach(([key, value]) => {
        next[key] = textOf(value);
      });
      setOverview(next);
      window.dispatchEvent(new CustomEvent(PROJECT_REQUIREMENT_CHANGED));
      message.success(data.interaction?.summary || '需求分析已完成');
    } catch (err: any) {
      message.error(apiError(err, '需求分析失败'));
    } finally {
      setLoading(false);
    }
  };

  const save = async (patch?: Partial<RequirementDocument>) => {
    const projectId = getCurrentProjectId();
    if (!projectId || !hasResult) return;
    setSaving(true);
    try {
      const nextOverview = { ...(doc?.overview || {}) };
      Object.entries(overview).forEach(([key, text]) => {
        nextOverview[key] = { ...(nextOverview[key] || {}), text };
      });
      const data = await saveRequirementAnalysis(projectId, {
        overview: nextOverview,
        user_notes: notes,
        ...patch,
      });
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
      await save();
      const data = await confirmRequirementAnalysis(projectId);
      setDoc(data);
      window.dispatchEvent(new CustomEvent(PROJECT_REQUIREMENT_CHANGED));
      message.success('需求分析已确认，可作为测试设计输入');
    } catch (err: any) {
      message.error(apiError(err, '确认失败'));
    } finally {
      setSaving(false);
    }
  };

  const modules = useMemo(() => {
    const map = new Map<string, any[]>();
    (doc?.functions || []).forEach((item) => {
      const key = item.module || '未分组';
      map.set(key, [...(map.get(key) || []), item]);
    });
    return [...map.entries()];
  }, [doc]);

  const questions = doc?.interaction?.questions || [];

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>需求分析</h1>
          <p>把 PRD、需求文档、原型说明、接口文档和用户描述，分析成可测试、可追踪的结果。本阶段不生成测试用例。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => openProjectAgent('分析当前需求材料')}>✦ Agent 分析</Button>
          <Button type="primary" loading={loading} onClick={() => void analyze()}>开始分析</Button>
        </div>
      </div>

      <div className="ra-source uw-panel">
        <div className="ra-source-head">
          <h3>需求材料</h3>
          <Upload
            multiple
            showUploadList={false}
            beforeUpload={(file) => {
              setFiles((prev) => [...prev, file]);
              return false;
            }}
          >
            <Button>上传文档</Button>
          </Upload>
        </div>
        <Input.TextArea
          value={source}
          onChange={(e) => setSource(e.target.value)}
          rows={8}
          placeholder="粘贴 PRD、需求说明、接口约定或用户描述。信息足够时会直接分析；只有影响结论的缺口才会提问。"
        />
        {files.length ? <p className="uw-tone-empty">待上传：{files.map((item) => item.name).join('、')}</p> : null}
        {doc?.source_files?.length ? <p className="uw-tone-empty">已解析文件：{doc.source_files.map((item) => item.name).join('、')}</p> : null}
      </div>

      {hasResult ? (
        <>
          <div className="ra-score">
            <div>
              <b>需求分析完成度：{doc?.completeness ?? 0}%</b>
              <Progress percent={doc?.completeness ?? 0} showInfo={false} />
              <p>{doc?.interaction?.summary}</p>
              {doc?.llm_error ? <p className="uw-tone-warn">模型未能完整分析：{doc.llm_error}。下面是基于原文的诚实拆解，没有编造业务规则。</p> : null}
            </div>
            <div className="uw-stats ra-stats">
              <div className="uw-stat"><b>{counts.requirements ?? 0}</b><span>已识别需求</span></div>
              <div className="uw-stat"><b>{counts.functions ?? 0}</b><span>已识别功能</span></div>
              <div className="uw-stat"><b>{counts.rules ?? 0}</b><span>已识别业务规则</span></div>
              <div className="uw-stat"><b>{counts.open_questions ?? 0}</b><span>待确认问题</span></div>
              <div className="uw-stat"><b>{counts.high_risks ?? 0}</b><span>高风险项</span></div>
            </div>
          </div>

          {questions.length ? (
            <div className="uw-panel">
              <h3>关键问题（可跳过）</h3>
              {questions.map((item) => (
                <div key={item.id || item.question} className="ra-question">
                  <p>{item.question}</p>
                  <Input.TextArea
                    rows={2}
                    value={answers[item.id || item.question] || ''}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [item.id || item.question]: e.target.value }))}
                    placeholder="补充后可重新分析；也可以跳过"
                  />
                </div>
              ))}
              <Button onClick={() => void analyze(true)} loading={loading}>根据补充重新分析</Button>
            </div>
          ) : null}

          <div className="sub-tabs">
            {SECTIONS.map((item) => (
              <button key={item.key} type="button" className={section === item.key ? 'is-on' : ''} onClick={() => setSection(item.key)}>
                {item.label}
              </button>
            ))}
          </div>

          {section === 'overview' ? (
            <div className="uw-panel ra-overview">
              <Field label="需求名称" value={doc?.overview?.name} />
              <Field label="需求目标" value={doc?.overview?.goal} />
              <Field label="业务背景" value={doc?.overview?.background} />
              <Field label="目标用户" value={doc?.overview?.users} />
              <Field label="需求范围" value={doc?.overview?.in_scope} />
              <Field label="非范围内容" value={doc?.overview?.out_of_scope} />
              {!confirmed ? (
                <div className="ra-edit">
                  <p>修改概述后保存，不会把推断写成原文。</p>
                  {(['name', 'goal', 'background', 'users', 'in_scope', 'out_of_scope'] as const).map((key) => (
                    <Input
                      key={key}
                      value={overview[key] || ''}
                      onChange={(e) => setOverview((prev) => ({ ...prev, [key]: e.target.value }))}
                      placeholder={{
                        name: '需求名称',
                        goal: '需求目标',
                        background: '业务背景',
                        users: '目标用户',
                        in_scope: '需求范围',
                        out_of_scope: '非范围内容',
                      }[key]}
                    />
                  ))}
                </div>
              ) : null}
              <div className="ra-reqs">
                <h3>原始需求条目</h3>
                {(doc?.requirements || []).map((item) => (
                  <div key={item.id} className="ra-req">
                    <b>{item.id}</b>
                    <span>{item.text}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {section === 'functions' ? (
            modules.length ? modules.map(([module, items]) => (
              <div key={module} className="uw-panel">
                <h3>{module}</h3>
                {items.map((item) => (
                  <div key={item.id || item.name} className="ra-fn">
                    <div className="ra-fn-head">
                      <b>{item.name || '未命名功能'}</b>
                      <Evidence value={item} sources={item.sources} />
                    </div>
                    <p>{item.description || '需求未给出功能描述'}</p>
                    <dl className="ra-grid">
                      <div><dt>输入</dt><dd>{(item.inputs || []).join('；') || '需求缺失'}</dd></div>
                      <div><dt>前置条件</dt><dd>{(item.preconditions || []).join('；') || '需求缺失'}</dd></div>
                      <div><dt>操作</dt><dd>{(item.operations || []).join('；') || '需求缺失'}</dd></div>
                      <div><dt>系统行为</dt><dd>{(item.system_behavior || []).join('；') || '需求缺失'}</dd></div>
                      <div><dt>输出/结果</dt><dd>{(item.outputs || []).join('；') || '需求缺失'}</dd></div>
                      <div><dt>业务规则</dt><dd>{(item.rules || []).join(' · ') || '需求缺失'}</dd></div>
                    </dl>
                  </div>
                ))}
              </div>
            )) : <Empty description="还没有拆出功能。需求不足时不会编造功能树。" />
          ) : null}

          {section === 'rules' ? (
            (doc?.rules || []).length ? (
              <div className="uw-panel">
                {(doc?.rules || []).map((item) => (
                  <div key={item.id} className="ra-row">
                    <div>
                      <b>{item.id}</b>
                      <Tag>{item.category || '其他'}</Tag>
                      <Evidence value={item} sources={item.sources} />
                    </div>
                    <p>{item.statement}</p>
                    {item.condition ? <p className="uw-tone-empty">条件：{item.condition}</p> : null}
                  </div>
                ))}
              </div>
            ) : <Empty description="原文没有可单独抽出的业务规则，不会编造规则。" />
          ) : null}

          {section === 'roles' ? (
            (doc?.roles || []).length ? (
              <div className="uw-panel">
                {(doc?.roles || []).map((item) => (
                  <div key={item.id || item.name} className="ra-row">
                    <div className="ra-fn-head">
                      <b>{item.name || '未命名角色'}</b>
                      <Evidence value={item} sources={item.sources} />
                    </div>
                    <p>可以做：{(item.can || []).join('；') || '需求缺失'}</p>
                    <p>不能做：{(item.cannot || []).join('；') || '需求缺失'}</p>
                    <p>数据范围：{item.data_scope || '需求缺失'}</p>
                    <p>操作权限：{(item.operations || []).join('；') || '需求缺失'}</p>
                    {item.difference ? <p>与其他角色差异：{item.difference}</p> : null}
                  </div>
                ))}
              </div>
            ) : <Empty description="需求未说明角色与权限。" />
          ) : null}

          {section === 'flows' ? (
            (doc?.flows || []).length ? (
              <div className="uw-panel">
                {(doc?.flows || []).map((item) => (
                  <div key={item.id} className="ra-row">
                    <div className="ra-fn-head">
                      <b>{item.name || item.id}</b>
                      <Tag>{item.kind === 'normal' ? '正常流程' : item.kind === 'exception' ? '异常流程' : item.kind === 'branch' ? '分支流程' : '状态流转'}</Tag>
                      <Evidence value={item} sources={item.sources} />
                    </div>
                    <div className="ra-flow">
                      {(item.steps || []).map((step: string, index: number) => (
                        <span key={`${item.id}-${index}`}>{step}{index < (item.steps || []).length - 1 ? ' → ' : ''}</span>
                      ))}
                    </div>
                    {(item.states || []).length ? <p className="uw-tone-empty">状态：{(item.states || []).join(' → ')}</p> : null}
                  </div>
                ))}
              </div>
            ) : <Empty description="需求未给出可梳理的业务流程。" />
          ) : null}

          {section === 'data' ? (
            (doc?.data || []).length ? (
              <div className="uw-panel">
                <table className="ra-table">
                  <thead>
                    <tr>
                      <th>对象</th><th>字段</th><th>类型</th><th>必填</th><th>长度/范围</th><th>默认值</th><th>唯一</th><th>来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(doc?.data || []).map((item) => (
                      <tr key={item.id}>
                        <td>{item.object || '-'}</td>
                        <td>{item.field || '-'}</td>
                        <td>{item.type || '需求缺失'}</td>
                        <td>{item.required || '需求缺失'}</td>
                        <td>{item.length || '需求缺失'}</td>
                        <td>{item.default || '需求缺失'}</td>
                        <td>{item.unique || '需求缺失'}</td>
                        <td>{(item.sources || []).join(' · ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty description="需求未定义数据对象。未说明的字段不会被补全。" />
          ) : null}

          {section === 'exceptions' ? (
            (doc?.exceptions || []).length ? (
              <div className="uw-panel">
                {(doc?.exceptions || []).map((item) => (
                  <div key={item.id} className="ra-row">
                    <div className="ra-fn-head">
                      <b>{item.scenario}</b>
                      <Tag color={item.defined ? 'success' : 'warning'}>{item.defined ? '需求已定义' : '需求未定义'}</Tag>
                    </div>
                    <p>{item.requirement || '需求未定义'}</p>
                    <Evidence value={item} sources={item.sources} />
                  </div>
                ))}
              </div>
            ) : <Empty description="尚未检查异常与边界。" />
          ) : null}

          {section === 'gaps' ? (
            <div className="uw-panel">
              <h3>完整性缺口</h3>
              {(doc?.gaps || []).length ? (doc?.gaps || []).map((item) => (
                <div key={item.id} className="ra-row">
                  <b>{item.id} {item.problem}</b>
                  <p>影响：{item.impact || '-'}</p>
                  <p>需要产品/研发确认：{item.need_confirm || '-'}</p>
                </div>
              )) : <p>没有识别出完整性缺口。</p>}
              <h3>需求歧义</h3>
              {(doc?.ambiguities || []).length ? (doc?.ambiguities || []).map((item) => (
                <div key={item.id} className="ra-row">
                  <p>原需求：{item.original}</p>
                  <ul>{(item.questions || []).map((q: string) => <li key={q}>{q}</li>)}</ul>
                </div>
              )) : <p>没有识别出会影响测试设计的歧义。</p>}
            </div>
          ) : null}

          {section === 'risks' ? (
            (doc?.risks || []).length ? (
              <div className="uw-panel">
                {(doc?.risks || []).map((item) => (
                  <div key={item.id} className="ra-row">
                    <div className="ra-fn-head">
                      <b>{item.point}</b>
                      <Tag color={item.level === '高' ? 'error' : item.level === '中' ? 'warning' : 'default'}>{item.level || '中'}</Tag>
                    </div>
                    <p>原因：{item.reason || '-'}</p>
                    <p>影响范围：{item.scope || '-'}</p>
                    <p>建议关注：{item.focus || '-'}</p>
                    <Evidence value={item} sources={item.sources} />
                  </div>
                ))}
                {(doc?.test_focus || []).length ? (
                  <div className="ra-row">
                    <h3>后续测试关注点</h3>
                    <ul>{(doc?.test_focus || []).map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                ) : null}
              </div>
            ) : <Empty description="还没有风险项。" />
          ) : null}

          <div className="uw-panel">
            <h3>确认备注</h3>
            <Input.TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="你可以改结论、补充约束，或标记某条为产品已确认。" disabled={confirmed} />
            <div className="ra-actions">
              <Button onClick={() => void save()} loading={saving} disabled={confirmed}>保存修改</Button>
              <Button type="primary" onClick={() => void confirm()} loading={saving} disabled={confirmed}>确认分析结果</Button>
              <Button disabled={!confirmed} onClick={() => navigate('/design')}>进入测试设计</Button>
              {confirmed ? <span className="uw-tone-ok">已确认，可作为测试设计输入</span> : <span className="uw-tone-empty">确认后才会交给测试设计，本阶段不会生成用例</span>}
            </div>
          </div>
        </>
      ) : (
        <div className="uw-panel">
          <Empty description="还没有需求分析结果。先提供材料再分析，信息不够完整也会先给出初步拆解。" />
        </div>
      )}
    </div>
  );
}
