import { useEffect, useState } from 'react';
import { Button, Empty, Form, Input, InputNumber, Modal, Select, Table, Tag, message } from 'antd';
import {
  createAssessment,
  deleteAssessment,
  listAssessments,
  runAssessmentStream,
  type Assessment,
} from '@/services/assessment';
import './product.css';

const STEPS = [
  '正在准备测试环境',
  '正在打开页面',
  '正在采集页面性能',
  '正在分析资源加载',
  '正在统计测试执行情况',
  '正在生成测评报告',
  '测评完成',
];

function scoreText(value?: number | null) {
  return value == null ? '未计入' : String(value);
}

export default function AssessmentPanel({
  projectId,
  canRun,
  canAdmin,
  envs,
}: {
  projectId: number;
  canRun: boolean;
  canAdmin: boolean;
  envs: any[];
}) {
  const [items, setItems] = useState<Assessment[]>([]);
  const [envCount, setEnvCount] = useState(0);
  const [current, setCurrent] = useState<Assessment | null>(null);
  const [open, setOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState('');
  const [form] = Form.useForm();

  const load = async () => {
    const data = await listAssessments(projectId);
    setItems(data?.items || []);
    setEnvCount(data?.environment_count ?? 0);
    if (current?.id) {
      const next = (data?.items || []).find((item: Assessment) => item.id === current.id);
      if (next) setCurrent(next);
    }
  };

  useEffect(() => {
    load().catch(() => message.error('无法加载效能测评'));
  }, [projectId]);

  const start = async (assessment: Assessment) => {
    setRunning(true);
    setStep('正在准备测试环境');
    setCurrent(assessment);
    try {
      const result = await runAssessmentStream(projectId, assessment.id, setStep);
      setCurrent(result);
      setStep(result.status === 'SUCCESS' ? '测评完成' : '测评未完成');
      if (result.status === 'FAILED') {
        message.error(result.error_message || '测评未完成');
      } else {
        message.success('测评完成');
      }
      load();
    } catch (err: any) {
      message.error(err?.message || '测评执行失败');
    } finally {
      setRunning(false);
    }
  };

  const report = current?.report || {};
  const unsupported: string[] = report.unsupported || [];
  const history = [...items].filter((item) => item.score_total != null).slice(0, 8);

  return (
    <div>
      <div className="product-card">
        <div className="product-card-head">
          <h2>效能测评</h2>
          {canRun && <Button type="primary" onClick={() => setOpen(true)}>新建效能测评</Button>}
        </div>
        {envCount <= 0 && (
          <p className="product-note">当前项目还没有测试环境。可以先到 Settings 配置，或在创建时直接填写目标页面地址。</p>
        )}
        {items.length === 0 ? <Empty description="还没有效能测评" /> : items.map((item) => (
          <button key={item.id} type="button" className={`product-result-item ${current?.id === item.id ? 'is-current' : ''}`} onClick={() => setCurrent(item)}>
            <div>
              <strong>{item.name}</strong>
              <div className="product-note">{item.target_url} · {item.created_at || ''}</div>
            </div>
            <span>
              {item.score_total != null ? `评分 ${item.score_total}` : item.status}
              {canRun && item.status !== 'RUNNING' && (
                <Button size="small" style={{ marginLeft: 8 }} loading={running && current?.id === item.id} onClick={(e) => { e.stopPropagation(); start(item); }}>
                  开始测评
                </Button>
              )}
              {canAdmin && (
                <Button size="small" danger type="link" onClick={async (e) => {
                  e.stopPropagation();
                  await deleteAssessment(projectId, item.id);
                  if (current?.id === item.id) setCurrent(null);
                  message.success('已删除');
                  load();
                }}>删除</Button>
              )}
            </span>
          </button>
        ))}
      </div>

      {(running || current) && (
        <div className="product-card">
          <h2>{current?.name || '效能测评报告'}</h2>
          {running && (
            <ul className="product-steps">
              {STEPS.map((item) => (
                <li key={item}>
                  <span className="product-dot">{step === item ? '●' : STEPS.indexOf(item) < STEPS.indexOf(step) ? '✓' : '○'}</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          )}
          {current?.status === 'FAILED' && <p className="product-fail">{current.error_message}</p>}
          {current?.score_total != null && (
            <>
              <div className="product-summary">
                <div className="product-stat"><b>{scoreText(current.score_total)}</b><span>总体评分</span></div>
                <div className="product-stat"><b>{scoreText(current.score_page)}</b><span>页面性能</span></div>
                <div className="product-stat"><b>{scoreText(current.score_resource)}</b><span>资源加载</span></div>
                <div className="product-stat"><b>{scoreText(current.score_network)}</b><span>接口响应</span></div>
              </div>
              <div className="product-summary">
                <div className="product-stat"><b>{scoreText(current.score_job)}</b><span>测试执行效率</span></div>
                <div className="product-stat"><b>{scoreText(current.score_regression)}</b><span>回归效率</span></div>
              </div>
              {unsupported.length > 0 && unsupported.map((item) => <p key={item} className="product-note">{item}。当前版本暂不支持该指标计入总分。</p>)}
              {typeof current.advice === 'string' ? <p>{current.advice}</p> : current.advice?.summary && <pre className="product-note">{current.advice.summary}</pre>}
              {report.page && (
                <p className="product-note">
                  TTFB {report.page.ttfb_ms || '-'}ms · DOM {report.page.dom_ready_ms || '-'}ms · Load {report.page.load_complete_ms || '-'}ms
                  {report.page.fcp_ms ? ` · FCP ${report.page.fcp_ms}ms` : ''}
                  {report.page.lcp_ms ? ` · LCP ${report.page.lcp_ms}ms` : ''}
                </p>
              )}
              <h2 style={{ marginTop: 24 }}>发现问题</h2>
              {(!current.issues || current.issues.length === 0) ? <Empty description="未发现明显问题" /> : (
                <Table
                  rowKey={(row) => `${row.metric}-${row.problem}`}
                  dataSource={current.issues}
                  pagination={false}
                  columns={[
                    { title: '问题', dataIndex: 'problem' },
                    { title: '指标', dataIndex: 'metric' },
                    { title: '实际值', dataIndex: 'actual', render: (v) => String(v ?? '-') },
                    { title: '参考值', dataIndex: 'reference' },
                    { title: '影响', dataIndex: 'impact' },
                    { title: '建议', dataIndex: 'advice' },
                  ]}
                />
              )}
            </>
          )}
        </div>
      )}

      <div className="product-card">
        <h2>效能测评历史</h2>
        {history.length === 0 ? <Empty description="还没有已完成的评分历史" /> : history.map((item) => (
          <div key={item.id} className="product-result-item">
            <span>{item.created_at?.slice(0, 10) || ''} · {item.name}</span>
            <Tag>评分：{item.score_total}</Tag>
          </div>
        ))}
        {history.length >= 2 && (
          <p className="product-note">
            性能趋势：{history.map((item) => item.score_page ?? '-').join(' → ')}
            ；执行效率：{history.map((item) => item.score_job ?? '-').join(' → ')}
            ；回归效率：{history.map((item) => item.score_regression ?? '-').join(' → ')}
          </p>
        )}
      </div>

      <Modal title="新建效能测评" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} okText="创建">
        <Form form={form} layout="vertical" onFinish={async (values) => {
          if (envCount <= 0 && !(values.target_url || '').trim()) {
            message.warning('请先配置测试环境，或直接填写目标页面地址');
            return;
          }
          const created = await createAssessment(projectId, values);
          message.success('测评已创建');
          setOpen(false);
          form.resetFields();
          await load();
          if (created?.id) start(created);
        }}>
          <Form.Item name="name" label="测评名称" rules={[{ required: true, message: '请填写测评名称' }]}>
            <Input placeholder="例如：商城首页效能" />
          </Form.Item>
          <Form.Item name="environment_id" label="测试环境">
            <Select
              allowClear
              placeholder={envCount <= 0 ? '请先配置测试环境' : '选择已有环境'}
              options={envs.map((env) => ({ value: env.id, label: `${env.display_name || env.name} ${env.base_url || ''}` }))}
            />
          </Form.Item>
          <Form.Item name="target_url" label="目标页面 URL">
            <Input placeholder="https://example.com" />
          </Form.Item>
          <Form.Item name="rounds" label="测试次数" initialValue={1}>
            <InputNumber min={1} max={3} />
          </Form.Item>
          <Form.Item name="scenario" label="测试场景" initialValue="page">
            <Select options={[
              { value: 'page', label: '页面性能' },
              { value: 'resource', label: '页面资源' },
              { value: 'full', label: '页面 + 测试执行 + 回归' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
