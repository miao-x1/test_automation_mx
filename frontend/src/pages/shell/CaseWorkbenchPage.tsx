import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Checkbox, Drawer, Empty, Input, Modal, Select, Table, Tag, Upload, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { apiError, openProjectAgent } from '@/services/projectExplorer';
import {
  PROJECT_CASES_CHANGED,
  batchCases,
  createCase,
  exportCasesCsv,
  fetchCaseContext,
  fetchCaseCoverage,
  fetchCaseQuality,
  fetchCases,
  generateCases,
  generateCasesUpload,
  reviewCases,
  updateCase,
  type WorkbenchCase,
} from '@/services/testCases';
import './shell.css';
import './caseWorkbench.css';

const TYPE_LABEL: Record<string, string> = {
  functional: '功能', error: '异常', boundary: '边界', permission: '权限',
  rule: '业务规则', state: '状态流转', api: '接口', data: '数据',
  concurrency: '并发', regression: '回归',
};
const SOURCE_LABEL: Record<string, string> = {
  TEST_DESIGN: '测试设计', REQUIREMENT: '需求分析', FILE: '上传文件',
  TEXT: '用户描述', MANUAL: '人工创建', IMPORT: '导入', API_SPEC: '接口文档',
};
const REVIEW_LABEL: Record<string, string> = {
  DRAFT: '草稿', AI_GENERATED: 'AI生成', PENDING_REVIEW: '待评审',
  CHANGES_REQUIRED: '需修改', APPROVED: '已通过', DEPRECATED: '已废弃',
};

function changed() {
  window.dispatchEvent(new CustomEvent(PROJECT_CASES_CHANGED));
}

