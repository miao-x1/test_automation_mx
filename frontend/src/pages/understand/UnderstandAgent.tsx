import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Empty, Input, message } from 'antd';
import { getCurrentProjectId } from '@/pages/product/projectStore';
import { apiError, askProjectAgent, previewGeneratedCases, PROJECT_MEMORY_CHANGED, type AgentReply } from '@/services/projectExplorer';
import { coverageTone } from './understanding';
import { useUnderstanding } from './UnderstandLayout';

type Job = { key: string; label: string; desc: string; q: string };

function matchFeature(features: any[], question: string) {
  const q = question.toLowerCase();
  return features.find((item) => {
    const name = String(item.name || '').toLowerCase();
    const route = String(item.entry_page || '').toLowerCase();
    return (name && q.includes(name)) || (route && q.includes(route));
  }) || null;
}

function buildJobs(data: any): Job[] {
  const features = data?.features || [];
  const jobs: Job[] = [
    { key: 'overview', label: '理解项目', desc: '核心模块、页面和测试风险', q: '这个项目是做什么的？核心模块和测试风险是什么？' },
  ];
  const primary = features[0];
  if (primary) {
    jobs.push({
      key: `locate-${primary.id}`,
      label: `定位 ${primary.name}`,
      desc: primary.entry_page || primary.module || '入口页面、函数和 API',
      q: `${primary.name}在哪里？入口页面、函数和 API 是什么？`,
    });
    jobs.push({
      key: `chain-${primary.id}`,
      label: `${primary.name} 调用链`,
      desc: (primary.chain || []).map((step: any) => step.layer).filter(Boolean).join(' → ') || '页面到服务',
      q: `${primary.name}的完整调用链是什么？`,
    });
    jobs.push({
      key: `cover-${primary.id}`,
      label: `${primary.name} 测试覆盖`,
      desc: primary.coverage?.rate ? `覆盖率 ${primary.coverage.rate}%` : '对照已有测试资产',
      q: `${primary.name}有没有测试完整？`,
    });
  }
  features.slice(1, 3).forEach((item: any) => {
    jobs.push({
      key: `locate-${item.id}`,
      label: `定位 ${item.name}`,
      desc: item.entry_page || item.module || '入口与代码',
      q: `${item.name}在哪里？入口页面、函数和 API 是什么？`,
    });
  });
  const weak = features.find((item: any) => !item.coverage?.rate || item.coverage.rate < 80) || primary;
  if (weak) {
    jobs.push({
      key: `gen-${weak.id}`,
      label: `生成 ${weak.name} 用例`,
      desc: '先预览，确认后再写入测试资产',
      q: `生成${weak.name}缺失测试用例`,
    });
  }
  return jobs;
}

function stepsFor(question: string) {
  if (/生成/.test(question) && /用例|测试/.test(question)) {
    return [
      { key: 'target', label: '识别要补的功能' },
      { key: 'cases', label: '对照已有测试资产' },
      { key: 'draft', label: '预览用例草稿' },
    ];
  }
  if (/覆盖|测试完整|缺口/.test(question)) {
    return [
      { key: 'target', label: '识别功能' },
      { key: 'cases', label: '对照已有测试' },
      { key: 'gap', label: '计算缺口' },
    ];
  }
  if (/调用链/.test(question)) {
    return [
      { key: 'target', label: '识别功能' },
      { key: 'page', label: '定位页面与入口' },
      { key: 'api', label: '定位接口与服务' },
    ];
  }
  return [
    { key: 'target', label: `识别目标：${question.slice(0, 18)}` },
    { key: 'page', label: '定位页面与代码' },
    { key: 'api', label: '定位接口' },
  ];
}

