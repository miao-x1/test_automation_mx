import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Empty, Input, InputNumber, Select, Table, Tag, message } from 'antd';
import { getCurrentProjectId, PROJECT_CHANGED } from '@/pages/product/projectStore';
import { apiError, openProjectAgent } from '@/services/projectExplorer';
import {
  batchPrepAccounts,
  checkPrepEnv,
  createRegression,
  createReport,
  createRunBatch,
  draftDefects,
  exportPrepAccounts,
  fetchDefects,
  fetchPipelineCases,
  fetchPrep,
  fetchRegressions,
  fetchReports,
  fetchRuns,
  generatePrepAccounts,
  generatePrepData,
  recommendRegression,
  recordRegression,
  recordRunResults,
  submitDefect,
  verifyDefect,
  PROJECT_PIPELINE_CHANGED,
} from '@/services/testPipeline';
import '../understand/understand.css';
import '../shell/shell.css';

function useProjectId() {
  return getCurrentProjectId();
}

function tone(status?: string) {
  if (status === 'PASS' || status === 'VERIFIED' || status === 'CLOSED' || status === 'ready') return 'success';
  if (status === 'FAIL' || status === 'REOPENED' || status === 'blocked') return 'error';
  if (status === 'UNKNOWN' || status === 'NOT_EXECUTED' || status === 'NEW') return 'warning';
  return 'default';
}

function reloadAll(load: () => void) {
  const run = () => load();
  window.addEventListener(PROJECT_CHANGED, run);
  window.addEventListener(PROJECT_PIPELINE_CHANGED, run);
  return () => {
    window.removeEventListener(PROJECT_CHANGED, run);
    window.removeEventListener(PROJECT_PIPELINE_CHANGED, run);
  };
}

function changed() {
  window.dispatchEvent(new CustomEvent(PROJECT_PIPELINE_CHANGED));
}