export default function CaseWorkbenchPage() {
  const navigate = useNavigate();
  const [ctx, setCtx] = useState<any>(null);
  const [items, setItems] = useState<WorkbenchCase[]>([]);
  const [stats, setStats] = useState<any>({});
  const [nav, setNav] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [type, setType] = useState<string>();
  const [priority, setPriority] = useState<string>();
  const [source, setSource] = useState<string>();
  const [selected, setSelected] = useState<number[]>([]);
  const [current, setCurrent] = useState<WorkbenchCase | null>(null);
  const [loading, setLoading] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [textOpen, setTextOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [text, setText] = useState('');
  const [files, setFiles] = useState<any[]>([]);
  const [genSource, setGenSource] = useState('TEXT');
  const [tdIds, setTdIds] = useState<string[]>([]);
  const [coverageOpen, setCoverageOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [types, setTypes] = useState<string[]>(['functional', 'error', 'boundary', 'permission', 'rule']);
  const [priorities, setPriorities] = useState<string[]>(['P0', 'P1', 'P2']);
  const [progress, setProgress] = useState<any[]>([]);
  const [quality, setQuality] = useState<any>(null);
  const [coverage, setCoverage] = useState<any>(null);
  const [draft, setDraft] = useState<any>({ case_name: '', module: '', type: 'functional', priority: 'P1', precondition: '', test_data: '', expected_result: '', steps: [{ stepNo: 1, action: '', data: '', expected: '' }] });

  const load = async () => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    const [context, data] = await Promise.all([fetchCaseContext(projectId), fetchCases(projectId)]);
    setCtx(context);
    setItems(data.items || []);
    setStats(data.statistics || {});
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载测试用例失败')));
    const reload = () => { void load().catch(() => undefined); };
    window.addEventListener(PROJECT_CHANGED, reload);
    window.addEventListener(PROJECT_CASES_CHANGED, reload);
    return () => {
      window.removeEventListener(PROJECT_CHANGED, reload);
      window.removeEventListener(PROJECT_CASES_CHANGED, reload);
    };
  }, []);

  const visible = useMemo(() => items.filter((item) => {
    if (nav === 'review' && item.review_status !== 'PENDING_REVIEW' && item.review_status !== 'AI_GENERATED') return false;
    if (nav === 'approved' && item.review_status !== 'APPROVED') return false;
    if (nav === 'changes' && item.review_status !== 'CHANGES_REQUIRED') return false;
    if (nav.startsWith('mod:') && item.module !== nav.slice(4)) return false;
    if (nav.startsWith('type:') && item.type !== nav.slice(5)) return false;
    if (type && item.type !== type) return false;
    if (priority && item.priority !== priority) return false;
    if (source && item.source_type !== source) return false;
    const blob = `${item.case_code} ${item.case_name} ${item.module}`.toLowerCase();
    return !keyword || blob.includes(keyword.toLowerCase());
  }), [items, nav, type, priority, source, keyword]);

  const runGenerate = async (payload: Record<string, unknown>) => {
    const projectId = getCurrentProjectId();
    if (!projectId) return;
    setLoading(true);
    setProgress([]);
    try {
      const uploadFiles = (payload.files as any[] | undefined)?.map((file) => file.originFileObj || file).filter(Boolean) as File[];
      const data = uploadFiles?.length
        ? await generateCasesUpload(projectId, String(payload.text || ''), uploadFiles)
        : await generateCases(projectId, payload);
      setProgress(data.progress || []);
      setQuality(data.quality);
      message.success(`已生成 ${data.count} 条用例，状态为 AI_GENERATED`);
      changed();
      await load();
      setGenOpen(false);
      setTextOpen(false);
      setUploadOpen(false);
    } catch (err: any) {
      message.error(apiError(err, '生成失败'));
    } finally {
      setLoading(false);
    }
  };

  const hasCases = items.length > 0;
  const sourceLine = ctx?.design?.available
    ? `来源：可承接测试设计${ctx.design.plan?.name ? ` · ${ctx.design.plan.name}` : ''}`
    : ctx?.requirement?.available
      ? '来源：可从需求分析生成'
      : '来源：用户创建 / 上传 / 描述';

  return (
    <div className="cw">
      <div className="cw-head">
        <div>
          <h1>测试用例{ctx?.design?.plan?.name ? ` · ${ctx.design.plan.name}` : ''}</h1>
          <p>{sourceLine}。AI 生成不是已评审，更不是已执行通过。</p>
        </div>
        <div className="cw-actions">
          <Button onClick={() => setUploadOpen(true)}>导入</Button>
          <Button type="primary" onClick={() => { setGenSource(ctx?.design?.available ? 'TEST_DESIGN' : 'TEXT'); setGenOpen(true); }}>AI 生成</Button>
          <Button onClick={() => setCreateOpen(true)}>新建用例</Button>
          <Button disabled={!selected.length} onClick={() => void reviewCases(getCurrentProjectId()!, selected, 'PENDING_REVIEW').then(() => { message.success('已提交评审'); changed(); void load(); })}>批量提交评审</Button>
          <Button disabled={!selected.length} onClick={() => void reviewCases(getCurrentProjectId()!, selected, 'APPROVED').then(() => { message.success('已人工通过'); changed(); void load(); })}>批量通过</Button>
          <Button disabled={!selected.length} onClick={() => void reviewCases(getCurrentProjectId()!, selected, 'CHANGES_REQUIRED').then(() => { message.success('已退回修改'); changed(); void load(); })}>批量退回</Button>
          <Button onClick={async () => {
            const data = await exportCasesCsv(getCurrentProjectId()!, selected.length ? selected : undefined);
            const blob = new Blob([data.csv || ''], { type: 'text/csv;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'test-cases.csv'; a.click();
            URL.revokeObjectURL(url);
          }}>导出</Button>
          <Button onClick={() => navigate('/prepare')}>进入测试准备</Button>
        </div>
      </div>

      {hasCases ? (
        <div className="cw-stats">
          <span>共 <b>{stats.total || 0}</b> 条</span>
          <span>P0 <b>{stats.P0 || 0}</b></span>
          <span>P1 <b>{stats.P1 || 0}</b></span>
          <span>P2 <b>{stats.P2 || 0}</b></span>
          <span>P3 <b>{stats.P3 || 0}</b></span>
          <span>待评审 <b>{(stats.AI_GENERATED || 0) + (stats.PENDING_REVIEW || 0)}</b></span>
          <span>已通过 <b>{stats.APPROVED || 0}</b></span>
          <span>需修改 <b>{stats.CHANGES_REQUIRED || 0}</b></span>
        </div>
      ) : null}

      {!hasCases ? (
        <div className="cw-main">
          <div className="cw-hint">
            <h2 style={{ margin: '0 0 8px' }}>开始创建测试用例</h2>
            <p>上一步可以提供输入，但不是进入本页的前提。没有测试设计也可以直接工作。</p>
          </div>
          {ctx?.design?.available ? (
            <div className="cw-hint">
              <b>可继续的测试工作</b>
              <p>{ctx.design.plan?.headline || '可以从已有对象和场景生成用例，不是进入本页的前提。'}</p>
              <div className="cw-objects">
                {(ctx.design.objects || []).map((item: any) => (
                  <p key={item.id}><b>{item.module || item.name}</b> {item.scenarios || 0} 个测试场景，预计生成 {Math.max(3, (item.scenarios || 1) * 2)}~{Math.max(8, (item.scenarios || 1) * 4)} 个测试用例</p>
                ))}
              </div>
              <Button type="primary" loading={loading} onClick={() => void runGenerate({ source_type: 'TEST_DESIGN' })}>选择并生成用例</Button>
            </div>
          ) : null}
          {ctx?.requirement?.available && !ctx?.design?.available ? (
            <div className="cw-hint">
              <b>已有需求分析</b>
              <p>没有测试设计时，可以直接根据需求生成用例，并保留 REQ 追溯。</p>
              <Button loading={loading} onClick={() => void runGenerate({ source_type: 'REQUIREMENT' })}>根据需求生成测试用例</Button>
            </div>
          ) : null}
          <div className="cw-start">
            <button type="button" className="cw-card" onClick={() => setUploadOpen(true)}>
              <b>上传测试资料</b>
              <p>PRD / API 文档 / Word / PDF / Excel。解析后生成结构化用例。</p>
            </button>
            <button type="button" className="cw-card" onClick={() => setTextOpen(true)}>
              <b>描述测试需求</b>
              <p>直接告诉系统要测什么，例如登录的正常、错误密码、锁定。</p>
            </button>
            <button type="button" className="cw-card" onClick={() => ctx?.design?.available ? void runGenerate({ source_type: 'TEST_DESIGN' }) : navigate('/design')}>
              <b>承接已有测试设计</b>
              <p>{ctx?.design?.available ? '读取 TD / TS / 方法 / 数据要求后生成用例。' : '当前没有测试设计，也可以先去设计，或用另外三种方式开始。'}</p>
            </button>
            <button type="button" className="cw-card" onClick={() => setCreateOpen(true)}>
              <b>手动创建</b>
              <p>自己写名称、前置、数据、步骤和预期，允许稍后补充关联。</p>
            </button>
          </div>
        </div>
      ) : (
        <div className="cw-body">
          <nav className="cw-nav">
            <div className="cw-nav-label">用例导航</div>
            {[
              ['overview', '概览', stats.total],
              ['all', '全部用例', stats.total],
              ['review', '待评审', (stats.AI_GENERATED || 0) + (stats.PENDING_REVIEW || 0)],
              ['approved', '已通过', stats.APPROVED],
              ['changes', '需修改', stats.CHANGES_REQUIRED],
            ].map(([key, label, count]) => (
              <button key={key} type="button" className={nav === key ? 'is-on' : ''} onClick={() => setNav(String(key))}>
                <span>{label}</span><span>{count || 0}</span>
              </button>
            ))}
            <div className="cw-nav-label">按模块</div>
            {Object.entries(stats.modules || {}).map(([mod, count]) => (
              <button key={mod} type="button" className={nav === `mod:${mod}` ? 'is-on' : ''} onClick={() => setNav(`mod:${mod}`)}>
                <span>{mod}</span><span>{count as number}</span>
              </button>
            ))}
            <div className="cw-nav-label">按类型</div>
            {Object.entries(stats.types || {}).map(([key, count]) => (
              <button key={key} type="button" className={nav === `type:${key}` ? 'is-on' : ''} onClick={() => setNav(`type:${key}`)}>
                <span>{TYPE_LABEL[key] || key}</span><span>{count as number}</span>
              </button>
            ))}
          </nav>
          <div className="cw-main">
            <div className="cw-toolbar">
              <Input allowClear placeholder="搜索用例" value={keyword} onChange={(e) => setKeyword(e.target.value)} style={{ maxWidth: 220 }} />
              <Select allowClear placeholder="类型" style={{ width: 120 }} value={type} onChange={setType} options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
              <Select allowClear placeholder="优先级" style={{ width: 100 }} value={priority} onChange={setPriority} options={['P0', 'P1', 'P2', 'P3'].map((v) => ({ value: v, label: v }))} />
              <Select allowClear placeholder="来源" style={{ width: 130 }} value={source} onChange={setSource} options={Object.entries(SOURCE_LABEL).map(([value, label]) => ({ value, label }))} />
              <Button onClick={async () => setQuality(await fetchCaseQuality(getCurrentProjectId()!))}>质量检查</Button>
              <Button onClick={async () => { const data = await fetchCaseCoverage(getCurrentProjectId()!); setCoverage(data); setCoverageOpen(true); }}>覆盖分析</Button>
              <Button disabled={!selected.length} onClick={() => void batchCases(getCurrentProjectId()!, selected, { priority: 'P0' }).then(() => { changed(); void load(); })}>批量 P0</Button>
              <Button disabled={!selected.length} onClick={() => void batchCases(getCurrentProjectId()!, selected, { copy: true }).then(() => { changed(); void load(); })}>批量复制</Button>
              <Button danger disabled={!selected.length} onClick={() => void batchCases(getCurrentProjectId()!, selected, { delete: true }).then(() => { changed(); void load(); })}>批量删除</Button>
              <Button onClick={() => openProjectAgent('根据当前项目生成测试用例')}>✦ Agent 生成</Button>
            </div>
            {nav === 'overview' ? (
              <div className="cw-hint">
                <p>用例是设计产物，不是执行结果。AI_GENERATED 不会自动变成已通过，更不会出现 PASS。</p>
                <p>已通过 {stats.APPROVED || 0} 条可进入测试准备；执行批次里每条仍从 NOT_EXECUTED 开始。</p>
                {ctx?.design?.available ? <p>已承接测试设计 {ctx.design.counts?.scenarios || ctx.design.scenarios?.length || 0} 个场景。</p> : <p>当前没有测试设计，也不影响继续维护本页用例。</p>}
              </div>
            ) : null}
            {quality ? <p className="cw-hint">{quality.summary} {quality.issues?.slice(0, 4).map((item: any) => `${item.id}:${item.problem}`).join('；')}</p> : null}
            {coverage && !coverageOpen ? <p className="cw-hint">需求覆盖 {coverage.requirement_rate == null ? '无需求条目可统计' : `${coverage.requirement_rate}%`}。未覆盖需求：{(coverage.missing_requirements || []).join('、') || '无'}。{(coverage.missing_dimensions || []).length ? `缺失维度：${coverage.missing_dimensions.join('、')}` : ''}</p> : null}
            <Table
              size="small"
              rowKey="id"
              dataSource={visible}
              rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as number[]) }}
              onRow={(row) => ({ onClick: () => setCurrent(row) })}
              pagination={{ pageSize: 12 }}
              columns={[
                { title: '编号', dataIndex: 'case_code', width: 110 },
                { title: '用例名称', dataIndex: 'case_name' },
                { title: '模块', dataIndex: 'module', width: 90 },
                { title: '类型', dataIndex: 'type', width: 90, render: (v: string) => TYPE_LABEL[v] || v },
                { title: '优先级', dataIndex: 'priority', width: 70 },
                { title: '来源', dataIndex: 'source_type', width: 100, render: (v: string) => SOURCE_LABEL[v] || v },
                { title: '评审', dataIndex: 'review_status', width: 90, render: (v: string) => <Tag>{REVIEW_LABEL[v] || v}</Tag> },
              ]}
            />
          </div>
        </div>
      )}

      <Drawer title={current ? `${current.case_code} ${current.case_name}` : '用例详情'} open={!!current} width={520} onClose={() => setCurrent(null)}>
        {current ? (
          <>
            <p><Tag>{current.priority}</Tag><Tag>{TYPE_LABEL[current.type || ''] || current.type}</Tag><Tag>{REVIEW_LABEL[current.review_status || '']}</Tag></p>
            <p>来源：{SOURCE_LABEL[current.source_type || ''] || current.source_type} {current.source_label || ''}</p>
            <p>需求：{(current.requirement_ids || []).join('、') || '未关联，可稍后补充'}</p>
            <p>测试设计：{(current.test_design_ids || []).join('、') || '未关联'}</p>
            <p>测试场景：{(current.test_scenario_ids || []).join('、') || '未关联'}</p>
            <p>前置条件：{current.precondition || '未填写'}</p>
            <p>测试数据：{current.test_data || '未填写'}</p>
            <table className="ra-table">
              <thead><tr><th>步骤</th><th>操作</th><th>数据</th><th>预期</th></tr></thead>
              <tbody>
                {(current.steps || []).map((step) => (
                  <tr key={step.stepNo}><td>{step.stepNo}</td><td>{step.action}</td><td>{step.data || '-'}</td><td>{step.expected || '-'}</td></tr>
                ))}
              </tbody>
            </table>
            <p>预期结果：{current.expected_result}</p>
            <div className="cw-actions" style={{ marginTop: 12 }}>
              <Button onClick={() => void reviewCases(getCurrentProjectId()!, [current.id], 'PENDING_REVIEW').then(() => { changed(); void load(); setCurrent({ ...current, review_status: 'PENDING_REVIEW' }); })}>提交评审</Button>
              <Button type="primary" onClick={() => void reviewCases(getCurrentProjectId()!, [current.id], 'APPROVED').then(() => { changed(); void load(); setCurrent({ ...current, review_status: 'APPROVED' }); })}>评审通过</Button>
              <Button onClick={() => void reviewCases(getCurrentProjectId()!, [current.id], 'CHANGES_REQUIRED').then(() => { changed(); void load(); })}>退回修改</Button>
              <Button onClick={() => { setDraft({ ...current, steps: current.steps?.length ? current.steps : [{ stepNo: 1, action: '', data: '', expected: '' }] }); setEditing(true); }}>编辑</Button>
              {(current.test_design_ids || [])[0] ? <Button onClick={() => navigate('/design')}>查看测试设计</Button> : null}
              {(current.requirement_ids || [])[0] ? <Button onClick={() => navigate('/understand/requirements')}>查看需求</Button> : null}
            </div>
          </>
        ) : null}
      </Drawer>

      <Modal title="AI 生成测试用例" open={genOpen} onCancel={() => setGenOpen(false)} onOk={() => void runGenerate({ source_type: genSource, text, types, priorities, td_ids: tdIds })} confirmLoading={loading} okText="开始生成">
        <p>默认由系统判断数量。生成结果是 AI_GENERATED，不会自动通过，也不会标成 PASS。</p>
        <Select
          style={{ width: '100%', marginBottom: 8 }}
          value={genSource}
          onChange={setGenSource}
          options={[
            { value: 'TEST_DESIGN', label: '当前测试设计', disabled: !ctx?.design?.available },
            { value: 'REQUIREMENT', label: '当前需求分析', disabled: !ctx?.requirement?.available },
            { value: 'TEXT', label: '我输入的测试目标' },
          ]}
        />
        {genSource === 'TEST_DESIGN' && (ctx?.design?.objects || []).length ? (
          <Select
            mode="multiple"
            allowClear
            placeholder="可选：限定测试对象，空则全部"
            style={{ width: '100%', marginBottom: 8 }}
            value={tdIds}
            onChange={setTdIds}
            options={(ctx.design.objects || []).map((item: any) => ({ value: item.id, label: `${item.module || item.name} · ${item.scenarios || 0} 场景` }))}
          />
        ) : null}
        {genSource === 'TEXT' ? <Input.TextArea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="例如：测试登录，覆盖正常登录、错误密码、账号不存在、锁定、验证码错误" /> : null}
        <div style={{ marginTop: 8 }}>
          {Object.entries(TYPE_LABEL).slice(0, 6).map(([value, label]) => (
            <Checkbox key={value} checked={types.includes(value)} onChange={(e) => setTypes(e.target.checked ? [...types, value] : types.filter((item) => item !== value))}>{label}</Checkbox>
          ))}
        </div>
        <div style={{ marginTop: 8 }}>
          {['P0', 'P1', 'P2', 'P3'].map((value) => (
            <Checkbox key={value} checked={priorities.includes(value)} onChange={(e) => setPriorities(e.target.checked ? [...priorities, value] : priorities.filter((item) => item !== value))}>{value}</Checkbox>
          ))}
        </div>
        {progress.length ? progress.map((item) => <p key={item.step}>✓ {item.step} {item.detail || ''}</p>) : null}
      </Modal>

      <Modal title="描述测试目标" open={textOpen} onCancel={() => setTextOpen(false)} onOk={() => void runGenerate({ source_type: 'TEXT', text })} confirmLoading={loading} okText="生成测试用例">
        <Input.TextArea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="测试用户登录功能，需要覆盖正常登录、错误密码、账号不存在、验证码错误、连续失败锁定。" />
      </Modal>

      <Modal title="上传测试资料" open={uploadOpen} onCancel={() => setUploadOpen(false)} onOk={() => void runGenerate({ source_type: 'FILE', text, files })} confirmLoading={loading} okText="解析并生成">
        <Upload
          multiple
          fileList={files}
          beforeUpload={(file) => { setFiles((prev) => [...prev, file]); return false; }}
          onRemove={(file) => setFiles((prev) => prev.filter((item) => item.uid !== file.uid))}
        >
          <Button>选择 PDF / Word / Excel / Markdown / TXT</Button>
        </Upload>
        <Input.TextArea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="可选：补充说明" style={{ marginTop: 8 }} />
      </Modal>

      <Modal
        title="覆盖分析"
        open={coverageOpen}
        onCancel={() => setCoverageOpen(false)}
        footer={[
          <Button key="close" onClick={() => setCoverageOpen(false)}>关闭</Button>,
          <Button key="miss" type="primary" loading={loading} onClick={() => void runGenerate({
            source_type: ctx?.design?.available ? 'TEST_DESIGN' : (ctx?.requirement?.available ? 'REQUIREMENT' : 'TEXT'),
            scenario_ids: coverage?.missing_scenarios || [],
            text: coverage?.missing_requirements?.length ? `补齐未覆盖需求：${(coverage.missing_requirements || []).join('、')}` : text,
          }).then(() => setCoverageOpen(false))}>生成缺失用例</Button>,
        ]}
      >
        <p>需求覆盖 {coverage?.requirement_rate == null ? '无需求条目可统计' : `${coverage.requirement_rate}%`}。场景覆盖 {coverage?.scenarios_total ? `${coverage.scenarios_covered}/${coverage.scenarios_total}` : '无场景可统计'}。</p>
        {(coverage?.missing_dimensions || []).length ? <p>缺失测试维度：{coverage.missing_dimensions.join('、')}</p> : null}
        <p>未覆盖需求：{(coverage?.missing_requirements || []).join('、') || '无'}</p>
        <p>未覆盖场景：{(coverage?.missing_scenarios || []).join('、') || '无'}</p>
        <table className="ra-table">
          <thead><tr><th>需求</th><th>测试设计</th><th>场景</th><th>用例</th><th>覆盖</th></tr></thead>
          <tbody>
            {(coverage?.rows || []).map((row: any) => (
              <tr key={row.req_id}>
                <td>{row.req_id}</td>
                <td>{(row.td_ids || []).join('、') || '-'}</td>
                <td>{(row.ts_ids || []).join('、') || '-'}</td>
                <td>{(row.case_codes || []).join('、') || '-'}</td>
                <td>{row.covered ? '✓' : '✕'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Modal>

      <Modal title={editing ? '编辑测试用例' : '新建测试用例'} open={createOpen || editing} onCancel={() => { setCreateOpen(false); setEditing(false); }} onOk={async () => {
        try {
          if (editing && current?.id) {
            await updateCase(getCurrentProjectId()!, current.id, draft);
            message.success('已保存修改');
          } else {
            await createCase(getCurrentProjectId()!, { ...draft, source_type: 'MANUAL', review_status: 'DRAFT' });
            message.success('已创建手工用例');
          }
          setCreateOpen(false);
          setEditing(false);
          changed();
          await load();
        } catch (err: any) {
          message.error(apiError(err, '保存失败'));
        }
      }} okText="保存">
        <Input placeholder="用例名称" value={draft.case_name} onChange={(e) => setDraft({ ...draft, case_name: e.target.value })} style={{ marginBottom: 8 }} />
        <Input placeholder="模块" value={draft.module} onChange={(e) => setDraft({ ...draft, module: e.target.value })} style={{ marginBottom: 8 }} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
          <Select value={draft.type} onChange={(value) => setDraft({ ...draft, type: value })} options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
          <Select value={draft.priority} onChange={(value) => setDraft({ ...draft, priority: value })} options={['P0', 'P1', 'P2', 'P3'].map((value) => ({ value, label: value }))} />
          <Select value={draft.risk_level || '中'} onChange={(value) => setDraft({ ...draft, risk_level: value })} options={['高', '中', '低'].map((value) => ({ value, label: `风险${value}` }))} />
        </div>
        <Input.TextArea rows={2} placeholder="前置条件" value={draft.precondition} onChange={(e) => setDraft({ ...draft, precondition: e.target.value })} style={{ marginBottom: 8 }} />
        <Input.TextArea rows={2} placeholder="测试数据" value={draft.test_data} onChange={(e) => setDraft({ ...draft, test_data: e.target.value })} style={{ marginBottom: 8 }} />
        {(draft.steps || []).map((step: any, index: number) => (
          <div key={index} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto auto', gap: 6, marginBottom: 6 }}>
            <Input placeholder={`步骤${index + 1} 操作`} value={step.action} onChange={(e) => {
              const steps = [...draft.steps]; steps[index] = { ...step, stepNo: index + 1, action: e.target.value }; setDraft({ ...draft, steps });
            }} />
            <Input placeholder="数据" value={step.data} onChange={(e) => {
              const steps = [...draft.steps]; steps[index] = { ...step, data: e.target.value }; setDraft({ ...draft, steps });
            }} />
            <Input placeholder="预期" value={step.expected} onChange={(e) => {
              const steps = [...draft.steps]; steps[index] = { ...step, expected: e.target.value }; setDraft({ ...draft, steps });
            }} />
            <Button onClick={() => {
              const steps = [...draft.steps];
              if (index > 0) [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
              setDraft({ ...draft, steps: steps.map((item: any, i: number) => ({ ...item, stepNo: i + 1 })) });
            }}>上</Button>
            <Button onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_: any, i: number) => i !== index) })}>删</Button>
          </div>
        ))}
        <Button onClick={() => setDraft({ ...draft, steps: [...draft.steps, { stepNo: draft.steps.length + 1, action: '', data: '', expected: '' }] })}>添加步骤</Button>
        <Input.TextArea rows={2} placeholder="总体预期结果" value={draft.expected_result} onChange={(e) => setDraft({ ...draft, expected_result: e.target.value })} style={{ marginTop: 8 }} />
        <Input placeholder="关联需求，逗号分隔，例如 REQ-001" value={(draft.requirement_ids || []).join(',')} onChange={(e) => setDraft({ ...draft, requirement_ids: e.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} style={{ marginTop: 8 }} />
        <Input placeholder="关联测试设计，逗号分隔，例如 TD-001" value={(draft.test_design_ids || []).join(',')} onChange={(e) => setDraft({ ...draft, test_design_ids: e.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} style={{ marginTop: 8 }} />
        <Input placeholder="关联测试场景，逗号分隔，例如 TS-001" value={(draft.test_scenario_ids || []).join(',')} onChange={(e) => setDraft({ ...draft, test_scenario_ids: e.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} style={{ marginTop: 8 }} />
        <Input placeholder="标签，逗号分隔" value={(draft.tags || []).join(',')} onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} style={{ marginTop: 8 }} />
      </Modal>
    </div>
  );
}