export function AgentSection() {
  const { data, loading: pageLoading } = useUnderstanding();
  const [params] = useSearchParams();
  const [question, setQuestion] = useState(params.get('q') || '');
  const [activeJob, setActiveJob] = useState('');
  const [loading, setLoading] = useState(false);
  const [last, setLast] = useState<AgentReply | null>(null);
  const [steps, setSteps] = useState<Array<{ key: string; label: string; status: string }>>([]);
  const [drafts, setDrafts] = useState<any[]>([]);

  const jobs = useMemo(() => buildJobs(data), [data]);
  const features = data?.features || [];
  const current = matchFeature(features, question) || (last ? features[0] : null);
  const page = (data?.pages || []).find((item: any) => item.feature === current?.name || item.route === current?.entry_page) || (data?.pages || [])[0];
  const api = (data?.apis || []).find((item: any) => (current?.apis || []).includes(item.name)) || (data?.apis || [])[0];
  const cases = current?.cases || [];
  const scale = data?.scale || {};
  const weak = (data?.coverage?.features || features).filter((item: any) => !item.rate && !item.coverage?.rate);

  const submit = async (text: string, jobKey = '') => {
    const projectId = getCurrentProjectId();
    const q = text.trim();
    if (!projectId || !q) return;
    setQuestion(q);
    setActiveJob(jobKey || jobs.find((item) => item.q === q)?.key || '');
    setLoading(true);
    setDrafts([]);
    const planned = stepsFor(q).map((item, index) => ({ ...item, status: index === 0 ? 'run' : 'wait' }));
    setSteps(planned);
    try {
      if (/生成/.test(q) && /用例|测试/.test(q)) {
        const preview = await previewGeneratedCases(projectId, q);
        setDrafts(preview?.cases || []);
        setLast({
          answer: `已预览 ${preview?.cases?.length || 0} 条用例，未写入测试资产。`,
          workspace: 'understand',
          project_id: projectId,
          locations: [],
          memory_used: [],
          actions: [],
        });
      } else {
        const reply = await askProjectAgent(projectId, q, 'understand');
        setLast(reply);
        window.dispatchEvent(new CustomEvent(PROJECT_MEMORY_CHANGED));
      }
      setSteps(planned.map((item) => ({ ...item, status: 'done' })));
    } catch (err: any) {
      message.error(apiError(err, '分析失败'));
      setSteps(planned.map((item, index) => ({ ...item, status: index === 0 ? 'bad' : 'wait' })));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (params.get('q')) void submit(params.get('q') || '');
  }, [params.get('q')]);

  const saveDrafts = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId || !drafts.length) return;
    await askProjectAgent(projectId, `生成${current?.name || ''}测试用例`, 'understand');
    message.success('已保存到测试任务');
  };

  if (pageLoading && !data) {
    return <div className="uw-panel"><Empty description="正在读取项目理解…" /></div>;
  }
  if (!data?.imported) {
    return <div className="uw-panel"><Empty description="先导入并分析项目，助手只基于真实解析结果工作。" /></div>;
  }

  return (
    <>
      <div className="uw-crumb">项目理解 / 项目助手</div>
      <div className="uw-pagehead">
        <div>
          <h2>项目助手</h2>
          <p>基于已解析的页面、功能、接口提问。先定位和分析，生成结果需确认后才写入测试资产。</p>
        </div>
      </div>

      <div className="uw-panel uw-ask">
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="针对当前项目提问，例如：登录功能在哪里？"
          onPressEnter={() => void submit(question)}
        />
        <Button type="primary" loading={loading} onClick={() => void submit(question)}>发送</Button>
      </div>

      <div className="uw-split">
        <div className="uw-panel">
          <h3>建议任务</h3>
          {jobs.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`uw-job ${activeJob === item.key ? 'is-on' : ''}`}
              onClick={() => void submit(item.q, item.key)}
            >
              <b>{item.label}</b>
              <span>{item.desc}</span>
            </button>
          ))}
        </div>

        <div>
          {steps.length ? (
            <div className="uw-panel">
              <h3>{loading ? '正在分析' : '分析步骤'}</h3>
              {steps.map((item) => (
                <div key={item.key} className={`uw-step uw-tone-${item.status === 'done' ? 'ok' : item.status === 'run' ? 'warn' : item.status === 'bad' ? 'bad' : 'empty'}`}>
                  {item.status === 'done' ? '✓' : item.status === 'run' ? '●' : item.status === 'bad' ? '×' : '○'} {item.label}
                </div>
              ))}
            </div>
          ) : null}

          {!last && !loading ? (
            <div className="uw-panel">
              <h3>当前项目</h3>
              <div className="uw-stats uw-stats-4" style={{ marginBottom: 12 }}>
                {[
                  ['页面', scale.pages],
                  ['功能', scale.features ?? features.length],
                  ['API', scale.apis],
                  ['用例', scale.cases],
                ].map(([label, value]) => (
                  <div key={String(label)} className="uw-stat">
                    <b>{value ?? 0}</b><span>{label}</span>
                  </div>
                ))}
              </div>
              <p className="uw-tone-empty">从左侧选一项，或直接问具体功能。助手不会另建一套知识，只复用项目理解结果。</p>
              {weak.length ? (
                <p>待补测试：{weak.map((item: any) => item.name).join('、')}</p>
              ) : null}
            </div>
          ) : null}

          {last ? (
            <div className="uw-panel uw-result">
              <h3>{current ? `「${current.name}」` : '分析结果'}</h3>
              <dl>
                <dt>功能入口</dt>
                <dd>{page?.route || current?.entry_page || '-'}</dd>
                <dt>前端</dt>
                <dd>{(current?.files || [])[0] || last.locations?.[0]?.path || '-'}</dd>
                <dt>API</dt>
                <dd>{current?.apis?.[0] || api?.name || '-'}</dd>
                <dt>调用链</dt>
                <dd>{(current?.chain || []).map((item: any) => item.layer).join(' → ') || last.path || '-'}</dd>
              </dl>
              <pre style={{ whiteSpace: 'pre-wrap', marginTop: 10 }}>{last.answer}</pre>
              {(last.locations || []).map((item) => (
                <div key={`${item.path}-${item.name}`}>
                  {item.path}:{item.line_start || 1} · {item.name}
                </div>
              ))}
            </div>
          ) : null}

          {/测试完整|覆盖|缺口/.test(question) && current ? (
            <div className="uw-panel">
              <h3>测试覆盖</h3>
              <p>{current.name}</p>
              <p>页面：{page?.route || '-'}</p>
              <p>已有测试：{cases.length}</p>
              <p className={`uw-tone-${coverageTone(current.coverage?.rate || 0, cases.length ? 0 : 1)}`}>
                覆盖率 {current.coverage?.rate || 0}%
              </p>
              {(cases.slice(0, 4).length ? cases.slice(0, 4) : [{ name: '暂无已落库用例' }]).map((item: any) => (
                <div key={item.id || item.name}>✓ {item.name}</div>
              ))}
              <Button type="primary" style={{ marginTop: 8 }} onClick={() => void submit(`生成${current.name}缺失测试用例`, `gen-${current.id}`)}>
                预览缺失用例
              </Button>
            </div>
          ) : null}

          {drafts.map((item, index) => (
            <div className="uw-panel" key={item.case_code || item.name || index}>
              <h3>{item.case_code || `TC-${index + 1}`} {item.name}</h3>
              <p className="uw-tone-empty">预览草稿，尚未写入测试资产</p>
              <p>前置条件　{item.precondition || '-'}</p>
              <ol>
                {(item.steps || []).map((step: any, i: number) => <li key={i}>{typeof step === 'string' ? step : step.action || JSON.stringify(step)}</li>)}
              </ol>
              <p>预期　{item.expected || item.expected_result || '-'}</p>
              <div style={{ display: 'flex', gap: 8 }}>
                <Button size="small" onClick={() => setDrafts((rows) => rows.filter((_, i) => i !== index))}>拒绝</Button>
                <Button size="small" type="primary" onClick={saveDrafts}>保存到测试用例</Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