export function TestPrepPage() {
  const navigate = useNavigate();
  const [prep, setPrep] = useState<any>({ datasets: [], accounts: [], env_checks: [], issues: [] });
  const [dataCount, setDataCount] = useState(20);
  const [accCount, setAccCount] = useState(10);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    setPrep(await fetchPrep(projectId));
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载测试准备失败')));
    return reloadAll(() => { void load(); });
  }, []);

  const run = async (fn: () => Promise<any>, ok: string) => {
    setLoading(true);
    try {
      const data = await fn();
      setPrep(data.prep || data);
      changed();
      message.success(ok);
    } catch (err: any) {
      message.error(apiError(err, '操作失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>测试准备</h1>
          <p>根据测试用例生成可执行的数据、账号清单和环境检查。不会假装已经写入被测系统。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => navigate('/test-tasks')}>查看测试用例</Button>
          <Button onClick={() => openProjectAgent('批量生成测试数据 20')}>✦ Agent 生成数据</Button>
        </div>
      </div>
      <div className="uw-stats ra-stats">
        <div className="uw-stat"><b>{prep.datasets?.length || 0}</b><span>测试数据</span></div>
        <div className="uw-stat"><b>{prep.accounts?.length || 0}</b><span>账号清单</span></div>
        <div className="uw-stat"><b>{prep.env_checks?.length || 0}</b><span>环境检查</span></div>
        <div className="uw-stat"><b>{prep.issues?.length || 0}</b><span>未解决问题</span></div>
        <div className="uw-stat"><b>{prep.status || 'empty'}</b><span>准备状态</span></div>
      </div>
      <div className="uw-panel ra-actions">
        <InputNumber min={1} max={500} value={dataCount} onChange={(v) => setDataCount(Number(v) || 20)} />
        <Button type="primary" loading={loading} onClick={() => void run(() => generatePrepData(useProjectId()!, dataCount), `已生成 ${dataCount} 条测试数据`)}>批量生成测试数据</Button>
        <InputNumber min={1} max={200} value={accCount} onChange={(v) => setAccCount(Number(v) || 10)} />
        <Button loading={loading} onClick={() => void run(() => generatePrepAccounts(useProjectId()!, accCount), `已生成 ${accCount} 个账号清单`)}>批量生成测试账号</Button>
        <Button loading={loading} onClick={() => void run(() => checkPrepEnv(useProjectId()!), '环境检查已写入')}>环境检查</Button>
        <Button disabled={!selected.length} onClick={() => void run(() => batchPrepAccounts(useProjectId()!, selected, 'enable'), '已批量启用清单')}>批量启用</Button>
        <Button disabled={!selected.length} onClick={() => void run(() => batchPrepAccounts(useProjectId()!, selected, 'disable'), '已批量禁用清单')}>批量禁用</Button>
        <Button disabled={!selected.length} onClick={() => void run(() => batchPrepAccounts(useProjectId()!, selected, 'recycle'), '已批量回收清单')}>批量回收</Button>
        <Button onClick={async () => {
          const data = await exportPrepAccounts(useProjectId()!);
          const blob = new Blob([data.csv || ''], { type: 'text/csv;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = 'test-accounts.csv';
          a.click();
          URL.revokeObjectURL(url);
        }}>导出账号</Button>
        <Button onClick={() => navigate('/execute')}>去测试执行</Button>
      </div>
      <div className="uw-panel">
        <h3>测试数据</h3>
        <Table
          size="small"
          rowKey="id"
          pagination={{ pageSize: 10 }}
          dataSource={prep.datasets || []}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 110 },
            { title: '用途', dataIndex: 'purpose' },
            { title: '用例', dataIndex: 'case_code', width: 120 },
            { title: '字段', render: (_: any, row: any) => (row.fields || []).map((f: any) => `${f.field}=${f.value}`).join('；') },
            { title: '状态', dataIndex: 'created_status', width: 100 },
          ]}
        />
      </div>
      <div className="uw-panel">
        <h3>账号清单（待在实际系统中创建）</h3>
        <Table
          size="small"
          rowKey="id"
          rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
          pagination={{ pageSize: 10 }}
          dataSource={prep.accounts || []}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 100 },
            { title: '账号', dataIndex: 'username' },
            { title: '密码', dataIndex: 'password' },
            { title: '角色', dataIndex: 'role' },
            { title: '状态', dataIndex: 'status' },
            { title: '说明', dataIndex: 'note' },
          ]}
        />
      </div>
      <div className="uw-panel">
        <h3>环境检查</h3>
        {(prep.env_checks || []).length ? (prep.env_checks || []).map((item: any) => (
          <p key={item.item}><Tag color={tone(item.status)}>{item.status}</Tag> {item.item}：{item.detail}</p>
        )) : <Empty description="还没有环境检查结果。" />}
        {(prep.issues || []).length ? <p className="uw-tone-warn">未解决问题：{(prep.issues || []).join('；')}</p> : null}
      </div>
    </div>
  );
}

export function TestRunPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<any>({ batches: [] });
  const [cases, setCases] = useState<any[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [batch, setBatch] = useState<any | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [actual, setActual] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    const [doc, list] = await Promise.all([fetchRuns(projectId), fetchPipelineCases(projectId)]);
    setRuns(doc);
    setCases(list || []);
    setBatch((doc.batches || [])[0] || null);
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载执行批次失败')));
    return reloadAll(() => { void load(); });
  }, []);

  const mark = async (status: string) => {
    if (!batch || !selected.length) return message.info('请先选择执行记录');
    if ((status === 'PASS' || status === 'FAIL') && !actual.trim()) return message.info(`标记 ${status} 必须填写实际结果`);
    setLoading(true);
    try {
      const next = await recordRunResults(useProjectId()!, batch.id, selected.map((id) => ({ id, status, actual })));
      setBatch(next);
      setRuns((prev: any) => ({
        ...prev,
        batches: (prev.batches || []).map((item: any) => item.id === next.id ? next : item),
      }));
      changed();
      message.success(`已批量标记 ${selected.length} 条为 ${status}`);
    } catch (err: any) {
      message.error(apiError(err, '记录失败'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>测试执行</h1>
          <p>对真实用例建批次、记结果。系统不会把未执行的用例自动标成 PASS。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => navigate('/prepare')}>测试准备</Button>
          <Button type="primary" loading={loading} onClick={async () => {
            setLoading(true);
            try {
              const created = await createRunBatch(useProjectId()!, picked.length ? picked : undefined);
              setBatch(created);
              await load();
              changed();
              message.success(`已创建 ${created.id}，${created.stats.total} 条 NOT_EXECUTED`);
            } catch (err: any) {
              message.error(apiError(err, '创建批次失败'));
            } finally {
              setLoading(false);
            }
          }}>批量开始执行</Button>
        </div>
      </div>
      <div className="uw-panel">
        <p>选择要纳入批次的用例（不选则纳入全部 {cases.length} 条）。</p>
        <Table
          size="small"
          rowKey="id"
          pagination={{ pageSize: 8 }}
          rowSelection={{ selectedRowKeys: picked, onChange: (keys) => setPicked(keys as number[]) }}
          dataSource={cases}
          columns={[
            { title: '用例', dataIndex: 'case_code', width: 120 },
            { title: '名称', dataIndex: 'case_name' },
            { title: '数据', dataIndex: 'test_data' },
          ]}
        />
      </div>
      <div className="sub-tabs">
        {(runs.batches || []).map((item: any) => (
          <button key={item.id} type="button" className={batch?.id === item.id ? 'is-on' : ''} onClick={() => setBatch(item)}>{item.id}</button>
        ))}
      </div>
      {batch ? (
        <>
          <div className="uw-stats ra-stats">
            <div className="uw-stat"><b>{batch.stats?.total || 0}</b><span>总用例</span></div>
            <div className="uw-stat"><b>{batch.stats?.PASS || 0}</b><span>PASS</span></div>
            <div className="uw-stat"><b>{batch.stats?.FAIL || 0}</b><span>FAIL</span></div>
            <div className="uw-stat"><b>{batch.stats?.BLOCKED || 0}</b><span>BLOCKED</span></div>
            <div className="uw-stat"><b>{batch.stats?.SKIPPED || 0}</b><span>SKIPPED</span></div>
            <div className="uw-stat"><b>{batch.stats?.NOT_EXECUTED || 0}</b><span>未执行</span></div>
          </div>
          <div className="uw-panel ra-actions">
            <Input.TextArea rows={2} value={actual} onChange={(e) => setActual(e.target.value)} placeholder="实际结果（PASS/FAIL 必填）" />
            <Button onClick={() => void mark('PASS')}>批量 PASS</Button>
            <Button danger onClick={() => void mark('FAIL')}>批量 FAIL</Button>
            <Button onClick={() => void mark('BLOCKED')}>批量 BLOCKED</Button>
            <Button onClick={() => void mark('SKIPPED')}>批量 SKIPPED</Button>
            <Button onClick={() => void mark('NOT_EXECUTED')}>批量重新执行</Button>
            <Button type="primary" onClick={async () => {
              try {
                const data = await draftDefects(useProjectId()!, batch.id);
                message.success(`已生成 ${data.count} 条缺陷草稿`);
                navigate('/defects');
              } catch (err: any) {
                message.error(apiError(err, '不能凭空生成缺陷'));
              }
            }}>从失败提交缺陷</Button>
          </div>
          <Table
            size="small"
            rowKey="id"
            rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
            dataSource={batch.results || []}
            columns={[
              { title: '执行', dataIndex: 'id', width: 100 },
              { title: '用例', dataIndex: 'case_code', width: 110 },
              { title: '数据', dataIndex: 'data_id', width: 100 },
              { title: '预期', dataIndex: 'expected' },
              { title: '实际', dataIndex: 'actual' },
              { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={tone(v)}>{v}</Tag> },
            ]}
          />
        </>
      ) : <Empty description="还没有执行批次。" />}
    </div>
  );
}

export function DefectPage() {
  const navigate = useNavigate();
  const [doc, setDoc] = useState<any>({ bugs: [] });
  const [current, setCurrent] = useState<any | null>(null);

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    const data = await fetchDefects(projectId);
    setDoc(data);
    setCurrent((data.bugs || [])[0] || null);
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载缺陷失败')));
    return reloadAll(() => { void load(); });
  }, []);

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>缺陷管理</h1>
          <p>缺陷必须来自失败执行或测试人员确认。AI 草稿不能直接当成事实。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => navigate('/execute')}>返回执行</Button>
          <Button type="primary" onClick={async () => {
            try {
              const data = await draftDefects(useProjectId()!);
              message.success(`已生成 ${data.count} 条草稿`);
              await load();
            } catch (err: any) {
              message.error(apiError(err, '没有 FAIL 记录'));
            }
          }}>从失败生成草稿</Button>
        </div>
      </div>
      <Table
        size="small"
        rowKey="id"
        dataSource={doc.bugs || []}
        onRow={(row) => ({ onClick: () => setCurrent(row) })}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 90 },
          { title: '标题', dataIndex: 'title' },
          { title: '用例', dataIndex: 'case_code', width: 110 },
          { title: '执行', dataIndex: 'exec_id', width: 100 },
          { title: '状态', dataIndex: 'status', render: (v: string, row: any) => <span><Tag color={tone(v)}>{v}</Tag>{row.draft ? '草稿' : ''}{row.duplicate_of ? ` 可能重复 ${row.duplicate_of}` : ''}</span> },
        ]}
      />
      {current ? (
        <div className="uw-panel">
          <h3>{current.id} {current.title}</h3>
          <p>关联：{current.case_code} / {current.exec_id} / {current.batch_id}</p>
          {current.duplicate_of ? <p className="uw-tone-warn">可能与 {current.duplicate_of} 为同一问题，未自动删除。</p> : null}
          <p>预期：{current.expected}</p>
          <Input.TextArea rows={3} value={current.actual} onChange={(e) => setCurrent({ ...current, actual: e.target.value })} />
          <div className="ra-actions" style={{ marginTop: 8 }}>
            <Select
              value={current.status}
              style={{ width: 160 }}
              onChange={(v) => setCurrent({ ...current, status: v })}
              options={['NEW', 'ASSIGNED', 'IN_PROGRESS', 'FIXED', 'REOPENED', 'REJECTED', 'DUPLICATE'].map((v) => ({ value: v, label: v }))}
            />
            <Button type="primary" onClick={async () => {
              try {
                await submitDefect(useProjectId()!, current);
                message.success('缺陷已确认提交');
                await load();
              } catch (err: any) {
                message.error(apiError(err, '提交失败'));
              }
            }}>确认提交</Button>
            <Button onClick={() => navigate('/verify')}>去验证</Button>
          </div>
        </div>
      ) : <Empty description="还没有缺陷。" />}
    </div>
  );
}

export function VerifyPage() {
  const [doc, setDoc] = useState<any>({ bugs: [] });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const open = useMemo(() => (doc.bugs || []).filter((item: any) => !item.draft), [doc]);

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    setDoc(await fetchDefects(projectId));
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载缺陷失败')));
    return reloadAll(() => { void load(); });
  }, []);

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>缺陷验证</h1>
          <p>开发标记 FIXED 不等于验证通过。必须按原步骤重测并留下实际结果。</p>
        </div>
      </div>
      {open.map((bug: any) => (
        <div key={bug.id} className="uw-panel">
          <div className="ra-fn-head">
            <b>{bug.id} {bug.title}</b>
            <Tag color={tone(bug.status)}>{bug.status}</Tag>
          </div>
          <p>原环境：{bug.env || '未记录'} ｜ 原用例：{bug.case_code} ｜ 原数据/步骤沿用缺陷记录</p>
          <p>预期：{bug.expected}</p>
          <p>原实际：{bug.actual}</p>
          <Input.TextArea rows={2} placeholder="本次验证的实际结果（必填）" value={notes[bug.id] || ''} onChange={(e) => setNotes((prev) => ({ ...prev, [bug.id]: e.target.value }))} />
          <Input placeholder="证据：截图/日志/接口响应说明，没有就写「无附件，仅文字记录」" value={evidence[bug.id] || ''} onChange={(e) => setEvidence((prev) => ({ ...prev, [bug.id]: e.target.value }))} style={{ marginTop: 8 }} />
          <div className="ra-actions">
            <Button type="primary" onClick={async () => {
              try {
                const proof = evidence[bug.id]?.trim();
                await verifyDefect(useProjectId()!, bug.id, 'PASS', notes[bug.id] || '', proof ? [proof] : []);
                message.success('验证通过，缺陷变为 VERIFIED');
                await load();
              } catch (err: any) {
                message.error(apiError(err, '验证失败'));
              }
            }}>验证通过</Button>
            <Button danger onClick={async () => {
              try {
                const proof = evidence[bug.id]?.trim();
                await verifyDefect(useProjectId()!, bug.id, 'FAIL', notes[bug.id] || '', proof ? [proof] : []);
                message.success('验证失败，缺陷重新打开');
                await load();
              } catch (err: any) {
                message.error(apiError(err, '验证失败'));
              }
            }}>验证失败并重开</Button>
          </div>
          {(bug.verifications || []).map((item: any) => (
            <p key={item.id}>{item.id} {item.result} {item.actual} {item.verified_at}</p>
          ))}
        </div>
      ))}
      {!open.length ? <Empty description="没有可验证的已提交缺陷。" /> : null}
    </div>
  );
}

export function RegressionPage() {
  const [defects, setDefects] = useState<any>({ bugs: [] });
  const [regs, setRegs] = useState<any>({ batches: [] });
  const [picked, setPicked] = useState<string[]>([]);
  const [recommend, setRecommend] = useState<any | null>(null);
  const [batch, setBatch] = useState<any | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [actual, setActual] = useState('');

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    const [d, r] = await Promise.all([fetchDefects(projectId), fetchRegressions(projectId)]);
    setDefects(d);
    setRegs(r);
    setBatch((r.batches || [])[0] || null);
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载回归失败')));
    return reloadAll(() => { void load(); });
  }, []);

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>回归测试</h1>
          <p>按缺陷模块合并受影响用例并去重，再记录真实回归结果。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={async () => {
            try {
              setRecommend(await recommendRegression(useProjectId()!, picked));
            } catch (err: any) {
              message.error(apiError(err, '请先选择缺陷'));
            }
          }}>预览回归范围</Button>
          <Button type="primary" onClick={async () => {
            try {
              const created = await createRegression(useProjectId()!, picked);
              setBatch(created);
              await load();
              message.success(`已创建 ${created.id}`);
            } catch (err: any) {
              message.error(apiError(err, '创建回归失败'));
            }
          }}>批量创建回归批次</Button>
        </div>
      </div>
      <Table
        size="small"
        rowKey="id"
        rowSelection={{ selectedRowKeys: picked, onChange: (keys) => setPicked(keys as string[]) }}
        dataSource={(defects.bugs || []).filter((item: any) => !item.draft)}
        columns={[
          { title: '缺陷', dataIndex: 'id', width: 90 },
          { title: '标题', dataIndex: 'title' },
          { title: '模块', dataIndex: 'module' },
          { title: '状态', dataIndex: 'status' },
        ]}
      />
      {recommend ? <p className="uw-panel">推荐 {recommend.cases?.length || 0} 条：{(recommend.cases || []).map((item: any) => item.case_code).join('、')}。{recommend.reason}</p> : null}
      {batch ? (
        <div className="uw-panel">
          <h3>{batch.id} {batch.reason}</h3>
          <p>修复验证 {batch.fix_verify} ｜ 回归风险 {batch.risk} ｜ PASS {batch.stats?.PASS} FAIL {batch.stats?.FAIL} 未执行 {batch.stats?.NOT_EXECUTED}</p>
          <Input.TextArea rows={2} value={actual} onChange={(e) => setActual(e.target.value)} placeholder="实际结果" />
          <div className="ra-actions">
            <Button onClick={async () => {
              if (!selected.length || !actual.trim()) return message.info('选择记录并填写实际结果');
              const next = await recordRegression(useProjectId()!, batch.id, selected.map((id) => ({ id, status: 'PASS', actual })));
              setBatch(next);
            }}>批量 PASS</Button>
            <Button danger onClick={async () => {
              if (!selected.length || !actual.trim()) return message.info('选择记录并填写实际结果');
              const next = await recordRegression(useProjectId()!, batch.id, selected.map((id) => ({ id, status: 'FAIL', actual })));
              setBatch(next);
            }}>批量 FAIL</Button>
            <Button onClick={async () => {
              if (!selected.length) return message.info('请先选择回归记录');
              const next = await recordRegression(useProjectId()!, batch.id, selected.map((id) => ({ id, status: 'BLOCKED', actual })));
              setBatch(next);
            }}>批量 BLOCKED</Button>
            <Button onClick={async () => {
              if (!selected.length) return message.info('请先选择回归记录');
              const next = await recordRegression(useProjectId()!, batch.id, selected.map((id) => ({ id, status: 'SKIPPED', actual })));
              setBatch(next);
            }}>批量 SKIPPED</Button>
          </div>
          <Table
            size="small"
            rowKey="id"
            rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]) }}
            dataSource={batch.results || []}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 90 },
              { title: '用例', dataIndex: 'case_code' },
              { title: '名称', dataIndex: 'case_name' },
              { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={tone(v)}>{v}</Tag> },
            ]}
          />
        </div>
      ) : <Empty description="还没有回归批次。" />}
    </div>
  );
}

export function TestReportPage() {
  const navigate = useNavigate();
  const [doc, setDoc] = useState<any>({ reports: [] });

  const load = async () => {
    const projectId = useProjectId();
    if (!projectId) return;
    setDoc(await fetchReports(projectId));
  };

  useEffect(() => {
    load().catch((err) => message.error(apiError(err, '加载报告失败')));
    return reloadAll(() => { void load(); });
  }, []);

  return (
    <div className="pw-page ra-page">
      <div className="pw-head">
        <div>
          <h1>测试报告</h1>
          <p>只汇总已经发生的准备、执行、缺陷和回归，不把未执行算作通过。</p>
        </div>
        <div className="pw-head-actions">
          <Button onClick={() => navigate('/execute')}>查看执行</Button>
          <Button type="primary" onClick={async () => {
            try {
              const report = await createReport(useProjectId()!);
              message.success(`已生成 ${report.id}`);
              await load();
            } catch (err: any) {
              message.error(apiError(err, '生成报告失败'));
            }
          }}>汇总本轮测试报告</Button>
        </div>
      </div>
      {(doc.reports || []).map((item: any) => (
        <div key={item.id} className="uw-panel">
          <h3>{item.id}</h3>
          <p>{item.conclusion}</p>
          <p>用例 {item.cases} ｜ 数据 {item.prep?.data} ｜ 账号 {item.prep?.accounts} ｜ 已执行 {item.execution?.executed ?? 0}/{item.execution?.total || 0} PASS {item.execution?.PASS} FAIL {item.execution?.FAIL} 未执行 {item.execution?.NOT_EXECUTED}</p>
          <p>已执行通过率 {item.execution?.pass_rate_of_executed == null ? '无（还没有真实执行）' : `${item.execution.pass_rate_of_executed}%`}。未执行不计入通过。</p>
          <p>缺陷 {item.defects?.total} 开放 {item.defects?.open} 已验证 {item.defects?.verified} ｜ 回归批次 {item.regression?.batches || 0} PASS {item.regression?.PASS || 0} FAIL {item.regression?.FAIL || 0}</p>
          <p>追溯：{(item.trace?.batches || []).join('、') || '无执行批次'} {(item.trace?.bugs || []).join('、')} {(item.trace?.regs || []).join('、')}</p>
          {item.honesty?.length ? <p className="uw-tone-empty">{item.honesty.join('；')}</p> : null}
        </div>
      ))}
      {!(doc.reports || []).length ? <Empty description="还没有测试报告。先有执行或缺陷数据再汇总。" /> : null}
    </div>
  );
}
